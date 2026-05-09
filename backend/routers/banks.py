from datetime import datetime
from decimal import Decimal
from typing import Optional

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cache import invalidate_cache, user_financial_cache_keys
from database import get_db
from models import BankAccount, ProviderToken, Transaction, User
from oauth2 import get_current_user
from providers.banking.registry import SUPPORTED_PROVIDERS, get_bank_provider
from services.audit_service import write_audit_log
from services.encryption_service import decrypt_value, encrypt_value
from utils.financial import (
    build_transaction_fingerprint,
    money,
    normalize_country,
    serialize_transaction,
    transaction_id,
    transaction_type,
)

router = APIRouter(prefix="/api/banks", tags=["banking"])


class BankConnectIn(BaseModel):
    provider: str
    country: str
    public_token: Optional[str] = None


class BankSyncIn(BaseModel):
    provider: Optional[str] = None
    account_id: Optional[int] = None


def _serialize_account(account: BankAccount) -> dict:
    return {
        "id": account.id,
        "accountId": f"acc_{account.id}",
        "provider": account.provider,
        "providerAccountId": account.provider_account_id,
        "name": account.name,
        "mask": account.mask,
        "institutionName": account.institution_name,
        "accountType": account.account_type,
        "balance": float(account.balance),
        "availableBalance": float(account.available_balance or account.balance),
        "currency": account.currency,
        "country": account.country,
        "status": account.status,
        "lastSyncedAt": account.last_synced_at.isoformat() if account.last_synced_at else None,
    }


@router.get("/providers")
def list_supported_providers():
    return {"providers": [{"key": key, **value} for key, value in SUPPORTED_PROVIDERS.items()]}


@router.post("/connect")
def connect_bank_provider(
    data: BankConnectIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider_name = data.provider.strip().lower()
    country = normalize_country(data.country)
    provider = get_bank_provider(provider_name, country)
    access_token = provider.exchange_public_token(data.public_token, country)

    token = ProviderToken(
        user_id=current_user.id,
        provider=provider_name,
        country=country,
        encrypted_token=encrypt_value(access_token),
    )
    db.add(token)
    db.flush()

    accounts = []
    for account_data in provider.list_accounts(access_token, country):
        existing = (
            db.query(BankAccount)
            .filter(
                BankAccount.user_id == current_user.id,
                BankAccount.provider == provider_name,
                BankAccount.provider_account_id == account_data.provider_account_id,
            )
            .first()
        )
        if existing:
            account = existing
            account.provider_token_id = token.id
            account.balance = account_data.balance
            account.available_balance = account_data.available_balance
            account.status = "active"
        else:
            account = BankAccount(
                user_id=current_user.id,
                provider_token_id=token.id,
                provider=provider_name,
                provider_account_id=account_data.provider_account_id,
                name=account_data.name,
                mask=account_data.mask,
                institution_name=account_data.institution_name,
                account_type=account_data.account_type,
                balance=account_data.balance,
                available_balance=account_data.available_balance,
                currency=account_data.currency,
                country=account_data.country,
            )
            db.add(account)
        account.last_synced_at = datetime.utcnow()
        accounts.append(account)

    write_audit_log(db, user_id=current_user.id, action="connect_bank", entity_type="provider", entity_id=provider_name, metadata={"country": country}, request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"message": "Bank provider connected", "accounts": [_serialize_account(account) for account in accounts]}


@router.get("/accounts")
def list_bank_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = (
        db.query(BankAccount)
        .filter(BankAccount.user_id == current_user.id, BankAccount.status == "active")
        .order_by(BankAccount.created_at.desc())
        .all()
    )
    return {"accounts": [_serialize_account(account) for account in accounts]}


@router.post("/sync")
def sync_transactions(
    data: BankSyncIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token_query = db.query(ProviderToken).filter(ProviderToken.user_id == current_user.id, ProviderToken.status == "active")
    if data.provider:
        token_query = token_query.filter(ProviderToken.provider == data.provider.strip().lower())
    tokens = token_query.all()
    if not tokens:
        raise HTTPException(status_code=404, detail="No connected provider tokens found")

    created = []
    skipped_duplicates = 0
    for token in tokens:
        access_token = decrypt_value(token.encrypted_token)
        provider = get_bank_provider(token.provider, token.country)
        account_query = db.query(BankAccount).filter(BankAccount.user_id == current_user.id, BankAccount.provider == token.provider)
        if data.account_id:
            account_query = account_query.filter(BankAccount.id == data.account_id)
        accounts = account_query.all()
        account_by_provider_id = {account.provider_account_id: account for account in accounts}
        provider_account_ids = list(account_by_provider_id)
        for tx_data in provider.list_transactions(access_token, provider_account_ids, token.country):
            account = account_by_provider_id.get(tx_data.provider_account_id)
            if not account:
                continue
            amount = money(tx_data.amount)
            fingerprint = build_transaction_fingerprint(
                user_id=current_user.id,
                amount=amount,
                currency=tx_data.currency,
                country=tx_data.country,
                source="bank",
                tx_date=tx_data.date,
                merchant=tx_data.merchant,
                description=tx_data.description,
                account_id=account.id,
                provider_transaction_id=tx_data.provider_transaction_id,
            )
            if db.query(Transaction.id).filter(Transaction.user_id == current_user.id, Transaction.fingerprint == fingerprint).first():
                skipped_duplicates += 1
                continue
            tx = Transaction(
                id=transaction_id(),
                user_id=current_user.id,
                account_id=account.id,
                provider_transaction_id=tx_data.provider_transaction_id,
                fingerprint=fingerprint,
                amount=amount,
                currency=tx_data.currency,
                country=tx_data.country,
                type=transaction_type(amount),
                merchant=tx_data.merchant,
                description=tx_data.description,
                category=tx_data.category,
                subcategory=tx_data.subcategory,
                payment_method=tx_data.payment_method,
                source="bank",
                date=tx_data.date,
            )
            db.add(tx)
            created.append(tx)
        for account_data in provider.refresh_balances(access_token, token.country):
            account = account_by_provider_id.get(account_data.provider_account_id)
            if account:
                account.balance = account_data.balance
                account.available_balance = account_data.available_balance
                account.last_synced_at = datetime.utcnow()

    write_audit_log(db, user_id=current_user.id, action="sync_bank_transactions", entity_type="transaction", metadata={"created": len(created), "duplicates": skipped_duplicates}, request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"created": len(created), "duplicates": skipped_duplicates, "transactions": [serialize_transaction(tx) for tx in created]}


@router.post("/refresh-balances")
def refresh_balances(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tokens = db.query(ProviderToken).filter(ProviderToken.user_id == current_user.id, ProviderToken.status == "active").all()
    updated = []
    for token in tokens:
        provider = get_bank_provider(token.provider, token.country)
        access_token = decrypt_value(token.encrypted_token)
        accounts = (
            db.query(BankAccount)
            .filter(BankAccount.user_id == current_user.id, BankAccount.provider == token.provider, BankAccount.status == "active")
            .all()
        )
        by_provider_id = {account.provider_account_id: account for account in accounts}
        for account_data in provider.refresh_balances(access_token, token.country):
            account = by_provider_id.get(account_data.provider_account_id)
            if account:
                account.balance = account_data.balance
                account.available_balance = account_data.available_balance
                account.last_synced_at = datetime.utcnow()
                updated.append(account)
    write_audit_log(db, user_id=current_user.id, action="refresh_balances", entity_type="bank_account", metadata={"updated": len(updated)}, request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"accounts": [_serialize_account(account) for account in updated]}


@router.delete("/{account_id}")
def remove_bank_account(
    account_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    account.status = "removed"
    write_audit_log(db, user_id=current_user.id, action="remove_bank_account", entity_type="bank_account", entity_id=str(account.id), request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"message": "Bank account removed"}

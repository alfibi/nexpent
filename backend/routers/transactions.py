import csv
import io
from decimal import Decimal
from typing import Optional

from anyio import from_thread
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cache import invalidate_cache, user_financial_cache_keys
from database import get_db
from models import BankAccount, Transaction, User
from oauth2 import get_current_user
from services.audit_service import write_audit_log
from services.cloudflareLLMService import llm_service
from utils.financial import (
    ALLOWED_SOURCES,
    build_transaction_fingerprint,
    clean_text,
    money,
    normalize_country,
    normalize_currency,
    parse_date,
    serialize_transaction,
    transaction_id,
    transaction_type,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionCreate(BaseModel):
    accountId: Optional[int] = None
    amount: Decimal = Field(...)
    currency: str
    country: str
    merchant: Optional[str] = None
    description: Optional[str] = ""
    category: Optional[str] = "Uncategorized"
    subcategory: Optional[str] = None
    paymentMethod: Optional[str] = "manual"
    source: Optional[str] = "manual"
    date: str
    providerTransactionId: Optional[str] = None


class TransactionUpdate(BaseModel):
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    merchant: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    paymentMethod: Optional[str] = None
    source: Optional[str] = None
    date: Optional[str] = None


class CategorizeIn(BaseModel):
    merchant: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    country: Optional[str] = None


def _query_for_user(db: Session, user_id: int):
    return db.query(Transaction).filter(Transaction.user_id == user_id)


def _ensure_account(db: Session, user_id: int, account_id: Optional[int]) -> Optional[BankAccount]:
    if account_id is None:
        return None
    account = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.user_id == user_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    return account


def _apply_filters(query, *, start_date, end_date, category, tx_type, source):
    if start_date:
        query = query.filter(Transaction.date >= parse_date(start_date))
    if end_date:
        query = query.filter(Transaction.date <= parse_date(end_date))
    if category:
        query = query.filter(Transaction.category == category)
    if tx_type:
        query = query.filter(Transaction.type == tx_type)
    if source:
        query = query.filter(Transaction.source == source)
    return query


@router.get("/duplicates")
def detect_duplicates(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Transaction.fingerprint)
        .filter(Transaction.user_id == current_user.id)
        .group_by(Transaction.fingerprint)
        .having(func.count(Transaction.id) > 1)
        .all()
    )
    fingerprints = [row[0] for row in rows]
    duplicates = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id, Transaction.fingerprint.in_(fingerprints))
        .order_by(Transaction.date.desc())
        .all()
        if fingerprints
        else []
    )
    return {"duplicates": [serialize_transaction(row) for row in duplicates]}


@router.post("/import-csv")
async def import_csv_transactions(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    created = []
    duplicates = 0
    for row_number, row in enumerate(reader, start=2):
        try:
            amount = money(row.get("amount"))
            currency = normalize_currency(row.get("currency") or "USD")
            country = normalize_country(row.get("country") or "US")
            tx_date = parse_date(row.get("date"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid CSV row {row_number}") from exc
        source = clean_text(row.get("source") or "csv", 30).lower()
        if source not in ALLOWED_SOURCES:
            source = "csv"
        fingerprint = build_transaction_fingerprint(
            user_id=current_user.id,
            amount=amount,
            currency=currency,
            country=country,
            source=source,
            tx_date=tx_date,
            merchant=row.get("merchant"),
            description=row.get("description"),
        )
        if db.query(Transaction.id).filter(Transaction.user_id == current_user.id, Transaction.fingerprint == fingerprint).first():
            duplicates += 1
            continue
        tx = Transaction(
            id=transaction_id(),
            user_id=current_user.id,
            fingerprint=fingerprint,
            amount=amount,
            currency=currency,
            country=country,
            type=transaction_type(amount),
            merchant=clean_text(row.get("merchant"), 180) or None,
            description=clean_text(row.get("description"), 500),
            category=clean_text(row.get("category"), 120) or "Uncategorized",
            subcategory=clean_text(row.get("subcategory"), 120) or None,
            payment_method=clean_text(row.get("paymentMethod") or row.get("payment_method"), 50) or "csv",
            source=source,
            date=tx_date,
        )
        db.add(tx)
        created.append(tx)
    write_audit_log(db, user_id=current_user.id, action="import_csv_transactions", entity_type="transaction", metadata={"created": len(created), "duplicates": duplicates}, request=request)
    db.commit()
    await invalidate_cache(*user_financial_cache_keys(current_user.id))
    return {"created": len(created), "duplicates": duplicates, "transactions": [serialize_transaction(row) for row in created]}


@router.get("")
def list_transactions(
    startDate: Optional[str] = Query(None),
    endDate: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = _apply_filters(
        _query_for_user(db, current_user.id),
        start_date=startDate,
        end_date=endDate,
        category=category,
        tx_type=type,
        source=source,
    )
    rows = query.order_by(Transaction.date.desc(), Transaction.created_at.desc()).limit(500).all()
    return {"transactions": [serialize_transaction(row) for row in rows]}


@router.post("")
def create_transaction(
    data: TransactionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _ensure_account(db, current_user.id, data.accountId)
    amount = money(data.amount)
    currency = normalize_currency(data.currency)
    country = normalize_country(data.country)
    source = clean_text(data.source or "manual", 30).lower()
    if source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail="Unsupported transaction source")
    tx_date = parse_date(data.date)
    fingerprint = build_transaction_fingerprint(
        user_id=current_user.id,
        amount=amount,
        currency=currency,
        country=country,
        source=source,
        tx_date=tx_date,
        merchant=data.merchant,
        description=data.description,
        account_id=account.id if account else None,
        provider_transaction_id=data.providerTransactionId,
    )
    if db.query(Transaction.id).filter(Transaction.user_id == current_user.id, Transaction.fingerprint == fingerprint).first():
        raise HTTPException(status_code=409, detail="Duplicate transaction detected")

    tx = Transaction(
        id=transaction_id(),
        user_id=current_user.id,
        account_id=account.id if account else None,
        provider_transaction_id=data.providerTransactionId,
        fingerprint=fingerprint,
        amount=amount,
        currency=currency,
        country=country,
        type=transaction_type(amount),
        merchant=clean_text(data.merchant, 180) or None,
        description=clean_text(data.description, 500),
        category=clean_text(data.category, 120) or "Uncategorized",
        subcategory=clean_text(data.subcategory, 120) or None,
        payment_method=clean_text(data.paymentMethod, 50) or "manual",
        source=source,
        date=tx_date,
    )
    db.add(tx)
    try:
        write_audit_log(db, user_id=current_user.id, action="create_transaction", entity_type="transaction", entity_id=tx.id, request=request)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate transaction detected") from exc
    db.refresh(tx)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return serialize_transaction(tx)


@router.get("/{transaction_id_value}")
def get_transaction(transaction_id_value: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tx = _query_for_user(db, current_user.id).filter(Transaction.id == transaction_id_value).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return serialize_transaction(tx)


@router.put("/{transaction_id_value}")
def update_transaction(
    transaction_id_value: str,
    data: TransactionUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tx = _query_for_user(db, current_user.id).filter(Transaction.id == transaction_id_value).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    updates = data.dict(exclude_unset=True)
    if "amount" in updates:
        tx.amount = money(updates["amount"])
        tx.type = transaction_type(tx.amount)
    if "currency" in updates:
        tx.currency = normalize_currency(updates["currency"])
    if "country" in updates:
        tx.country = normalize_country(updates["country"])
    if "merchant" in updates:
        tx.merchant = clean_text(updates["merchant"], 180) or None
    if "description" in updates:
        tx.description = clean_text(updates["description"], 500)
    if "category" in updates:
        tx.category = clean_text(updates["category"], 120) or "Uncategorized"
    if "subcategory" in updates:
        tx.subcategory = clean_text(updates["subcategory"], 120) or None
    if "paymentMethod" in updates:
        tx.payment_method = clean_text(updates["paymentMethod"], 50) or "manual"
    if "source" in updates:
        source = clean_text(updates["source"], 30).lower()
        if source not in ALLOWED_SOURCES:
            raise HTTPException(status_code=400, detail="Unsupported transaction source")
        tx.source = source
    if "date" in updates:
        tx.date = parse_date(updates["date"])

    tx.fingerprint = build_transaction_fingerprint(
        user_id=current_user.id,
        amount=tx.amount,
        currency=tx.currency,
        country=tx.country,
        source=tx.source,
        tx_date=tx.date,
        merchant=tx.merchant,
        description=tx.description,
        account_id=tx.account_id,
        provider_transaction_id=tx.provider_transaction_id,
    )
    duplicate = (
        db.query(Transaction.id)
        .filter(Transaction.user_id == current_user.id, Transaction.fingerprint == tx.fingerprint, Transaction.id != tx.id)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Duplicate transaction detected")

    write_audit_log(db, user_id=current_user.id, action="update_transaction", entity_type="transaction", entity_id=tx.id, request=request)
    db.commit()
    db.refresh(tx)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return serialize_transaction(tx)


@router.delete("/{transaction_id_value}")
def delete_transaction(
    transaction_id_value: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tx = _query_for_user(db, current_user.id).filter(Transaction.id == transaction_id_value).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(tx)
    write_audit_log(db, user_id=current_user.id, action="delete_transaction", entity_type="transaction", entity_id=transaction_id_value, request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"message": "Transaction deleted"}


@router.post("/{transaction_id_value}/categorize")
def categorize_existing_transaction(
    transaction_id_value: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tx = _query_for_user(db, current_user.id).filter(Transaction.id == transaction_id_value).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    result = llm_service.generate_json(
        "categorize_transaction",
        {
            "merchant": tx.merchant,
            "description": tx.description,
            "amount": float(tx.amount),
            "currency": tx.currency,
            "country": tx.country,
        },
        {"category": "string", "subcategory": "string|null", "confidence": "number"},
    )
    tx.category = clean_text(result.get("category"), 120) or tx.category
    tx.subcategory = clean_text(result.get("subcategory"), 120) or tx.subcategory
    write_audit_log(db, user_id=current_user.id, action="categorize_transaction", entity_type="transaction", entity_id=tx.id, request=request)
    db.commit()
    db.refresh(tx)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return serialize_transaction(tx)

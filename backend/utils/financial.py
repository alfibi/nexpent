import hashlib
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from fastapi import HTTPException


ALLOWED_SOURCES = {"bank", "cash", "manual", "csv", "receipt", "transfer"}


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clean_text(value: Optional[str], max_length: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    return cleaned[:max_length]


def normalize_currency(value: str) -> str:
    currency = clean_text(value, 3).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise HTTPException(status_code=400, detail="Currency must be an ISO 4217 code")
    return currency


def normalize_country(value: str) -> str:
    country = clean_text(value, 2).upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise HTTPException(status_code=400, detail="Country must be an ISO 3166-1 alpha-2 code")
    return country


def parse_date(value: Optional[Union[str, date]]) -> date:
    if isinstance(value, date):
        return value
    if not value:
        return date.today()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format") from exc


def transaction_type(amount: Decimal) -> str:
    if amount > 0:
        return "income"
    if amount < 0:
        return "expense"
    raise HTTPException(status_code=400, detail="Transaction amount cannot be zero")


def transaction_id() -> str:
    return f"txn_{uuid.uuid4().hex[:24]}"


def build_transaction_fingerprint(
    *,
    user_id: int,
    amount: Decimal,
    currency: str,
    country: str,
    source: str,
    tx_date: date,
    merchant: Optional[str],
    description: Optional[str],
    account_id: Optional[int] = None,
    provider_transaction_id: Optional[str] = None,
) -> str:
    if provider_transaction_id:
        base = f"{user_id}|provider|{account_id or ''}|{provider_transaction_id}"
    else:
        base = "|".join(
            [
                str(user_id),
                str(account_id or ""),
                str(amount),
                currency,
                country,
                source,
                tx_date.isoformat(),
                clean_text(merchant, 180).lower(),
                clean_text(description, 500).lower(),
            ]
        )
    return hashlib.sha256(base.encode()).hexdigest()


def serialize_transaction(row) -> dict:
    return {
        "id": row.id,
        "userId": f"user_{row.user_id}",
        "accountId": f"acc_{row.account_id}" if row.account_id else None,
        "receiptId": row.receipt_id,
        "providerTransactionId": row.provider_transaction_id,
        "amount": float(row.amount),
        "currency": row.currency,
        "country": row.country,
        "type": row.type,
        "merchant": row.merchant,
        "description": row.description,
        "category": row.category,
        "subcategory": row.subcategory,
        "paymentMethod": row.payment_method,
        "source": row.source,
        "date": row.date.isoformat() if row.date else None,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "primary_label": row.merchant or row.category,
        "secondary_label": row.subcategory or row.description,
        "transaction_type": row.type,
        "payment_method": row.payment_method,
    }


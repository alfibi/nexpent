import re
import shutil
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Optional

from anyio import from_thread
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cache import invalidate_cache, user_financial_cache_keys
from config import RECEIPT_UPLOAD_DIR
from database import get_db
from models import Receipt, ReceiptItem, Transaction, User
from oauth2 import get_current_user
from providers.ocr.mock import get_ocr_provider
from receipt_extraction.ocr import OCRDependencyError, PaddleReceiptOCR
from receipt_extraction.parser import ReceiptOCRParser
from services.audit_service import write_audit_log
from services.cloudflareLLMService import llm_service
from utils.financial import (
    build_transaction_fingerprint,
    clean_text,
    money,
    normalize_country,
    normalize_currency,
    parse_date,
    serialize_transaction,
    transaction_id,
)

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

OCR_UNAVAILABLE_MESSAGE = (
    "OCR could not read text from this receipt. Install the backend OCR requirements "
    "(paddleocr and paddlepaddle) or install Tesseract for local fallback OCR."
)


class ReceiptItemIn(BaseModel):
    name: str
    quantity: Optional[Decimal] = 1
    unitPrice: Optional[Decimal] = None
    totalPrice: Optional[Decimal] = 0
    category: Optional[str] = None


class ReceiptCorrectionIn(BaseModel):
    merchant: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    date: Optional[str] = None
    category: Optional[str] = "Uncategorized"
    subcategory: Optional[str] = None
    items: Optional[list[ReceiptItemIn]] = None


def _clean_ocr_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:8000]


def _extract_ocr_text(file_path: Path) -> tuple[str, str]:
    """Return raw OCR text and cleaned LLM-ready text for a receipt upload."""
    errors: list[str] = []
    if file_path.suffix.lower() in IMAGE_EXTENSIONS:
        try:
            ocr = PaddleReceiptOCR(lang="en")
            parser = ReceiptOCRParser()
            for preprocess in (False, True):
                document = ocr.extract(file_path, preprocess=preprocess)
                parsed = parser.parse(document)
                if parsed.text.strip():
                    return document.text[:8000], parsed.text[:8000]
        except OCRDependencyError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"PaddleOCR failed: {exc}")

    raw_text = get_ocr_provider().extract_text(str(file_path))
    if not raw_text.strip():
        detail = OCR_UNAVAILABLE_MESSAGE
        if errors:
            detail = f"{detail} {' '.join(errors)}"
        raise HTTPException(status_code=503, detail=detail)
    return raw_text[:8000], _clean_ocr_text(raw_text)


def _serialize_receipt(receipt: Receipt) -> dict:
    return {
        "id": receipt.id,
        "merchant": receipt.merchant,
        "amount": float(receipt.amount) if receipt.amount is not None else None,
        "currency": receipt.currency,
        "country": receipt.country,
        "date": receipt.purchased_at.isoformat() if receipt.purchased_at else None,
        "status": receipt.status,
        "rawText": receipt.raw_text,
        "cleanedText": receipt.cleaned_text,
        "transaction": serialize_transaction(receipt.transaction) if receipt.transaction else None,
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "quantity": float(item.quantity),
                "unitPrice": float(item.unit_price) if item.unit_price is not None else None,
                "totalPrice": float(item.total_price),
                "category": item.category,
            }
            for item in receipt.items
        ],
        "createdAt": receipt.created_at.isoformat() if receipt.created_at else None,
    }


def _safe_amount(value) -> Optional[Decimal]:
    try:
        parsed = money(value)
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _safe_date(value) -> Optional[object]:
    try:
        return parse_date(value) if value else None
    except HTTPException:
        return None


def _normalize_extracted_receipt(extraction: dict, default_currency: str) -> dict:
    amount = extraction.get("amount", extraction.get("total"))
    normalized_items = []
    raw_items = extraction.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            normalized_items.append(
                {
                    "name": item.get("name"),
                    "quantity": item.get("quantity", 1),
                    "unitPrice": item.get("unitPrice", item.get("unit_price")),
                    "totalPrice": item.get("totalPrice", item.get("total_price", item.get("price", 0))),
                    "category": item.get("category"),
                }
            )
    return {
        **extraction,
        "amount": amount,
        "currency": extraction.get("currency") or default_currency,
        "items": normalized_items,
    }


def _receipt_schema_hint() -> dict:
    return {
        "merchant": "string",
        "amount": "number",
        "currency": "string",
        "date": "YYYY-MM-DD|null",
        "items": [{"name": "string", "quantity": "number", "totalPrice": "number", "category": "string|null"}],
        "category": "string",
    }


def _amount_or_none(extraction: dict) -> Optional[Decimal]:
    return _safe_amount(extraction.get("amount", extraction.get("total")))


def _merge_ai_and_ocr_extraction(ai_extraction: dict, ocr_extraction: dict, default_currency: str) -> dict:
    ai = _normalize_extracted_receipt(ai_extraction if isinstance(ai_extraction, dict) else {}, default_currency)
    ocr = _normalize_extracted_receipt(ocr_extraction if isinstance(ocr_extraction, dict) else {}, default_currency)

    ai_amount = _amount_or_none(ai)
    ocr_amount = _amount_or_none(ocr)
    use_ocr_amount = bool(ocr_amount and ocr.get("amountSource") == "labeled_total")
    if ocr_amount and ai_amount:
        lower_bound = ocr_amount * Decimal("0.80")
        upper_bound = ocr_amount * Decimal("1.20")
        use_ocr_amount = use_ocr_amount or not (lower_bound <= ai_amount <= upper_bound)

    merged = {**ocr, **ai}
    if use_ocr_amount and ocr_amount is not None:
        merged["amount"] = ocr_amount
    elif ai_amount is not None:
        merged["amount"] = ai_amount
    elif ocr_amount is not None:
        merged["amount"] = ocr_amount

    if not ai.get("merchant") and ocr.get("merchant"):
        merged["merchant"] = ocr["merchant"]
    if not ai.get("date") and ocr.get("date"):
        merged["date"] = ocr["date"]
    if not ai.get("items") and ocr.get("items"):
        merged["items"] = ocr["items"]
    if not clean_text(ai.get("category"), 120) and ocr.get("category"):
        merged["category"] = ocr["category"]
    return merged


def _extract_structured_receipt(cleaned_text: str, normalized_country: str, normalized_currency: str) -> dict:
    ocr_extraction = llm_service._extract_receipt_fallback(
        {"cleaned_text": cleaned_text, "country": normalized_country, "currency": normalized_currency}
    )
    try:
        ai_extraction = llm_service.generate_json(
            "extract_receipt",
            {"cleaned_text": cleaned_text, "country": normalized_country, "currency": normalized_currency},
            _receipt_schema_hint(),
        )
    except Exception:
        ai_extraction = {}
    return _merge_ai_and_ocr_extraction(ai_extraction, ocr_extraction, normalized_currency)


def _replace_items(db: Session, receipt: Receipt, items: list[dict]) -> None:
    db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).delete(synchronize_session=False)
    for item in items:
        name = clean_text(item.get("name"), 180)
        if not name:
            continue
        db.add(
            ReceiptItem(
                receipt_id=receipt.id,
                name=name,
                quantity=money(item.get("quantity", 1)),
                unit_price=money(item["unitPrice"]) if item.get("unitPrice") is not None else None,
                total_price=money(item.get("totalPrice", item.get("total_price", 0))),
                category=clean_text(item.get("category"), 120) or None,
            )
        )


def _upsert_receipt_transaction(
    db: Session,
    user_id: int,
    receipt: Receipt,
    *,
    category: str = "Uncategorized",
    subcategory: Optional[str] = None,
) -> Optional[Transaction]:
    if receipt.amount is None or receipt.amount <= 0:
        return None
    tx_amount = -abs(money(receipt.amount))
    tx_date = receipt.purchased_at or parse_date(None)
    description = f"Cash receipt: {receipt.merchant or 'Unknown merchant'}"
    fingerprint = build_transaction_fingerprint(
        user_id=user_id,
        amount=tx_amount,
        currency=receipt.currency,
        country=receipt.country,
        source="receipt",
        tx_date=tx_date,
        merchant=receipt.merchant,
        description=description,
    )
    tx = receipt.transaction
    if tx:
        tx.amount = tx_amount
        tx.currency = receipt.currency
        tx.country = receipt.country
        tx.type = "expense"
        tx.merchant = receipt.merchant
        tx.description = description
        tx.category = category
        tx.subcategory = subcategory
        tx.payment_method = "cash"
        tx.source = "receipt"
        tx.date = tx_date
        tx.fingerprint = fingerprint
        return tx
    tx = Transaction(
        id=transaction_id(),
        user_id=user_id,
        receipt_id=receipt.id,
        fingerprint=fingerprint,
        amount=tx_amount,
        currency=receipt.currency,
        country=receipt.country,
        type="expense",
        merchant=receipt.merchant,
        description=description,
        category=category,
        subcategory=subcategory,
        payment_method="cash",
        source="receipt",
        date=tx_date,
    )
    db.add(tx)
    return tx


@router.post("/upload")
def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    country: str = Form("US"),
    currency: str = Form("USD"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_country = normalize_country(country)
    normalized_currency = normalize_currency(currency)
    RECEIPT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt"}:
        raise HTTPException(status_code=400, detail="Unsupported receipt file type")
    image_path = RECEIPT_UPLOAD_DIR / f"{uuid.uuid4().hex}{extension}"
    with image_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    raw_text, cleaned_text = _extract_ocr_text(image_path)
    extraction = _extract_structured_receipt(cleaned_text, normalized_country, normalized_currency)

    receipt = Receipt(
        user_id=current_user.id,
        image_path=str(image_path),
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        merchant=clean_text(extraction.get("merchant"), 180) or None,
        amount=_safe_amount(extraction.get("amount")),
        currency=normalize_currency(extraction.get("currency") or normalized_currency),
        country=normalized_country,
        purchased_at=_safe_date(extraction.get("date")),
        status="needs_correction" if not _safe_amount(extraction.get("amount")) else "processed",
    )
    db.add(receipt)
    db.flush()
    _replace_items(db, receipt, extraction.get("items") if isinstance(extraction.get("items"), list) else [])
    tx = _upsert_receipt_transaction(
        db,
        current_user.id,
        receipt,
        category=clean_text(extraction.get("category"), 120) or "Uncategorized",
        subcategory=clean_text(extraction.get("subcategory"), 120) or None,
    )
    try:
        write_audit_log(db, user_id=current_user.id, action="upload_receipt", entity_type="receipt", entity_id=str(receipt.id), request=request)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate receipt transaction detected") from exc
    db.refresh(receipt)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_receipt(receipt)


@router.get("")
def list_receipts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    receipts = db.query(Receipt).filter(Receipt.user_id == current_user.id).order_by(Receipt.created_at.desc()).limit(100).all()
    return {"receipts": [_serialize_receipt(receipt) for receipt in receipts]}


@router.get("/{receipt_id}")
def get_receipt(receipt_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == current_user.id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return _serialize_receipt(receipt)


@router.put("/{receipt_id}/correct")
def correct_receipt(
    receipt_id: int,
    data: ReceiptCorrectionIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == current_user.id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if data.merchant is not None:
        receipt.merchant = clean_text(data.merchant, 180) or None
    if data.amount is not None:
        amount = money(data.amount)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Receipt amount must be positive")
        receipt.amount = amount
    if data.currency is not None:
        receipt.currency = normalize_currency(data.currency)
    if data.country is not None:
        receipt.country = normalize_country(data.country)
    if data.date is not None:
        receipt.purchased_at = parse_date(data.date)
    if data.items is not None:
        _replace_items(db, receipt, [item.dict() for item in data.items])
    receipt.status = "corrected"
    _upsert_receipt_transaction(
        db,
        current_user.id,
        receipt,
        category=clean_text(data.category, 120) or "Uncategorized",
        subcategory=clean_text(data.subcategory, 120) or None,
    )
    try:
        write_audit_log(db, user_id=current_user.id, action="correct_receipt", entity_type="receipt", entity_id=str(receipt.id), request=request)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate receipt transaction detected") from exc
    db.refresh(receipt)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_receipt(receipt)

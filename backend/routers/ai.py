import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import AIChatMessage, AIInsight, Transaction, User
from oauth2 import get_current_user
from services.audit_service import write_audit_log
from services.calculation_service import savingsRate, totalExpenses, totalIncome
from services.cloudflareLLMService import llm_service
from utils.financial import clean_text

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class AnalyzeIn(BaseModel):
    month: Optional[str] = None


class CategorizeIn(BaseModel):
    merchant: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = "USD"
    country: Optional[str] = "US"


class ExtractReceiptIn(BaseModel):
    cleanedText: str = Field(..., min_length=1)
    currency: Optional[str] = "USD"
    country: Optional[str] = "US"


def _financial_context(db: Session, user_id: int, limit: int = 120) -> dict:
    rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(limit)
        .all()
    )
    income = totalIncome(rows)
    expenses = totalExpenses(rows)
    saved = income - expenses
    categories: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    merchants: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for tx in rows:
        if tx.amount < 0:
            categories[tx.category or "Uncategorized"] += abs(tx.amount)
            merchants[tx.merchant or "Unknown"] += abs(tx.amount)
    return {
        "transaction_count": len(rows),
        "income": float(income),
        "expenses": float(expenses),
        "savings": float(saved),
        "savings_rate": float(savingsRate(income, saved)),
        "top_categories": [
            {"category": key, "total": float(value)}
            for key, value in sorted(categories.items(), key=lambda item: item[1], reverse=True)[:8]
        ],
        "top_merchants": [
            {"merchant": key, "total": float(value)}
            for key, value in sorted(merchants.items(), key=lambda item: item[1], reverse=True)[:8]
        ],
    }


def _serialize_insight(row: AIInsight) -> dict:
    try:
        payload = json.loads(row.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "type": row.insight_type,
        "title": row.title,
        "summary": row.summary,
        "payload": payload,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/chat")
def chat(
    data: ChatIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = clean_text(data.message, 2000)
    context = _financial_context(db, current_user.id)
    db.add(AIChatMessage(user_id=current_user.id, role="user", content=message))
    result = llm_service.generate_json(
        "chat",
        {"question": message, "financial_context": context},
        {"message": "string", "suggestedActions": ["string"]},
    )
    answer = clean_text(result.get("message") or result.get("summary"), 4000)
    if not answer:
        answer = "I could not generate advice right now. Your exact calculations are still available in reports."
    db.add(AIChatMessage(user_id=current_user.id, role="assistant", content=answer))
    write_audit_log(db, user_id=current_user.id, action="ai_chat", entity_type="ai_chat_message", request=request)
    db.commit()
    return {"message": answer, "context": context, "suggestedActions": result.get("suggestedActions", [])}


@router.post("/analyze-spending")
def analyze_spending(
    data: AnalyzeIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = _financial_context(db, current_user.id)
    result = llm_service.generate_json(
        "generate_insights",
        {"month": data.month, "financial_context": context},
        {"title": "string", "summary": "string", "recommendations": ["string"], "risks": ["string"]},
    )
    insight = AIInsight(
        user_id=current_user.id,
        insight_type="spending_analysis",
        title=clean_text(result.get("title"), 180) or "Spending analysis",
        summary=clean_text(result.get("summary"), 4000) or "Spending analysis generated.",
        payload=json.dumps(result),
    )
    db.add(insight)
    db.flush()
    write_audit_log(db, user_id=current_user.id, action="generate_ai_spending_analysis", entity_type="ai_insight", entity_id=str(insight.id), request=request)
    db.commit()
    db.refresh(insight)
    return _serialize_insight(insight)


@router.post("/categorize-transaction")
def categorize_transaction(data: CategorizeIn, current_user: User = Depends(get_current_user)):
    result = llm_service.generate_json(
        "categorize_transaction",
        {
            "merchant": clean_text(data.merchant, 180),
            "description": clean_text(data.description, 500),
            "amount": float(data.amount) if data.amount is not None else None,
            "currency": data.currency,
            "country": data.country,
        },
        {"category": "string", "subcategory": "string|null", "confidence": "number"},
    )
    return {
        "category": clean_text(result.get("category"), 120) or "Uncategorized",
        "subcategory": clean_text(result.get("subcategory"), 120) or None,
        "confidence": result.get("confidence", 0),
    }


@router.post("/extract-receipt")
def extract_receipt(data: ExtractReceiptIn, current_user: User = Depends(get_current_user)):
    result = llm_service.generate_json(
        "extract_receipt",
        {"cleaned_text": data.cleanedText[:8000], "currency": data.currency, "country": data.country},
        {
            "merchant": "string",
            "amount": "number",
            "currency": "string",
            "date": "YYYY-MM-DD|null",
            "items": [{"name": "string", "quantity": "number", "totalPrice": "number"}],
        },
    )
    return result


@router.get("/insights")
def list_ai_insights(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(AIInsight)
        .filter(AIInsight.user_id == current_user.id)
        .order_by(AIInsight.created_at.desc())
        .limit(20)
        .all()
    )
    return {"insights": [_serialize_insight(row) for row in rows]}


from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import mean
from typing import Optional

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cache import invalidate_cache, user_financial_cache_keys
from database import get_db
from models import (
    BankAccount,
    BillNegotiation,
    CreditProfile,
    NetWorthItem,
    SharedAccessGrant,
    Subscription,
    Transaction,
    User,
)
from oauth2 import get_current_user
from services.audit_service import write_audit_log
from utils.financial import clean_text, money, normalize_country, normalize_currency, parse_date

router = APIRouter(prefix="/api/financial-tools", tags=["financial-tools"])

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "cancel_requested"}
BILL_STATUSES = {"requested", "negotiating", "succeeded", "failed", "cancelled"}
NET_WORTH_TYPES = {"asset", "liability"}
SHARE_ROLES = {"viewer", "editor"}


class SubscriptionStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1, max_length=30)
    notes: Optional[str] = Field(default=None, max_length=1000)


class BillNegotiationCreate(BaseModel):
    providerName: str = Field(..., min_length=1, max_length=180)
    billType: str = Field(default="utility", max_length=80)
    currentAmount: Decimal = Field(..., gt=0)
    targetAmount: Optional[Decimal] = Field(default=None, gt=0)
    currency: str = "USD"
    country: str = "US"
    notes: Optional[str] = Field(default="", max_length=1000)


class BillNegotiationUpdate(BaseModel):
    status: Optional[str] = None
    currentAmount: Optional[Decimal] = Field(default=None, gt=0)
    targetAmount: Optional[Decimal] = Field(default=None, gt=0)
    negotiatedAmount: Optional[Decimal] = Field(default=None, ge=0)
    successFeePercentage: Optional[Decimal] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = Field(default=None, max_length=1000)


class NetWorthItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=180)
    itemType: str = Field(..., min_length=1, max_length=20)
    category: str = Field(default="other", max_length=80)
    balance: Decimal = Field(..., ge=0)
    currency: str = "USD"
    country: str = "US"
    notes: Optional[str] = Field(default="", max_length=1000)
    asOfDate: Optional[str] = None


class NetWorthItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=180)
    itemType: Optional[str] = Field(default=None, max_length=20)
    category: Optional[str] = Field(default=None, max_length=80)
    balance: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)
    asOfDate: Optional[str] = None


class CreditProfileCreate(BaseModel):
    score: int = Field(..., ge=300, le=850)
    bureau: str = Field(default="manual", max_length=80)
    scoringModel: str = Field(default="manual", max_length=80)
    status: str = Field(default="self_reported", max_length=40)
    notes: Optional[str] = Field(default="", max_length=1000)
    reportedAt: Optional[str] = None


class ShareGrantCreate(BaseModel):
    inviteEmail: str = Field(..., min_length=3, max_length=255)
    role: str = "viewer"


def _decimal(value) -> Decimal:
    return money(value or 0)


def _serialize_money(value) -> float:
    return float(_decimal(value))


def _normalized_name(value: str) -> str:
    return clean_text(value, 180).lower()


def _monthly_equivalent(amount: Decimal, frequency: str) -> Decimal:
    if frequency == "weekly":
        return amount * Decimal("4.3333")
    if frequency == "biweekly":
        return amount * Decimal("2.1667")
    if frequency == "quarterly":
        return amount / Decimal("3")
    if frequency == "yearly":
        return amount / Decimal("12")
    return amount


def _annual_equivalent(amount: Decimal, frequency: str) -> Decimal:
    return _monthly_equivalent(amount, frequency) * Decimal("12")


def _infer_frequency(gaps: list[int]) -> tuple[str, int]:
    avg_gap = round(mean(gaps)) if gaps else 30
    if avg_gap <= 10:
        return "weekly", max(avg_gap, 7)
    if avg_gap <= 20:
        return "biweekly", max(avg_gap, 14)
    if avg_gap <= 45:
        return "monthly", max(avg_gap, 30)
    if avg_gap <= 110:
        return "quarterly", max(avg_gap, 90)
    return "yearly", max(avg_gap, 365)


def _looks_like_subscription(rows: list[Transaction]) -> bool:
    if len(rows) < 2:
        return False
    amounts = [abs(_decimal(row.amount)) for row in rows]
    average_amount = sum(amounts, Decimal("0.00")) / Decimal(len(amounts))
    if average_amount <= 0:
        return False
    variance_limit = max(Decimal("2.00"), average_amount * Decimal("0.15"))
    if any(abs(amount - average_amount) > variance_limit for amount in amounts):
        return False
    dates = sorted(row.date for row in rows if row.date)
    gaps = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
    return any(5 <= gap <= 370 for gap in gaps)


def _serialize_subscription(subscription: Subscription) -> dict:
    amount = abs(_decimal(subscription.amount))
    return {
        "id": subscription.id,
        "displayName": subscription.display_name,
        "merchant": subscription.merchant,
        "amount": _serialize_money(amount),
        "currency": subscription.currency,
        "country": subscription.country,
        "category": subscription.category,
        "frequency": subscription.frequency,
        "monthlyCost": _serialize_money(_monthly_equivalent(amount, subscription.frequency)),
        "annualCost": _serialize_money(_annual_equivalent(amount, subscription.frequency)),
        "source": subscription.source,
        "status": subscription.status,
        "occurrenceCount": subscription.occurrence_count,
        "firstSeenDate": subscription.first_seen_date.isoformat() if subscription.first_seen_date else None,
        "lastSeenDate": subscription.last_seen_date.isoformat() if subscription.last_seen_date else None,
        "nextExpectedDate": subscription.next_expected_date.isoformat() if subscription.next_expected_date else None,
        "cancellationRequestedAt": subscription.cancellation_requested_at.isoformat() if subscription.cancellation_requested_at else None,
        "cancellationNotes": subscription.cancellation_notes,
        "updatedAt": subscription.updated_at.isoformat() if subscription.updated_at else None,
    }


def _serialize_bill(row: BillNegotiation) -> dict:
    current = _decimal(row.current_amount)
    negotiated = _decimal(row.negotiated_amount) if row.negotiated_amount is not None else None
    estimated = max(current - negotiated, Decimal("0.00")) if negotiated is not None else _decimal(row.estimated_savings)
    return {
        "id": row.id,
        "providerName": row.provider_name,
        "billType": row.bill_type,
        "currentAmount": _serialize_money(current),
        "targetAmount": _serialize_money(row.target_amount) if row.target_amount is not None else None,
        "negotiatedAmount": _serialize_money(negotiated) if negotiated is not None else None,
        "estimatedSavings": _serialize_money(estimated),
        "successFeePercentage": float(row.success_fee_percentage or 0),
        "currency": row.currency,
        "country": row.country,
        "status": row.status,
        "notes": row.notes,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_net_worth_item(row: NetWorthItem) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "itemType": row.item_type,
        "category": row.category,
        "balance": _serialize_money(row.balance),
        "currency": row.currency,
        "country": row.country,
        "source": row.source,
        "notes": row.notes,
        "asOfDate": row.as_of_date.isoformat() if row.as_of_date else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_credit(row: CreditProfile) -> dict:
    return {
        "id": row.id,
        "score": row.score,
        "bureau": row.bureau,
        "scoringModel": row.scoring_model,
        "status": row.status,
        "notes": row.notes,
        "reportedAt": row.reported_at.isoformat(),
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_share(row: SharedAccessGrant) -> dict:
    return {
        "id": row.id,
        "inviteEmail": row.invite_email,
        "role": row.role,
        "status": row.status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "revokedAt": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def _scan_subscriptions(db: Session, user_id: int) -> list[Subscription]:
    rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id, Transaction.amount < 0)
        .order_by(Transaction.date.asc())
        .all()
    )
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for row in rows:
        label = row.merchant or row.description or row.category
        key = _normalized_name(label)
        if key:
            grouped[key].append(row)

    detected = []
    for key, group in grouped.items():
        if not _looks_like_subscription(group):
            continue
        dates = sorted(row.date for row in group if row.date)
        gaps = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
        frequency, avg_gap = _infer_frequency(gaps)
        amounts = [abs(_decimal(row.amount)) for row in group]
        average_amount = sum(amounts, Decimal("0.00")) / Decimal(len(amounts))
        latest = max(group, key=lambda item: item.date)
        existing = (
            db.query(Subscription)
            .filter(Subscription.user_id == user_id, Subscription.normalized_name == key, Subscription.currency == latest.currency)
            .first()
        )
        if existing:
            subscription = existing
            if subscription.status in {"cancelled", "ignored"}:
                continue
            subscription.display_name = latest.merchant or latest.description or existing.display_name
            subscription.merchant = latest.merchant
            subscription.amount = money(average_amount)
            subscription.country = latest.country
            subscription.category = latest.category or "Subscriptions"
            subscription.frequency = frequency
            subscription.occurrence_count = len(group)
            subscription.first_seen_date = dates[0]
            subscription.last_seen_date = dates[-1]
            subscription.next_expected_date = dates[-1] + timedelta(days=avg_gap)
            subscription.source = "detected"
        else:
            subscription = Subscription(
                user_id=user_id,
                normalized_name=key,
                display_name=latest.merchant or latest.description or "Recurring charge",
                merchant=latest.merchant,
                amount=money(average_amount),
                currency=latest.currency,
                country=latest.country,
                category=latest.category or "Subscriptions",
                frequency=frequency,
                source="detected",
                status="active",
                occurrence_count=len(group),
                first_seen_date=dates[0],
                last_seen_date=dates[-1],
                next_expected_date=dates[-1] + timedelta(days=avg_gap),
            )
            db.add(subscription)
        detected.append(subscription)
    return detected


def _is_liability_account(account: BankAccount) -> bool:
    account_type = (account.account_type or "").lower()
    return any(term in account_type for term in ("credit", "loan", "mortgage", "debt"))


def _net_worth_payload(db: Session, user_id: int) -> dict:
    items = db.query(NetWorthItem).filter(NetWorthItem.user_id == user_id).order_by(NetWorthItem.updated_at.desc()).all()
    accounts = db.query(BankAccount).filter(BankAccount.user_id == user_id, BankAccount.status == "active").all()

    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"assets": Decimal("0.00"), "liabilities": Decimal("0.00")})
    account_items = []
    for account in accounts:
        balance = _decimal(account.balance)
        is_liability = _is_liability_account(account) or balance < 0
        amount = abs(balance)
        bucket = "liabilities" if is_liability else "assets"
        totals[account.currency][bucket] += amount
        account_items.append(
            {
                "id": f"account_{account.id}",
                "name": account.name,
                "itemType": "liability" if is_liability else "asset",
                "category": account.account_type,
                "balance": _serialize_money(amount),
                "currency": account.currency,
                "country": account.country,
                "source": "bank",
                "notes": account.institution_name or "",
                "asOfDate": account.last_synced_at.date().isoformat() if account.last_synced_at else None,
                "updatedAt": account.updated_at.isoformat() if account.updated_at else None,
            }
        )

    for item in items:
        bucket = "assets" if item.item_type == "asset" else "liabilities"
        totals[item.currency][bucket] += _decimal(item.balance)

    totals_by_currency = []
    for currency, values in sorted(totals.items()):
        assets = values["assets"]
        liabilities = values["liabilities"]
        totals_by_currency.append(
            {
                "currency": currency,
                "assets": _serialize_money(assets),
                "liabilities": _serialize_money(liabilities),
                "netWorth": _serialize_money(assets - liabilities),
            }
        )

    return {
        "totalsByCurrency": totals_by_currency,
        "manualItems": [_serialize_net_worth_item(item) for item in items],
        "accountItems": account_items,
    }


@router.get("/overview")
def get_financial_tools_overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.user_id == current_user.id)
        .order_by(Subscription.next_expected_date.asc(), Subscription.display_name.asc())
        .all()
    )
    bills = (
        db.query(BillNegotiation)
        .filter(BillNegotiation.user_id == current_user.id)
        .order_by(BillNegotiation.updated_at.desc())
        .all()
    )
    credit_history = (
        db.query(CreditProfile)
        .filter(CreditProfile.user_id == current_user.id)
        .order_by(CreditProfile.reported_at.desc(), CreditProfile.created_at.desc())
        .limit(12)
        .all()
    )
    shares = (
        db.query(SharedAccessGrant)
        .filter(SharedAccessGrant.user_id == current_user.id)
        .order_by(SharedAccessGrant.created_at.desc())
        .all()
    )
    monthly_subscription_cost = sum(
        (
            _monthly_equivalent(abs(_decimal(row.amount)), row.frequency)
            for row in subscriptions
            if row.status in ACTIVE_SUBSCRIPTION_STATUSES
        ),
        Decimal("0.00"),
    )
    return {
        "subscriptions": [_serialize_subscription(row) for row in subscriptions],
        "subscriptionSummary": {
            "activeCount": sum(1 for row in subscriptions if row.status in ACTIVE_SUBSCRIPTION_STATUSES),
            "monthlyCost": _serialize_money(monthly_subscription_cost),
            "annualCost": _serialize_money(monthly_subscription_cost * Decimal("12")),
        },
        "billNegotiations": [_serialize_bill(row) for row in bills],
        "billSummary": {
            "openCount": sum(1 for row in bills if row.status in {"requested", "negotiating"}),
            "estimatedSavings": _serialize_money(sum((_decimal(row.estimated_savings) for row in bills), Decimal("0.00"))),
        },
        "netWorth": _net_worth_payload(db, current_user.id),
        "creditProfile": _serialize_credit(credit_history[0]) if credit_history else None,
        "creditHistory": [_serialize_credit(row) for row in credit_history],
        "sharedAccess": [_serialize_share(row) for row in shares],
    }


@router.post("/subscriptions/scan")
def scan_subscriptions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    detected = _scan_subscriptions(db, current_user.id)
    write_audit_log(
        db,
        user_id=current_user.id,
        action="scan_subscriptions",
        entity_type="subscription",
        metadata={"detected": len(detected)},
        request=request,
    )
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"detected": len(detected), "subscriptions": [_serialize_subscription(row) for row in detected]}


@router.post("/subscriptions/{subscription_id}/cancel-request")
def request_subscription_cancellation(
    subscription_id: int,
    data: SubscriptionStatusUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscription = db.query(Subscription).filter(Subscription.id == subscription_id, Subscription.user_id == current_user.id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.status = "cancel_requested"
    subscription.cancellation_requested_at = datetime.utcnow()
    subscription.cancellation_notes = clean_text(data.notes, 1000)
    write_audit_log(
        db,
        user_id=current_user.id,
        action="request_subscription_cancellation",
        entity_type="subscription",
        entity_id=str(subscription.id),
        request=request,
    )
    db.commit()
    db.refresh(subscription)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_subscription(subscription)


@router.patch("/subscriptions/{subscription_id}")
def update_subscription_status(
    subscription_id: int,
    data: SubscriptionStatusUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscription = db.query(Subscription).filter(Subscription.id == subscription_id, Subscription.user_id == current_user.id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    status = data.status.strip().lower()
    if status not in {"active", "cancel_requested", "cancelled", "ignored"}:
        raise HTTPException(status_code=400, detail="Unsupported subscription status")
    subscription.status = status
    if data.notes is not None:
        subscription.cancellation_notes = clean_text(data.notes, 1000)
    write_audit_log(db, user_id=current_user.id, action="update_subscription", entity_type="subscription", entity_id=str(subscription.id), request=request)
    db.commit()
    db.refresh(subscription)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_subscription(subscription)


@router.post("/bill-negotiations")
def create_bill_negotiation(
    data: BillNegotiationCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bill = BillNegotiation(
        user_id=current_user.id,
        provider_name=clean_text(data.providerName, 180),
        bill_type=clean_text(data.billType, 80).lower() or "utility",
        current_amount=money(data.currentAmount),
        target_amount=money(data.targetAmount) if data.targetAmount is not None else None,
        currency=normalize_currency(data.currency),
        country=normalize_country(data.country),
        notes=clean_text(data.notes, 1000),
    )
    db.add(bill)
    db.flush()
    write_audit_log(db, user_id=current_user.id, action="create_bill_negotiation", entity_type="bill_negotiation", entity_id=str(bill.id), request=request)
    db.commit()
    db.refresh(bill)
    return _serialize_bill(bill)


@router.patch("/bill-negotiations/{bill_id}")
def update_bill_negotiation(
    bill_id: int,
    data: BillNegotiationUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bill = db.query(BillNegotiation).filter(BillNegotiation.id == bill_id, BillNegotiation.user_id == current_user.id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill negotiation not found")
    updates = data.dict(exclude_unset=True)
    if "status" in updates and updates["status"]:
        status = updates["status"].strip().lower()
        if status not in BILL_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported bill negotiation status")
        bill.status = status
    if "currentAmount" in updates and updates["currentAmount"] is not None:
        bill.current_amount = money(updates["currentAmount"])
    if "targetAmount" in updates:
        bill.target_amount = money(updates["targetAmount"]) if updates["targetAmount"] is not None else None
    if "negotiatedAmount" in updates:
        bill.negotiated_amount = money(updates["negotiatedAmount"]) if updates["negotiatedAmount"] is not None else None
    if "successFeePercentage" in updates and updates["successFeePercentage"] is not None:
        bill.success_fee_percentage = money(updates["successFeePercentage"])
    if "notes" in updates and updates["notes"] is not None:
        bill.notes = clean_text(updates["notes"], 1000)
    if bill.negotiated_amount is not None:
        bill.estimated_savings = max(_decimal(bill.current_amount) - _decimal(bill.negotiated_amount), Decimal("0.00"))
    write_audit_log(db, user_id=current_user.id, action="update_bill_negotiation", entity_type="bill_negotiation", entity_id=str(bill.id), request=request)
    db.commit()
    db.refresh(bill)
    return _serialize_bill(bill)


@router.delete("/bill-negotiations/{bill_id}")
def delete_bill_negotiation(
    bill_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bill = db.query(BillNegotiation).filter(BillNegotiation.id == bill_id, BillNegotiation.user_id == current_user.id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill negotiation not found")
    db.delete(bill)
    write_audit_log(db, user_id=current_user.id, action="delete_bill_negotiation", entity_type="bill_negotiation", entity_id=str(bill_id), request=request)
    db.commit()
    return {"message": "Bill negotiation deleted"}


@router.post("/net-worth/items")
def create_net_worth_item(
    data: NetWorthItemCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item_type = data.itemType.strip().lower()
    if item_type not in NET_WORTH_TYPES:
        raise HTTPException(status_code=400, detail="Net worth item type must be asset or liability")
    item = NetWorthItem(
        user_id=current_user.id,
        name=clean_text(data.name, 180),
        item_type=item_type,
        category=clean_text(data.category, 80).lower() or "other",
        balance=money(data.balance),
        currency=normalize_currency(data.currency),
        country=normalize_country(data.country),
        notes=clean_text(data.notes, 1000),
        as_of_date=parse_date(data.asOfDate) if data.asOfDate else date.today(),
    )
    db.add(item)
    db.flush()
    write_audit_log(db, user_id=current_user.id, action="create_net_worth_item", entity_type="net_worth_item", entity_id=str(item.id), request=request)
    db.commit()
    db.refresh(item)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_net_worth_item(item)


@router.patch("/net-worth/items/{item_id}")
def update_net_worth_item(
    item_id: int,
    data: NetWorthItemUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(NetWorthItem).filter(NetWorthItem.id == item_id, NetWorthItem.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Net worth item not found")
    updates = data.dict(exclude_unset=True)
    if "name" in updates and updates["name"]:
        item.name = clean_text(updates["name"], 180)
    if "itemType" in updates and updates["itemType"]:
        item_type = updates["itemType"].strip().lower()
        if item_type not in NET_WORTH_TYPES:
            raise HTTPException(status_code=400, detail="Net worth item type must be asset or liability")
        item.item_type = item_type
    if "category" in updates and updates["category"]:
        item.category = clean_text(updates["category"], 80).lower() or "other"
    if "balance" in updates and updates["balance"] is not None:
        item.balance = money(updates["balance"])
    if "currency" in updates and updates["currency"]:
        item.currency = normalize_currency(updates["currency"])
    if "country" in updates and updates["country"]:
        item.country = normalize_country(updates["country"])
    if "notes" in updates and updates["notes"] is not None:
        item.notes = clean_text(updates["notes"], 1000)
    if "asOfDate" in updates:
        item.as_of_date = parse_date(updates["asOfDate"]) if updates["asOfDate"] else None
    write_audit_log(db, user_id=current_user.id, action="update_net_worth_item", entity_type="net_worth_item", entity_id=str(item.id), request=request)
    db.commit()
    db.refresh(item)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_net_worth_item(item)


@router.delete("/net-worth/items/{item_id}")
def delete_net_worth_item(
    item_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(NetWorthItem).filter(NetWorthItem.id == item_id, NetWorthItem.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Net worth item not found")
    db.delete(item)
    write_audit_log(db, user_id=current_user.id, action="delete_net_worth_item", entity_type="net_worth_item", entity_id=str(item_id), request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"message": "Net worth item deleted"}


@router.post("/credit-profile")
def create_credit_profile(
    data: CreditProfileCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = CreditProfile(
        user_id=current_user.id,
        score=data.score,
        bureau=clean_text(data.bureau, 80),
        scoring_model=clean_text(data.scoringModel, 80),
        status=clean_text(data.status, 40).lower() or "self_reported",
        notes=clean_text(data.notes, 1000),
        reported_at=parse_date(data.reportedAt) if data.reportedAt else date.today(),
    )
    db.add(profile)
    db.flush()
    write_audit_log(db, user_id=current_user.id, action="create_credit_profile", entity_type="credit_profile", entity_id=str(profile.id), request=request)
    db.commit()
    db.refresh(profile)
    return _serialize_credit(profile)


@router.post("/shared-access")
def create_shared_access_grant(
    data: ShareGrantCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = data.role.strip().lower()
    if role not in SHARE_ROLES:
        raise HTTPException(status_code=400, detail="Shared access role must be viewer or editor")
    invite_email = clean_text(data.inviteEmail, 255).lower()
    if "@" not in invite_email:
        raise HTTPException(status_code=400, detail="Invite email must be valid")
    grant = SharedAccessGrant(user_id=current_user.id, invite_email=invite_email, role=role, status="invited")
    db.add(grant)
    db.flush()
    write_audit_log(db, user_id=current_user.id, action="create_shared_access", entity_type="shared_access", entity_id=str(grant.id), request=request)
    db.commit()
    db.refresh(grant)
    return _serialize_share(grant)


@router.delete("/shared-access/{grant_id}")
def revoke_shared_access_grant(
    grant_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    grant = db.query(SharedAccessGrant).filter(SharedAccessGrant.id == grant_id, SharedAccessGrant.user_id == current_user.id).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Shared access grant not found")
    grant.status = "revoked"
    grant.revoked_at = datetime.utcnow()
    write_audit_log(db, user_id=current_user.id, action="revoke_shared_access", entity_type="shared_access", entity_id=str(grant.id), request=request)
    db.commit()
    db.refresh(grant)
    return _serialize_share(grant)

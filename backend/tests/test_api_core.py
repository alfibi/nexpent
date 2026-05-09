import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./backend/tests/test_nexpent.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-api-tests")

from fastapi.testclient import TestClient

from database import Base, engine
from main import app


def setup_module():
    db_path = Path("backend/tests/test_nexpent.db")
    if db_path.exists():
        db_path.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module():
    Base.metadata.drop_all(bind=engine)
    db_path = Path("backend/tests/test_nexpent.db")
    if db_path.exists():
        db_path.unlink()


def test_auth_and_manual_transaction_flow():
    client = TestClient(app)

    register = client.post(
        "/api/auth/register",
        json={"username": "apiuser", "email": "apiuser@example.com", "password": "strongpass123"},
    )
    assert register.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"username": "apiuser", "password": "strongpass123", "remember": False},
    )
    assert login.status_code == 200

    created = client.post(
        "/api/transactions",
        json={
            "amount": -24.99,
            "currency": "USD",
            "country": "US",
            "merchant": "Starbucks",
            "description": "Card payment at Starbucks",
            "category": "Food & Drinks",
            "subcategory": "Coffee",
            "paymentMethod": "card",
            "source": "manual",
            "date": "2026-04-25",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["type"] == "expense"
    assert payload["currency"] == "USD"

    duplicate = client.post(
        "/api/transactions",
        json={
            "amount": -24.99,
            "currency": "USD",
            "country": "US",
            "merchant": "Starbucks",
            "description": "Card payment at Starbucks",
            "category": "Food & Drinks",
            "subcategory": "Coffee",
            "paymentMethod": "card",
            "source": "manual",
            "date": "2026-04-25",
        },
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/transactions?category=Food%20%26%20Drinks")
    assert listed.status_code == 200
    assert len(listed.json()["transactions"]) == 1


def test_financial_tools_flow():
    client = TestClient(app)

    register = client.post(
        "/api/auth/register",
        json={"username": "planneruser", "email": "planner@example.com", "password": "strongpass123"},
    )
    assert register.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"username": "planneruser", "password": "strongpass123", "remember": False},
    )
    assert login.status_code == 200

    for tx_date in ("2026-01-05", "2026-02-05", "2026-03-05"):
        created = client.post(
            "/api/transactions",
            json={
                "amount": -12.99,
                "currency": "USD",
                "country": "US",
                "merchant": "StreamBox",
                "description": "Monthly streaming plan",
                "category": "Subscriptions",
                "paymentMethod": "card",
                "source": "manual",
                "date": tx_date,
            },
        )
        assert created.status_code == 200

    scanned = client.post("/api/financial-tools/subscriptions/scan")
    assert scanned.status_code == 200
    scan_payload = scanned.json()
    assert scan_payload["detected"] == 1
    subscription_id = scan_payload["subscriptions"][0]["id"]

    cancel = client.post(
        f"/api/financial-tools/subscriptions/{subscription_id}/cancel-request",
        json={"status": "cancel_requested", "notes": "No longer needed"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancel_requested"

    bill = client.post(
        "/api/financial-tools/bill-negotiations",
        json={
            "providerName": "Fiber Co",
            "billType": "internet",
            "currentAmount": 100,
            "targetAmount": 80,
            "currency": "USD",
            "country": "US",
        },
    )
    assert bill.status_code == 200

    item = client.post(
        "/api/financial-tools/net-worth/items",
        json={
            "name": "Brokerage",
            "itemType": "asset",
            "category": "investment",
            "balance": 2500,
            "currency": "USD",
            "country": "US",
        },
    )
    assert item.status_code == 200

    credit = client.post(
        "/api/financial-tools/credit-profile",
        json={"score": 735, "bureau": "manual", "scoringModel": "FICO-like", "reportedAt": "2026-04-01"},
    )
    assert credit.status_code == 200

    share = client.post(
        "/api/financial-tools/shared-access",
        json={"inviteEmail": "partner@example.com", "role": "viewer"},
    )
    assert share.status_code == 200

    overview = client.get("/api/financial-tools/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["subscriptionSummary"]["activeCount"] == 1
    assert payload["creditProfile"]["score"] == 735
    assert payload["netWorth"]["totalsByCurrency"][0]["netWorth"] == 2500.0


def test_receipt_upload_creates_receipt_transaction(monkeypatch):
    from routers import receipts

    client = TestClient(app)

    register = client.post(
        "/api/auth/register",
        json={"username": "receiptuser", "email": "receipt@example.com", "password": "strongpass123"},
    )
    assert register.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"username": "receiptuser", "password": "strongpass123", "remember": False},
    )
    assert login.status_code == 200

    monkeypatch.setattr(receipts, "_extract_ocr_text", lambda path: ("Corner Store\nTotal $12.34", "Corner Store\nTotal $12.34"))
    monkeypatch.setattr(
        receipts.llm_service,
        "generate_json",
        lambda task, payload, schema: {
            "merchant": "Corner Store",
            "amount": 12.34,
            "currency": "USD",
            "date": "2026-04-26",
            "items": [{"name": "Milk", "quantity": 1, "totalPrice": 4.99}],
            "category": "Groceries",
        },
    )

    uploaded = client.post(
        "/api/receipts/upload",
        data={"country": "US", "currency": "USD"},
        files={"file": ("receipt.jpg", b"fake image bytes", "image/jpeg")},
    )

    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["merchant"] == "Corner Store"
    assert payload["amount"] == 12.34
    assert payload["items"][0]["name"] == "Milk"
    assert payload["transaction"]["amount"] == -12.34
    assert payload["transaction"]["category"] == "Groceries"
    assert payload["transaction"]["source"] == "receipt"

    listed = client.get("/api/transactions?source=receipt")
    assert listed.status_code == 200
    transactions = listed.json()["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["receiptId"] == payload["id"]

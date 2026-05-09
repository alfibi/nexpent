import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from config import (
    ACCESS_TOKEN_MINUTES,
    APP_ENV,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    CORS_ORIGINS,
    FRONTEND_DIST_DIR,
    FRONTEND_INDEX,
    RECEIPT_UPLOAD_DIR,
    REMEMBER_ME_DAYS,
)
from database import SessionLocal, engine
from models import (
    Base,
    User,
    Category,
    Subcategory,
    PaymentMethod,
    ExpenseNew,
    Income,
    UserProfile,
    RecurringPattern,
    Budget,
)
from crud import fetch_all_transactions, fetch_latest_activity
from routers import (
    ai,
    analytics_api,
    auth_api,
    banks,
    budgets,
    dashboard,
    financial_tools,
    goals,
    insights,
    lookups,
    receipt_extraction,
    receipts,
    recurring,
    transactions,
)
from oauth2 import create_access_token, get_current_user
from schemas import RegisterIn, LoginRequest, ProfileUpdate
from passlib.hash import argon2
import bcrypt
from cache import close_redis, init_redis, invalidate_cache, user_financial_cache_keys
from scheduler import start_scheduler, stop_scheduler
from middleware.rate_limit import RateLimitMiddleware

# ---------------------------------------------------------
# APP
# ---------------------------------------------------------
app = FastAPI(title="Nexpent API")

if APP_ENV == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response

# ---------------------------------------------------------
# ROUTERS
# ---------------------------------------------------------
app.include_router(lookups.router)
app.include_router(dashboard.router)
app.include_router(insights.router)
app.include_router(recurring.router)
app.include_router(budgets.router)
app.include_router(budgets.router, prefix="/api")
app.include_router(auth_api.router)
app.include_router(banks.router)
app.include_router(transactions.router)
app.include_router(receipt_extraction.router, prefix="/api")
app.include_router(receipts.router)
app.include_router(goals.router)
app.include_router(financial_tools.router)
app.include_router(analytics_api.router)
app.include_router(ai.router)

# ---------------------------------------------------------
# DB
# ---------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    try:
        RECEIPT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            _apply_lightweight_schema_upgrades(connection)
            for statement in (
                "CREATE INDEX IF NOT EXISTS ix_expenses_new_user_date ON expenses_new (user_id, date DESC)",
                "CREATE INDEX IF NOT EXISTS ix_income_user_date ON income (user_id, date DESC)",
                "CREATE INDEX IF NOT EXISTS ix_expenses_new_user_category ON expenses_new (user_id, category_id)",
                "CREATE INDEX IF NOT EXISTS ix_transactions_user_date_runtime ON transactions (user_id, date DESC)",
                "CREATE INDEX IF NOT EXISTS ix_transactions_user_category_runtime ON transactions (user_id, category)",
                "CREATE INDEX IF NOT EXISTS ix_bank_accounts_user_runtime ON bank_accounts (user_id)",
            ):
                connection.execute(text(statement))
        print("✅ Database tables created / verified.")
    except Exception as e:
        print(f"⚠️  Could not connect to database: {e}")
        print("   The server will start, but DB operations will fail.")
    await init_redis()
    try:
        start_scheduler()
    except Exception as e:
        print(f"⚠️  Scheduler failed to start: {e}")


def _apply_lightweight_schema_upgrades(connection):
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names(schema="public" if engine.dialect.name == "postgresql" else None))
    if "budgets" not in existing_tables:
        return

    schema_prefix = "public." if engine.dialect.name == "postgresql" else ""
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("budgets", schema="public" if engine.dialect.name == "postgresql" else None)
    }
    budget_columns = {
        "period": "VARCHAR(20) DEFAULT 'monthly' NOT NULL",
        "currency": "VARCHAR(3) DEFAULT 'USD' NOT NULL",
        "country": "VARCHAR(2) DEFAULT 'US' NOT NULL",
        "starts_on": "DATE",
    }
    for column_name, column_type in budget_columns.items():
        if column_name in existing_columns:
            continue
        connection.execute(text(f"ALTER TABLE {schema_prefix}budgets ADD COLUMN {column_name} {column_type}"))

@app.on_event("shutdown")
async def on_shutdown():
    stop_scheduler()
    await close_redis()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------
# STATIC + ROOT
# ---------------------------------------------------------
if (FRONTEND_DIST_DIR / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")),
        name="assets",
    )


def frontend_response():
    if FRONTEND_INDEX.is_file():
        return FileResponse(str(FRONTEND_INDEX))

    return JSONResponse(
        status_code=503,
        content={
            "message": (
                "Frontend static files are not being served by FastAPI in the current Next.js setup. "
                "Run `npm run dev` in the frontend directory and open http://localhost:3000 during development."
            )
        },
    )


@app.get("/")
def root():
    return frontend_response()


# ---------------------------------------------------------
# INPUT MODELS
# ---------------------------------------------------------
class ExpenseIn(BaseModel):
    amount: float = Field(..., gt=0)
    category_id: int = Field(..., gt=0)
    subcategory_id: int = Field(..., gt=0)
    payment_method_id: int = Field(..., gt=0)
    description: str = Field(default="", max_length=500)
    date: Optional[str] = None


class IncomeIn(BaseModel):
    amount: float = Field(..., gt=0)
    type: str = Field(..., min_length=1, max_length=50)
    source: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    payment_method: Optional[str] = None
    is_recurring: bool = False
    frequency: Optional[str] = None
    date: Optional[str] = None


# ---------------------------------------------------------
# AUTH HELPERS
# ---------------------------------------------------------
def verify_password(plain_password: str, hashed_password: str, algo: str) -> bool:
    try:
        if algo == "argon2":
            return argon2.verify(plain_password, hashed_password)
        elif algo == "bcrypt":
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        else:
            return False
    except Exception:
        return False


def serialize_user_with_profile(user: User, profile: Optional[UserProfile]) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "profile": {
            "full_name": profile.full_name if profile else None,
            "dob": profile.dob.isoformat() if profile and profile.dob else None,
            "phone": profile.phone if profile else None,
            "address_line1": profile.address_line1 if profile else None,
            "address_line2": profile.address_line2 if profile else None,
            "city": profile.city if profile else None,
            "state": profile.state if profile else None,
            "country": profile.country if profile else None,
            "postal_code": profile.postal_code if profile else None,
        },
    }


def parse_optional_date(raw_value: Optional[str]) -> date:
    if not raw_value:
        return date.today()

    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format") from exc


def parse_optional_datetime(raw_value: Optional[str]) -> datetime:
    if not raw_value:
        return datetime.now()

    try:
        return datetime.strptime(raw_value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format") from exc


# ---------------------------------------------------------
# REGISTER
# ---------------------------------------------------------
@app.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    username = data.username.strip()
    email = data.email.strip().lower()
    password = data.password.strip()

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="Username, email, and password are required")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    user = User(
        username=username,
        email=email,
        password_hash=hashed,
        password_algo="bcrypt",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    profile = UserProfile(user_id=user.id)
    db.add(profile)
    db.commit()

    return {"message": "User registered successfully"}


# ---------------------------------------------------------
# LOGIN
# ---------------------------------------------------------
@app.post("/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    username = data.username.strip()
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not verify_password(data.password, user.password_hash, user.password_algo):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    remember = data.remember or False

    expires = (
        timedelta(days=REMEMBER_ME_DAYS)
        if remember
        else timedelta(minutes=ACCESS_TOKEN_MINUTES)
    )

    token = create_access_token({"sub": user.username}, expires_delta=expires)

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=int(expires.total_seconds()),
        path="/",
    )

    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    payload = serialize_user_with_profile(user, profile)
    payload.update(
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": int(expires.total_seconds()),
        }
    )
    return payload


# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------
@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",
    )
    return {"message": "Logged out"}




# ---------------------------------------------------------
# ME
# ---------------------------------------------------------
@app.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.id)
        .first()
    )
    return serialize_user_with_profile(current_user, profile)


# ---------------------------------------------------------
# PROFILE
# ---------------------------------------------------------
@app.get("/profile")
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.id)
        .first()
    )

    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return serialize_user_with_profile(current_user, profile)


@app.put("/profile")
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.id)
        .first()
    )

    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    profile_updates = (
        data.model_dump(exclude_unset=True)
        if hasattr(data, "model_dump")
        else data.dict(exclude_unset=True)
    )

    for field, value in profile_updates.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)

    return {"message": "Profile updated"}


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
# ---------------------------------------------------------
# ADD EXPENSE / INCOME
# ---------------------------------------------------------
@app.post("/add-expense")
async def add_expense(
    expense: ExpenseIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category = db.query(Category).filter(Category.id == expense.category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="Invalid category")

    subcategory = (
        db.query(Subcategory)
        .filter(
            Subcategory.id == expense.subcategory_id,
            Subcategory.category_id == expense.category_id,
        )
        .first()
    )
    if not subcategory:
        raise HTTPException(status_code=400, detail="Invalid subcategory")

    payment_method = (
        db.query(PaymentMethod)
        .filter(PaymentMethod.id == expense.payment_method_id)
        .first()
    )
    if not payment_method:
        raise HTTPException(status_code=400, detail="Invalid payment method")

    d = parse_optional_date(expense.date)

    exp = ExpenseNew(
        user_id=current_user.id,
        amount=expense.amount,
        category_id=category.id,
        subcategory_id=subcategory.id,
        payment_method_id=payment_method.id,
        description=expense.description,
        date=d,
    )
    db.add(exp)
    try:
        db.commit()
        db.refresh(exp)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to add expense: {exc}")

    # Invalidate cache
    await invalidate_cache(*user_financial_cache_keys(current_user.id))

    return {
        "message": "Expense added",
        "expense": {
            "id": exp.id,
            "amount": float(exp.amount),
            "date": exp.date.isoformat() if exp.date else None,
        },
    }


@app.post("/add-income")
async def add_income(
    income: IncomeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = parse_optional_datetime(income.date)

    inc = Income(
        user_id=current_user.id,
        amount=income.amount,
        type=income.type,
        source=income.source,
        description=income.description,
        payment_method=income.payment_method,
        is_recurring=income.is_recurring,
        frequency=income.frequency if income.is_recurring else None,
        date=d,
    )
    db.add(inc)
    try:
        db.commit()
        db.refresh(inc)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to add income: {exc}")

    # Invalidate cache
    await invalidate_cache(*user_financial_cache_keys(current_user.id))

    return {
        "message": "Income added",
        "income": {
            "id": inc.id,
            "amount": float(inc.amount),
            "type": inc.type,
            "source": inc.source,
            "date": inc.date.isoformat() if inc.date else None,
        },
    }


# ---------------------------------------------------------
# TOTALS
# ---------------------------------------------------------
@app.get("/totals")
def totals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total_expenses = (
        db.query(func.coalesce(func.sum(ExpenseNew.amount), 0))
        .filter(ExpenseNew.user_id == current_user.id)
        .scalar()
    )
    total_income = (
        db.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id)
        .scalar()
    )

    return {
        "total_expenses": float(total_expenses),
        "total_income": float(total_income),
        "net": float(total_income - total_expenses),
    }


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "database": "unavailable",
                "detail": str(exc),
            },
        )

    return {
        "status": "ok",
        "database": "connected",
        "frontend_built": FRONTEND_INDEX.is_file(),
    }


# ---------------------------------------------------------
# LATEST TRANSACTIONS
# ---------------------------------------------------------
@app.get("/latest-transactions")
def latest_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return fetch_latest_activity(db, current_user, limit=25)


@app.get("/transactions.html")
def transactions_page():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    file_path = os.path.join(base_dir, "frontend", "transactions.html")
    return FileResponse(file_path)


# ---------------------------------------------------------
# ALL TRANSACTIONS
# ---------------------------------------------------------
@app.get("/all-transactions")
def all_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return fetch_all_transactions(db, current_user)


# ---------------------------------------------------------
# MONTHLY TREND
# ---------------------------------------------------------
@app.get("/monthly-trend")
def monthly_trend(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(
            func.date_trunc("month", ExpenseNew.date).label("month"),
            func.sum(ExpenseNew.amount).label("total"),
        )
        .filter(ExpenseNew.user_id == current_user.id)
        .group_by(func.date_trunc("month", ExpenseNew.date))
        .order_by(func.date_trunc("month", ExpenseNew.date))
        .all()
    )

    return [
        {"month": r.month.strftime("%Y-%m"), "total": float(r.total)}
        for r in rows
    ]


# ---------------------------------------------------------
# CATEGORY PIE
# ---------------------------------------------------------
@app.get("/category-pie")
def category_pie(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Category.name, func.sum(ExpenseNew.amount).label("total"))
        .join(ExpenseNew, ExpenseNew.category_id == Category.id)
        .filter(ExpenseNew.user_id == current_user.id)
        .group_by(Category.name)
        .order_by(Category.name)
        .all()
    )

    return [
        {"category": name, "total": float(total)}
        for name, total in rows
    ]


# ---------------------------------------------------------
# INCOME VS EXPENSES
# ---------------------------------------------------------
@app.get("/income-vs-expenses-monthly")
def income_vs_expenses_monthly(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    income_q = (
        db.query(
            func.date_trunc("month", Income.date).label("month"),
            func.sum(Income.amount).label("income"),
        )
        .filter(Income.user_id == current_user.id)
        .group_by(func.date_trunc("month", Income.date))
        .subquery()
    )

    expenses_q = (
        db.query(
            func.date_trunc("month", ExpenseNew.date).label("month"),
            func.sum(ExpenseNew.amount).label("expenses"),
        )
        .filter(ExpenseNew.user_id == current_user.id)
        .group_by(func.date_trunc("month", ExpenseNew.date))
        .subquery()
    )

    months_q = (
        db.query(func.date_trunc("month", Income.date).label("month"))
        .filter(Income.user_id == current_user.id)
        .union(
            db.query(func.date_trunc("month", ExpenseNew.date).label("month"))
            .filter(ExpenseNew.user_id == current_user.id)
        )
        .subquery()
    )

    rows = (
        db.query(
            months_q.c.month.label("month"),
            func.coalesce(income_q.c.income, 0).label("income"),
            func.coalesce(expenses_q.c.expenses, 0).label("expenses"),
        )
        .outerjoin(income_q, income_q.c.month == months_q.c.month)
        .outerjoin(expenses_q, expenses_q.c.month == months_q.c.month)
        .order_by(months_q.c.month)
        .all()
    )

    return [
        {
            "month": r.month.strftime("%Y-%m"),
            "income": float(r.income),
            "expenses": float(r.expenses),
        }
        for r in rows
    ]


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_catch_all(full_path: str):
    requested_file = FRONTEND_DIST_DIR / full_path
    if requested_file.is_file():
        return FileResponse(str(requested_file))

    if "." in Path(full_path).name:
        raise HTTPException(status_code=404, detail="Not found")

    return frontend_response()

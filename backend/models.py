from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Date, Text
from sqlalchemy import Index, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)

    password_hash = Column(String, nullable=False)
    password_algo = Column(String, default="argon2")

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    token_version = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    profile = relationship("UserProfile", back_populates="user", uselist=False)

    # ADD THESE BACK
    expenses = relationship("ExpenseNew", back_populates="user")
    income = relationship("Income", back_populates="user")
    recurring_patterns = relationship("RecurringPattern", back_populates="user")
    budgets = relationship("Budget", back_populates="user")
    bank_accounts = relationship("BankAccount", back_populates="user")
    provider_tokens = relationship("ProviderToken", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    receipts = relationship("Receipt", back_populates="user")
    savings_goals = relationship("SavingsGoal", back_populates="user")
    ai_insights = relationship("AIInsight", back_populates="user")
    ai_chat_messages = relationship("AIChatMessage", back_populates="user")
    monthly_summaries = relationship("MonthlySummary", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")
    bill_negotiations = relationship("BillNegotiation", back_populates="user")
    net_worth_items = relationship("NetWorthItem", back_populates="user")
    credit_profiles = relationship("CreditProfile", back_populates="user")
    shared_access_grants = relationship("SharedAccessGrant", back_populates="user")


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User")



class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)

    full_name = Column(String)
    dob = Column(Date)
    phone = Column(String)
    address_line1 = Column(String)
    address_line2 = Column(String)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    postal_code = Column(String)

    user = relationship("User", back_populates="profile")
# CATEGORY
# ---------------------------------------------------------
class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    subcategories = relationship("Subcategory", back_populates="category")
    expenses = relationship("ExpenseNew", back_populates="category")


# ---------------------------------------------------------
# SUBCATEGORY
# ---------------------------------------------------------
class Subcategory(Base):
    __tablename__ = "subcategories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    category = relationship("Category", back_populates="subcategories")
    expenses = relationship("ExpenseNew", back_populates="subcategory")


# ---------------------------------------------------------
# PAYMENT METHOD
# ---------------------------------------------------------
class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    expenses = relationship("ExpenseNew", back_populates="payment_method")


# ---------------------------------------------------------
# EXPENSE (NEW MODEL)
# ---------------------------------------------------------
class ExpenseNew(Base):
    __tablename__ = "expenses_new"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"), nullable=False)
    payment_method_id = Column(Integer, ForeignKey("payment_methods.id"), nullable=False)
    description = Column(Text)
    date = Column(Date, nullable=False)

    user = relationship("User", back_populates="expenses")
    category = relationship("Category", back_populates="expenses")
    subcategory = relationship("Subcategory", back_populates="expenses")
    payment_method = relationship("PaymentMethod", back_populates="expenses")


# ---------------------------------------------------------
# INCOME
# ---------------------------------------------------------
class Income(Base):
    __tablename__ = "income"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    type = Column(String(20), nullable=False)
    source = Column(String, nullable=False)
    description = Column(Text)
    payment_method = Column(String(50))
    is_recurring = Column(Boolean, default=False)
    frequency = Column(String(20))
    date = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="income")


# ---------------------------------------------------------
# RECURRING PATTERN
# ---------------------------------------------------------
class RecurringPattern(Base):
    __tablename__ = "recurring_patterns"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    description = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    transaction_type = Column(String(10), nullable=False, default="expense")  # expense | income

    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"), nullable=True)
    payment_method_id = Column(Integer, ForeignKey("payment_methods.id"), nullable=True)

    frequency = Column(String(20), nullable=False)  # weekly/biweekly/monthly/quarterly/yearly
    avg_gap_days = Column(Integer, nullable=False, default=30)
    occurrence_count = Column(Integer, nullable=False, default=0)

    status = Column(String(20), nullable=False, default="suggested")  # suggested | confirmed | dismissed
    auto_create = Column(Boolean, default=False)

    last_seen_date = Column(Date, nullable=True)
    next_expected_date = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="recurring_patterns")
    category = relationship("Category")
    subcategory = relationship("Subcategory")
    payment_method_rel = relationship("PaymentMethod")


# ---------------------------------------------------------
# BUDGET
# ---------------------------------------------------------
class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    monthly_limit = Column(Numeric(10, 2), nullable=False)
    period = Column(String(20), nullable=False, default="monthly")
    currency = Column(String(3), nullable=False, default="USD")
    country = Column(String(2), nullable=False, default="US")
    starts_on = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="budgets")
    category = relationship("Category")

    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "period", name="uq_budget_user_category_period"),
        Index("ix_budgets_user_category", "user_id", "category_id"),
    )


class ProviderToken(Base):
    __tablename__ = "provider_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    country = Column(String(2), nullable=False)
    encrypted_token = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="provider_tokens")

    __table_args__ = (
        Index("ix_provider_tokens_user_provider", "user_id", "provider"),
    )


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider_token_id = Column(Integer, ForeignKey("provider_tokens.id"), nullable=True)
    provider = Column(String(50), nullable=False)
    provider_account_id = Column(String(120), nullable=False)
    name = Column(String(160), nullable=False)
    mask = Column(String(12), nullable=True)
    institution_name = Column(String(160), nullable=True)
    account_type = Column(String(50), nullable=False, default="checking")
    balance = Column(Numeric(14, 2), nullable=False, default=0)
    available_balance = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), nullable=False)
    country = Column(String(2), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="bank_accounts")
    provider_token = relationship("ProviderToken")
    transactions = relationship("Transaction", back_populates="account")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "provider_account_id", name="uq_bank_account_provider_id"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=True, index=True)
    provider_transaction_id = Column(String(160), nullable=True)
    fingerprint = Column(String(128), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    country = Column(String(2), nullable=False)
    type = Column(String(20), nullable=False)
    merchant = Column(String(180), nullable=True)
    description = Column(Text, nullable=False, default="")
    category = Column(String(120), nullable=False, default="Uncategorized")
    subcategory = Column(String(120), nullable=True)
    payment_method = Column(String(50), nullable=False, default="manual")
    source = Column(String(30), nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
    account = relationship("BankAccount", back_populates="transactions")
    receipt = relationship("Receipt", back_populates="transaction", foreign_keys=[receipt_id])

    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_transaction_user_fingerprint"),
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_user_category", "user_id", "category"),
        Index("ix_transactions_provider_transaction_id", "provider_transaction_id"),
    )


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    image_path = Column(Text, nullable=False)
    raw_text = Column(Text, nullable=False, default="")
    cleaned_text = Column(Text, nullable=False, default="")
    merchant = Column(String(180), nullable=True)
    amount = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="USD")
    country = Column(String(2), nullable=False, default="US")
    purchased_at = Column(Date, nullable=True)
    status = Column(String(30), nullable=False, default="processed")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="receipts")
    transaction = relationship(
        "Transaction",
        back_populates="receipt",
        foreign_keys="Transaction.receipt_id",
        uselist=False,
    )
    items = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False, index=True)
    name = Column(String(180), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False, default=1)
    unit_price = Column(Numeric(14, 2), nullable=True)
    total_price = Column(Numeric(14, 2), nullable=False, default=0)
    category = Column(String(120), nullable=True)

    receipt = relationship("Receipt", back_populates="items")


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    target_amount = Column(Numeric(14, 2), nullable=False)
    current_amount = Column(Numeric(14, 2), nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="USD")
    country = Column(String(2), nullable=False, default="US")
    target_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="savings_goals")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    normalized_name = Column(String(180), nullable=False)
    display_name = Column(String(180), nullable=False)
    merchant = Column(String(180), nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    country = Column(String(2), nullable=False, default="US")
    category = Column(String(120), nullable=False, default="Subscriptions")
    frequency = Column(String(20), nullable=False, default="monthly")
    source = Column(String(30), nullable=False, default="detected")
    status = Column(String(30), nullable=False, default="active")
    occurrence_count = Column(Integer, nullable=False, default=0)
    first_seen_date = Column(Date, nullable=True)
    last_seen_date = Column(Date, nullable=True)
    next_expected_date = Column(Date, nullable=True)
    cancellation_requested_at = Column(DateTime, nullable=True)
    cancellation_notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscriptions")

    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", "currency", name="uq_subscription_user_name_currency"),
        Index("ix_subscriptions_user_status", "user_id", "status"),
    )


class BillNegotiation(Base):
    __tablename__ = "bill_negotiations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider_name = Column(String(180), nullable=False)
    bill_type = Column(String(80), nullable=False, default="utility")
    current_amount = Column(Numeric(14, 2), nullable=False)
    target_amount = Column(Numeric(14, 2), nullable=True)
    negotiated_amount = Column(Numeric(14, 2), nullable=True)
    estimated_savings = Column(Numeric(14, 2), nullable=False, default=0)
    success_fee_percentage = Column(Numeric(5, 2), nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="USD")
    country = Column(String(2), nullable=False, default="US")
    status = Column(String(30), nullable=False, default="requested")
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="bill_negotiations")

    __table_args__ = (
        Index("ix_bill_negotiations_user_status", "user_id", "status"),
    )


class NetWorthItem(Base):
    __tablename__ = "net_worth_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(180), nullable=False)
    item_type = Column(String(20), nullable=False)
    category = Column(String(80), nullable=False, default="other")
    balance = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    country = Column(String(2), nullable=False, default="US")
    source = Column(String(30), nullable=False, default="manual")
    notes = Column(Text, nullable=False, default="")
    as_of_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="net_worth_items")

    __table_args__ = (
        Index("ix_net_worth_items_user_type", "user_id", "item_type"),
    )


class CreditProfile(Base):
    __tablename__ = "credit_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    bureau = Column(String(80), nullable=False, default="manual")
    scoring_model = Column(String(80), nullable=False, default="manual")
    status = Column(String(40), nullable=False, default="self_reported")
    notes = Column(Text, nullable=False, default="")
    reported_at = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="credit_profiles")

    __table_args__ = (
        Index("ix_credit_profiles_user_reported", "user_id", "reported_at"),
    )


class SharedAccessGrant(Base):
    __tablename__ = "shared_access_grants"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invite_email = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, default="viewer")
    status = Column(String(30), nullable=False, default="invited")
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="shared_access_grants")

    __table_args__ = (
        Index("ix_shared_access_user_status", "user_id", "status"),
    )


class AIInsight(Base):
    __tablename__ = "ai_insights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    insight_type = Column(String(50), nullable=False)
    title = Column(String(180), nullable=False)
    summary = Column(Text, nullable=False)
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="ai_insights")


class AIChatMessage(Base):
    __tablename__ = "ai_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="ai_chat_messages")


class MonthlySummary(Base):
    __tablename__ = "monthly_summaries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False)
    currency = Column(String(3), nullable=False)
    country = Column(String(2), nullable=False)
    income = Column(Numeric(14, 2), nullable=False, default=0)
    expenses = Column(Numeric(14, 2), nullable=False, default=0)
    savings = Column(Numeric(14, 2), nullable=False, default=0)
    savings_rate = Column(Numeric(8, 4), nullable=False, default=0)
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="monthly_summaries")

    __table_args__ = (
        UniqueConstraint("user_id", "month", "currency", name="uq_monthly_summary_user_month_currency"),
        Index("ix_monthly_summaries_user_month", "user_id", "month"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(80), nullable=False)
    entity_type = Column(String(80), nullable=False)
    entity_id = Column(String(120), nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    ip_address = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")

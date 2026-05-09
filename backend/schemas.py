from datetime import date
from typing import Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: Optional[bool] = False


class RegisterIn(BaseModel):
    username: str
    email: str
    password: str


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    dob: Optional[date] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None


class BudgetCreate(BaseModel):
    category_id: int
    monthly_limit: float
    period: Optional[str] = "monthly"
    currency: Optional[str] = "USD"
    country: Optional[str] = "US"


class BudgetUpdate(BaseModel):
    category_id: Optional[int] = None
    monthly_limit: Optional[float] = None
    period: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None


class AutoCreateToggle(BaseModel):
    enabled: bool

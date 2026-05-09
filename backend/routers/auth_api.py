from datetime import timedelta

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session, joinedload

from config import ACCESS_TOKEN_MINUTES, COOKIE_SAMESITE, COOKIE_SECURE, REMEMBER_ME_DAYS
from database import get_db
from models import (
    AIChatMessage,
    AIInsight,
    AuditLog,
    BankAccount,
    BillNegotiation,
    Budget,
    CreditProfile,
    ExpenseNew,
    Income,
    MonthlySummary,
    NetWorthItem,
    ProviderToken,
    Receipt,
    ReceiptItem,
    SavingsGoal,
    SharedAccessGrant,
    Subscription,
    Transaction,
    User,
    UserProfile,
)
from oauth2 import create_access_token, get_current_user
from schemas import LoginRequest, ProfileUpdate, RegisterIn
from security import hash_password, verify_password
from services.audit_service import write_audit_log

router = APIRouter(prefix="/api/auth", tags=["api-auth"])


def _serialize_user(user: User, profile: Optional[UserProfile]) -> dict:
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


def _get_or_create_profile(db: Session, user_id: int) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile:
        return profile

    profile = UserProfile(user_id=user_id)
    db.add(profile)
    db.flush()
    return profile


@router.post("/register")
def register_api(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    username = data.username.strip()
    email = data.email.strip().lower()
    password = data.password.strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password, "argon2"),
        password_algo="argon2",
    )
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id))
    write_audit_log(db, user_id=user.id, action="register", entity_type="user", entity_id=str(user.id), request=request)
    db.commit()
    return {"message": "User registered successfully"}


@router.post("/login")
def login_api(data: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    username = data.username.strip()
    user = (
        db.query(User)
        .options(joinedload(User.profile))
        .filter(User.username == username, User.is_active.is_(True))
        .first()
    )
    if not user or not verify_password(data.password, user.password_hash, user.password_algo):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    expires = timedelta(days=REMEMBER_ME_DAYS) if data.remember else timedelta(minutes=ACCESS_TOKEN_MINUTES)
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

    payload = _serialize_user(user, user.profile)
    payload.update({"access_token": token, "token_type": "bearer", "expires_in": int(expires.total_seconds())})
    write_audit_log(db, user_id=user.id, action="login", entity_type="user", entity_id=str(user.id), request=request)
    db.commit()
    return payload


@router.post("/logout")
def logout_api(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out"}


@router.get("/me")
def me_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).options(joinedload(User.profile)).filter(User.id == current_user.id).first()
    return _serialize_user(user, user.profile if user else None)


@router.get("/profile")
def get_profile_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _get_or_create_profile(db, current_user.id)
    db.commit()
    return _serialize_user(current_user, profile)


@router.put("/profile")
def update_profile_api(
    data: ProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, current_user.id)
    profile_updates = (
        data.model_dump(exclude_unset=True)
        if hasattr(data, "model_dump")
        else data.dict(exclude_unset=True)
    )

    for field, value in profile_updates.items():
        setattr(profile, field, value)

    write_audit_log(
        db,
        user_id=current_user.id,
        action="update_profile",
        entity_type="user_profile",
        entity_id=str(profile.id),
        request=request,
    )
    db.commit()
    db.refresh(profile)
    return _serialize_user(current_user, profile)


@router.delete("/me/data")
def delete_my_financial_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uid = current_user.id
    receipt_ids = [row[0] for row in db.query(Receipt.id).filter(Receipt.user_id == uid).all()]
    if receipt_ids:
        db.query(ReceiptItem).filter(ReceiptItem.receipt_id.in_(receipt_ids)).delete(synchronize_session=False)
    for model in (
        AIChatMessage,
        AIInsight,
        MonthlySummary,
        SharedAccessGrant,
        CreditProfile,
        NetWorthItem,
        BillNegotiation,
        Subscription,
        SavingsGoal,
        Budget,
        Transaction,
        Receipt,
        BankAccount,
        ProviderToken,
        ExpenseNew,
        Income,
    ):
        db.query(model).filter(model.user_id == uid).delete(synchronize_session=False)
    write_audit_log(db, user_id=uid, action="delete_financial_data", entity_type="user", entity_id=str(uid), request=request)
    db.commit()
    return {"message": "Financial data deleted"}


@router.delete("/me")
def deactivate_me(
    response: Response,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.is_active = False
    current_user.token_version += 1
    write_audit_log(db, user_id=current_user.id, action="deactivate_account", entity_type="user", entity_id=str(current_user.id), request=request)
    db.commit()
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Account deactivated"}

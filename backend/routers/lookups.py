from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Category, Subcategory, PaymentMethod

router = APIRouter()

# ---------------------------------------------------------
# RESTORE /config FOR FRONTEND
# ---------------------------------------------------------
@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    categories = [
        {"id": c.id, "name": c.name}
        for c in db.query(Category).all()
    ]

    subcategories = [
        {"id": s.id, "name": s.name, "category_id": s.category_id}
        for s in db.query(Subcategory).all()
    ]

    payment_methods = [
        {"id": p.id, "name": p.name}
        for p in db.query(PaymentMethod).all()
    ]

    return {
        "categories": categories,
        "subcategories": subcategories,
        "payment_methods": payment_methods
    }



# ---------------------------------------------------------
# INDIVIDUAL LOOKUP ENDPOINTS (OPTIONAL BUT USEFUL)
# ---------------------------------------------------------
@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()


@router.get("/subcategories")
def get_subcategories(db: Session = Depends(get_db)):
    return db.query(Subcategory).all()


@router.get("/payment-methods")
def get_payment_methods(db: Session = Depends(get_db)):
    return db.query(PaymentMethod).all()

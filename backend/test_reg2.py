from database import SessionLocal
from main import register
from schemas import RegisterIn

db = SessionLocal()
data = RegisterIn(username="mudii2", email="mudii2@example.com", password="password")
try:
    register(data, db)
except Exception as e:
    import traceback
    traceback.print_exc()

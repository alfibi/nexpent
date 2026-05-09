import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
url = os.getenv("DATABASE_URL")
engine = create_engine(url)
with engine.connect() as conn:
    print(conn.execute(text("SHOW search_path")).scalar())
    print(conn.execute(text("SELECT username FROM public.users LIMIT 1")).scalar())
    try:
        print(conn.execute(text("SELECT username FROM users LIMIT 1")).scalar())
    except Exception as e:
        print("Error without public:", e)

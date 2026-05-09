import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData

load_dotenv()
url = os.getenv("DATABASE_URL")
engine = create_engine(url)
meta = MetaData()
meta.reflect(bind=engine)
meta.drop_all(bind=engine)
print("Dropped all tables.")

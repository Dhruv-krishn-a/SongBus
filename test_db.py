import os
from dotenv import load_dotenv

load_dotenv(".env")

from app.core.database import SessionLocal
from app.models.schema import User
db = SessionLocal()
try:
    users = db.query(User).all()
    print("Users found:", len(users))
except Exception as e:
    import traceback
    traceback.print_exc()

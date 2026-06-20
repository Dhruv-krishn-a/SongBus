import os
from dotenv import load_dotenv
load_dotenv(".env")
from app.core.database import SessionLocal
from app.models.schema import User
db = SessionLocal()
users = db.query(User).all()
for u in users:
    print(u.email)

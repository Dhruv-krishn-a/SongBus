import logging
from app.core.database import SessionLocal
from app.services.cleaner import DataCleaner
from app.models.schema import User

# Configure SQLAlchemy logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

def test_clean():
    db = SessionLocal()
    user = db.query(User).filter(User.email == "dhruv.krishn.a@gmail.com").first()
    
    if user:
        print("Cleaning for user:", user.email)
        res = DataCleaner.clean_database(db, user.id)
        print("Result:", res)

test_clean()

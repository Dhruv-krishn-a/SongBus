import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.pool import NullPool

# Load DB URL from environment
SQLALCHEMY_DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL", "sqlite:///./playlistiq.db")

# If using PostgreSQL (Supabase), ensure the scheme is correct and handle special characters
is_postgres = SQLALCHEMY_DATABASE_URL.startswith("postgres://") or SQLALCHEMY_DATABASE_URL.startswith("postgresql://")

if is_postgres:
    # SQLAlchemy requires "postgresql://" not "postgres://"
    if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    # Use QueuePool with strict limits to avoid EMAXCONN on Supabase 
    # but prevent 'SSL connection closed' errors caused by NullPool's rapid connect/disconnect cycles
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_pre_ping=True,
        pool_recycle=300, # Recycle connections after 5 minutes
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

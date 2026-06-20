import asyncio
from app.core.database import SessionLocal
from app.models.schema import Track

async def test():
    db = SessionLocal()
    t = db.query(Track).filter(Track.title.ilike('%remind me to forget%')).first()
    print("Album:", repr(t.album))

asyncio.run(test())

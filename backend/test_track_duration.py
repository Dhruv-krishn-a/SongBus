import asyncio
from app.core.database import SessionLocal
from app.models.schema import Track

async def test():
    db = SessionLocal()
    t = db.query(Track).filter(Track.title.ilike('%remind me to forget%')).first()
    print("Duration MS:", t.duration_ms)
    print("Duration Sec:", t.duration_ms // 1000 if t.duration_ms else None)

asyncio.run(test())

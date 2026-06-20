import asyncio
from app.core.database import SessionLocal
from app.models.schema import Track, User
from app.api.music import enrich_single_track

async def test():
    db = SessionLocal()
    track = db.query(Track).first()
    user = db.query(User).filter(User.id == track.owner_id).first()
    try:
        res = await enrich_single_track(track.id, db, user)
        print("Success:", res.title)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

asyncio.run(test())

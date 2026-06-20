import asyncio
from app.core.database import SessionLocal
from app.models.schema import Track, User
from app.api.music import enrich_single_track

async def test():
    db = SessionLocal()
    track = db.query(Track).filter(Track.title.ilike('%remind me to forget%')).first()
    user = db.query(User).filter(User.id == track.owner_id).first()
    
    print("Before:", track.lyrics_not_found)
    await enrich_single_track(track.id, db, user)
    print("After:", track.lyrics_not_found, "Lyrics len:", len(track.lyrics) if track.lyrics else None)

asyncio.run(test())

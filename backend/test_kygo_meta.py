import asyncio
from app.core.database import SessionLocal
from app.models.schema import Track, User
from app.api.music import enrich_single_track
from app.services.analysis import AnalysisEngine

async def test():
    db = SessionLocal()
    track = db.query(Track).filter(Track.title.ilike('%remind me to forget%')).first()
    raw_title = track.title or ""
    raw_artist = track.artist or ""
    clean_meta = AnalysisEngine.normalize_track_metadata(raw_title, raw_artist)
    print("Raw Title:", repr(raw_title))
    print("Raw Artist:", repr(raw_artist))
    print("Clean Title:", repr(clean_meta["title"]))
    print("Clean Artist:", repr(clean_meta["artist"]))

asyncio.run(test())

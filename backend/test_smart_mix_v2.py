import asyncio
from app.core.database import SessionLocal
from app.models.schema import Track
from app.services.smart_mix import SmartMixEngine
import json

def test():
    db = SessionLocal()
    # Fetch all tracks that have some tags
    tracks = db.query(Track).filter(Track.owner_id == 1).limit(100).all()
    db.close()
    
    if not tracks:
        print("No tracks found.")
        return
        
    print(f"Testing SmartMixEngine with {len(tracks)} tracks...")
    result = SmartMixEngine.generate_ai_playlists_direct(tracks)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test()

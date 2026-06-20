import asyncio
import os
from dotenv import load_dotenv
from app.core.database import SessionLocal
from app.models.schema import Track
from app.services.analysis import AnalysisEngine
import json

load_dotenv()

def test_smart_mix():
    db = SessionLocal()
    # Fetch 10 tracks that have genres/moods already populated
    tracks = db.query(Track).filter(Track.owner_id == 1).limit(10).all()
    db.close()
    
    if not tracks:
        print("No tracks found in the database.")
        return
        
    print(f"Testing auto_group_library_ai with {len(tracks)} tracks...")
    
    # We need to run it in a sync context because the function is sync
    try:
        result = AnalysisEngine.auto_group_library_ai(tracks)
        print("\nSUCCESS! Generated Smart Playlists:")
        print(json.dumps(result, indent=2))
        
        # Print a summary
        if "playlists" in result:
            print("\nSummary:")
            for p in result["playlists"]:
                print(f"- {p['name']} ({len(p['track_ids'])} tracks)")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_smart_mix()

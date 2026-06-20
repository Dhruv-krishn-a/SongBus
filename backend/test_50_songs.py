import json
import logging
from app.core.database import SessionLocal
from app.models.schema import Track
from app.services.smart_mix import SmartMixEngine

# Setup basic logging to see HDBSCAN / embedding output
logging.basicConfig(level=logging.INFO)

def test_generate_playlists():
    print("Connecting to database...")
    db = SessionLocal()
    try:
        # Fetch up to 50 tracks that have some metadata
        tracks = db.query(Track).filter(
            Track.owner_id == 1,
            Track.genre.isnot(None)
        ).limit(50).all()
        
        # If we didn't get 50 with genres, just grab any 50
        if len(tracks) < 50:
            more_tracks = db.query(Track).filter(Track.owner_id == 1).limit(50 - len(tracks)).all()
            # Avoid duplicates if we mixed queries
            track_ids = {t.id for t in tracks}
            for t in more_tracks:
                if t.id not in track_ids:
                    tracks.append(t)
                    track_ids.add(t.id)

        print(f"Loaded {len(tracks)} tracks from database.")
        
        if not tracks:
            print("No tracks found in the database for user 1.")
            return

        print("\nStarting SmartMixEngine...")
        result = SmartMixEngine.generate_ai_playlists_direct(tracks)
        
        if "error" in result:
            print(f"\nERROR: {result['error']}")
        else:
            print("\n=== SUCCESS: Generated Playlists ===")
            print(f"Total Tracks Sent: {result.get('track_count')}")
            print(f"Classified Tracks Used: {result.get('classified_count')}")
            print(f"Unclassified Tracks Skipped: {result.get('unclassified_count')}")
            print(f"Number of Clusters Formed: {result.get('cluster_count')}")
            print("\nPlaylists:")
            
            for i, p in enumerate(result.get("playlists", [])):
                print(f"\n[{i+1}] {p.get('name')}")
                if p.get("description"):
                    print(f"    Description: {p.get('description')}")
                if p.get("confidence"):
                    print(f"    Confidence: {p.get('confidence')}")
                print(f"    Tracks: {len(p.get('track_ids', []))}")
                
    finally:
        db.close()

if __name__ == "__main__":
    test_generate_playlists()

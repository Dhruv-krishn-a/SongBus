import traceback
from app.core.database import SessionLocal
from app.models import schema
from app.api.youtube import request_with_refresh, fetch_user_playlists_response, fetch_playlist_items_response
from dotenv import load_dotenv

load_dotenv()
db = SessionLocal()
user = db.query(schema.User).first()

try:
    print("Testing fetch_user_playlists_response...")
    res = request_with_refresh(user, db, lambda t: fetch_user_playlists_response(t))
    if res.status_code != 200:
        print("ERROR:", res.text)
    else:
        pls = res.json().get("items", [])
        print("Success! Playlists length:", len(pls))
        if len(pls) > 0:
            first_pl = pls[0]
            pid = first_pl.get("id")
            print("First playlist ID:", pid)
            print("\nTesting fetch_playlist_items_response...")
            res2 = request_with_refresh(user, db, lambda t: fetch_playlist_items_response(t, pid))
            if res2.status_code != 200:
                print("ERROR:", res2.text)
            else:
                items = res2.json().get("items", [])
                print("Success! Playlist items length:", len(items))
except Exception:
    traceback.print_exc()


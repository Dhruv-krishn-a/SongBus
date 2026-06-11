import os
import sys
import traceback
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
from backend.app.core.database import SessionLocal
from backend.app.models import schema
from backend.app.api.youtube import get_ytmusic_oauth_client

def test():
    db = SessionLocal()
    user = db.query(schema.User).first()
    if not user:
        print("No user found")
        return
    
    print(f"Testing for user {user.email}")
    try:
        yt = get_ytmusic_oauth_client(user)
        print("YT client created. Headers:", yt.headers)
        
        print("Trying to fetch liked songs playlist 'LM'...")
        pl = yt.get_playlist("LM", limit=1)
        print("Success! Track count:", pl.get("trackCount"))
    except Exception as e:
        print("Failed:")
        traceback.print_exc()
        
if __name__ == "__main__":
    test()

import traceback
import json
import os
from app.core.database import SessionLocal
from app.models import schema
from app.api.youtube import get_ytmusic_oauth_client
from dotenv import load_dotenv
from ytmusicapi import YTMusic

load_dotenv()
db = SessionLocal()
user = db.query(schema.User).first()

auth_dict = {
    "access_token": user.yt_access_token,
    "refresh_token": user.yt_refresh_token,
    "expires_at": int(user.yt_token_expiry.timestamp()) if user.yt_token_expiry else 0,
    "expires_in": 3599,
    "client_id": os.getenv("YTMUSIC_OAUTH_CLIENT_ID"),
    "client_secret": os.getenv("YTMUSIC_OAUTH_CLIENT_SECRET"),
    "scope": "https://www.googleapis.com/auth/youtube",
    "token_type": "Bearer"
}
with open("tmp_oauth.json", "w") as f:
    json.dump(auth_dict, f)

try:
    print("Testing YTMusic('tmp_oauth.json')...")
    yt = YTMusic("tmp_oauth.json")
    print("Success! History length:", len(yt.get_history()))
except Exception:
    traceback.print_exc()


import os
import json
import re
import requests
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.models import schema
from app.api.deps import get_current_user
from app.core import tasks
from app.services.spotify import SpotifyService
from app.api.music import enrich_tracks_chunk
from datetime import datetime, timedelta
from urllib.parse import quote

router = APIRouter()

class OAuthCallback(BaseModel):
    code: str


class BrowserAuthPayload(BaseModel):
    headers_raw: str


def get_youtube_redirect_uri() -> str:
    # 1. Try environment variable (Vercel / Production)
    env_uri = os.getenv("YOUTUBE_REDIRECT_URI")
    if env_uri:
        return env_uri.strip()
        
    # 2. Fallback to Localhost (Development)
    # Defaulting to http since Vite usually runs without SSL locally.
    return "http://localhost:5173/callback/youtube"


def get_ytmusic_browser_auth_path() -> str:
    return os.getenv("YTMUSIC_BROWSER_AUTH_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "browser.json")))


_BROWSER_HEADER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")
_BROWSER_AUTH_ALLOWED_KEYS = {
    "accept",
    "accept-language",
    "authorization",
    "cookie",
    "origin",
    "priority",
    "referer",
    "user-agent",
    "x-browser-channel",
    "x-browser-copyright",
    "x-browser-validation",
    "x-browser-year",
    "x-client-data",
    "x-goog-authuser",
    "x-goog-event-time",
    "x-goog-request-time",
    "x-goog-visitor-id",
    "x-origin",
    "x-youtube-ad-signals",
    "x-youtube-client-name",
    "x-youtube-client-version",
    "x-youtube-device",
    "x-youtube-identity-token",
    "x-youtube-page-cl",
    "x-youtube-page-label",
    "x-youtube-time-zone",
    "x-youtube-utc-offset",
}


def parse_browser_headers(headers_raw: str) -> dict[str, str]:
    """
    Parse a devtools-style header dump into a browser auth JSON object.
    Keeps only real header names and ignores pseudo headers / decoded blocks.
    """
    lines = [line.rstrip() for line in headers_raw.splitlines()]
    headers: dict[str, str] = {}
    pending_key: str | None = None
    skip_next_value = False
    in_decoded_block = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if skip_next_value:
            skip_next_value = False
            continue

        if in_decoded_block:
            if stripped.startswith("x-") and _BROWSER_HEADER_NAME_RE.fullmatch(stripped):
                in_decoded_block = False
            else:
                continue

        if stripped == "Decoded:":
            in_decoded_block = True
            continue

        if pending_key is not None:
            headers[pending_key] = stripped
            pending_key = None
            continue

        if stripped.startswith(":"):
            skip_next_value = True
            continue
        if not _BROWSER_HEADER_NAME_RE.fullmatch(stripped):
            continue

        pending_key = stripped

    if pending_key is not None:
        raise HTTPException(status_code=400, detail=f"Missing value for header '{pending_key}'.")

    required = {"cookie", "x-goog-authuser"}
    # Use lowercase keys for checking required headers
    lowercase_headers = {k.lower() for k in headers}
    missing = sorted(required - lowercase_headers)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required headers: {', '.join(missing)}.",
        )

    return headers


def sanitize_browser_auth_file(auth_path: str) -> None:
    if not os.path.exists(auth_path):
        return

    try:
        with open(auth_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    cleaned: dict[str, str] = {}
    for key, value in data.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in {"decoded", "https", "music.youtube.com"}:
            continue
        if normalized_key in _BROWSER_AUTH_ALLOWED_KEYS or normalized_key.startswith("sec-") or normalized_key.startswith("x-"):
            cleaned[normalized_key] = value

    # Fix potential multi-value authorization header
    if "authorization" in cleaned:
        auth_val = cleaned["authorization"]
        if "SAPISIDHASH" in auth_val and " " in auth_val:
            parts = auth_val.split()
            # If we have multiple hashes (e.g. SAPISID1PHASH, SAPISID3PHASH),
            # keep only the first type and its value
            if len(parts) > 2:
                cleaned["authorization"] = f"{parts[0]} {parts[1]}"

    if cleaned and cleaned != data:
        with open(auth_path, "w", encoding="utf-8") as handle:
            json.dump(cleaned, handle, ensure_ascii=True, indent=4, sort_keys=True)

@router.get("/spotify/auth-url")
def get_spotify_auth_url(current_user: schema.User = Depends(get_current_user)):
    spotify_service = SpotifyService()
    url = spotify_service.get_auth_url()
    return {"url": url}

@router.post("/spotify/callback")
def spotify_callback(
    data: OAuthCallback,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    spotify_service = SpotifyService()
    try:
        # Request access token using the code
        token_info = spotify_service.auth_manager.get_access_token(data.code)
        
        # Save token info
        current_user.spotify_access_token = token_info.get("access_token")
        current_user.spotify_refresh_token = token_info.get("refresh_token")
        expires_in = token_info.get("expires_in", 3600)
        current_user.spotify_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
        
        # Get Spotify user ID
        client = spotify_service.get_client_from_token(token_info)
        spotify_me = client.me()
        current_user.spotify_id = spotify_me.get("id")
        
        db.commit()
        
        return {"message": "Spotify connected successfully", "spotify_id": current_user.spotify_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect Spotify: {str(e)}")

@router.get("/youtube/auth-url")
def get_youtube_auth_url(current_user: schema.User = Depends(get_current_user)):
    client_id = os.getenv("YTMUSIC_OAUTH_CLIENT_ID")
    redirect_uri = get_youtube_redirect_uri()
    scope = "https://www.googleapis.com/auth/youtube"
    
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={quote(redirect_uri, safe='')}&"
        f"response_type=code&"
        f"scope={quote(scope, safe='')}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return {"url": url}

@router.post("/youtube/callback")
def youtube_callback(
    data: OAuthCallback,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    client_id = os.getenv("YTMUSIC_OAUTH_CLIENT_ID")
    client_secret = os.getenv("YTMUSIC_OAUTH_CLIENT_SECRET")
    redirect_uri = get_youtube_redirect_uri()
    
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": data.code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    res = requests.post(token_url, data=payload)
    if res.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange Google code")
    
    tokens = res.json()
    current_user.yt_access_token = tokens.get("access_token")
    if tokens.get("refresh_token"):
        current_user.yt_refresh_token = tokens.get("refresh_token")
    
    expires_in = tokens.get("expires_in", 3600)
    current_user.yt_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    
    db.commit()
    return {"message": "YouTube Music connected successfully"}


@router.post("/youtube/browser-auth")
def save_youtube_browser_auth(
    payload: BrowserAuthPayload,
    current_user: schema.User = Depends(get_current_user),
):
    auth_path = get_ytmusic_browser_auth_path()
    os.makedirs(os.path.dirname(auth_path), exist_ok=True)
    try:
        headers = parse_browser_headers(payload.headers_raw)
        with open(auth_path, "w", encoding="utf-8") as handle:
            json.dump(headers, handle, ensure_ascii=True, indent=4, sort_keys=True)
        return {
            "message": "YouTube Music browser auth saved successfully",
            "auth_path": auth_path,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save browser auth: {str(e)}")

@router.post("/spotify/disconnect")
def disconnect_spotify(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.spotify_access_token = None
    current_user.spotify_refresh_token = None
    current_user.spotify_id = None
    db.commit()
    return {"message": "Spotify disconnected successfully"}

@router.post("/youtube/disconnect")
def disconnect_youtube(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.yt_access_token = None
    current_user.yt_refresh_token = None
    current_user.yt_token_expiry = None
    db.commit()
    return {"message": "YouTube Music disconnected successfully"}

@router.get("/status")
def get_integration_status(current_user: schema.User = Depends(get_current_user)):
    return {
        "spotify_connected": bool(current_user.spotify_access_token),
        "youtube_connected": bool(current_user.yt_access_token)
    }

@router.get("/spotify/playlists")
def get_spotify_playlists(
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.spotify_access_token:
        raise HTTPException(status_code=400, detail="Spotify not connected")
    
    spotify_service = SpotifyService()
    client = spotify_service.get_valid_client(current_user, db)
    
    playlists = []
    
    # 1. Add Liked Songs
    try:
        liked = client.current_user_saved_tracks(limit=1)
        playlists.append({
            "id": "__liked_songs__",
            "title": "Liked Songs",
            "track_count": liked.get("total", 0),
            "source": "spotify"
        })
    except Exception as e:
        print(f"Liked songs count error: {e}")

    # 2. Get real playlists (paging through all)
    offset = 0
    limit = 50
    while True:
        playlists_data = spotify_service.get_user_playlists(client, limit=limit, offset=offset)
        if not playlists_data or not playlists_data.get("items"):
            break
            
        for item in playlists_data.get("items", []):
            if not item: continue
            playlists.append({
                "id": item.get("id"),
                "title": item.get("name"),
                "track_count": item.get("tracks", {}).get("total", 0),
                "source": "spotify"
            })
            
        if len(playlists_data.get("items", [])) < limit:
            break
        offset += limit
            
    return {"playlists": playlists}

def _import_spotify_playlist_task(task_id: str, user_id: int, playlist_id: str):
    from app.services.ytmusic import YTMusicService
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        spotify_service = SpotifyService()
        client = spotify_service.get_valid_client(user, db)
        
        # Initialize YT once for the whole task
        yt_auth_path = get_ytmusic_browser_auth_path()
        if not os.path.exists(yt_auth_path):
            yt_auth_path = None
        yt_service = YTMusicService(yt_auth_path)
        
        tasks.update_task(task_id, status="running", message="Fetching tracks...")
        
        # Get tracks
        all_tracks = []
        limit = 50
        offset = 0
        
        if playlist_id == "__liked_songs__":
            while True:
                page = client.current_user_saved_tracks(limit=limit, offset=offset)
                if not page or not page.get("items"): break
                all_tracks.extend(page["items"])
                if len(page["items"]) < limit: break
                offset += limit
        else:
            while True:
                page = spotify_service.get_playlist_tracks(client, playlist_id, limit=limit, offset=offset)
                if not page or not page.get("items"): break
                all_tracks.extend(page["items"])
                if len(page["items"]) < limit: break
                offset += limit

        total = len(all_tracks)
        tasks.update_task(task_id, total=total, message=f"Importing {total} tracks...")

        # 1. Pre-load existing track IDs to avoid DB hits inside loop
        existing_tracks = {
            t.external_id: t for t in db.query(schema.Track).filter(schema.Track.owner_id == user_id).all()
            if t.external_id
        }
        
        imported = 0
        chunk_size = 50 # Larger chunk for fewer commits
        for i in range(0, total, chunk_size):
            chunk = all_tracks[i:i+chunk_size]
            current_batch = []
            for item in chunk:
                track_data = item.get("track")
                if not track_data: continue
                
                title = track_data.get("name")
                artists = ", ".join([a.get("name") for a in track_data.get("artists", [])])
                ext_id = track_data.get("id")
                
                t = existing_tracks.get(ext_id)
                if not t:
                    thumb = None
                    if track_data.get("album", {}).get("images"):
                        thumb = track_data["album"]["images"][0].get("url")

                    t = schema.Track(
                        title=title, artist=artists, external_id=ext_id, source="spotify", 
                        owner_id=user.id, spotify_uri=track_data.get("uri"),
                        duration_ms=track_data.get("duration_ms"),
                        thumbnail_url=thumb,
                        album=track_data.get("album", {}).get("name")
                    )
                    db.add(t)
                    db.flush() # Flush to get ID
                    existing_tracks[ext_id] = t
                current_batch.append(t)
                imported += 1
            
            # Deep Enrichment for this chunk - Using pre-initialized services
            if current_batch:
                enrich_tracks_chunk(db, current_batch, user_id, include_lyrics=True, spotify_client=client, yt_service=yt_service)
                
            tasks.update_task(task_id, progress=imported)
            db.commit()
        tasks.update_task(task_id, status="completed", message=f"Successfully imported {imported} tracks.")
    except Exception as e:
        tasks.update_task(task_id, status="failed", error=str(e))
    finally:
        db.close()

@router.post("/spotify/import-playlist/{playlist_id}")
def import_spotify_playlist(
    playlist_id: str,
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user)
):
    task_id = tasks.create_task("Spotify Playlist Import")
    background_tasks.add_task(_import_spotify_playlist_task, task_id, current_user.id, playlist_id)
    return {"task_id": task_id}

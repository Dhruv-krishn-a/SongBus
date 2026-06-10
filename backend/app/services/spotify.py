import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
from app.models import schema
from sqlalchemy.orm import Session
from fastapi import HTTPException

class SpotifyService:
    def __init__(self):
        self.client_id = os.getenv("SPOTIPY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        # Back to environment based, using secure https as default fallback
        self.redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI", "https://localhost:5173/callback").strip()
        
        if not self.client_id or not self.client_secret:
            self.auth_manager = None
        else:
            self.scope = "playlist-modify-public playlist-modify-private user-library-read"
            self.auth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                open_browser=False
            )

    def get_auth_url(self):
        if not self.auth_manager:
            raise HTTPException(status_code=500, detail="Spotify API keys not configured in .env")
        url = self.auth_manager.get_authorize_url()
        print(f"DEBUG: Final Spotify Auth URL: {url}")
        return url

    def get_client_from_token(self, token_info: dict):
        return spotipy.Spotify(auth=token_info.get("access_token"))

    def get_valid_client(self, user: schema.User, db: Session):
        """
        Returns an authenticated Spotify client, refreshing the token if expired.
        """
        if not self.auth_manager:
            raise HTTPException(status_code=500, detail="Spotify API keys not configured in .env")

        now = datetime.utcnow()
        if user.spotify_token_expiry and now >= (user.spotify_token_expiry - timedelta(minutes=5)):
            # Refresh token
            token_info = self.auth_manager.refresh_access_token(user.spotify_refresh_token)
            user.spotify_access_token = token_info['access_token']
            if 'refresh_token' in token_info:
                user.spotify_refresh_token = token_info['refresh_token']
            
            expires_in = token_info.get("expires_in", 3600)
            user.spotify_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
            db.commit()

        return spotipy.Spotify(auth=user.spotify_access_token)

    def search_and_match_track(self, client: spotipy.Spotify, track: schema.Track):
        """
        Searches Spotify for a match and returns URI if found.
        Uses a weighted matching logic (Title/Artist + Duration).
        """
        if track.spotify_uri:
            return track.spotify_uri

        # 1. Clean query
        query = f"track:{track.title} artist:{track.artist}"
        try:
            results = client.search(q=query, type="track", limit=5)
            candidates = results.get("tracks", {}).get("items", [])
            
            best_match = None
            
            for cand in candidates:
                # Basic matching criteria:
                # 1. Duration check (within 10 seconds)
                if track.duration_ms:
                    duration_diff = abs(cand['duration_ms'] - track.duration_ms)
                    if duration_diff > 10000: # 10s tolerance
                        continue
                
                # 2. Prefer official versions (not live, not karaoke)
                title_lower = cand['name'].lower()
                if "live" in title_lower or "karaoke" in title_lower:
                    if "live" not in track.title.lower():
                        continue
                
                best_match = cand['uri']
                break
                
            return best_match
        except Exception:
            return None

    def create_playlist(self, client: spotipy.Spotify, user_id: str, name: str, description: str = ""):
        try:
            return client.user_playlist_create(user=user_id, name=name, public=False, description=description)
        except Exception:
            return None

    def add_tracks_to_playlist(self, client: spotipy.Spotify, playlist_id: str, track_uris: list):
        # Spotify allows max 100 tracks per request
        try:
            for i in range(0, len(track_uris), 100):
                client.playlist_add_items(playlist_id=playlist_id, items=track_uris[i:i+100])
            return True
        except Exception:
            return False

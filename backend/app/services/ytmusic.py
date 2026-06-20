import os
import requests
from datetime import datetime, timedelta
from ytmusicapi import YTMusic
from sqlalchemy.orm import Session
from app.models import schema

class YTMusicService:
    def __init__(self, headers_auth: str = None, access_token: str = None):
        """
        Initialize the YouTube Music API client.
        We can use access_token directly for OAuth Custom Full mode.
        """
        if access_token:
            self.client = YTMusic({"authorization": f"Bearer {access_token}"})
        elif headers_auth:
            # Load from string or file depending on ytmusicapi implementation
            try:
                self.client = YTMusic(headers_auth)
            except Exception:
                # Fallback to unauthenticated client
                self.client = YTMusic()
        else:
            self.client = YTMusic()

    @staticmethod
    def get_valid_client(user: schema.User, db: Session) -> 'YTMusicService':
        """
        Returns an authenticated YTMusicService instance, refreshing the token if expired.
        """
        if not user.yt_access_token:
            return YTMusicService()

        now = datetime.utcnow()
        if user.yt_token_expiry and now >= (user.yt_token_expiry - timedelta(minutes=5)):
            client_id = os.getenv("YTMUSIC_OAUTH_CLIENT_ID")
            client_secret = os.getenv("YTMUSIC_OAUTH_CLIENT_SECRET")
            if client_id and client_secret and user.yt_refresh_token:
                token_url = "https://oauth2.googleapis.com/token"
                payload = {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": user.yt_refresh_token,
                    "grant_type": "refresh_token",
                }
                res = requests.post(token_url, data=payload)
                if res.status_code == 200:
                    tokens = res.json()
                    user.yt_access_token = tokens.get("access_token")
                    if tokens.get("refresh_token"):
                        user.yt_refresh_token = tokens.get("refresh_token")
                    expires_in = tokens.get("expires_in", 3600)
                    user.yt_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
                    db.commit()

        return YTMusicService(access_token=user.yt_access_token)

    def get_liked_songs(self, limit: int = 100):
        """
        Fetch user's liked songs from YouTube Music.
        Requires authenticated client.
        """
        try:
            return self.client.get_liked_songs(limit=limit)
        except Exception:
            # Handle unauthenticated state appropriately
            return []

    def get_playlists(self):
        """
        Fetch user's playlists.
        """
        try:
            return self.client.get_library_playlists()
        except Exception:
            return []
            
    def get_playlist_tracks(self, playlist_id: str):
        """
        Fetch tracks for a specific playlist.
        """
        try:
            return self.client.get_playlist(playlistId=playlist_id)
        except Exception:
            return None

    def search_and_match_track(self, title: str, artist: str, duration_ms: int = None):
        """
        Searches YouTube Music for a track and returns its videoId.
        """
        query = f"{title} {artist}"
        try:
            results = self.client.search(query, filter="songs", limit=5)
            best_match = None
            for res in results:
                if duration_ms and res.get("duration_seconds"):
                    duration_diff = abs((res["duration_seconds"] * 1000) - duration_ms)
                    if duration_diff > 10000:
                        continue
                best_match = res.get("videoId")
                break
            return best_match
        except Exception:
            return None

    def create_playlist(self, name: str, description: str = ""):
        """
        Creates a new playlist on YouTube Music.
        """
        try:
            return self.client.create_playlist(title=name, description=description)
        except Exception:
            return None

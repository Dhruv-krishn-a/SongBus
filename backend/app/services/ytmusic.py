from ytmusicapi import YTMusic

class YTMusicService:
    def __init__(self, headers_auth: str = None):
        """
        Initialize the YouTube Music API client.
        For MVP, users might provide headers_auth JSON string 
        to access their personal library, or we can use OAuth.
        """
        if headers_auth:
            # Load from string or file depending on ytmusicapi implementation
            # For simplicity, if headers_auth is a path to a json file:
            try:
                self.client = YTMusic(headers_auth)
            except Exception:
                # Fallback to unauthenticated client
                self.client = YTMusic()
        else:
            self.client = YTMusic()

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

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

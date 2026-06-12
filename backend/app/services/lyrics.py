import requests
import httpx
import urllib.parse
import re

class LyricsService:
    """
    Highly accurate service to fetch lyrics from LRCLIB.
    LRCLIB is a massive, free, open-source lyrics API.
    """
    BASE_URL = "https://lrclib.net/api"
    # LRCLIB recommends a descriptive User-Agent
    HEADERS = {
        "User-Agent": "SongBus (https://github.com/dhruv-krishn-a/SongBus)"
    }

    @staticmethod
    def _clean_string(text: str) -> str:
        """Removes noise tags and special characters for better searching."""
        if not text: return ""
        
        # 1. Remove bracketed content: (Official Video), [Lyrics], (Prod. by...)
        text = re.sub(r'[\(\[].*?[\)\]]', '', text)
        
        # 2. YouTube Metadata: Remove "Coke Studio", "Season X", "Episode X"
        text = re.sub(r'(?i)coke studio|season \d+|episode \d+|official music video|lyrical video', '', text)
        
        # 3. Artist Metadata: Change "x", "ft.", "feat." to space for cleaner matching
        text = re.sub(r'(?i)\s+x\s+|\s+ft\.?\s+|\s+feat\.?\s+', ' ', text)

        # 4. Remove special symbols like pipes, dashes, and extra whitespace
        text = text.replace('|', ' ').replace('-', ' ')
        text = re.sub(r'[^\w\s]', '', text) # Remove punctuation
        
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    async def async_fetch_lyrics(client: httpx.AsyncClient, title: str, artist: str, album: str = None, duration_ms: int = None) -> str | None:
        """
        Fetches lyrics asynchronously using a multi-stage matching strategy.
        """
        clean_title = LyricsService._clean_string(title)
        clean_artist = LyricsService._clean_string(artist)

        try:
            # --- STAGE 1: Exact Signature Match ---
            if duration_ms:
                duration_sec = duration_ms // 1000
                params = {
                    "track_name": clean_title,
                    "artist_name": clean_artist,
                    "duration": duration_sec
                }
                if album:
                    params["album_name"] = LyricsService._clean_string(album)
                
                response = await client.get(f"{LyricsService.BASE_URL}/get", params=params, headers=LyricsService.HEADERS)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("instrumental"): return "Instrumental"
                    return data.get("syncedLyrics") or data.get("plainLyrics")

            # --- STAGE 2: Weighted Search ---
            search_query = f"{clean_title} {clean_artist}"
            encoded_query = urllib.parse.quote(search_query)
            
            response = await client.get(f"{LyricsService.BASE_URL}/search?q={encoded_query}", headers=LyricsService.HEADERS)
            
            if response.status_code == 200:
                results = response.json()
                if results and len(results) > 0:
                    best_match = None
                    if duration_ms:
                        duration_sec = duration_ms // 1000
                        for res in results:
                            res_duration = res.get("duration")
                            if res_duration and abs(res_duration - duration_sec) <= 4:
                                best_match = res
                                break
                    
                    if not best_match:
                        best_match = results[0]
                    
                    if best_match.get("instrumental"): return "Instrumental"
                    return best_match.get("syncedLyrics") or best_match.get("plainLyrics")
            
            # --- STAGE 3: Recursive Regional Fallback ---
            if "various" in artist.lower():
                response = await client.get(f"{LyricsService.BASE_URL}/search?q={encoded_query}", headers=LyricsService.HEADERS)
                if response.status_code == 200:
                    results = response.json()
                    if results: return results[0].get("syncedLyrics") or results[0].get("plainLyrics")

            return None
            
        except Exception as e:
            print(f"LRCLIB Async Error for {title}: {e}")
            return None

    @staticmethod
    def fetch_lyrics(title: str, artist: str, album: str = None, duration_ms: int = None) -> str | None:
        """
        Fetches lyrics using a multi-stage matching strategy.
        1. Exact Match (get endpoint)
        2. Fuzzy Search + Duration Verification
        3. Fallback Cleaned Search
        """
        clean_title = LyricsService._clean_string(title)
        clean_artist = LyricsService._clean_string(artist)

        try:
            # --- STAGE 1: Exact Signature Match ---
            # This is the most efficient and reliable method.
            if duration_ms:
                duration_sec = duration_ms // 1000
                params = {
                    "track_name": clean_title,
                    "artist_name": clean_artist,
                    "duration": duration_sec
                }
                if album:
                    params["album_name"] = LyricsService._clean_string(album)
                
                response = requests.get(f"{LyricsService.BASE_URL}/get", params=params, headers=LyricsService.HEADERS, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    # We prefer Synced > Plain > Instrumental (None)
                    if data.get("instrumental"): return "Instrumental"
                    return data.get("syncedLyrics") or data.get("plainLyrics")

            # --- STAGE 2: Weighted Search ---
            # If exact match fails (common for YouTube titles), we search and verify manually.
            search_query = f"{clean_title} {clean_artist}"
            encoded_query = urllib.parse.quote(search_query)
            
            response = requests.get(f"{LyricsService.BASE_URL}/search?q={encoded_query}", headers=LyricsService.HEADERS, timeout=15)
            
            if response.status_code == 200:
                results = response.json()
                if results and len(results) > 0:
                    # Filter results by duration (within 4 seconds tolerance)
                    best_match = None
                    if duration_ms:
                        duration_sec = duration_ms // 1000
                        for res in results:
                            res_duration = res.get("duration")
                            if res_duration and abs(res_duration - duration_sec) <= 4:
                                best_match = res
                                break
                    
                    # If no perfect duration match, take the first result as it's the highest relevance
                    if not best_match:
                        best_match = results[0]
                    
                    if best_match.get("instrumental"): return "Instrumental"
                    return best_match.get("syncedLyrics") or best_match.get("plainLyrics")
            
            # --- STAGE 3: Recursive Regional Fallback ---
            # Special logic for Pakistani/Indian songs where artists might be "Various" 
            # or the title might contain regional suffixes.
            if "various" in artist.lower():
                response = requests.get(f"{LyricsService.BASE_URL}/search?q={encoded_query}", headers=LyricsService.HEADERS, timeout=15)
                if response.status_code == 200:
                    results = response.json()
                    if results: return results[0].get("syncedLyrics") or results[0].get("plainLyrics")

            return None
            
        except Exception as e:
            print(f"LRCLIB Error for {title}: {e}")
            return None

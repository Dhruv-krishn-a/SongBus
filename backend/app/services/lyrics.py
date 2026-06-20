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
        import asyncio
        clean_title = LyricsService._clean_string(title)
        clean_artist = LyricsService._clean_string(artist)

        async def _make_request(url: str, params: dict = None) -> httpx.Response | None:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await client.get(url, params=params, headers=LyricsService.HEADERS, timeout=15.0)
                    if response.status_code == 429:
                        await asyncio.sleep(3 ** attempt)
                        continue
                    return response
                except httpx.TimeoutException:
                    pass
                except Exception as e:
                    pass
            return None

        try:
            if duration_ms:
                duration_sec = duration_ms // 1000
                params = {
                    "track_name": clean_title,
                    "artist_name": clean_artist,
                    "duration": duration_sec
                }
                if album: params["album_name"] = LyricsService._clean_string(album)
                
                response = await _make_request(f"{LyricsService.BASE_URL}/get", params=params)
                if response and response.status_code == 200:
                    data = response.json()
                    if data.get("instrumental"): return "Instrumental"
                    return data.get("syncedLyrics") or data.get("plainLyrics")

            search_query = f"{clean_title} {clean_artist}"
            encoded_query = urllib.parse.quote(search_query)
            
            response = await _make_request(f"{LyricsService.BASE_URL}/search?q={encoded_query}")
            if response and response.status_code == 200:
                results = response.json()
                valid_results = [r for r in results if r.get("syncedLyrics") or r.get("plainLyrics")]
                print(f"LRCLIB: found {len(valid_results)} valid results")
                
                if valid_results and len(valid_results) > 0:
                    best_match = None
                    if duration_ms:
                        duration_sec = duration_ms // 1000
                        for res in valid_results:
                            if res.get("duration") and abs(res.get("duration") - duration_sec) <= 4:
                                best_match = res
                                break
                    if not best_match: best_match = valid_results[0]
                    print(f"LRCLIB: using best_match id {best_match.get('id')}")
                    if best_match.get("instrumental"): return "Instrumental"
                    return best_match.get("syncedLyrics") or best_match.get("plainLyrics")
            
            print(f"LRCLIB: no 200 response or no results. status: {response.status_code if response else 'None'}")
            
            if "various" in artist.lower():
                response = await _make_request(f"{LyricsService.BASE_URL}/search?q={encoded_query}")
                if response and response.status_code == 200:
                    results = response.json()
                    if results: return results[0].get("syncedLyrics") or results[0].get("plainLyrics")

            return None
            
        except Exception as e:
            print(f"LRCLIB Async Error for {title}: {e}")
            import traceback
            traceback.print_exc()
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
                
                response = requests.get(f"{LyricsService.BASE_URL}/get", params=params, headers=LyricsService.HEADERS, timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    # We prefer Synced > Plain > Instrumental (None)
                    if data.get("instrumental"): return "Instrumental"
                    return data.get("syncedLyrics") or data.get("plainLyrics")

            # --- STAGE 2: Weighted Search ---
            # If exact match fails (common for YouTube titles), we search and verify manually.
            search_query = f"{clean_title} {clean_artist}"
            encoded_query = urllib.parse.quote(search_query)
            
            response = requests.get(f"{LyricsService.BASE_URL}/search?q={encoded_query}", headers=LyricsService.HEADERS, timeout=2)
            
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
                response = requests.get(f"{LyricsService.BASE_URL}/search?q={encoded_query}", headers=LyricsService.HEADERS, timeout=2)
                if response.status_code == 200:
                    results = response.json()
                    if results: return results[0].get("syncedLyrics") or results[0].get("plainLyrics")

            return None
            
        except requests.exceptions.Timeout:
            # Silently fail on lyrics timeout to keep the import moving
            return None
        except Exception as e:
            print(f"LRCLIB Error for {title}: {e}")
            return None

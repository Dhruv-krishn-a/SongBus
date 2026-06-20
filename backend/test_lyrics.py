import asyncio, httpx
from app.services.lyrics import LyricsService
from app.services.analysis import AnalysisEngine

async def test():
    client = httpx.AsyncClient()
    
    title = "Remind Me to Forget"
    artist = "KYGO - TOPIC"
    
    clean = AnalysisEngine.normalize_track_metadata(title, artist)
    print("Clean:", clean)
    
    search_query = f"{clean['title']} {clean['artist']}"
    res = await client.get(f"https://lrclib.net/api/search?q={search_query}", headers=LyricsService.HEADERS)
    print("Status:", res.status_code)
    results = res.json()
    print("Results len:", len(results))
    if results:
        print("First result lyrics:", bool(results[0].get('syncedLyrics')))
    
    await client.aclose()

asyncio.run(test())

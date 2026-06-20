import asyncio, httpx
from app.core.database import SessionLocal
from app.models.schema import Track, User
from app.services.spotify import SpotifyService
import dotenv
dotenv.load_dotenv()

async def test():
    client = httpx.AsyncClient()
    sp = SpotifyService()
    print('Has ID:', bool(sp.client_id))
    token = await sp.async_get_app_token(client)
    print('Token:', bool(token))
    db = SessionLocal()
    t = db.query(Track).filter(Track.title.ilike('%am i wrong%')).first()
    print('Track:', t.title)
    uri = await sp.async_search_and_match_track(client, token, t.title, t.artist, t.duration_ms)
    print('URI:', uri)
    if uri:
        feats = await sp.async_get_audio_features(client, token, [uri])
        print('Feats:', feats)
    await client.aclose()

asyncio.run(test())

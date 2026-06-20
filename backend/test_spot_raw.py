import asyncio
import httpx
import dotenv
from app.services.spotify import SpotifyService
from app.core.database import SessionLocal
from app.models.schema import User

dotenv.load_dotenv()

async def test():
    async with httpx.AsyncClient() as client:
        sp = SpotifyService()
        token = await sp.async_get_app_token(client)
        print("Token:", token[:10])
        
        track_id = "6xTU6B6nFwKKTSZ9ySXS80"
        res = await client.get(f"https://api.spotify.com/v1/tracks/{track_id}", headers={"Authorization": f"Bearer {token}"})
        print(res.json())

        artist_id = res.json()["artists"][0]["id"]
        res_a = await client.get(f"https://api.spotify.com/v1/artists/{artist_id}", headers={"Authorization": f"Bearer {token}"})
        print(res_a.json())

asyncio.run(test())

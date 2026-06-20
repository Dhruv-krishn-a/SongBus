import asyncio
import httpx
import dotenv
from app.services.spotify import SpotifyService
from app.core.database import SessionLocal
from app.models.schema import User, Track

dotenv.load_dotenv()

async def test():
    db = SessionLocal()
    user = db.query(User).filter(User.email == "dhruv.krishn.a@gmail.com").first()
    
    async with httpx.AsyncClient() as client:
        sp = SpotifyService()
        token = await sp.async_get_app_token(client)
        print("Got token:", token[:10])
        
        # Test a search
        uri = await sp.async_search_and_match_track(client, token, "Remind Me to Forget", "Kygo")
        print("URI:", uri)
        
        if uri:
            track_id = uri.split(":")[-1]
            res = await client.get(f"https://api.spotify.com/v1/tracks/{track_id}", headers={"Authorization": f"Bearer {token}"})
            print("Track status:", res.status_code)
            if res.status_code == 200:
                data = res.json()
                print("Popularity:", data.get("popularity"))
                if data.get("album") and data["album"].get("release_date"):
                    print("Release:", data["album"]["release_date"])
                
                if data.get("artists"):
                    artist_id = data["artists"][0].get("id")
                    a_res = await client.get(f"https://api.spotify.com/v1/artists/{artist_id}", headers={"Authorization": f"Bearer {token}"})
                    print("Artist status:", a_res.status_code)
                    if a_res.status_code == 200:
                        print("Genres:", a_res.json().get("genres"))

asyncio.run(test())

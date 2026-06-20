import asyncio, httpx, dotenv
from app.services.spotify import SpotifyService
from app.core.database import SessionLocal
from app.models.schema import User

dotenv.load_dotenv()

async def test():
    db = SessionLocal()
    user = db.query(User).filter(User.spotify_access_token.isnot(None)).first()
    if not user:
        print("No user with spotify token")
        return
        
    client = httpx.AsyncClient()
    token = user.spotify_access_token
    print('User Token:', bool(token))
    
    res = await client.get('https://api.spotify.com/v1/audio-features?ids=6xTU6B6nFwKKTSZ9ySXS80', headers={'Authorization': f'Bearer {token}'})
    print('Res status:', res.status_code)
    print('Res json:', res.json())
    await client.aclose()

asyncio.run(test())

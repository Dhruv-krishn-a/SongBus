import asyncio
import httpx
import os
import json
import re
from dotenv import load_dotenv
from app.core.database import SessionLocal
from app.models.schema import Track

load_dotenv()
api_key = os.getenv("AICREDITS_API_KEY")

async def test_api():
    db = SessionLocal()
    tracks = db.query(Track).filter(Track.owner_id == 1).limit(10).all()
    db.close()
    
    if not tracks:
        print("No tracks found in the database.")
        return

    url = "https://api.aicredits.in/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    track_list = [f"ID: {t.id} | {t.title} by {t.artist}" for t in tracks]
    tracks_str = "\n".join(track_list)

    prompt = f"""
You are an expert music understanding system. I will provide a list of songs with their IDs.
For each song, deeply analyze its emotional signature, cultural context, and thematic content.

Return the result in valid JSON format as an object where keys are the track IDs (as strings), and values are objects containing these arrays of lowercase string tags:
- "genres": broad genres (e.g., ["desi-hip-hop", "urdu-poetry-rap", "pop"])
- "moods": the feeling (e.g., ["melancholic", "nostalgic", "introspective"])
- "themes": lyrical or cultural topics (e.g., ["yearning", "lost-love", "memory"])
- "emotions": human emotions (e.g., ["sadness", "hope", "regret"])
- "contexts": when/where to listen (e.g., ["late-night", "alone", "thinking-about-someone"])

Keep the arrays concise (2-4 tags each).

Tracks:
{tracks_str}

Example: {{"1": {{"genres": ["pop"], "moods": ["upbeat"], "themes": ["party"], "emotions": ["joy"], "contexts": ["workout"]}}}}
"""

    # We don't know exactly what model the user wrote, so we will use the one currently in api/music.py
    # Actually, we should parse it from api/music.py to be 100% accurate to what the user updated!
    with open("app/api/music.py", "r") as f:
        content = f.read()
        model_match = re.search(r'"model":\s*"([^"]+)"', content)
        model_name = model_match.group(1) if model_match else "google/gemini-2.5-flash"
    
    print(f"Using model found in code: {model_name}")

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            print("Sending 10 tracks to AI...")
            print("Tracks:\n" + tracks_str + "\n")
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                res_json = response.json()
                content = res_json['choices'][0]['message']['content']
                content = re.sub(r'```(?:json)?', '', content).strip()
                parsed = json.loads(content)
                print("\nSUCCESS! Parsed JSON Response:")
                print(json.dumps(parsed, indent=2))
            else:
                print(f"Failed Response: {response.text}")
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(test_api())

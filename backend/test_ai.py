import asyncio
import httpx
import os
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("AICREDITS_API_KEY")

async def test_api():
    url = "https://api.aicredits.in/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt = "Return exactly this JSON: {\"test\": \"success\"}"
    payload = {
        "model": "google/gemini-2.0-flash",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            print(f"Sending request to {url} with model {payload['model']}...")
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(test_api())

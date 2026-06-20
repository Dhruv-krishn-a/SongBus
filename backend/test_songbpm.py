import asyncio
import httpx

async def scrape():
    url = "https://songbpm.com/searches?q=Remind+Me+to+Forget+Kygo"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        res = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"})
        print("Status:", res.status_code)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, 'html.parser')
            # Just print the first few dl elements
            for dl in soup.find_all('dl')[:5]:
                print(dl.text)

asyncio.run(scrape())

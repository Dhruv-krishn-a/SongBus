from app.models.schema import Track
from typing import List
import re
import os

class AnalysisEngine:
    """
    Smart Analysis Engine for categorizing tracks based on metadata.
    Future versions can integrate ML models or external APIs (e.g., Librosa, Spotify Audio Features).
    """

    @staticmethod
    def classify_genre(track: Track) -> str:
        """
        Intelligently identifies genre based on metadata keywords.
        """
        text = f"{track.title} {track.artist} {track.album or ''}".lower()
        
        genre_map = {
            "Bollywood": ["bollywood", "hindi", "t-series", "arijit", "shreya", "neha kakkar", "punjabi", "bhangra"],
            "Electronic/Remix": ["remix", "edm", "trap", "house", "dubstep", "techno", "progressive", "mix"],
            "Rock/Metal": ["rock", "metal", "grunge", "punk", "alternative", "guitar", "band"],
            "Pop": ["pop", "hits", "chart", "top", "billboard"],
            "Hip-Hop/Rap": ["rap", "hip hop", "trap", "beats", "lofi hip hop"],
            "Classical": ["classical", "piano", "symphony", "orchestra", "violin", "sonata"],
            "Acoustic/Indie": ["acoustic", "unplugged", "indie", "lofi", "chill", "folk"],
            "Devotional": ["bhakti", "bhajan", "mantra", "god", "krishna", "shiva"],
        }

        for genre, keywords in genre_map.items():
            if any(kw in text for kw in keywords):
                return genre
        
        return track.genre or "Various"

    @staticmethod
    def classify_mood(track: Track) -> str:
        """
        Identifies mood based on metadata signals.
        """
        text = f"{track.title} {track.album or ''}".lower()
        
        mood_map = {
            "Energetic/Party": ["party", "dance", "club", "gym", "workout", "hype", "pump", "hard", "bass"],
            "Sad/Emotional": ["sad", "cry", "alone", "broken", "heart", "pain", "missing", "nostalgic"],
            "Chill/Relaxed": ["chill", "relax", "calm", "sleep", "lofi", "study", "peaceful", "soft"],
            "Romantic": ["love", "romance", "romantic", "valentines", "sweet", "ishq", "pyar"],
            "Dark/Intense": ["dark", "evil", "intense", "heavy", "shadow", "night", "danger"],
        }

        for mood, keywords in mood_map.items():
            if any(kw in text for kw in keywords):
                return mood
                
        return track.mood or "Neutral"

    @staticmethod
    def normalize_track_metadata(raw_title: str, raw_artist: str) -> dict:
        """
        Extracts clean Artist and Title from messy YouTube strings.
        Example: "Nico & Vinz - Am I Wrong (Gryffin Remix)" -> Artist: "Nico & Vinz", Title: "Am I Wrong (Gryffin Remix)"
        """
        # 1. Common "Noise" to strip from titles
        noise_patterns = [
            r"\(Official\s*Video\)", r"\[Official\s*Video\]",
            r"\(Lyrics\)", r"\[Lyrics\]",
            r"\(Audio\)", r"\[Audio\]",
            r"\(Official\s*Audio\)", r"\[Official\s*Audio\]",
            r"\(HD\)", r"\[HD\]",
            r"\(4K\)", r"\[4K\]",
            r"\(Full\s*Video\)", r"\[Full\s*Video\]",
            r"\(Lyric\s*Video\)", r"\[Lyric\s*Video\]",
            r"\(Visualizer\)", r"\[Visualizer\]",
            r"\|.*$", # Strip everything after a pipe (often channel names or extra info)
        ]

        clean_title = raw_title
        for pattern in noise_patterns:
            clean_title = re.sub(pattern, "", clean_title, flags=re.IGNORECASE).strip()

        # 2. Delimiter Split (Artist - Title)
        # Handle " - ", " – ", " | ", " : "
        delimiters = [
            r" - ",      # standard hyphen
            " \u2013 ",   # en dash
            " \u2014 ",   # em dash
            r" \| ",      # pipe
            r" : ",       # colon
            r" by ",      # "Artist by Title" or vice versa
        ]
        
        parsed_artist = raw_artist
        parsed_title = clean_title

        for delim in delimiters:
            if re.search(delim, clean_title):
                parts = re.split(delim, clean_title, maxsplit=1)
                parsed_artist = parts[0].strip()
                parsed_title = parts[1].strip()
                break
        
        # 3. Handle cases where Artist is "Various Artists" or channel names like "WaveMusic"
        # If the parsed artist looks like a known YouTube curator or the raw artist was a curator,
        # we try to keep the one extracted from the title.
        
        curators = {"wavemusic", "t-series", "sony music india", "zee music company", "vevo", "proximity", "trap nation"}
        if parsed_artist.lower() in curators and raw_artist.lower() not in curators:
             # If the split gave us a curator but the raw one wasn't, the raw one might be better?
             # Actually, usually the title is more reliable for Artist - Title.
             pass

        return {
            "title": parsed_title,
            "artist": parsed_artist
        }

    @staticmethod
    def parse_semantic_query(prompt: str) -> dict:
        """
        Translates a natural language user prompt into a structured JSON filter object
        that the database can execute.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "AI API Key not configured"}

        system_prompt = f"""
        You are an AI DJ mapping user intent to database parameters.
        The user will provide a prompt describing the kind of playlist they want.
        Translate their intent into the following strict JSON format. Only include the keys you are confident in filtering by.
        Do NOT wrap in markdown ticks.
        
        Valid Keys:
        - "bpm_min" (integer, e.g., 120 for workout, 60 for chill)
        - "bpm_max" (integer, e.g., 160)
        - "energy_min" (float 0.0 to 1.0, e.g., 0.8 for hype)
        - "energy_max" (float 0.0 to 1.0)
        - "danceability_min" (float 0.0 to 1.0)
        - "valence_min" (float 0.0 to 1.0, high is happy)
        - "valence_max" (float 0.0 to 1.0, low is sad/dark)
        - "genres" (array of strings, e.g., ["Pop", "Rock", "Electronic/Remix"])
        - "moods" (array of strings, e.g., ["Energetic/Party", "Chill/Relaxed", "Sad/Emotional"])
        
        User Prompt: "{prompt}"
        """

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": system_prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        import requests
        import json
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                content = response.json()['candidates'][0]['content']['parts'][0]['text']
                import re
                content = re.sub(r'```(?:json)?', '', content).strip()
                return json.loads(content)
            return {"error": "Failed to generate filters."}
        except Exception as e:
            print(f"AI Parse Error: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_ai_insights(tracks: List[Track]) -> dict:
        """
        Uses Gemini AI to analyze the library and provide deep insights.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "AI API Key not configured"}

        # Prepare a summarized list of tracks for the AI
        track_list = [f"{t.title} by {t.artist}" for t in tracks]
        tracks_str = "\n".join(track_list)

        prompt = f"""
        You are a world-class music critic and behavioral analyst. I am providing you with a list of songs from a user's personal music library.
        Based ONLY on the titles and artists provided, deeply analyze their musical taste and provide a sophisticated profile.
        
        Tracks:
        {tracks_str}
        
        Return the result in valid JSON format with exactly these keys:
        - "personality": A highly specific, 2-3 sentence 'Music Personality' profile. Be observant and creative, avoiding generic statements. Describe their vibe, energy, and the emotional resonance of their collection.
        - "themes": An array of the Top 3 dominant themes, eras, or motifs (e.g., ["Late-night Lo-Fi", "Aggressive Workout Energy", "Acoustic Melancholy"]).
        - "vibe_score": An integer (1-100) representing a 'Vibe Check' score, indicating how consistent or unique their taste is.
        - "recommendation": A single, specific song title and artist they should listen to next, which perfectly matches their taste but is NOT in the list provided.
        """

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json",
            }
        }

        try:
            import requests
            import json
            import re
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                content = result['candidates'][0]['content']['parts'][0]['text']
                # Strip markdown code blocks if the model wrapped the JSON
                content = re.sub(r'```(?:json)?', '', content).strip()
                return json.loads(content)
            return {"error": f"AI API Error: {response.text}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def batch_classify_ai(tracks: List[Track]) -> dict:
        """
        Uses Gemini AI to intelligently classify genres and moods for a list of tracks.
        Processes in chunks and implements retry logic for 503 errors.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "AI API Key not configured"}

        if not tracks:
            return {}

        import requests
        import json
        import re
        import time

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        
        all_classifications = {}
        chunk_size = 50
        
        for i in range(0, len(tracks), chunk_size):
            chunk = tracks[i:i + chunk_size]
            track_list = [f"ID: {t.id} | {t.title} by {t.artist}" for t in chunk]
            tracks_str = "\n".join(track_list)

            prompt = f"""
            You are an expert music classification AI. I will provide a list of songs with their IDs.
            For each song, determine the most accurate broad 'genre' and 'mood'.
            
            Genres should be standardized, e.g.: "Pop", "Rock", "Hip-Hop", "Electronic", "Classical", "Jazz", "R&B", "Indie", "Bollywood", "Devotional", "Acoustic".
            Moods should be descriptive, e.g.: "Energetic", "Chill", "Melancholy", "Romantic", "Upbeat", "Dark", "Focus", "Party".
            
            Tracks:
            {tracks_str}
            
            Return the result in valid JSON format as an object where the keys are the track IDs (as strings), and the values are objects with "genre" and "mood" strings.
            Example: {{"1": {{"genre": "Pop", "mood": "Upbeat"}}, "2": {{"genre": "Rock", "mood": "Energetic"}}}}
            """

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            }

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.post(url, json=payload, timeout=60)
                    if response.status_code == 200:
                        result = response.json()
                        content = result['candidates'][0]['content']['parts'][0]['text']
                        content = re.sub(r'```(?:json)?', '', content).strip()
                        parsed = json.loads(content)
                        all_classifications.update(parsed)
                        break # Success, break retry loop
                    elif response.status_code == 503:
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt) # Exponential backoff: 1s, 2s
                            continue
                        else:
                            return {"error": "AI API is currently overloaded. Please try again in a few minutes."}
                    else:
                        return {"error": f"AI API Error: {response.text}"}
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return {"error": str(e)}
                    
        return all_classifications

    @staticmethod
    def analyze_library(tracks: List[Track]) -> dict:
        """
        Generates basic insights for the user's library.
        """
        total_tracks = len(tracks)
        genres = {}
        artists = {}
        moods = {}

        for track in tracks:
            # Update Genre
            genre = AnalysisEngine.classify_genre(track)
            genres[genre] = genres.get(genre, 0) + 1
            
            # Update Mood
            mood = AnalysisEngine.classify_mood(track)
            moods[mood] = moods.get(mood, 0) + 1
            
            # Update Artist
            if track.artist:
                artists[track.artist] = artists.get(track.artist, 0) + 1

        top_artist = max(artists, key=artists.get) if artists else "Unknown"
        top_genre = max(genres, key=genres.get) if genres else "Unknown"

        return {
            "total_tracks": total_tracks,
            "top_artist": top_artist,
            "top_genre": top_genre,
            "mood_distribution": moods,
            "genre_distribution": genres
        }

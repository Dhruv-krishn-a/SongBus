from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import requests

from app.models.schema import Track


def _clean_string(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _split_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    parts = re.split(r"[,\|;/]+", text)
    return [p.strip() for p in parts if p.strip()]


def _join_tags(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, list):
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(cleaned) if cleaned else None
    cleaned = str(value).strip()
    return cleaned or None


def _strip_code_fences(text: str) -> str:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return cleaned


def fix_unescaped_quotes(json_str: str) -> str:
    chars = list(json_str)
    in_string = False
    escaped = False
    for i in range(len(chars)):
        c = chars[i]
        if c == "\\":
            escaped = not escaped
        elif c == "\"":
            if escaped:
                escaped = False
            else:
                is_boundary = False
                back_idx = i - 1
                while back_idx >= 0 and chars[back_idx].isspace():
                    back_idx -= 1
                fwd_idx = i + 1
                while fwd_idx < len(chars) and chars[fwd_idx].isspace():
                    fwd_idx += 1
                
                if back_idx >= 0 and chars[back_idx] in ("{", "[", ","):
                    is_boundary = True
                elif fwd_idx < len(chars) and chars[fwd_idx] == ":":
                    is_boundary = True
                elif back_idx >= 0 and chars[back_idx] == ":":
                    is_boundary = True
                elif fwd_idx < len(chars) and chars[fwd_idx] in (",", "}", "]"):
                    is_boundary = True
                
                if is_boundary:
                    in_string = not in_string
                else:
                    chars[i] = "\\\""
        else:
            escaped = False
    return "".join(chars)


def _parse_json_object(text: str) -> dict:
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as err:
        repaired = ""
        try:
            repaired = fix_unescaped_quotes(cleaned)
            parsed = json.loads(repaired)
        except Exception:
            print("JSON PARSE FAILED IN _parse_json_object!")
            print("Raw Text:", repr(text))
            print("Cleaned Text:", repr(cleaned))
            print("Repaired Text:", repr(repaired))
            raise err
    if not isinstance(parsed, dict):
        raise ValueError("AI response was not a JSON object")
    return parsed


def _parse_json_array(text: str) -> list:
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as err:
        repaired = ""
        try:
            repaired = fix_unescaped_quotes(cleaned)
            parsed = json.loads(repaired)
        except Exception:
            print("JSON PARSE FAILED IN _parse_json_array!")
            print("Raw Text:", repr(text))
            print("Cleaned Text:", repr(cleaned))
            print("Repaired Text:", repr(repaired))
            raise err
    if not isinstance(parsed, list):
        raise ValueError("AI response was not a JSON array")
    return parsed


def _aicredits_chat_completion(
    *,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    AICredits OpenAI-compatible chat completion helper.
    Docs:
    - https://aicredits.in/docs/api-reference
    - https://aicredits.in/docs/structured-outputs
    """
    api_key = os.getenv("AICREDITS_API_KEY")
    if not api_key:
        raise RuntimeError("AI API Key not configured")

    payload: Dict[str, Any] = {
        "model": model or os.getenv("AICREDITS_MODEL", "google/gemini-2.0-flash"),
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format
    # Do not set max_tokens inside payload since the AICredits gateway has a bug where passing 
    # max_tokens restricts the response to a tiny size (~60 tokens), causing truncation errors.
    pass

    response = requests.post(
        "https://api.aicredits.in/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )

    if response.status_code != 200:
        raise RuntimeError(f"AICredits API Error: {response.text}")

    result = response.json()
    try:
        content = result["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("AI response payload was malformed") from exc

    return _parse_json_object(content)


class AnalysisEngine:
    """
    Smart Analysis Engine for categorizing tracks based on metadata.

    This version keeps the lightweight keyword classifiers for fast local fallback,
    while routing structured AI calls through AICredits for richer semantic analysis.
    """

    @staticmethod
    def classify_genre(track: Track) -> str:
        """
        Intelligently identifies genre based on metadata keywords.
        """
        text = f"{track.title or ''} {track.artist or ''} {track.album or ''}".lower()

        genre_map = {
            "Bollywood": ["bollywood", "hindi", "t-series", "arijit", "shreya", "neha kakkar", "punjabi", "bhangra"],
            "Electronic/Remix": ["remix", "edm", "trap", "house", "dubstep", "techno", "progressive", "mix"],
            "Rock/Metal": ["rock", "metal", "grunge", "punk", "alternative", "guitar", "band"],
            "Pop": ["pop", "hits", "chart", "top", "billboard"],
            "Hip-Hop/Rap": ["rap", "hip hop", "hip-hop", "trap", "beats", "lofi hip hop"],
            "Classical": ["classical", "piano", "symphony", "orchestra", "violin", "sonata"],
            "Acoustic/Indie": ["acoustic", "unplugged", "indie", "lofi", "chill", "folk"],
            "Devotional": ["bhakti", "bhajan", "mantra", "god", "krishna", "shiva"],
            "R&B/Soul": ["r&b", "rnb", "soul", "neo soul", "groove"],
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
        text = f"{track.title or ''} {track.artist or ''} {track.album or ''}".lower()

        mood_map = {
            "Energetic/Party": ["party", "dance", "club", "gym", "workout", "hype", "pump", "hard", "bass", "turn up"],
            "Sad/Emotional": ["sad", "cry", "alone", "broken", "heart", "pain", "missing", "nostalgic", "tear"],
            "Chill/Relaxed": ["chill", "relax", "calm", "sleep", "lofi", "study", "peaceful", "soft", "laid back"],
            "Romantic": ["love", "romance", "romantic", "valentines", "sweet", "ishq", "pyar", "soulmate"],
            "Dark/Intense": ["dark", "evil", "intense", "heavy", "shadow", "night", "danger", "anger"],
            "Hopeful": ["hope", "dream", "believe", "rise", "light", "sunrise"],
            "Reflective": ["reflect", "memory", "memories", "thought", "introspective", "meditate"],
        }

        for mood, keywords in mood_map.items():
            if any(kw in text for kw in keywords):
                return mood

        return track.mood or "Neutral"

    @staticmethod
    def normalize_track_metadata(raw_title: str | None, raw_artist: str | None) -> dict:
        """
        Extracts clean Artist and Title from messy YouTube strings.

        Example:
            "Nico & Vinz - Am I Wrong (Gryffin Remix)"
            -> Artist: "Nico & Vinz", Title: "Am I Wrong (Gryffin Remix)"
        """
        raw_title = str(raw_title or "")
        raw_artist = str(raw_artist or "")

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
            r"\|.*$",
        ]

        clean_title = raw_title
        for pattern in noise_patterns:
            clean_title = re.sub(pattern, "", clean_title, flags=re.IGNORECASE).strip()

        delimiters = [
            r" - ",
            " \u2013 ",
            " \u2014 ",
            r" \| ",
            r" : ",
            r" by ",
        ]

        parsed_artist = raw_artist
        parsed_title = clean_title

        for delim in delimiters:
            if re.search(delim, clean_title, flags=re.IGNORECASE):
                parts = re.split(delim, clean_title, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) >= 2:
                    parsed_artist = parts[0].strip()
                    parsed_title = parts[1].strip()
                break

        curators = {"wavemusic", "t-series", "sony music india", "zee music company", "vevo", "proximity", "trap nation"}
        if parsed_artist.lower() in curators and raw_artist.lower() not in curators:
            pass

        artist = re.sub(r"(?i)\s*-\s*topic$", "", parsed_artist)
        artist = re.sub(r"(?i)\s+topic$", "", artist)
        artist = re.sub(r"(?i)vevo$", "", artist)
        artist = artist.strip(" -|:")

        title = parsed_title.strip()

        return {
            "title": title,
            "artist": artist,
        }

    @staticmethod
    def parse_semantic_query(prompt: str) -> dict:
        """
        Translates a natural language user prompt into a structured JSON filter object
        that the database can execute.
        """
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
        try:
            return _aicredits_chat_completion(
                messages=[{"role": "user", "content": system_prompt}],
                temperature=0.0,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            print(f"AI Parse Error: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_ai_insights(tracks: List[Track]) -> dict:
        """
        Uses AICredits AI to analyze the library and provide deep insights.
        """
        if not tracks:
            return {"error": "No tracks provided"}

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
        try:
            return _aicredits_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def batch_classify_ai(tracks: List[Track]) -> dict:
        """
        Uses AICredits AI to intelligently classify genres and moods for a list of tracks.
        Processes in chunks and implements retry logic for 429/503 errors.
        """
        if not tracks:
            return {}

        all_classifications = {}
        chunk_size = 50

        for i in range(0, len(tracks), chunk_size):
            chunk = tracks[i : i + chunk_size]
            track_list = [f"ID: {t.id} | {t.title} by {t.artist}" for t in chunk]
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

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    parsed = _aicredits_chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=4096,
                        response_format={"type": "json_object"},
                    )

                    for track_id, data in parsed.items():
                        if not isinstance(data, dict):
                            continue
                        all_classifications[str(track_id)] = {
                            "genre": ", ".join(_split_tags(data.get("genres"))),
                            "mood": ", ".join(_split_tags(data.get("moods"))),
                            "themes": ", ".join(_split_tags(data.get("themes"))),
                            "emotions": ", ".join(_split_tags(data.get("emotions"))),
                            "contexts": ", ".join(_split_tags(data.get("contexts"))),
                        }
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                    return {"error": str(e)}

        return all_classifications

    @staticmethod
    def auto_group_library_ai(tracks: List[Track]) -> dict:
        """
        Uses AICredits to dynamically generate highly creative playlist themes based on the ENTIRE library,
        then maps all tracks locally for scalability.
        """
        if not tracks:
            return {"error": "No tracks provided"}

        track_list = []
        for t in tracks:
            meta = f"{t.title} by {t.artist} | Genre: {t.genre or 'Unknown'} | Mood: {t.mood or 'Unknown'}"
            track_list.append(meta)

        tracks_str = "\n".join(track_list)

        prompt = f"""
You are a world-class DJ and music curator. I am providing you with a user's ENTIRE music library (thousands of tracks).
Your task is to invent 4 to 7 highly creative, personalized, and thematic playlists based on their overall taste.

DO NOT use generic names like "Pop Playlist". Be creative (e.g., "Neon Midnight Drives", "Sunday Morning Coffee").
For each playlist, provide an array of exactly 10 to 15 single-word lowercase keywords. These keywords should be a mix of genres, moods, AND exact names of artists that belong to this theme so I can programmatically search the rest of their library.

Sample Tracks:
{tracks_str}

Return valid JSON as an object with a single key "playlists" whose value is an array of objects.
Each object must have:
- "name" (string)
- "keywords" (array of lowercase strings)

Example:
{{"playlists": [{{"name": "Midnight Synthwave", "keywords": ["synthwave", "dark", "electronic", "kavinsky", "night", "ambient", "daft punk"]}}]}}
"""

        try:
            parsed = _aicredits_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            themes = parsed.get("playlists", [])
            if not isinstance(themes, list):
                themes = []

            final_playlists = []
            for theme in themes:
                if not isinstance(theme, dict):
                    continue
                theme_name = theme.get("name")
                keywords = theme.get("keywords", [])
                if isinstance(keywords, str):
                    keywords = [k.strip().lower() for k in keywords.split(",") if k.strip()]
                elif isinstance(keywords, list):
                    keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]
                else:
                    keywords = []

                matched_ids = []
                for t in tracks:
                    combined_tags: List[str] = []
                    combined_tags.extend(_split_tags(t.genre))
                    combined_tags.extend(_split_tags(t.mood))
                    combined_tags.extend(_split_tags(getattr(t, "themes", None)))
                    combined_tags.extend(_split_tags(getattr(t, "emotions", None)))
                    combined_tags.extend(_split_tags(getattr(t, "contexts", None)))
                    if t.title:
                        combined_tags.extend(re.findall(r"[a-z0-9]+", t.title.lower()))
                    if t.artist:
                        combined_tags.extend(re.findall(r"[a-z0-9]+", t.artist.lower()))

                    normalized_combined = {_clean_string(tag) for tag in combined_tags if tag}
                    normalized_keywords = {_clean_string(kw) for kw in keywords if kw}

                    if normalized_combined & normalized_keywords:
                        matched_ids.append(t.id)
                        continue

                    if any(
                        kw and any(kw in _clean_string(tag) or _clean_string(tag) in kw for tag in combined_tags)
                        for kw in keywords
                    ):
                        matched_ids.append(t.id)

                final_playlists.append(
                    {
                        "name": theme_name,
                        "track_ids": matched_ids,
                    }
                )

            return {"playlists": final_playlists}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def analyze_library(tracks: List[Track]) -> dict:
        """
        Generates basic insights for the user's library.
        """
        total_tracks = len(tracks)
        genres: Dict[str, int] = {}
        artists: Dict[str, int] = {}
        moods: Dict[str, int] = {}
        themes: Dict[str, int] = {}
        emotions: Dict[str, int] = {}
        contexts: Dict[str, int] = {}

        for track in tracks:
            for genre in _split_tags(AnalysisEngine.classify_genre(track)):
                genres[genre] = genres.get(genre, 0) + 1

            for mood in _split_tags(AnalysisEngine.classify_mood(track)):
                moods[mood] = moods.get(mood, 0) + 1

            if track.artist:
                artists[track.artist] = artists.get(track.artist, 0) + 1

            for theme in _split_tags(getattr(track, "themes", None)):
                themes[theme] = themes.get(theme, 0) + 1

            for emotion in _split_tags(getattr(track, "emotions", None)):
                emotions[emotion] = emotions.get(emotion, 0) + 1

            for context in _split_tags(getattr(track, "contexts", None)):
                contexts[context] = contexts.get(context, 0) + 1

        top_artist = max(artists, key=artists.get) if artists else "Unknown"
        top_genre = max(genres, key=genres.get) if genres else "Unknown"
        top_mood = max(moods, key=moods.get) if moods else "Unknown"

        return {
            "total_tracks": total_tracks,
            "top_artist": top_artist,
            "top_genre": top_genre,
            "top_mood": top_mood,
            "mood_distribution": moods,
            "genre_distribution": genres,
            "theme_distribution": themes,
            "emotion_distribution": emotions,
            "context_distribution": contexts,
        }

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import List

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import tasks
from app.core.database import SessionLocal, get_db
from app.models import schema
from app.services.analysis import AnalysisEngine
from app.services.lyrics import LyricsService
from app.services.spotify import SpotifyService


class BatchNormalizeRequest(BaseModel):
    track_ids: List[int]


router = APIRouter()

# Keep sorting predictable and index-friendly.
_ALLOWED_SORT_COLUMNS = {
    "created_at": "created_at",
    "title": "title",
    "artist": "artist",
    "album": "album",
    "genre": "genre",
    "mood": "mood",
    "source": "source",
    "release_year": "release_year",
    "popularity": "popularity",
}


def _safe_sort_column(sort_by: str | None):
    key = (sort_by or "created_at").strip().lower()
    column_name = _ALLOWED_SORT_COLUMNS.get(key, "created_at")
    return getattr(schema.Track, column_name, schema.Track.created_at)


def _parse_json_object(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("AI response was not a JSON object")
    return parsed


def _retry_delay_seconds(response: requests.Response | None, attempt: int) -> int:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1, int(float(retry_after)))
            except Exception:
                pass
    return min(30, 2**attempt)


def _clean_ai_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _ai_cache_key(prefix: str, title: str | None, artist: str | None) -> str:
    return f"{prefix}:{_clean_ai_text(title)}:{_clean_ai_text(artist)}"


def _coerce_string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            item_str = str(item).strip()
            if item_str:
                result.append(item_str)
        return result
    item = str(value).strip()
    return [item] if item else []


def _join_tags(value, limit: int | None = None) -> str | None:
    tags = _coerce_string_list(value)
    if limit is not None:
        tags = tags[:limit]
    if not tags:
        return None
    return ", ".join(tags)


def _normalized_ai_payload(info: dict) -> dict:
    """
    Normalizes rich AI output into a predictable shape.
    Supports both legacy single genre/mood fields and the newer plural tag schema.
    """
    genres = _coerce_string_list(info.get("genres"))
    moods = _coerce_string_list(info.get("moods"))
    themes = _coerce_string_list(info.get("themes"))
    emotions = _coerce_string_list(info.get("emotions"))
    contexts = _coerce_string_list(info.get("contexts"))

    genre = info.get("genre")
    mood = info.get("mood")

    # Fallbacks for backwards compatibility
    if not genres and genre:
        genres = _coerce_string_list(genre)
    if not moods and mood:
        moods = _coerce_string_list(mood)

    return {
        "genre": _join_tags(genres, limit=2) or _join_tags(genre, limit=2),
        "mood": _join_tags(moods, limit=2) or _join_tags(mood, limit=2),
        "genres": genres,
        "moods": moods,
        "themes": themes,
        "emotions": emotions,
        "contexts": contexts,
    }



@router.get("/library")
def get_library(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    artist: str | None = None,
    genre: str | None = None,
    mood: str | None = None,
    search: str | None = None,
    source: str | None = None,
    sort_by: str | None = "created_at",
    sort_order: str | None = "desc",
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id)

    if source:
        query = query.filter(schema.Track.source == source)
    if artist:
        query = query.filter(schema.Track.artist.ilike(f"%{artist}%"))
    if genre:
        query = query.filter(schema.Track.genre == genre)
    if mood:
        query = query.filter(schema.Track.mood == mood)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (schema.Track.title.ilike(search_filter))
            | (schema.Track.artist.ilike(search_filter))
            | (schema.Track.album.ilike(search_filter))
        )

    sort_col = _safe_sort_column(sort_by)
    if (sort_order or "desc").lower() == "desc":
        query = query.order_by(sort_col.desc(), schema.Track.id.desc())
    else:
        query = query.order_by(sort_col.asc(), schema.Track.id.asc())

    total = query.count()
    tracks = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "tracks": tracks,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


@router.delete("/tracks/{track_id}")
def delete_track(
    track_id: int,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = (
        db.query(schema.Track)
        .filter(schema.Track.id == track_id, schema.Track.owner_id == current_user.id)
        .first()
    )

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.track_id == track_id).delete()
    db.delete(track)
    db.commit()
    return {"message": "Track deleted successfully"}


@router.post("/clean-database")
def clean_database(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cleans the database by removing duplicates, junk tracks, and normalizing metadata."""
    from app.services.cleaner import DataCleaner
    result = DataCleaner.clean_database(db, current_user.id)
    return {
        "message": f"Database cleaned! Deleted {result.get('deleted_junk', 0)} junk tracks, merged {result['merged_groups']} groups, and deleted {result['deleted_duplicates']} duplicates.",
        "details": result
    }


@router.get("/tracks/{track_id}/enrich")
async def enrich_single_track(track_id: int, db: Session = Depends(get_db), current_user: schema.User = Depends(get_current_user)):
    track = db.query(schema.Track).filter(schema.Track.id == track_id, schema.Track.owner_id == current_user.id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    
    import httpx
    import asyncio
    from app.services.lyrics import LyricsService
    from app.services.spotify import SpotifyService
    from app.services.analysis import AnalysisEngine
    
    updated = False
    
    # Clean messy YouTube titles before searching
    raw_title = track.title or ""
    raw_artist = track.artist or ""
    clean_meta = AnalysisEngine.normalize_track_metadata(raw_title, raw_artist)
    search_title = clean_meta["title"]
    search_artist = clean_meta["artist"]
    
    async with httpx.AsyncClient() as client:
        # 1. Fetch Lyrics if missing (Force retry even if previously not found, since user clicked it)
        if not track.lyrics:
            try:
                res = await LyricsService.async_fetch_lyrics(client, search_title, search_artist, track.album, track.duration_ms)
                if res:
                    track.lyrics = res
                    track.lyrics_not_found = False
                    updated = True
                else:
                    track.lyrics_not_found = True
                    updated = True
            except Exception as e:
                pass
        # 2. Fetch Deep Classification Data (Genres, Popularity, Release Year, Explicit)
        if track.popularity is None or track.genre is None:
            try:
                from app.services.spotify import SpotifyService
                spotify_service = SpotifyService()
                
                # Use User token or App token
                token = current_user.spotify_access_token
                if not token:
                    token = await spotify_service.async_get_app_token(client)
                
                if token:
                    if not track.spotify_uri:
                        uri = await spotify_service.async_search_and_match_track(client, token, search_title, search_artist, track.duration_ms)
                        if uri:
                            track.spotify_uri = uri
                            updated = True
                    
                    if track.spotify_uri:
                        spotify_track_id = track.spotify_uri.split(":")[-1]
                        res = await client.get(f"https://api.spotify.com/v1/tracks/{spotify_track_id}", headers={"Authorization": f"Bearer {token}"})
                        if res.status_code == 200:
                            data = res.json()
                            track.popularity = data.get("popularity")
                            track.explicit = data.get("explicit")
                            if data.get("album") and data["album"].get("release_date"):
                                track.release_year = data["album"]["release_date"].split("-")[0]
                            
                            if data.get("artists") and len(data["artists"]) > 0:
                                artist_id = data["artists"][0].get("id")
                                a_res = await client.get(f"https://api.spotify.com/v1/artists/{artist_id}", headers={"Authorization": f"Bearer {token}"})
                                if a_res.status_code == 200:
                                    a_data = a_res.json()
                                    genres = a_data.get("genres", [])
                                    if genres:
                                        track.genre = ", ".join(genres[:3])
                            updated = True
            except Exception as e:
                pass

        # Last.fm integration removed as requested, using AI for tags exclusively.

    if updated:
        track.last_enriched_at = datetime.utcnow()
        db.commit()
        db.refresh(track)
        
    return track


@router.post("/normalize/{track_id}")
def normalize_track(
    track_id: int,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = (
        db.query(schema.Track)
        .filter(schema.Track.id == track_id, schema.Track.owner_id == current_user.id)
        .first()
    )

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    normalized = AnalysisEngine.normalize_track_metadata(track.title, track.artist)

    track.title = normalized["title"]
    track.artist = normalized["artist"]

    # Re-classify with new metadata
    track.genre = AnalysisEngine.classify_genre(track)
    track.mood = AnalysisEngine.classify_mood(track)

    db.commit()
    db.refresh(track)

    return track


@router.get("/normalize/preview")
def preview_normalization(
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracks = (
        db.query(schema.Track)
        .filter(schema.Track.owner_id == current_user.id)
        .yield_per(500)
    )
    preview = []

    for track in tracks:
        normalized = AnalysisEngine.normalize_track_metadata(track.title, track.artist)
        if normalized["title"] != track.title or normalized["artist"] != track.artist:
            preview.append(
                {
                    "id": track.id,
                    "current_title": track.title,
                    "current_artist": track.artist,
                    "proposed_title": normalized["title"],
                    "proposed_artist": normalized["artist"],
                }
            )

    return {"preview": preview}


def _classify_all_task(task_id: str, user_id: int):
    db = SessionLocal()
    session = requests.Session()

    try:
        tasks.update_task(task_id, status="running", message="Loading library...")
        tracks = db.query(schema.Track).filter(schema.Track.owner_id == user_id).all()
        if not tracks:
            tasks.update_task(task_id, status="completed", message="Library is empty.", progress=0, total=0)
            return

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            tasks.update_task(task_id, status="failed", error="AI API Key not configured")
            return

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent?key={api_key}"

        chunk_size = 50
        total_tracks = len(tracks)
        tasks.update_task(task_id, total=total_tracks, message="Starting AI classification...")

        updated_count = 0
        processed_count = 0

        for i in range(0, total_tracks, chunk_size):
            chunk = tracks[i : i + chunk_size]
            track_list = [f"ID: {t.id} | {t.title} by {t.artist}" for t in chunk]
            tracks_str = "\n".join(track_list)

            prompt = f"""
You are an expert music understanding system. I will provide a list of songs with their IDs.
For each song, identify rich music metadata using only lowercase string tags.

Return valid JSON as an object where keys are track IDs (as strings), and values are objects containing:
- "genres": broad genres (2-4 tags)
- "moods": the feeling (2-4 tags)
- "themes": lyrical or cultural topics (2-4 tags)
- "emotions": human emotions (2-4 tags)
- "contexts": when/where to listen (2-4 tags)

Tracks:
{tracks_str}

Example: {{"1": {{"genres": ["pop"], "moods": ["upbeat"], "themes": ["party"], "emotions": ["joy"], "contexts": ["workout"]}}}}
"""

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"},
            }

            max_retries = 3
            success = False

            for attempt in range(max_retries):
                try:
                    response = session.post(url, json=payload, timeout=60)
                    if response.status_code == 200:
                        result = response.json()
                        content = result["candidates"][0]["content"]["parts"][0]["text"]
                        classifications = _parse_json_object(content)

                        chunk_updated = 0
                        for track in chunk:
                            track_id_str = str(track.id)
                            info = classifications.get(track_id_str)
                            if isinstance(info, dict):
                                changed = False
                                normalized = _normalized_ai_payload(info)

                                if normalized["genre"]:
                                    track.genre = normalized["genre"]
                                    changed = True
                                if normalized["mood"]:
                                    track.mood = normalized["mood"]
                                    changed = True

                                if hasattr(track, "themes") and normalized["themes"]:
                                    track.themes = normalized["themes"]
                                    changed = True
                                if hasattr(track, "emotions") and normalized["emotions"]:
                                    track.emotions = normalized["emotions"]
                                    changed = True
                                if hasattr(track, "contexts") and normalized["contexts"]:
                                    track.contexts = normalized["contexts"]
                                    changed = True

                                if changed:
                                    chunk_updated += 1

                        db.commit()
                        updated_count += chunk_updated
                        success = True
                        break

                    if response.status_code in (429, 502, 503, 504):
                        if attempt < max_retries - 1:
                            time.sleep(_retry_delay_seconds(response, attempt))
                            continue
                        tasks.update_task(
                            task_id,
                            status="failed",
                            error="AI API is temporarily unavailable. Please try again later.",
                        )
                        return

                    tasks.update_task(task_id, status="failed", error=f"AI API Error: {response.text}")
                    return

                except Exception as exc:
                    if attempt < max_retries - 1:
                        time.sleep(_retry_delay_seconds(None, attempt))
                        continue
                    tasks.update_task(task_id, status="failed", error=str(exc))
                    return

            if success:
                processed_count += len(chunk)
                tasks.update_task(
                    task_id,
                    progress=processed_count,
                    message=f"Classified {processed_count}/{total_tracks} tracks...",
                )

        result = {
            "message": f"Successfully AI classified {updated_count} tracks.",
            "updated_count": updated_count,
        }
        tasks.update_task(
            task_id,
            status="completed",
            message="Classification complete!",
            progress=total_tracks,
            result=result,
        )

    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        session.close()
        db.close()


@router.post("/normalize/batch")
def batch_normalize(
    request: BatchNormalizeRequest,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracks = (
        db.query(schema.Track)
        .filter(schema.Track.id.in_(request.track_ids), schema.Track.owner_id == current_user.id)
        .all()
    )

    for track in tracks:
        normalized = AnalysisEngine.normalize_track_metadata(track.title, track.artist)
        track.title = normalized["title"]
        track.artist = normalized["artist"]
        track.genre = AnalysisEngine.classify_genre(track)
        track.mood = AnalysisEngine.classify_mood(track)

    db.commit()
    return {"message": f"Successfully normalized {len(tracks)} tracks"}


@router.post("/clear")
def clear_database(
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes all tracks and playlist links for the current user."""
    db.query(schema.PlaylistTrack).filter(
        schema.PlaylistTrack.playlist_id.in_(
            db.query(schema.Playlist.id).filter(schema.Playlist.owner_id == current_user.id)
        )
    ).delete(synchronize_session=False)

    db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).delete(synchronize_session=False)
    db.commit()
    return {"message": "Database cleared successfully"}


@router.get("/insights")
def get_insights(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
    insights = AnalysisEngine.analyze_library(tracks)
    return insights


@router.get("/insights/ai")
def get_ai_insights_endpoint(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Generates AI insights using Gemini based on the current library."""
    tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
    if not tracks:
        raise HTTPException(status_code=400, detail="Import some music first to generate AI insights.")

    return AnalysisEngine.get_ai_insights(tracks)


@router.get("/playlists")
def get_playlists(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlists = db.query(schema.Playlist).filter(schema.Playlist.owner_id == current_user.id).all()
    return {"playlists": playlists}


# --- High Performance Multi-Threaded Enrichment ---
GLOBAL_URI_CACHE = {}
GLOBAL_LYRICS_CACHE = {}
SPOTIFY_COOLDOWN_UNTIL = 0
YT_COOLDOWN_UNTIL = 0

def enrich_tracks_chunk(db: Session, tracks: List[schema.Track], user_id: int, include_lyrics: bool = False, spotify_client=None, yt_service=None):
    """
    Core enrichment logic that matches tracks across platforms, 
    fetches DNA (BPM/Energy), and retrieves lyrics.
    """
    import concurrent.futures
    import time
    from app.services.ytmusic import YTMusicService
    global SPOTIFY_COOLDOWN_UNTIL, YT_COOLDOWN_UNTIL
    
    # 1. Initialize Services if not provided
    spotify_service = SpotifyService()
    if not spotify_client:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if user and user.spotify_access_token:
            try:
                spotify_client = spotify_service.get_valid_client(user, db)
            except Exception: pass
            
    if not yt_service:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if user and user.yt_access_token:
            yt_service = YTMusicService.get_valid_client(user, db)
        else:
            yt_service = YTMusicService()

    # 2. Bulk Stateless Cache
    from sqlalchemy import tuple_
    track_keys = [(t.title, t.artist) for t in tracks]
    if track_keys:
        cache_matches = db.query(schema.Track).filter(
            tuple_(schema.Track.title, schema.Track.artist).in_(track_keys),
            (schema.Track.bpm.is_not(None)) | (schema.Track.lyrics.is_not(None))
        ).all()
        
        cache_map = {(m.title, m.artist): m for m in cache_matches}
        for t in tracks:
            m = cache_map.get((t.title, t.artist))
            if m:
                if not t.bpm:
                    t.bpm, t.energy, t.danceability, t.valence = m.bpm, m.energy, m.danceability, m.valence
                if not t.lyrics: t.lyrics = m.lyrics
                if not t.spotify_uri: t.spotify_uri = m.spotify_uri
                if not t.matched_youtube_id: t.matched_youtube_id = m.matched_youtube_id

    def process_track_thread(t_data):
        res = {"spotify_uri": None, "matched_youtube_id": None, "lyrics": None}
        global SPOTIFY_COOLDOWN_UNTIL, YT_COOLDOWN_UNTIL
        try:
            if t_data.get("spotify_uri") and t_data.get("lyrics") and t_data.get("matched_youtube_id"):
                return res

            # 1. Spotify Match (Skip if in Cooldown)
            if spotify_client and not t_data.get("spotify_uri"):
                if time.time() > SPOTIFY_COOLDOWN_UNTIL:
                    try:
                        uri = spotify_service.search_and_match_track(spotify_client, type('obj', (object,), t_data))
                        if uri: res["spotify_uri"] = uri
                    except Exception as e:
                        if "429" in str(e):
                            SPOTIFY_COOLDOWN_UNTIL = time.time() + 60 # 1 min backoff
                        print(f"Spotify Search Rate Limit: {e}")
            
            # 2. YouTube Match (Skip if in Cooldown)
            if not t_data.get("matched_youtube_id") and t_data.get("source") == "spotify":
                if time.time() > YT_COOLDOWN_UNTIL:
                    try:
                        yt_id = yt_service.search_and_match_track(t_data['title'], t_data['artist'], t_data.get('duration_ms'))
                        if yt_id: res["matched_youtube_id"] = yt_id
                    except Exception as e:
                        if "429" in str(e):
                            YT_COOLDOWN_UNTIL = time.time() + 60
            
            # 3. Lyrics
            if include_lyrics and not t_data.get("lyrics"):
                lyrics = LyricsService.fetch_lyrics(t_data['title'], t_data['artist'], t_data.get('album'), t_data.get('duration_ms'))
                if lyrics: res["lyrics"] = lyrics
        except Exception: pass
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        track_data = [
            {
                "title": t.title, "artist": t.artist, "album": t.album, 
                "duration_ms": t.duration_ms, "spotify_uri": t.spotify_uri,
                "matched_youtube_id": t.matched_youtube_id, "lyrics": t.lyrics,
                "source": t.source
            } for t in tracks
        ]
        
        futures = {executor.submit(process_track_thread, d): idx for idx, d in enumerate(track_data)}
        for future in concurrent.futures.as_completed(futures):
            try:
                idx = futures[future]
                result = future.result()
                t = tracks[idx]
                if result.get("spotify_uri"): t.spotify_uri = result["spotify_uri"]
                if result.get("matched_youtube_id"): t.matched_youtube_id = result["matched_youtube_id"]
                if result.get("lyrics"): t.lyrics = result["lyrics"]
                t.last_enriched_at = datetime.utcnow()
            except Exception: pass
        
        # 3. Bulk DNA (Safe from Search Rate limits)
        if spotify_client:
            matched_uris = [t.spotify_uri for t in tracks if t.spotify_uri and t.bpm is None]
            if matched_uris:
                track_map = {t.spotify_uri: t for t in tracks if t.spotify_uri}
                try:
                    features = spotify_service.get_audio_features(spotify_client, matched_uris)
                    for f in features or []:
                        if f and f.get("uri") in track_map:
                            target = track_map[f["uri"]]
                            target.bpm = f.get("tempo")
                            target.energy = f.get("energy")
                            target.danceability = f.get("danceability")
                            target.valence = f.get("valence")
                except Exception: pass
    
    db.commit()

def _fetch_lyrics_task(task_id: str, user_id: int):
    from datetime import datetime
    import asyncio
    import httpx
    import redis.asyncio as redis
    from app.services.lyrics import LyricsService

    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        # Only query tracks that don't have lyrics and haven't been marked as unfound (handling NULLs)
        tracks = (
            db.query(schema.Track)
            .filter(schema.Track.owner_id == user_id)
            .filter(schema.Track.lyrics.is_(None))
            .filter(or_(schema.Track.lyrics_not_found == False, schema.Track.lyrics_not_found.is_(None)))
            .all()
        )

        if not tracks:
            tasks.update_task(task_id, status="completed", message="All missing lyrics have been searched.", progress=0, total=0)
            return

        total_tracks = len(tracks)
        tasks.update_task(task_id, total=total_tracks, message="Fetching lyrics...")

        async def _async_lyrics_fetcher():
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            
            # Use httpx.AsyncClient and semaphore to limit concurrency respectfully
            semaphore = asyncio.Semaphore(15) # 15 concurrent requests max
            processed = 0
            
            # Share a single async client for all requests
            async with httpx.AsyncClient() as client:
                async def process_track(track_id, title, artist, album, duration_ms):
                    title_str = title or ""
                    artist_str = artist or ""
                    
                    cache_key = f"lyrics:{LyricsService._clean_string(title_str)}:{LyricsService._clean_string(artist_str)}"
                    
                    # 1. Global Redis Deduplication Check
                    try:
                        cached = await redis_client.get(cache_key)
                        if cached:
                            if cached == "NOT_FOUND":
                                return track_id, None, False
                            return track_id, cached, False
                    except Exception as e:
                        pass
                    
                    # 2. Async API Fetch with Concurrency Limit
                    network_error = False
                    async with semaphore:
                        try:
                            res = await LyricsService.async_fetch_lyrics(client, title_str, artist_str, album, duration_ms)
                        except httpx.RequestError:
                            network_error = True
                            res = None
                        except Exception:
                            res = None
                        
                        # 3. Save to Global Cache (only if no network error)
                        if not network_error:
                            try:
                                if res:
                                    await redis_client.set(cache_key, res, ex=86400 * 30) # Cache for 30 days globally
                                else:
                                    # We cache NOT_FOUND for 1 day
                                    await redis_client.set(cache_key, "NOT_FOUND", ex=86400)
                            except Exception as e:
                                pass
                        
                        return track_id, res, network_error

                chunk_size = 50
                for i in range(0, total_tracks, chunk_size):
                    chunk = tracks[i:i+chunk_size]
                    fetch_tasks = [
                        process_track(t.id, t.title, t.artist, t.album, t.duration_ms) 
                        for t in chunk
                    ]
                    responses = await asyncio.gather(*fetch_tasks)
                    
                    # Process results and COMMIT incrementally
                    network_failures_in_chunk = 0
                    for tid, lyrics, net_err in responses:
                        if net_err:
                            network_failures_in_chunk += 1
                            continue # Skip DB updates for this track to try again later
                            
                        # Find track object
                        t = next((tr for tr in chunk if tr.id == tid), None)
                        if t:
                            if lyrics:
                                t.lyrics = lyrics
                            else:
                                t.lyrics_not_found = True
                            t.last_enriched_at = datetime.utcnow()
                    
                    # Commit this chunk to DB immediately (Rock-solid resume support)
                    db.commit()
                        
                    processed += len(chunk)
                    
                    if network_failures_in_chunk > 20:
                        # Massive network drop detected, abort gracefully
                        raise Exception("Severe network instability detected. Task paused to protect data. Please resume later.")

                    # Safely run the synchronous DB update outside of the concurrent worker threads!
                    await asyncio.to_thread(tasks.update_task, task_id, status="running", progress=processed, message=f"Processed {processed}/{total_tracks} tracks...")

            await redis_client.aclose()
            return processed

        # Run async code inside the synchronous FastAPI BackgroundTask thread
        processed_count = asyncio.run(_async_lyrics_fetcher())

        tasks.update_task(task_id, status="completed", message=f"Successfully processed {processed_count} tracks.")
    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()

def _run_ai_classification_task(task_id: str, user_id: int):
    from datetime import datetime
    import asyncio
    import httpx
    import json
    import os
    import re
    import redis.asyncio as redis
    from app.services.analysis import AnalysisEngine

    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        # Query tracks missing genre or mood
        tracks = (
            db.query(schema.Track)
            .filter(schema.Track.owner_id == user_id)
            .filter((schema.Track.genre.is_(None)) | (schema.Track.mood.is_(None)))
            .filter(or_(schema.Track.ai_not_found == False, schema.Track.ai_not_found.is_(None)))
            .all()
        )

        if not tracks:
            tasks.update_task(task_id, status="completed", message="AI classification is up to date.", progress=0, total=0)
            return

        total_tracks = len(tracks)
        tasks.update_task(task_id, total=total_tracks, message="Running AI Classification...")

        # Convert tracks to list of dictionaries to avoid lazy loading of properties across threads/async tasks
        plain_tracks = []
        for t in tracks:
            plain_tracks.append({
                "id": t.id,
                "title": t.title or "",
                "artist": t.artist or "",
                "album": t.album or ""
            })

        async def _async_ai_classifier():
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            api_key = os.getenv("AICREDITS_API_KEY")
            
            results = {}
            processed = 0
            
            # Step 1: Check Global Redis Cache first
            uncached_tracks = []
            for t in plain_tracks:
                title = t["title"]
                artist = t["artist"]
                cache_key = _ai_cache_key("ai_class_deep", title, artist)
                
                try:
                    cached = await redis_client.get(cache_key)
                    if cached:
                        if cached != "NOT_FOUND":
                            data = json.loads(cached)
                            results[t["id"]] = data
                        processed += 1
                        if processed % 10 == 0:
                            tasks.update_task(task_id, progress=processed, message=f"Processed {processed}/{total_tracks} tracks (Cache hit)...")
                        continue
                except Exception as e:
                    print(f"Redis AI cache error: {e}")
                
                uncached_tracks.append(t)

            if not api_key and uncached_tracks:
                # Fallback to local heuristic if no API key
                for t in uncached_tracks:
                    class MockTrack:
                        def __init__(self, title, artist, album):
                            self.title, self.artist, self.album = title, artist, album
                            self.genre, self.mood = None, None
                    mock_t = MockTrack(t["title"], t["artist"], t["album"])
                    genre = AnalysisEngine.classify_genre(mock_t)
                    mood = AnalysisEngine.classify_mood(mock_t)
                    results[t["id"]] = {
                        "genre": genre,
                        "mood": mood,
                        "genres": _coerce_string_list(genre),
                        "moods": _coerce_string_list(mood),
                        "themes": [],
                        "emotions": [],
                        "contexts": [],
                    }
                return results

            if uncached_tracks:
                # Use AICredits gateway – model gemini-2.5-flash
                chunk_size = 50
                if not api_key:
                    tasks.update_task(task_id, status='failed', error='AICREDITS_API_KEY not set')
                    return results
                url = "https://api.aicredits.in/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                async with httpx.AsyncClient() as client:
                    for i in range(0, len(uncached_tracks), chunk_size):
                        chunk = uncached_tracks[i:i + chunk_size]
                        
                        track_list = [f"ID: {t['id']} | {t['title']} by {t['artist']}" for t in chunk]
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

Keep the arrays concise (2-4 tags each). Use lowercase tags only.

Tracks:
{tracks_str}

Example: {{"1": {{"genres": ["pop"], "moods": ["upbeat"], "themes": ["party"], "emotions": ["joy"], "contexts": ["workout"]}}}}
"""
                        payload = {
                            "model": "google/gemini-2.5-flash",
                            "messages": [{"role": "user", "content": prompt}],
                            "response_format": {"type": "json_object"}
                        }
                        
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                response = await client.post(url, headers=headers, json=payload, timeout=120.0)
                                if response.status_code == 200:
                                    res_json = response.json()
                                    content = res_json['choices'][0]['message']['content']
                                    content = re.sub(r'```(?:json)?', '', content).strip()
                                    parsed = json.loads(content)
                                    for t in chunk:
                                        t_id_str = str(t["id"])
                                        if t_id_str in parsed:
                                            info = parsed[t_id_str]
                                            
                                            gs = info.get("genres", [])
                                            ms = info.get("moods", [])
                                            ts = info.get("themes", [])
                                            ems = info.get("emotions", [])
                                            ctxs = info.get("contexts", [])
                                            
                                            def format_list(val):
                                                if not val:
                                                    return None
                                                if isinstance(val, list):
                                                    return ", ".join(str(x).strip() for x in val if str(x).strip())
                                                return str(val).strip()
                                                
                                            results[t["id"]] = {
                                                "genre": format_list(info.get("genre") or gs),
                                                "mood": format_list(info.get("mood") or ms),
                                                "themes": format_list(ts),
                                                "emotions": format_list(ems),
                                                "contexts": format_list(ctxs),
                                            }
                                            
                                            # cache result
                                            cache_key = _ai_cache_key("ai_class_deep", t["title"], t["artist"])
                                            try:
                                                await redis_client.set(cache_key, json.dumps(results[t["id"]]), ex=86400 * 30)
                                            except Exception:
                                                pass
                                    processed += len(chunk)
                                    tasks.update_task(task_id, progress=processed, message=f"AI Classified {processed}/{total_tracks} tracks...")
                                    break
                                elif response.status_code in (429, 503):
                                    if attempt < max_retries - 1:
                                        await asyncio.sleep(2 ** attempt)
                                        continue
                                else:
                                    tasks.update_task(task_id, status='failed', error=f"AICredits error {response.status_code}: {response.text}")
                                    return results
                            except Exception as e:
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                                else:
                                    tasks.update_task(task_id, status='failed', error=str(e))
                                    return results
                        
            await redis_client.aclose()
            return results

        # Run async logic
        results = asyncio.run(_async_ai_classifier())

        found = 0
        for t in tracks:
            info = results.get(t.id)
            if info:
                t.genre = info.get("genre") or t.genre
                t.mood = info.get("mood") or t.mood
                t.themes = info.get("themes") or t.themes
                t.emotions = info.get("emotions") or t.emotions
                t.contexts = info.get("contexts") or t.contexts
                found += 1
            else:
                t.ai_not_found = True
            t.last_enriched_at = datetime.utcnow()
            
        db.commit()

        tasks.update_task(task_id, status="completed", message=f"Successfully classified {found} tracks.")
    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()

@router.post("/fetch-lyrics")
def fetch_missing_lyrics(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Starts a background worker to fetch missing lyrics."""
    active = tasks.get_active_tasks(current_user.id)
    existing = next((t for t in active if t['name'] == "Fetch Lyrics"), None)
    if existing:
        return {"task_id": existing['id'], "message": "Lyrics fetching already in progress"}

    task_id = tasks.create_task("Fetch Lyrics", current_user.id)
    background_tasks.add_task(_fetch_lyrics_task, task_id, current_user.id)
    return {"task_id": task_id}


@router.post("/classify-all")
def classify_all_tracks(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Starts a dedicated background task to classify tracks using AI."""
    active = tasks.get_active_tasks(current_user.id)
    existing = next((t for t in active if t['name'] == "AI Classification"), None)
    if existing:
        return {"task_id": existing['id'], "message": "AI classification already in progress"}

    task_id = tasks.create_task("AI Classification", current_user.id)
    background_tasks.add_task(_run_ai_classification_task, task_id, current_user.id)
    return {"task_id": task_id}


@router.post("/sync-history")
def sync_history(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a background task to sync play history from connected platforms."""
    task_id = tasks.create_task("History Sync", current_user.id)
    background_tasks.add_task(_sync_history_task, task_id, current_user.id)
    return {"task_id": task_id, "message": "History sync started in background"}


def _sync_history_task(task_id: str, user_id: int):
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        tasks.update_task(task_id, total=50, message="Syncing listening history...")
        added_history_count = 0
        processed_count = 0

        # Pre-load existing tracks for memory matching
        existing_tracks = {
            t.external_id: t for t in db.query(schema.Track).filter(schema.Track.owner_id == user_id).all()
            if t.external_id
        }

        def get_or_create_track_memory(title, artist, ext_id=None, source=None):
            t = existing_tracks.get(ext_id)
            if not t:
                # Fallback to title/artist check (less precise but good for history)
                t = next((et for et in existing_tracks.values() if et.title == title and et.artist == artist), None)
            
            if not t:
                t = schema.Track(title=title, artist=artist, external_id=ext_id, source=source or "history", owner_id=user.id)
                db.add(t)
                db.flush() # Get ID
                existing_tracks[ext_id] = t
            return t

        if user.spotify_access_token:
            spotify_service = SpotifyService()
            try:
                spotify_client = spotify_service.get_valid_client(user, db)
                history = spotify_service.get_recently_played_history(spotify_client, limit=50)
                if history and "items" in history:
                    for item in history["items"]:
                        track_data = item.get("track", {})
                        played_at_str = item.get("played_at")
                        if not track_data or not played_at_str: continue
                        try:
                            played_at = datetime.fromisoformat(played_at_str.replace('Z', '+00:00')).replace(tzinfo=None)
                        except: played_at = datetime.utcnow()
                        ext_id = track_data.get("id")
                        uri = track_data.get("uri")
                        title = track_data.get("name")
                        artists = ", ".join([a.get("name") for a in track_data.get("artists", [])])
                        
                        t = get_or_create_track_memory(title, artists, ext_id, "spotify")
                        
                        if uri and not t.spotify_uri: t.spotify_uri = uri
                        
                        existing_hist = db.query(schema.PlayHistory).filter(schema.PlayHistory.owner_id == user.id, schema.PlayHistory.track_id == t.id, schema.PlayHistory.played_at == played_at).first()
                        if not existing_hist:
                            db.add(schema.PlayHistory(owner_id=user.id, track_id=t.id, played_at=played_at, platform="spotify"))
                            added_history_count += 1
                        processed_count += 1
                        tasks.update_task(task_id, progress=processed_count, message=f"Synced Spotify ({processed_count}/50)...")
            except Exception as e: print(f"Spotify history error: {e}")
        db.commit()
        tasks.update_task(task_id, status="completed", message=f"Synced {added_history_count} records.", progress=50)
    except Exception as e:
        db.rollback(); tasks.update_task(task_id, status="failed", error=str(e))
    finally: db.close()

def _sync_spotify_library_task(task_id: str, user_id: int):
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        spotify_service = SpotifyService()
        client = spotify_service.get_valid_client(user, db)
        
        tasks.update_task(task_id, status="running", message="Connecting to Spotify...")
        
        # Test the connection and get total count
        try:
            first_page = client.current_user_saved_tracks(limit=1)
        except Exception as e:
            tasks.update_task(task_id, status="failed", error=f"Spotify API Error: {str(e)}")
            return

        if not first_page or first_page.get("total") == 0:
            tasks.update_task(task_id, status="completed", message="Your Spotify 'Liked Songs' library is empty.")
            return

        total_tracks = first_page.get("total", 0)
        tasks.update_task(task_id, total=total_tracks, message=f"Syncing {total_tracks} liked songs...")

        import re
        def norm(s):
            return re.sub(r'[^a-z0-9]', '', str(s).lower()) if s else ""

        all_existing_tracks = db.query(schema.Track).filter(schema.Track.owner_id == user.id).all()
        existing_tracks_by_ext = {t.external_id: t for t in all_existing_tracks if getattr(t, 'external_id', None)}
        existing_tracks_by_uri = {t.spotify_uri: t for t in all_existing_tracks if getattr(t, 'spotify_uri', None)}
        
        existing_tracks_by_name = {}
        for t in all_existing_tracks:
            nt, na = norm(t.title), norm(t.artist)
            if nt: existing_tracks_by_name[(nt, na)] = t

        processed_count = 0
        added_count = 0
        limit = 50
        
        for offset in range(0, total_tracks, limit):
            try:
                page = client.current_user_saved_tracks(limit=limit, offset=offset)
            except Exception as e:
                print(f"Error fetching page at offset {offset}: {e}")
                break

            if not page or not page.get("items"):
                break

            current_batch = []
            for item in page.get("items", []):
                try:
                    track_data = item.get("track", {})
                    if not track_data: continue
                    
                    title = track_data.get("name")
                    artists = ", ".join([a.get("name") for a in track_data.get("artists", [])])
                    ext_id = track_data.get("id")
                    uri = track_data.get("uri")
                    
                    nt, na = norm(title), norm(artists)
                    
                    # 1. Match by External ID or URI
                    t = existing_tracks_by_ext.get(ext_id) or existing_tracks_by_uri.get(uri)
                    
                    # 2. Match by Name/Artist (Cross-platform)
                    if not t and nt and (nt, na) in existing_tracks_by_name:
                        t = existing_tracks_by_name[(nt, na)]

                    if not t:
                        # Create new track
                        album_data = track_data.get("album", {})
                        t = schema.Track(
                            title=title, 
                            artist=artists, 
                            album=album_data.get("name"), 
                            duration_ms=track_data.get("duration_ms"), 
                            thumbnail_url=album_data.get("images", [{}])[0].get("url") if album_data.get("images") else None, 
                            spotify_uri=uri, 
                            external_id=ext_id, 
                            source="spotify", 
                            owner_id=user.id, 
                            release_year=album_data.get("release_date", "")[:4]
                        )
                        db.add(t)
                        db.flush()
                        existing_tracks_by_ext[ext_id] = t
                        if nt: existing_tracks_by_name[(nt, na)] = t
                        added_count += 1
                    else:
                        # Update existing track with Spotify metadata if missing
                        if not t.spotify_uri: t.spotify_uri = uri
                        if not t.external_id: t.external_id = ext_id
                    
                    processed_count += 1
                except Exception as e:
                    print(f"Skipping malformed track: {e}")
                    continue
            
            tasks.update_task(task_id, progress=processed_count, message=f"Processed {processed_count}/{total_tracks} tracks...")
            db.commit()

        tasks.update_task(task_id, status="completed", message=f"Successfully synced {added_count} new tracks and updated {processed_count - added_count} existing ones.")
    except Exception as e: 
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(e))
    finally: 
        db.close()

@router.post("/sync-spotify")
def sync_spotify_library(background_tasks: BackgroundTasks, current_user: schema.User = Depends(get_current_user)):
    task_id = tasks.create_task("Spotify Library Sync", current_user.id)
    background_tasks.add_task(_sync_spotify_library_task, task_id, current_user.id)
    return {"task_id": task_id}

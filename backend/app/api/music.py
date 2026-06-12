from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import List

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
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

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

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
                                genre = info.get("genre")
                                mood = info.get("mood")

                                if isinstance(genre, str) and genre:
                                    track.genre = genre
                                    changed = True
                                if isinstance(mood, str) and mood:
                                    track.mood = mood
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


@router.post("/classify-all")
def classify_all_tracks(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Starts a background task to classify all imported tracks."""
    task_id = tasks.create_task("AI Batch Classification")
    background_tasks.add_task(_classify_all_task, task_id, current_user.id)
    return {"task_id": task_id, "message": "Classification started in background"}


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


def _enrich_library_task(task_id: str, user_id: int):
    import asyncio
    asyncio.run(_enrich_library_task_async(task_id, user_id))

async def _enrich_library_task_async(task_id: str, user_id: int):
    import httpx
    import asyncio
    
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        tracks = db.query(schema.Track).filter(schema.Track.owner_id == user_id).all()
        if not tracks:
            tasks.update_task(task_id, status="completed", message="Library is empty.", progress=0, total=0)
            return

        total_tracks = len(tracks)
        tasks.update_task(task_id, total=total_tracks, message="Starting high-speed shadow enrichment...")

        spotify_service = None
        spotify_token = None
        if user.spotify_access_token:
            spotify_service = SpotifyService()
            try:
                # Get valid client just to refresh token if needed, then extract the raw token
                client = spotify_service.get_valid_client(user, db)
                spotify_token = client._auth
            except Exception as exc:
                print(f"Spotify client error: {exc}")

        processed_count = 0
        enriched_count = 0
        chunk_size = 100 # Larger chunks for async processing
        
        # Concurrency limit to prevent hitting API limits instantly
        semaphore = asyncio.Semaphore(50) 
        
        async def process_single_track(client: httpx.AsyncClient, track):
            has_new_data = False
            async with semaphore:
                # 1. Spotify Match
                if spotify_token and not track.spotify_uri:
                    uri = await spotify_service.async_search_and_match_track(client, spotify_token, track)
                    if uri:
                        track.spotify_uri = uri
                        has_new_data = True
                
                # 2. Lyrics
                if not track.lyrics:
                    lyrics = await LyricsService.async_fetch_lyrics(client, track.title, track.artist, track.album, track.duration_ms)
                    if lyrics:
                        track.lyrics = lyrics
                        has_new_data = True
            return has_new_data

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(0, total_tracks, chunk_size):
                chunk = tracks[i : i + chunk_size]
                chunk_touched = False

                # Launch async requests for lyrics and spotify match
                coroutines = [process_single_track(client, t) for t in chunk]
                results = await asyncio.gather(*coroutines, return_exceptions=True)
                
                for r in results:
                    if isinstance(r, bool) and r:
                        chunk_touched = True
                        enriched_count += 1

                # Bulk fetch Spotify DNA for the chunk
                if spotify_token and spotify_service:
                    uris_to_fetch = [t.spotify_uri for t in chunk if t.spotify_uri and not t.bpm]
                    if uris_to_fetch:
                        track_lookup = {t.spotify_uri: t for t in chunk if t.spotify_uri}
                        try:
                            features = await spotify_service.async_get_audio_features(client, spotify_token, uris_to_fetch)
                        except Exception as exc:
                            print(f"Spotify audio feature error: {exc}")
                            features = []

                        for f in features or []:
                            if f and isinstance(f, dict) and "uri" in f:
                                track = track_lookup.get(f["uri"])
                                if track:
                                    track.bpm = f.get("tempo")
                                    track.energy = f.get("energy")
                                    track.danceability = f.get("danceability")
                                    track.valence = f.get("valence")
                                    chunk_touched = True

                processed_count += len(chunk)
                tasks.update_task(
                    task_id,
                    progress=processed_count,
                    message=f"Enriching {processed_count}/{total_tracks} tracks via shadow sync...",
                )
                db.commit()

        result = {"message": f"Successfully enriched tracks with {enriched_count} updated items."}
        tasks.update_task(
            task_id,
            status="completed",
            message="Enrichment complete!",
            progress=total_tracks,
            result=result,
        )

    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()


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

        def get_or_create_track(title, artist, ext_id=None, source=None):
            t = None
            if ext_id:
                t = (
                    db.query(schema.Track)
                    .filter(schema.Track.owner_id == user.id, schema.Track.external_id == ext_id)
                    .first()
                )
            if not t:
                t = (
                    db.query(schema.Track)
                    .filter(schema.Track.owner_id == user.id, schema.Track.title == title, schema.Track.artist == artist)
                    .first()
                )
            if not t:
                t = schema.Track(title=title, artist=artist, external_id=ext_id, source=source or "history", owner_id=user.id)
                db.add(t)
                db.flush()
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
                        if not track_data or not played_at_str:
                            continue

                        try:
                            played_at = datetime.fromisoformat(played_at_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        except Exception:
                            played_at = datetime.utcnow()

                        ext_id = track_data.get("id")
                        uri = track_data.get("uri")
                        title = track_data.get("name")
                        artists = ", ".join([a.get("name") for a in track_data.get("artists", [])])

                        t = get_or_create_track(title, artists, ext_id, "spotify")
                        if uri and not t.spotify_uri:
                            t.spotify_uri = uri

                        existing_hist = (
                            db.query(schema.PlayHistory)
                            .filter(
                                schema.PlayHistory.owner_id == user.id,
                                schema.PlayHistory.track_id == t.id,
                                schema.PlayHistory.played_at == played_at,
                            )
                            .first()
                        )

                        if not existing_hist:
                            db.add(
                                schema.PlayHistory(
                                    owner_id=user.id,
                                    track_id=t.id,
                                    played_at=played_at,
                                    platform="spotify",
                                )
                            )
                            added_history_count += 1

                        processed_count += 1
                        tasks.update_task(
                            task_id,
                            progress=processed_count,
                            message=f"Synced Spotify ({processed_count}/50)...",
                        )
            except Exception as exc:
                print(f"Spotify history error: {exc}")

        db.commit()
        result = {"message": f"Successfully synced {added_history_count} new play history records."}
        tasks.update_task(task_id, status="completed", message="History sync complete!", progress=50, result=result)

    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()


# --- In-Memory Global Caches for Backend Worker ---
# In a true multi-worker production environment, use Redis for this.
# This prevents querying APIs for the exact same Title/Artist across different users or playlist imports.
GLOBAL_URI_CACHE = {}
GLOBAL_LYRICS_CACHE = {}

def _enrich_library_task(task_id: str, user_id: int, include_lyrics: bool = False):
    import asyncio
    asyncio.run(_enrich_library_task_async(task_id, user_id, include_lyrics))

async def _enrich_library_task_async(task_id: str, user_id: int, include_lyrics: bool):
    import httpx
    import asyncio
    
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        # BUDGET & PRIORITIZATION:
        # Instead of doing 1,500 at once, we set a strict limit of 200 tracks per job.
        # We prioritize cheap wins: Tracks missing Spotify DNA (BPM/Energy).
        # We intentionally use `is_(None)` as it translates correctly in SQLAlchemy.
        budget_limit = 200
        
        filter_condition = (schema.Track.bpm.is_(None)) | (schema.Track.spotify_uri.is_(None))
        if include_lyrics:
             filter_condition = filter_condition | (schema.Track.lyrics.is_(None))

        tracks = (
            db.query(schema.Track)
            .filter(schema.Track.owner_id == user_id, filter_condition)
            .limit(budget_limit)
            .all()
        )

        if not tracks:
            tasks.update_task(task_id, status="completed", message="All tracks are already enriched!", progress=0, total=0)
            return

        total_tracks = len(tracks)
        tasks.update_task(task_id, total=total_tracks, message=f"Starting backend job for {total_tracks} tracks...")

        spotify_service = None
        spotify_token = None
        if user.spotify_access_token:
            spotify_service = SpotifyService()
            try:
                # Refresh token if needed
                client = spotify_service.get_valid_client(user, db)
                spotify_token = client._auth
            except Exception as exc:
                print(f"Spotify client error: {exc}")

        processed_count = 0
        enriched_count = 0
        chunk_size = 50 # Process in manageable batches of 50 to avoid any timeouts
        
        # Concurrency limit to prevent overwhelming APIs
        semaphore = asyncio.Semaphore(15) 

        async def process_single_track(client: httpx.AsyncClient, track):
            has_new_data = False
            cache_key = f"{track.title.lower()}_{track.artist.lower()}"
            
            async with semaphore:
                # 1. Spotify Match (Check Cache First)
                if spotify_token and not track.spotify_uri:
                    if cache_key in GLOBAL_URI_CACHE:
                        if GLOBAL_URI_CACHE[cache_key]: # None means we already searched and failed
                            track.spotify_uri = GLOBAL_URI_CACHE[cache_key]
                            has_new_data = True
                    else:
                        uri = await spotify_service.async_search_and_match_track(client, spotify_token, track)
                        GLOBAL_URI_CACHE[cache_key] = uri # Cache result (even if None, so we don't retry)
                        if uri:
                            track.spotify_uri = uri
                            has_new_data = True
                
                # 2. Lyrics (Optional, Check Cache First)
                if include_lyrics and not track.lyrics:
                    if cache_key in GLOBAL_LYRICS_CACHE:
                        if GLOBAL_LYRICS_CACHE[cache_key]:
                            track.lyrics = GLOBAL_LYRICS_CACHE[cache_key]
                            has_new_data = True
                    else:
                        lyrics = await LyricsService.async_fetch_lyrics(client, track.title, track.artist, track.album, track.duration_ms)
                        GLOBAL_LYRICS_CACHE[cache_key] = lyrics
                        if lyrics:
                            track.lyrics = lyrics
                            has_new_data = True
            return has_new_data

        async with httpx.AsyncClient(timeout=20.0) as client:
            for i in range(0, total_tracks, chunk_size):
                chunk = tracks[i : i + chunk_size]
                chunk_touched = False

                # Launch async requests for lyrics and spotify match
                coroutines = [process_single_track(client, t) for t in chunk]
                results = await asyncio.gather(*coroutines, return_exceptions=True)
                
                for r in results:
                    if isinstance(r, bool) and r:
                        chunk_touched = True
                        enriched_count += 1

                # Bulk fetch Spotify DNA for the chunk
                if spotify_token and spotify_service:
                    uris_to_fetch = [t.spotify_uri for t in chunk if t.spotify_uri and not t.bpm]
                    if uris_to_fetch:
                        track_lookup = {t.spotify_uri: t for t in chunk if t.spotify_uri}
                        try:
                            features = await spotify_service.async_get_audio_features(client, spotify_token, uris_to_fetch)
                        except Exception as exc:
                            print(f"Spotify audio feature error: {exc}")
                            features = []

                        for f in features or []:
                            if f and isinstance(f, dict) and "uri" in f:
                                track = track_lookup.get(f["uri"])
                                if track:
                                    track.bpm = f.get("tempo")
                                    track.energy = f.get("energy")
                                    track.danceability = f.get("danceability")
                                    track.valence = f.get("valence")
                                    chunk_touched = True

                processed_count += len(chunk)
                tasks.update_task(
                    task_id,
                    progress=processed_count,
                    message=f"Processing chunk ({processed_count}/{total_tracks})...",
                )
                db.commit()

        result = {"message": f"Successfully enriched {enriched_count} tracks in this run."}
        tasks.update_task(
            task_id,
            status="completed",
            message="Batch Enrichment complete!",
            progress=total_tracks,
            result=result,
        )

    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()

class EnrichRequest(BaseModel):
    include_lyrics: bool = False

@router.post("/enrich-all")
def enrich_all_tracks(
    request: EnrichRequest,
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a robust background worker task to enrich tracks. Has built-in budgets and caches."""
    task_id = tasks.create_task("Data Enrichment Job")
    background_tasks.add_task(_enrich_library_task, task_id, current_user.id, request.include_lyrics)
    return {"task_id": task_id, "message": "Enrichment worker queued"}


@router.post("/sync-history")
def sync_history(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a background task to sync play history from connected platforms."""
    task_id = tasks.create_task("History Sync")
    background_tasks.add_task(_sync_history_task, task_id, current_user.id)
    return {"task_id": task_id, "message": "History sync started in background"}


def _sync_spotify_library_task(task_id: str, user_id: int):
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user or not user.spotify_access_token:
            tasks.update_task(task_id, status="failed", error="Spotify not connected")
            return

        spotify_service = SpotifyService()
        client = spotify_service.get_valid_client(user, db)

        tasks.update_task(task_id, status="running", message="Fetching Spotify library...")

        first_page = spotify_service.get_library_tracks(client, limit=1)
        if not first_page:
            tasks.update_task(task_id, status="completed", message="Library is empty.")
            return

        total_tracks = first_page.get("total", 0)
        tasks.update_task(task_id, total=total_tracks, message=f"Syncing {total_tracks} tracks...")

        processed_count = 0
        added_count = 0

        limit = 50
        for offset in range(0, total_tracks, limit):
            page = spotify_service.get_library_tracks(client, limit=limit, offset=offset)
            if not page:
                break

            items = page.get("items", [])
            for item in items:
                track_data = item.get("track", {})
                if not track_data:
                    continue

                title = track_data.get("name")
                artists = ", ".join([a.get("name") for a in track_data.get("artists", [])])
                album_data = track_data.get("album", {})
                album_name = album_data.get("name")
                duration_ms = track_data.get("duration_ms")
                ext_id = track_data.get("id")
                uri = track_data.get("uri")

                thumbnails = album_data.get("images", [])
                thumb_url = thumbnails[0].get("url") if thumbnails else None

                t = (
                    db.query(schema.Track)
                    .filter(schema.Track.owner_id == user.id, schema.Track.external_id == ext_id)
                    .first()
                )

                if not t:
                    t = schema.Track(
                        title=title,
                        artist=artists,
                        album=album_name,
                        duration_ms=duration_ms,
                        thumbnail_url=thumb_url,
                        spotify_uri=uri,
                        external_id=ext_id,
                        source="spotify",
                        owner_id=user.id,
                        release_year=album_data.get("release_date", "")[:4] if album_data.get("release_date") else None,
                        popularity=track_data.get("popularity"),
                    )
                    t.genre = AnalysisEngine.classify_genre(t)
                    t.mood = AnalysisEngine.classify_mood(t)
                    db.add(t)
                    added_count += 1
                else:
                    if not t.spotify_uri:
                        t.spotify_uri = uri
                    if not t.thumbnail_url:
                        t.thumbnail_url = thumb_url

                processed_count += 1
                if processed_count % 10 == 0 or processed_count == total_tracks:
                    tasks.update_task(
                        task_id,
                        progress=processed_count,
                        message=f"Syncing Spotify ({processed_count}/{total_tracks})...",
                    )

            db.commit()

        result = {"message": f"Successfully synced {added_count} new tracks from Spotify."}
        tasks.update_task(
            task_id,
            status="completed",
            message="Spotify sync complete!",
            progress=total_tracks,
            result=result,
        )

    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()


@router.post("/sync-spotify")
def sync_spotify_library(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a background task to sync the entire Spotify Liked Songs library."""
    task_id = tasks.create_task("Spotify Library Sync")
    background_tasks.add_task(_sync_spotify_library_task, task_id, current_user.id)
    return {"task_id": task_id, "message": "Spotify sync started in background"}
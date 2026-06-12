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

def enrich_tracks_chunk(db: Session, tracks: List[schema.Track], user_id: int, include_lyrics: bool = False):
    """
    Core enrichment logic that matches tracks across platforms, 
    fetches DNA (BPM/Energy), and retrieves lyrics.
    """
    import concurrent.futures
    from app.api.integrations import get_ytmusic_browser_auth_path
    from app.services.ytmusic import YTMusicService
    
    # 1. Initialize Services
    spotify_service = SpotifyService()
    spotify_client = None
    user = db.query(schema.User).filter(schema.User.id == user_id).first()
    
    if user and user.spotify_access_token:
        try:
            spotify_client = spotify_service.get_valid_client(user, db)
        except Exception: pass
            
    yt_auth_path = get_ytmusic_browser_auth_path()
    if not os.path.exists(yt_auth_path):
        yt_auth_path = None
    yt_service = YTMusicService(yt_auth_path)

    def process_track_thread(t_data):
        res = {"spotify_uri": None, "matched_youtube_id": None, "lyrics": None}
        try:
            # 1. Spotify Match
            if spotify_client and not t_data.get("spotify_uri"):
                uri = spotify_service.search_and_match_track(spotify_client, type('obj', (object,), t_data))
                if uri: res["spotify_uri"] = uri
            
            # 2. YouTube Match
            if not t_data.get("matched_youtube_id") and t_data.get("source") == "spotify":
                yt_id = yt_service.search_and_match_track(t_data['title'], t_data['artist'], t_data.get('duration_ms'))
                if yt_id: res["matched_youtube_id"] = yt_id

            # 3. Lyrics
            if include_lyrics and not t_data.get("lyrics"):
                lyrics = LyricsService.fetch_lyrics(t_data['title'], t_data['artist'], t_data.get('album'), t_data.get('duration_ms'))
                if lyrics: res["lyrics"] = lyrics
        except Exception: pass
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
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
            idx = futures[future]
            result = future.result()
            t = tracks[idx]
            if result.get("spotify_uri"): t.spotify_uri = result["spotify_uri"]
            if result.get("matched_youtube_id"): t.matched_youtube_id = result["matched_youtube_id"]
            if result.get("lyrics"): t.lyrics = result["lyrics"]
            t.last_enriched_at = datetime.utcnow()
        
        # 2. Bulk DNA
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

def _enrich_library_task(task_id: str, user_id: int, include_lyrics: bool = False):
    from datetime import datetime
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        budget_limit = 200
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        
        tracks = (
            db.query(schema.Track)
            .filter(schema.Track.owner_id == user_id)
            .filter(
                (schema.Track.last_enriched_at.is_(None)) | (schema.Track.last_enriched_at < seven_days_ago)
            )
            .limit(budget_limit)
            .all()
        )

        if not tracks:
            tasks.update_task(task_id, status="completed", message="Library already up to date!", progress=0, total=0)
            return

        total_tracks = len(tracks)
        tasks.update_task(task_id, total=total_tracks, message="Building Bridge...")

        # Process in batches of 10 for progress updates
        processed = 0
        chunk_size = 10
        for i in range(0, total_tracks, chunk_size):
            chunk = tracks[i : i + chunk_size]
            enrich_tracks_chunk(db, chunk, user_id, include_lyrics=include_lyrics)
            processed += len(chunk)
            tasks.update_task(task_id, progress=processed)

        tasks.update_task(task_id, status="completed", message="Bridge building complete!", progress=total_tracks)

    except Exception as exc:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(exc))
    finally:
        db.close()

class EnrichAllRequest(BaseModel):
    include_lyrics: bool = False

@router.post("/enrich-all")
def enrich_all_tracks(
    request: EnrichAllRequest,
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a robust background worker task to enrich tracks. Has built-in budgets and caches."""
    task_id = tasks.create_task("Data Enrichment Job")
    background_tasks.add_task(_enrich_library_task, task_id, current_user.id, request.include_lyrics)
    return {"task_id": task_id, "message": "Enrichment worker queued"}


@router.post("/classify-all")
def classify_all_tracks(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a dedicated background task to ONLY classify tracks using AI."""
    task_id = tasks.create_task("AI Classification Job")
    background_tasks.add_task(_classify_all_task, task_id, current_user.id)
    return {"task_id": task_id, "message": "AI classification started"}


@router.post("/sync-history")
def sync_history(
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
):
    """Starts a background task to sync play history from connected platforms."""
    task_id = tasks.create_task("History Sync")
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

        def get_or_create_track(title, artist, ext_id=None, source=None):
            t = None
            if ext_id:
                t = db.query(schema.Track).filter(schema.Track.owner_id == user.id, schema.Track.external_id == ext_id).first()
            if not t:
                t = db.query(schema.Track).filter(schema.Track.owner_id == user.id, schema.Track.title == title, schema.Track.artist == artist).first()
            if not t:
                t = schema.Track(title=title, artist=artist, external_id=ext_id, source=source or "history", owner_id=user.id)
                db.add(t); db.flush()
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
                        t = get_or_create_track(title, artists, ext_id, "spotify")
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
        tasks.update_task(task_id, status="running", message="Scanning Liked Songs...")
        first_page = spotify_service.get_library_tracks(client, limit=1)
        if not first_page: tasks.update_task(task_id, status="completed", message="Library empty."); return
        total_tracks = first_page.get("total", 0)
        tasks.update_task(task_id, total=total_tracks, message=f"Syncing {total_tracks} tracks...")
        processed_count = 0; added_count = 0; limit = 50
        for offset in range(0, total_tracks, limit):
            page = spotify_service.get_library_tracks(client, limit=limit, offset=offset)
            if not page: break
            current_batch = []
            for item in page.get("items", []):
                track_data = item.get("track", {})
                if not track_data: continue
                title = track_data.get("name")
                artists = ", ".join([a.get("name") for a in track_data.get("artists", [])])
                ext_id = track_data.get("id")
                t = db.query(schema.Track).filter(schema.Track.owner_id == user.id, schema.Track.external_id == ext_id).first()
                if not t:
                    t = schema.Track(title=title, artist=artists, album=track_data.get("album", {}).get("name"), duration_ms=track_data.get("duration_ms"), thumbnail_url=track_data.get("album", {}).get("images", [{}])[0].get("url"), spotify_uri=track_data.get("uri"), external_id=ext_id, source="spotify", owner_id=user.id, release_year=track_data.get("album", {}).get("release_date", "")[:4])
                    db.add(t); added_count += 1
                current_batch.append(t)
                processed_count += 1
            
            # Deep Enrichment during import
            if current_batch:
                enrich_tracks_chunk(db, current_batch, user_id, include_lyrics=True)
                
            if processed_count % 10 == 0: tasks.update_task(task_id, progress=processed_count)
            db.commit()
        tasks.update_task(task_id, status="completed", message=f"Synced {added_count} new tracks.")
    except Exception as e: db.rollback(); tasks.update_task(task_id, status="failed", error=str(e))
    finally: db.close()

@router.post("/sync-spotify")
def sync_spotify_library(background_tasks: BackgroundTasks, current_user: schema.User = Depends(get_current_user)):
    task_id = tasks.create_task("Spotify Library Sync")
    background_tasks.add_task(_sync_spotify_library_task, task_id, current_user.id)
    return {"task_id": task_id}

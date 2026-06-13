from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.models import schema
from app.api.deps import get_current_user
from app.services.analysis import AnalysisEngine
from app.core import tasks
from app.api.music import enrich_tracks_chunk
from ytmusicapi import YTMusic
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from requests import Response

router = APIRouter()


def duration_to_ms(duration: str | None) -> int | None:
    if not duration:
        return None

    match = re.fullmatch(
        r"P(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        duration,
    )
    if not match:
        return None

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def refresh_youtube_access_token(current_user: schema.User, db: Session) -> str:
    if not current_user.yt_refresh_token:
        raise HTTPException(status_code=400, detail="YouTube refresh token is missing. Reconnect YouTube Music.")

    client_id = os.getenv("YTMUSIC_OAUTH_CLIENT_ID")
    client_secret = os.getenv("YTMUSIC_OAUTH_CLIENT_SECRET")
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": current_user.yt_refresh_token,
        "grant_type": "refresh_token",
    }

    response = requests.post(token_url, data=payload, timeout=20)
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to refresh YouTube access token. Reconnect YouTube Music.")

    tokens = response.json()
    current_user.yt_access_token = tokens.get("access_token")
    expires_in = int(tokens.get("expires_in", 3600))
    current_user.yt_token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    db.commit()
    db.refresh(current_user)
    return current_user.yt_access_token


def get_valid_youtube_access_token(current_user: schema.User, db: Session) -> str:
    if not current_user.yt_access_token:
        raise HTTPException(status_code=400, detail="YouTube Music is not connected.")

    expires_at = current_user.yt_token_expiry
    if expires_at is None:
        return current_user.yt_access_token

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= datetime.now(timezone.utc) + timedelta(minutes=1):
        return refresh_youtube_access_token(current_user, db)

    return current_user.yt_access_token


def fetch_liked_videos_response(access_token: str, page_token: str | None = None) -> Response:
    params = {
        "part": "snippet,contentDetails",
        "myRating": "like",
        "maxResults": 50,
    }
    if page_token:
        params["pageToken"] = page_token

    return requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )


def fetch_user_playlists_response(access_token: str, page_token: str | None = None) -> Response:
    params = {
        "part": "snippet,contentDetails",
        "mine": "true",
        "maxResults": 50,
    }
    if page_token:
        params["pageToken"] = page_token

    return requests.get(
        "https://www.googleapis.com/youtube/v3/playlists",
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )


def fetch_playlist_items_response(access_token: str, playlist_id: str, page_token: str | None = None) -> Response:
    params = {
        "part": "snippet,contentDetails",
        "playlistId": playlist_id,
        "maxResults": 50,
    }
    if page_token:
        params["pageToken"] = page_token

    return requests.get(
        "https://www.googleapis.com/youtube/v3/playlistItems",
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )


def fetch_videos_response(access_token: str, video_ids: list[str]) -> Response:
    return requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "part": "snippet,contentDetails",
            "id": ",".join(video_ids),
            "maxResults": 50,
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )


def parse_youtube_api_error(response: Response) -> str:
    try:
        return response.json().get("error", {}).get("message", response.text)
    except Exception:
        return response.text


def get_ytmusic_oauth_client(current_user: schema.User) -> YTMusic:
    if not current_user.yt_access_token:
        raise HTTPException(status_code=400, detail="YouTube Music is not connected.")
    
    client_id = os.getenv("YTMUSIC_OAUTH_CLIENT_ID")
    client_secret = os.getenv("YTMUSIC_OAUTH_CLIENT_SECRET")
    
    expires_at = int(current_user.yt_token_expiry.timestamp()) if current_user.yt_token_expiry else int(time.time() + 3600)
    
    auth_dict = {
        "access_token": current_user.yt_access_token,
        "refresh_token": current_user.yt_refresh_token,
        "expires_at": expires_at,
        "expires_in": max(0, expires_at - int(time.time())),
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://www.googleapis.com/auth/youtube",
        "token_type": "Bearer"
    }
    
    from ytmusicapi.auth.oauth import OAuthCredentials
    oauth_creds = OAuthCredentials(client_id=client_id, client_secret=client_secret)
    return YTMusic(auth=auth_dict, oauth_credentials=oauth_creds)


def serialize_ytmusic_track(track: dict) -> dict:
    artists = ", ".join(artist.get("name", "") for artist in track.get("artists", []) if artist.get("name"))
    album = track.get("album", {})
    thumbnails = track.get("thumbnails", [])
    thumbnail_url = thumbnails[-1].get("url") if thumbnails else None
    
    return {
        "videoId": track.get("videoId"),
        "title": track.get("title", "Unknown Title"),
        "artist": artists or "Unknown Artist",
        "album": album.get("name") if isinstance(album, dict) else None,
        "duration_ms": (track.get("duration_seconds") or 0) * 1000 or None,
        "thumbnail_url": thumbnail_url,
    }


def collect_liked_videos(
    current_user: schema.User,
    db: Session,
    *,
    music_only: bool,
    task_id: str = None,
) -> list[dict]:
    items = []
    next_page_token = None
    fetched_count = 0

    while True:
        response = request_with_refresh(
            current_user,
            db,
            lambda token: fetch_liked_videos_response(token, next_page_token),
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch YouTube likes: {parse_youtube_api_error(response)}",
            )

        payload = response.json()
        total_available = payload.get("pageInfo", {}).get("totalResults", 0)
        
        for item in payload.get("items", []):
            fetched_count += 1
            snippet = item.get("snippet", {})
            
            if music_only:
                cat_id = snippet.get("categoryId")
                is_music = (cat_id == "10") # 10 is the official Music category
                
                # If not strictly categorized as music, check titles and channels for strong signals
                if not is_music:
                    title = snippet.get("title", "").lower()
                    channel = snippet.get("channelTitle", "").lower()
                    
                    music_title_keywords = [
                        "official video", "music video", "official audio", 
                        "lyric", "live performance", "feat.", "ft.", "official visualizer"
                    ]
                    music_channel_keywords = ["vevo", " - topic"]
                    
                    if any(k in title for k in music_title_keywords) or \
                       any(k in channel for k in music_channel_keywords):
                        is_music = True
                
                if not is_music:
                    continue

            items.append(item)

        if task_id:
            tasks.update_task(task_id, progress=0, total=total_available, message=f"Fetched {fetched_count} items from YouTube...")

        next_page_token = payload.get("nextPageToken")
        if not next_page_token:
            break

    return items


def request_with_refresh(
    current_user: schema.User,
    db: Session,
    request_factory,
) -> Response:
    access_token = get_valid_youtube_access_token(current_user, db)
    response = request_factory(access_token)
    if response.status_code == 401 and current_user.yt_refresh_token:
        access_token = refresh_youtube_access_token(current_user, db)
        response = request_factory(access_token)
    return response


def upsert_track_for_user(
    current_user: schema.User,
    db: Session,
    *,
    title: str,
    artist: str | None,
    album: str | None,
    duration_ms: int | None,
    external_id: str,
) -> tuple[schema.Track, bool]:
    existing = db.query(schema.Track).filter(
        schema.Track.owner_id == current_user.id,
        schema.Track.external_id == external_id
    ).first()

    if existing:
        if not existing.album and album:
            existing.album = album
        if not existing.duration_ms and duration_ms:
            existing.duration_ms = duration_ms
        return existing, False

    new_track = schema.Track(
        title=title,
        artist=artist or "Unknown Artist",
        album=album,
        duration_ms=duration_ms,
        external_id=external_id,
        source="youtube",
        owner_id=current_user.id,
    )
    new_track.genre = AnalysisEngine.classify_genre(new_track)
    new_track.mood = AnalysisEngine.classify_mood(new_track)
    db.add(new_track)
    db.flush()
    return new_track, True


def upsert_playlist_for_user(
    current_user: schema.User,
    db: Session,
    *,
    playlist_id: str,
    playlist_name: str,
) -> schema.Playlist:
    playlist = db.query(schema.Playlist).filter(
        schema.Playlist.owner_id == current_user.id,
        schema.Playlist.external_id == playlist_id,
    ).first()

    if playlist:
        if playlist.name != playlist_name:
            playlist.name = playlist_name
        return playlist

    playlist = schema.Playlist(
        name=playlist_name,
        source="youtube",
        external_id=playlist_id,
        owner_id=current_user.id,
    )
    db.add(playlist)
    db.flush()
    return playlist


@router.get("/youtube/playlists")
def list_youtube_playlists(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        liked_videos = collect_liked_videos(current_user, db, music_only=False)

        playlists_map = {
            "__liked_videos__": {
                "id": "__liked_videos__",
                "title": "Liked Music",
                "description": "Imported from your YouTube liked music videos",
                "track_count": len(liked_videos),
                "source": "youtube",
            },
        }

        next_page_token = None
        while True:
            response = request_with_refresh(
                current_user,
                db,
                lambda token: fetch_user_playlists_response(token, next_page_token),
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to fetch YouTube playlists: {parse_youtube_api_error(response)}",
                )

            payload = response.json()
            for item in payload.get("items", []):
                pid = item.get("id")
                if not pid or pid in playlists_map:
                    continue
                    
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                playlists_map[pid] = {
                    "id": pid,
                    "title": snippet.get("title", "Untitled Playlist"),
                    "description": snippet.get("description", ""),
                    "track_count": content_details.get("itemCount", 0),
                    "source": "youtube",
                }

            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                break

        return {"playlists": list(playlists_map.values())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load YouTube playlists: {str(e)}")


def _import_playlist_task(task_id: str, playlist_id: str, user_id: int):
    from app.services.spotify import SpotifyService
    from app.api.integrations import get_ytmusic_browser_auth_path
    from app.services.ytmusic import YTMusicService

    db = SessionLocal()
    try:
        tasks.update_task(task_id, status="running", message="Loading existing tracks...")
        current_user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not current_user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        # Initialize Services ONCE
        spotify_service = SpotifyService()
        spotify_client = None
        if current_user.spotify_access_token:
            try:
                spotify_client = spotify_service.get_valid_client(current_user, db)
            except Exception: pass
            
        yt_auth_path = get_ytmusic_browser_auth_path()
        if not os.path.exists(yt_auth_path):
            yt_auth_path = None
        yt_service = YTMusicService(yt_auth_path)

        # Pre-load existing data for this user to minimize DB hits
        existing_tracks = {
            t.external_id: t for t in db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
            if t.external_id
        }

        def get_or_create_track(title, artist, album, duration_ms, ext_id, thumbnail_url=None):
            if ext_id in existing_tracks:
                t = existing_tracks[ext_id]
                if not t.album and album:
                    t.album = album
                if not t.duration_ms and duration_ms:
                    t.duration_ms = duration_ms
                if not t.thumbnail_url and thumbnail_url:
                    t.thumbnail_url = thumbnail_url
                return t, False

            t = schema.Track(
                title=title,
                artist=artist or "Unknown Artist",
                album=album,
                duration_ms=duration_ms,
                thumbnail_url=thumbnail_url,
                external_id=ext_id,
                source="youtube",
                owner_id=current_user.id,
            )
            # AI classification is now optional/later
            db.add(t)
            existing_tracks[ext_id] = t
            return t, True

        imported_count = 0
        linked_count = 0
        processed_count = 0
        playlist_title = ""

        # Handle cached '__liked_songs__' from earlier ytmusicapi implementation
        if playlist_id == "__liked_songs__":
            playlist_id = "__liked_videos__"

        if playlist_id == "__liked_videos__":
            tasks.update_task(task_id, message="Fetching Liked Music...")
            playlist_title = "Liked Music"
            items = collect_liked_videos(current_user, db, music_only=True, task_id=task_id)
            local_playlist = upsert_playlist_for_user(current_user, db, playlist_id=playlist_id, playlist_name=playlist_title)
            existing_links = {pt.track_id for pt in db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == local_playlist.id).all()}
            processed_video_ids = set()

            tasks.update_task(task_id, total=len(items), message=f"Starting import of {len(items)} tracks...")
            current_batch = []

            for item in items:
                processed_count += 1
                if processed_count % 100 == 0:
                    tasks.update_task(task_id, progress=processed_count, message=f"Processing {processed_count}/{len(items)}")
                    db.flush()

                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                video_id = item.get("id")
                if not video_id:
                    continue

                if video_id in processed_video_ids:
                    continue
                processed_video_ids.add(video_id)

                thumbnails = snippet.get("thumbnails", {})
                thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default")
                thumb_url = thumb.get("url") if thumb else None

                track, created = get_or_create_track(
                    snippet.get("title", "Unknown Title"), snippet.get("channelTitle"), None,
                    duration_to_ms(content_details.get("duration")), video_id, thumb_url
                )
                if created:
                    imported_count += 1
                
                current_batch.append(track)

                if getattr(track, "id", None) not in existing_links:
                    db.add(schema.PlaylistTrack(playlist_id=local_playlist.id, track=track))
                    if getattr(track, "id", None) is not None:
                        existing_links.add(track.id)
                    linked_count += 1

                if len(current_batch) >= 50:
                    db.flush()
                    enrich_tracks_chunk(db, current_batch, user_id, include_lyrics=True, spotify_client=spotify_client, yt_service=yt_service)
                    current_batch = []
                    db.commit()
            
            if current_batch:
                db.flush()
                enrich_tracks_chunk(db, current_batch, user_id, include_lyrics=True, spotify_client=spotify_client, yt_service=yt_service)
                db.commit()

        else:
            tasks.update_task(task_id, message="Fetching Playlist...")
            playlist_title = None
            next_page_token = None
            local_playlist = None

            # Fetch all video IDs
            all_items = []
            while True:
                response = request_with_refresh(current_user, db, lambda token: fetch_playlist_items_response(token, playlist_id, next_page_token))
                if response.status_code != 200:
                    raise Exception(f"Failed to fetch YouTube playlist items: {parse_youtube_api_error(response)}")
                payload = response.json()
                all_items.extend(payload.get("items", []))
                next_page_token = payload.get("nextPageToken")
                if not next_page_token:
                    break

            tasks.update_task(task_id, total=len(all_items))
            current_batch = []

            video_ids = []
            playlist_item_lookup = {}
            for item in all_items:
                snippet = item.get("snippet", {})
                if playlist_title is None:
                    playlist_title = snippet.get("playlistTitle") or "Imported YouTube Playlist"
                resource = snippet.get("resourceId", {})
                video_id = resource.get("videoId")
                if not video_id:
                    continue
                video_ids.append(video_id)
                playlist_item_lookup[video_id] = item

            local_playlist = upsert_playlist_for_user(current_user, db, playlist_id=playlist_id, playlist_name=playlist_title or "Imported YouTube Playlist")
            existing_links = {pt.track_id for pt in db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == local_playlist.id).all()}
            processed_video_ids = set()

            # Fetch video details in batches of 50
            video_details = {}
            for i in range(0, len(video_ids), 50):
                batch_ids = video_ids[i:i+50]
                videos_response = request_with_refresh(current_user, db, lambda token: fetch_videos_response(token, batch_ids))
                if videos_response.status_code == 200:
                    for video in videos_response.json().get("items", []):
                        video_details[video.get("id")] = video

            for video_id in video_ids:
                if video_id in processed_video_ids:
                    continue
                processed_video_ids.add(video_id)

                processed_count += 1
                if processed_count % 100 == 0:
                    tasks.update_task(task_id, progress=processed_count, message=f"Processing {processed_count}/{len(video_ids)}")
                    db.flush()

                item = playlist_item_lookup[video_id]
                detail = video_details.get(video_id, {})
                snippet = detail.get("snippet") or item.get("snippet", {})
                content_details = detail.get("contentDetails", {})

                thumbnails = snippet.get("thumbnails", {})
                thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default")
                thumb_url = thumb.get("url") if thumb else None

                track, created = get_or_create_track(
                    snippet.get("title", "Unknown Title"), snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle"), None,
                    duration_to_ms(content_details.get("duration")), video_id, thumb_url
                )
                if created:
                    imported_count += 1
                
                current_batch.append(track)

                if getattr(track, "id", None) not in existing_links:
                    db.add(schema.PlaylistTrack(playlist_id=local_playlist.id, track=track))
                    if getattr(track, "id", None) is not None:
                        existing_links.add(track.id)
                    linked_count += 1
                
                if len(current_batch) >= 50:
                    db.flush()
                    enrich_tracks_chunk(db, current_batch, user_id, include_lyrics=True, spotify_client=spotify_client, yt_service=yt_service)
                    current_batch = []
                    db.commit()
            
            if current_batch:
                db.flush()
                enrich_tracks_chunk(db, current_batch, user_id, include_lyrics=True, spotify_client=spotify_client, yt_service=yt_service)
                db.commit()

        db.commit()
        result = {
            "message": f"Imported playlist '{playlist_title or playlist_id}'",
            "playlist_id": playlist_id,
            "playlist_name": playlist_title or "Imported YouTube Playlist",
            "imported_tracks": imported_count,
            "linked_tracks": linked_count,
            "processed_tracks": processed_count,
        }
        tasks.update_task(task_id, status="completed", message="Import complete!", result=result)

    except Exception as e:
        db.rollback()
        tasks.update_task(task_id, status="failed", error=str(e))
    finally:
        db.close()


@router.post("/youtube/import-playlist/{playlist_id}")
def import_youtube_playlist(
    playlist_id: str,
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check for already running task for this specific playlist
    active = tasks.get_active_tasks(current_user.id)
    existing = next((t for t in active if t['name'] == f"Import Playlist {playlist_id}"), None)
    if existing:
        return {"task_id": existing['id'], "message": "Import already in progress"}

    task_id = tasks.create_task(f"Import Playlist {playlist_id}", current_user.id)
    background_tasks.add_task(_import_playlist_task, task_id, playlist_id, current_user.id)
    return {"task_id": task_id, "message": "Import started in background"}
@router.post("/youtube/import")
def import_youtube_library(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Imports liked YouTube videos using the official Google API."""
    try:
        access_token = get_valid_youtube_access_token(current_user, db)
        imported_count = 0
        processed_count = 0
        next_page_token = None

        while True:
            response = fetch_liked_videos_response(access_token, next_page_token)
            if response.status_code == 401 and current_user.yt_refresh_token:
                access_token = refresh_youtube_access_token(current_user, db)
                response = fetch_liked_videos_response(access_token, next_page_token)

            if response.status_code != 200:
                detail = response.json().get("error", {}).get("message", response.text)
                raise HTTPException(status_code=502, detail=f"Failed to fetch YouTube likes: {detail}")

            payload = response.json()
            items = payload.get("items", [])

            for item in items:
                processed_count += 1
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                video_id = item.get("id")

                if snippet.get("categoryId") and snippet.get("categoryId") != "10":
                    continue

                if not video_id or not snippet.get("title"):
                    continue

                existing = db.query(schema.Track).filter(
                    schema.Track.owner_id == current_user.id,
                    schema.Track.external_id == video_id
                ).first()

                if existing:
                    continue

                new_track = schema.Track(
                    title=snippet["title"],
                    artist=snippet.get("channelTitle", "Unknown Artist"),
                    album=None,
                    duration_ms=duration_to_ms(content_details.get("duration")),
                    external_id=video_id,
                    source="youtube",
                    owner_id=current_user.id
                )
                new_track.genre = AnalysisEngine.classify_genre(new_track)
                new_track.mood = AnalysisEngine.classify_mood(new_track)

                db.add(new_track)
                imported_count += 1

            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                break
        
        db.commit()
        return {
            "message": f"Successfully imported {imported_count} tracks",
            "count": imported_count,
            "processed": processed_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import from YouTube: {str(e)}")

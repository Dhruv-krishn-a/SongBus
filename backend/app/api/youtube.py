from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.models import schema
from app.api.deps import get_current_user
from app.services.analysis import AnalysisEngine
from app.core import tasks
from ytmusicapi import YTMusic
import os
import re
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


def get_ytmusic_browser_auth_path() -> str:
    return os.getenv("YTMUSIC_BROWSER_AUTH_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "browser.json"))


def get_ytmusic_client() -> YTMusic:
    auth_path = os.path.abspath(get_ytmusic_browser_auth_path())
    if not os.path.exists(auth_path):
        raise HTTPException(
            status_code=400,
            detail=(
                "YouTube Music browser authentication is not configured. "
                f"Add a browser auth file at {auth_path} or set YTMUSIC_BROWSER_AUTH_PATH."
            ),
        )
    from app.api.integrations import sanitize_browser_auth_file
    sanitize_browser_auth_file(auth_path)
    return YTMusic(auth_path)


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
) -> list[dict]:
    items = []
    next_page_token = None

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
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            if music_only and snippet.get("categoryId") and snippet.get("categoryId") != "10":
                continue
            items.append(item)

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
        ytmusic = get_ytmusic_client()
        liked_songs_playlist = ytmusic.get_playlist("LM", limit=1)
        ytmusic_playlists = ytmusic.get_library_playlists(limit=None)
        liked_videos = collect_liked_videos(current_user, db, music_only=False)

        playlists_map = {
            "__liked_songs__": {
                "id": "__liked_songs__",
                "title": "Liked songs",
                "description": "Imported from your YouTube Music liked songs",
                "track_count": liked_songs_playlist.get("trackCount", 0),
                "source": "ytmusic",
            },
            "__liked_videos__": {
                "id": "__liked_videos__",
                "title": "Liked videos",
                "description": "Imported from your YouTube liked videos",
                "track_count": len(liked_videos),
                "source": "youtube",
            },
        }

        for playlist in ytmusic_playlists:
            pid = playlist.get("playlistId")
            if pid:
                playlists_map[pid] = {
                    "id": pid,
                    "title": playlist.get("title", "Untitled Playlist"),
                    "description": "Imported from your YouTube Music library",
                    "track_count": playlist.get("count", 0),
                    "source": "ytmusic",
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
    db = SessionLocal()
    try:
        tasks.update_task(task_id, status="running", message="Loading existing tracks...")
        current_user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not current_user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        # Pre-load existing data for this user to minimize DB hits
        existing_tracks = {
            t.external_id: t for t in db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
            if t.external_id
        }

        def get_or_create_track(title, artist, album, duration_ms, ext_id, thumbnail_url=None):
            if ext_id in existing_tracks:
                t = existing_tracks[ext_id]
                if not t.album and album: t.album = album
                if not t.duration_ms and duration_ms: t.duration_ms = duration_ms
                if not t.thumbnail_url and thumbnail_url: t.thumbnail_url = thumbnail_url
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
            t.genre = AnalysisEngine.classify_genre(t)
            t.mood = AnalysisEngine.classify_mood(t)
            db.add(t)
            db.flush()
            existing_tracks[ext_id] = t
            return t, True

        imported_count = 0
        linked_count = 0
        processed_count = 0
        playlist_title = ""

        if playlist_id == "__liked_songs__":
            tasks.update_task(task_id, message="Fetching Liked Songs...")
            ytmusic = get_ytmusic_client()
            liked_playlist = ytmusic.get_playlist("LM", limit=None)
            playlist_title = liked_playlist.get("title") or "Liked songs"
            local_playlist = upsert_playlist_for_user(current_user, db, playlist_id, playlist_title)
            existing_links = {pt.track_id for pt in db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == local_playlist.id).all()}

            tracks_to_process = liked_playlist.get("tracks", [])
            tasks.update_task(task_id, total=len(tracks_to_process))

            for item in tracks_to_process:
                processed_count += 1
                tasks.update_task(task_id, progress=processed_count, message=f"Processing {processed_count}/{len(tracks_to_process)}")

                normalized = serialize_ytmusic_track(item)
                video_id = normalized.get("videoId")
                if not video_id: continue

                track, created = get_or_create_track(
                    normalized["title"], normalized["artist"], normalized["album"],
                    normalized["duration_ms"], video_id, normalized.get("thumbnail_url")
                )
                if created: imported_count += 1

                if track.id not in existing_links:
                    db.add(schema.PlaylistTrack(playlist_id=local_playlist.id, track_id=track.id))
                    existing_links.add(track.id)
                    linked_count += 1

        elif playlist_id == "__liked_videos__":
            tasks.update_task(task_id, message="Fetching Liked Videos...")
            playlist_title = "Liked videos"
            items = collect_liked_videos(current_user, db, music_only=False)
            local_playlist = upsert_playlist_for_user(current_user, db, playlist_id, playlist_title)
            existing_links = {pt.track_id for pt in db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == local_playlist.id).all()}

            tasks.update_task(task_id, total=len(items))

            for item in items:
                processed_count += 1
                tasks.update_task(task_id, progress=processed_count, message=f"Processing {processed_count}/{len(items)}")

                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                video_id = item.get("id")
                if not video_id: continue

                thumbnails = snippet.get("thumbnails", {})
                thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default")
                thumb_url = thumb.get("url") if thumb else None

                track, created = get_or_create_track(
                    snippet.get("title", "Unknown Title"), snippet.get("channelTitle"), None,
                    duration_to_ms(content_details.get("duration")), video_id, thumb_url
                )
                if created: imported_count += 1

                if track.id not in existing_links:
                    db.add(schema.PlaylistTrack(playlist_id=local_playlist.id, track_id=track.id))
                    existing_links.add(track.id)
                    linked_count += 1

        else:
            tasks.update_task(task_id, message="Fetching Playlist...")
            ytmusic = get_ytmusic_client()
            ytmusic_playlist_ids = {playlist.get("playlistId") for playlist in ytmusic.get_library_playlists(limit=None)}

            if playlist_id in ytmusic_playlist_ids:
                playlist = ytmusic.get_playlist(playlist_id, limit=None)
                playlist_title = playlist.get("title") or "Imported YouTube Music Playlist"
                local_playlist = upsert_playlist_for_user(current_user, db, playlist_id, playlist_title)
                existing_links = {pt.track_id for pt in db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == local_playlist.id).all()}

                tracks_to_process = playlist.get("tracks", [])
                tasks.update_task(task_id, total=len(tracks_to_process))

                for item in tracks_to_process:
                    processed_count += 1
                    tasks.update_task(task_id, progress=processed_count, message=f"Processing {processed_count}/{len(tracks_to_process)}")

                    normalized = serialize_ytmusic_track(item)
                    video_id = normalized.get("videoId")
                    if not video_id: continue

                    track, created = get_or_create_track(
                        normalized["title"], normalized["artist"], normalized["album"],
                        normalized["duration_ms"], video_id, normalized.get("thumbnail_url")
                    )
                    if created: imported_count += 1

                    if track.id not in existing_links:
                        db.add(schema.PlaylistTrack(playlist_id=local_playlist.id, track_id=track.id))
                        existing_links.add(track.id)
                        linked_count += 1
            else:
                # Fallback API
                playlist_title = None
                next_page_token = None
                local_playlist = None

                # Try to fetch all video IDs first
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

                video_ids = []
                playlist_item_lookup = {}
                for item in all_items:
                    snippet = item.get("snippet", {})
                    if playlist_title is None:
                        playlist_title = snippet.get("playlistTitle") or "Imported YouTube Playlist"
                    resource = snippet.get("resourceId", {})
                    video_id = resource.get("videoId")
                    if not video_id: continue
                    video_ids.append(video_id)
                    playlist_item_lookup[video_id] = item

                local_playlist = upsert_playlist_for_user(current_user, db, playlist_id, playlist_title or "Imported YouTube Playlist")
                existing_links = {pt.track_id for pt in db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == local_playlist.id).all()}

                # Fetch video details in batches of 50
                video_details = {}
                for i in range(0, len(video_ids), 50):
                    batch_ids = video_ids[i:i+50]
                    videos_response = request_with_refresh(current_user, db, lambda token: fetch_videos_response(token, batch_ids))
                    if videos_response.status_code == 200:
                        for video in videos_response.json().get("items", []):
                            video_details[video.get("id")] = video

                for video_id in video_ids:
                    processed_count += 1
                    tasks.update_task(task_id, progress=processed_count, message=f"Processing {processed_count}/{len(video_ids)}")

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
                    if created: imported_count += 1

                    if track.id not in existing_links:
                        db.add(schema.PlaylistTrack(playlist_id=local_playlist.id, track_id=track.id))
                        existing_links.add(track.id)
                        linked_count += 1

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
):
    task_id = tasks.create_task(f"Import Playlist {playlist_id}")
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

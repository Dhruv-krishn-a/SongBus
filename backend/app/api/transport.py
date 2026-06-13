from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.models import schema
from app.api.deps import get_current_user
from app.services.spotify import SpotifyService
from app.services.ytmusic import YTMusicService
from app.core import tasks
from pydantic import BaseModel
from typing import List
import os

router = APIRouter()

@router.get("/audit")
def audit_transport(
    source: str, 
    destination: str, 
    current_user: schema.User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """
    Evaluates the library to see how many tracks from `source` can be exported to `destination`.
    """
    if source not in ["youtube", "spotify"] or destination not in ["youtube", "spotify"]:
        raise HTTPException(status_code=400, detail="Invalid source or destination")

    source_tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id, schema.Track.source == source).all()
    
    ready = []
    missing = []

    for track in source_tracks:
        if destination == "spotify":
            if track.spotify_uri:
                ready.append({"id": track.id, "title": track.title, "artist": track.artist, "thumbnail_url": track.thumbnail_url})
            else:
                missing.append({"id": track.id, "title": track.title, "artist": track.artist, "thumbnail_url": track.thumbnail_url})
        elif destination == "youtube":
            if track.matched_youtube_id:
                ready.append({"id": track.id, "title": track.title, "artist": track.artist, "thumbnail_url": track.thumbnail_url})
            else:
                missing.append({"id": track.id, "title": track.title, "artist": track.artist, "thumbnail_url": track.thumbnail_url})

    return {
        "ready": ready,
        "missing": missing,
        "total_source": len(source_tracks)
    }

class ExportRequest(BaseModel):
    track_ids: List[int]
    destination: str
    playlist_name: str

def _export_job(task_id: str, user_id: int, track_ids: List[int], destination: str, playlist_name: str):
    db = SessionLocal()
    try:
        user = db.query(schema.User).filter(schema.User.id == user_id).first()
        if not user:
            tasks.update_task(task_id, status="failed", error="User not found")
            return

        tracks = db.query(schema.Track).filter(schema.Track.id.in_(track_ids), schema.Track.owner_id == user_id).all()
        if not tracks:
            tasks.update_task(task_id, status="failed", error="No tracks found to export")
            return

        total = len(tracks)
        tasks.update_task(task_id, total=total, message=f"Exporting to {destination}...")

        exported = 0

        if destination == "spotify":
            if not user.spotify_access_token:
                tasks.update_task(task_id, status="failed", error="Spotify not connected")
                return
            
            spotify_service = SpotifyService()
            client = spotify_service.get_valid_client(user, db)
            
            me = client.current_user()
            new_playlist = spotify_service.create_playlist(client, me['id'], playlist_name, "Exported from SongBus")
            
            if not new_playlist:
                tasks.update_task(task_id, status="failed", error="Could not create Spotify playlist")
                return
            
            uris = [t.spotify_uri for t in tracks if t.spotify_uri]
            for i in range(0, len(uris), 100):
                batch = uris[i:i+100]
                client.playlist_add_items(playlist_id=new_playlist['id'], items=batch)
                exported += len(batch)
                tasks.update_task(task_id, progress=exported, message=f"Exported {exported}/{total}...")
                
        elif destination == "youtube":
            from app.api.integrations import get_ytmusic_browser_auth_path
            yt_auth_path = None
            path = get_ytmusic_browser_auth_path()
            if os.path.exists(path):
                yt_auth_path = path
                
            yt_service = YTMusicService(yt_auth_path)
            # Actually, YTMusic API requires creating a playlist and adding videoIds.
            # We don't have the create playlist implemented fully yet, we can stub or implement it here.
            try:
                playlist_id = yt_service.create_playlist(playlist_name, "Exported from SongBus")
                if not playlist_id:
                    tasks.update_task(task_id, status="failed", error="Could not create YouTube playlist")
                    return
                    
                video_ids = [t.matched_youtube_id for t in tracks if t.matched_youtube_id]
                for i in range(0, len(video_ids), 50):
                    batch = video_ids[i:i+50]
                    yt_service.client.add_playlist_items(playlist_id, batch)
                    exported += len(batch)
                    tasks.update_task(task_id, progress=exported, message=f"Exported {exported}/{total}...")
            except Exception as e:
                print(f"YT Export Error: {e}")
                tasks.update_task(task_id, status="failed", error="Failed to export to YouTube. Make sure your browser headers are valid.")
                return

        tasks.update_task(task_id, status="completed", message=f"Successfully exported {exported} tracks to {destination}.", progress=total, result={"exported": exported})

    except Exception as e:
        tasks.update_task(task_id, status="failed", error=str(e))
    finally:
        db.close()


@router.post("/export")
def export_tracks(
    request: ExportRequest,
    background_tasks: BackgroundTasks,
    current_user: schema.User = Depends(get_current_user)
):
    task_id = tasks.create_task("Export Library", current_user.id)
    background_tasks.add_task(_export_job, task_id, current_user.id, request.track_ids, request.destination, request.playlist_name)
    return {"task_id": task_id, "message": "Export job queued"}

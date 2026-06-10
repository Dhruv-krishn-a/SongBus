from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import schema
from app.services.analysis import AnalysisEngine
from app.api.deps import get_current_user
from pydantic import BaseModel
from typing import List

class BatchNormalizeRequest(BaseModel):
    track_ids: List[int]

router = APIRouter()

@router.get("/library")
def get_library(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    artist: str | None = None,
    genre: str | None = None,
    mood: str | None = None,
    search: str | None = None,
    sort_by: str | None = "created_at",
    sort_order: str | None = "desc",
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id)

    if artist:
        query = query.filter(schema.Track.artist.ilike(f"%{artist}%"))
    if genre:
        query = query.filter(schema.Track.genre == genre)
    if mood:
        query = query.filter(schema.Track.mood == mood)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (schema.Track.title.ilike(search_filter)) | 
            (schema.Track.artist.ilike(search_filter)) |
            (schema.Track.album.ilike(search_filter))
        )

    # Dynamic Sorting
    sort_col = getattr(schema.Track, sort_by, schema.Track.created_at)
    if sort_order == "desc":
        query = query.order_by(sort_col.desc(), schema.Track.id.desc())
    else:
        query = query.order_by(sort_col.asc(), schema.Track.id.asc())

    total = query.count()
    tracks = (
        query.offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
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
    track = db.query(schema.Track).filter(
        schema.Track.id == track_id,
        schema.Track.owner_id == current_user.id
    ).first()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Also remove from any playlist links (Cascade usually handles this, but let's be explicit if needed)
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
    track = db.query(schema.Track).filter(
        schema.Track.id == track_id,
        schema.Track.owner_id == current_user.id
    ).first()

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
    tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
    preview = []
    
    for track in tracks:
        normalized = AnalysisEngine.normalize_track_metadata(track.title, track.artist)
        if normalized["title"] != track.title or normalized["artist"] != track.artist:
            preview.append({
                "id": track.id,
                "current_title": track.title,
                "current_artist": track.artist,
                "proposed_title": normalized["title"],
                "proposed_artist": normalized["artist"]
            })
            
    return {"preview": preview}

@router.post("/classify-all")
def classify_all_tracks(
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Uses AI to classify all imported tracks."""
    tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
    if not tracks:
        raise HTTPException(status_code=400, detail="Library is empty.")

    # Process in chunks if library is large (e.g. > 1000 tracks), but gemini-2.5-flash can handle a lot. 
    # For now, process all at once. If it times out, we can chunk later.
    classifications = AnalysisEngine.batch_classify_ai(tracks)
    
    if "error" in classifications:
        raise HTTPException(status_code=500, detail=classifications["error"])

    updated_count = 0
    for track in tracks:
        track_id_str = str(track.id)
        if track_id_str in classifications:
            info = classifications[track_id_str]
            # Only update if the AI returned a string
            if isinstance(info, dict):
                if "genre" in info and isinstance(info["genre"], str):
                    track.genre = info["genre"]
                if "mood" in info and isinstance(info["mood"], str):
                    track.mood = info["mood"]
                updated_count += 1
                
    db.commit()
    return {"message": f"Successfully AI classified {updated_count} tracks."}

@router.post("/normalize/batch")
def batch_normalize(
    request: BatchNormalizeRequest,
    current_user: schema.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracks = db.query(schema.Track).filter(
        schema.Track.id.in_(request.track_ids),
        schema.Track.owner_id == current_user.id
    ).all()
    
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
    # Delete playlist links first
    db.query(schema.PlaylistTrack).filter(
        schema.PlaylistTrack.playlist_id.in_(
            db.query(schema.Playlist.id).filter(schema.Playlist.owner_id == current_user.id)
        )
    ).delete(synchronize_session=False)

    # Delete tracks
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

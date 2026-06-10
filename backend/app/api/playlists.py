from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import schema
from app.api.deps import get_current_user
from app.services.spotify import SpotifyService
from datetime import datetime, timedelta
import requests

router = APIRouter()

@router.post("/generate-playlists")
def generate_smart_playlists(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Groups user's library into Smart Playlists based on detected Genre."""
    tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
    if not tracks:
        raise HTTPException(status_code=400, detail="Your library is empty. Import some music first!")

    genre_groups = {}
    for track in tracks:
        genre = track.genre or "Various"
        if genre not in genre_groups:
            genre_groups[genre] = []
        genre_groups[genre].append(track)
        
    generated_count = 0
    
    for genre, group_tracks in genre_groups.items():
        if len(group_tracks) < 3: 
            continue
            
        playlist_name = f"Smart Mix: {genre}"
        
        # Upsert playlist
        playlist = db.query(schema.Playlist).filter(
            schema.Playlist.owner_id == current_user.id,
            schema.Playlist.name == playlist_name
        ).first()
        
        if not playlist:
            playlist = schema.Playlist(
                name=playlist_name,
                source="smart_generated",
                owner_id=current_user.id
            )
            db.add(playlist)
            db.flush()
            generated_count += 1
        
        # Clear old tracks and add current ones
        db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == playlist.id).delete()
        for track in group_tracks:
            db.add(schema.PlaylistTrack(playlist_id=playlist.id, track_id=track.id))
            
    db.commit()
    return {"message": f"Successfully updated your Smart Mixes. Created {generated_count} new playlists."}

@router.post("/export-spotify/{playlist_id}")
def export_to_spotify(playlist_id: int, current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Exports a Smart Playlist to Spotify with intelligent matching."""
    if not current_user.spotify_access_token:
        raise HTTPException(status_code=400, detail="Spotify is not connected. Visit Settings.")
        
    playlist = db.query(schema.Playlist).filter(
        schema.Playlist.id == playlist_id,
        schema.Playlist.owner_id == current_user.id
    ).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found.")
        
    # Get tracks in this playlist
    tracks = db.query(schema.Track).join(schema.PlaylistTrack).filter(
        schema.PlaylistTrack.playlist_id == playlist_id
    ).all()
    
    if not tracks:
        raise HTTPException(status_code=400, detail="This playlist has no tracks to export.")

    spotify_service = SpotifyService()
    client = spotify_service.get_valid_client(current_user, db)
    
    # 1. Ensure Spotify Playlist exists
    sp_playlist_id = playlist.external_id
    if not sp_playlist_id:
        sp_playlist = spotify_service.create_playlist(
            client=client,
            user_id=current_user.spotify_id,
            name=playlist.name,
            description="Created by SongBus Intelligence"
        )
        if not sp_playlist:
            raise HTTPException(status_code=500, detail="Failed to create Spotify playlist.")
        sp_playlist_id = sp_playlist.get("id")
        playlist.external_id = sp_playlist_id
        db.commit()

    # 2. Match Tracks & Collect URIs
    track_uris = []
    matched_count = 0
    
    for track in tracks:
        uri = spotify_service.search_and_match_track(client, track)
        if uri:
            track_uris.append(uri)
            matched_count += 1
            # Cache the URI for future exports
            if not track.spotify_uri:
                track.spotify_uri = uri

    # 3. Push to Spotify
    if track_uris:
        # Clear existing items first to avoid duplicates on re-export
        client.playlist_replace_items(sp_playlist_id, track_uris[:100])
        if len(track_uris) > 100:
            spotify_service.add_tracks_to_playlist(client, sp_playlist_id, track_uris[100:])
        
    db.commit()
    return {
        "message": "Playlist synced to Spotify!",
        "matched": matched_count,
        "total": len(tracks),
        "playlist_url": f"https://open.spotify.com/playlist/{sp_playlist_id}"
    }

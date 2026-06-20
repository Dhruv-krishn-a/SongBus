from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import schema
from app.api.deps import get_current_user
from app.services.analysis import AnalysisEngine
from app.services.spotify import SpotifyService
from pydantic import BaseModel

router = APIRouter()

class AIGenerateRequest(BaseModel):
    prompt: str

@router.post("/ai-generate")
def ai_generate_playlist(
    request: AIGenerateRequest, 
    current_user: schema.User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """
    Translates user prompt into a SQL query using Gemini to build a Smart Playlist.
    """
    filters = AnalysisEngine.parse_semantic_query(request.prompt)
    if "error" in filters:
        raise HTTPException(status_code=500, detail=filters["error"])
        
    query = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id)
    
    # Apply JSON filters mapped by AI
    if filters.get("bpm_min"):
        query = query.filter(schema.Track.bpm >= filters["bpm_min"])
    if filters.get("bpm_max"):
        query = query.filter(schema.Track.bpm <= filters["bpm_max"])
    if filters.get("energy_min"):
        query = query.filter(schema.Track.energy >= filters["energy_min"])
    if filters.get("energy_max"):
        query = query.filter(schema.Track.energy <= filters["energy_max"])
    if filters.get("danceability_min"):
        query = query.filter(schema.Track.danceability >= filters["danceability_min"])
    if filters.get("valence_min"):
        query = query.filter(schema.Track.valence >= filters["valence_min"])
    if filters.get("valence_max"):
        query = query.filter(schema.Track.valence <= filters["valence_max"])
    if filters.get("genres"):
        query = query.filter(schema.Track.genre.in_(filters["genres"]))
    if filters.get("moods"):
        query = query.filter(schema.Track.mood.in_(filters["moods"]))
        
    tracks = query.limit(50).all()
    
    if not tracks:
        return {"tracks": [], "filters_applied": filters, "message": "No tracks matched this vibe."}
        
    return {
        "tracks": [
            {
                "id": t.id, 
                "title": t.title, 
                "artist": t.artist, 
                "thumbnail_url": t.thumbnail_url,
                "genre": t.genre,
                "mood": t.mood,
                "bpm": t.bpm,
                "energy": t.energy
            } for t in tracks
        ],
        "filters_applied": filters,
        "message": f"Generated a {len(tracks)}-track mix!"
    }

@router.post("/generate-playlists")
def generate_smart_playlists(current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Groups user's library into Smart Playlists based on Gemini AI analysis."""
    tracks = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id).all()
    if not tracks:
        raise HTTPException(status_code=400, detail="Your library is empty. Import some music first!")
        
    if len(tracks) < 3:
        raise HTTPException(status_code=400, detail="You need at least 3 tracks in your library to generate a smart playlist.")

    from app.services.smart_mix import SmartMixEngine
    # Use Gemini to directly generate creative, personalized groupings from the entire library
    ai_result = SmartMixEngine.generate_ai_playlists_direct(tracks)
    if "error" in ai_result:
        raise HTTPException(status_code=500, detail=ai_result["error"])
        
    ai_playlists = ai_result.get("playlists", [])
    if not ai_playlists:
        raise HTTPException(status_code=400, detail="AI couldn't find enough similar tracks to group. Try importing more varied music!")

    # Delete all previous AI-generated playlists to prevent duplicates on re-run
    old_playlists = db.query(schema.Playlist).filter(
        schema.Playlist.owner_id == current_user.id,
        schema.Playlist.source == "ai_generated"
    ).all()
    for old_pl in old_playlists:
        db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == old_pl.id).delete()
        db.delete(old_pl)
    db.flush()

    generated_count = 0
    
    for pl_data in ai_playlists:
        theme_name = pl_data.get("name")
        description = pl_data.get("description", "")
        track_ids = pl_data.get("track_ids", [])
        
        # Only create a mix if we have at least 3 tracks for it
        if len(track_ids) < 3: 
            continue
            
        playlist = schema.Playlist(
            name=theme_name,
            description=description,
            source="ai_generated",
            owner_id=current_user.id
        )
        db.add(playlist)
        db.flush()
        generated_count += 1
        
        for t_id in track_ids:
            # Verify the track belongs to the user just in case
            t = db.query(schema.Track).filter(schema.Track.id == t_id, schema.Track.owner_id == current_user.id).first()
            if t:
                db.add(schema.PlaylistTrack(playlist_id=playlist.id, track_id=t.id))
            
    db.commit()

    stats = ai_result
    return {
        "message": f"Created {generated_count} personalized Smart Mixes from {stats.get('classified_count', '?')} classified tracks ({stats.get('cluster_count', '?')} clusters detected).",
        "playlists_created": generated_count,
        "cluster_count": stats.get("cluster_count"),
        "unclassified_count": stats.get("unclassified_count", 0),
    }

def get_external_id(playlist: schema.Playlist, platform: str) -> str | None:
    # If the source matches the platform, external_id is directly the ID (for backward compatibility / imported playlists)
    if playlist.source == platform:
        return playlist.external_id
    
    val = playlist.external_id
    if not val:
        return None
        
    if val.startswith("plat:"):
        # Format: plat:spotify=ID1;ytmusic=ID2
        parts = val[5:].split(";")
        for part in parts:
            if "=" in part:
                p, pid = part.split("=", 1)
                if p == platform:
                    return pid
        return None
        
    # Backward compatibility: if no prefix, and playlist.source is "ai_generated" or "custom_smart", it was probably Spotify
    if platform == "spotify" and (playlist.source in ("ai_generated", "custom_smart")):
        return val
        
    return None

def set_external_id(playlist: schema.Playlist, platform: str, external_id: str):
    if playlist.source == platform:
        playlist.external_id = external_id
        return
        
    # Otherwise, build/update the plat: format
    val = playlist.external_id
    ids = {}
    if val and val.startswith("plat:"):
        parts = val[5:].split(";")
        for part in parts:
            if "=" in part:
                p, pid = part.split("=", 1)
                ids[p] = pid
    elif val and playlist.source in ("ai_generated", "custom_smart"):
        ids["spotify"] = val
        
    ids[platform] = external_id
    playlist.external_id = "plat:" + ";".join(f"{p}={pid}" for p, pid in ids.items())

@router.post("/export-spotify/{playlist_id}")
def export_to_spotify(playlist_id: int, current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Exports a Smart Playlist to Spotify with intelligent matching."""
    import logging
    logger = logging.getLogger("songbus.export")
    
    logger.info(f"{'='*60}")
    logger.info(f"[export_to_spotify] === EXPORT STARTED ===")
    logger.info(f"[export_to_spotify] playlist_id={playlist_id}")
    logger.info(f"[export_to_spotify] SongBus user id={current_user.id}, email={getattr(current_user, 'email', 'N/A')}")
    logger.info(f"[export_to_spotify] spotify_id (stored)={current_user.spotify_id}")
    logger.info(f"[export_to_spotify] has access_token={bool(current_user.spotify_access_token)}")
    logger.info(f"[export_to_spotify] has refresh_token={bool(current_user.spotify_refresh_token)}")
    logger.info(f"[export_to_spotify] token_expiry={current_user.spotify_token_expiry}")
    if current_user.spotify_access_token:
        logger.info(f"[export_to_spotify] token prefix={current_user.spotify_access_token[:20]}...")
    logger.info(f"{'='*60}")
    
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
    logger.info(f"[export_to_spotify] SpotifyService created. redirect_uri={spotify_service.redirect_uri}")
    logger.info(f"[export_to_spotify] Requested scopes={spotify_service.scope}")
    
    try:
        client = spotify_service.get_valid_client(current_user, db)
        logger.info(f"[export_to_spotify] Got valid Spotify client successfully")
    except Exception as e:
        logger.error(f"[export_to_spotify] get_valid_client FAILED: {type(e).__name__}: {e}")
        raise
    
    # 1. Ensure Spotify Playlist exists
    sp_playlist_id = get_external_id(playlist, "spotify")
    logger.info(f"[export_to_spotify] Existing spotify playlist_id from DB: {sp_playlist_id}")
    
    if not sp_playlist_id:
        try:
            logger.info(f"[export_to_spotify] No existing Spotify playlist — creating new one...")
            sp_playlist = spotify_service.create_playlist(
                client=client,
                user_id=current_user.spotify_id,
                name=playlist.name,
                description="Created by SongBus Intelligence"
            )
            if not sp_playlist:
                raise Exception("Failed to get playlist ID from Spotify.")
            sp_playlist_id = sp_playlist.get("id")
            logger.info(f"[export_to_spotify] Created Spotify playlist: {sp_playlist_id}")
        except Exception as e:
            logger.error(f"[export_to_spotify] Playlist creation FAILED: {type(e).__name__}: {e}")
            if hasattr(e, "http_status"):
                logger.error(f"[export_to_spotify] HTTP status: {e.http_status}")
            if hasattr(e, "http_status") and e.http_status == 403:
                raise HTTPException(
                    status_code=403,
                    detail="Spotify returned 403 Forbidden. Your connection might lack playlist modification scopes. Please disconnect and reconnect Spotify in Settings."
                )
            raise HTTPException(status_code=500, detail=f"Failed to create Spotify playlist: {str(e)}")
            
        set_external_id(playlist, "spotify", sp_playlist_id)
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

@router.post("/export-ytmusic/{playlist_id}")
def export_to_ytmusic(playlist_id: int, current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Exports a Smart Playlist to YouTube Music with intelligent matching."""
    if not current_user.yt_access_token:
        raise HTTPException(status_code=400, detail="YouTube Music is not connected. Visit Settings.")
        
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

    from app.api.youtube import get_valid_youtube_access_token, get_ytmusic_oauth_client
    
    # Ensure token is valid (refreshes if needed)
    get_valid_youtube_access_token(current_user, db)
    client = get_ytmusic_oauth_client(current_user)

    # Match Tracks & Collect Video IDs
    video_ids = []
    matched_count = 0
    
    for track in tracks:
        video_id = track.matched_youtube_id
        if not video_id:
            query = f"{track.title} {track.artist}"
            try:
                results = client.search(query, filter="songs", limit=5)
                for res in results:
                    if track.duration_ms and res.get("duration_seconds"):
                        duration_diff = abs((res["duration_seconds"] * 1000) - track.duration_ms)
                        if duration_diff > 15000: # 15s tolerance
                            continue
                    video_id = res.get("videoId")
                    if video_id:
                        break
            except Exception as e:
                print(f"Error searching YTMusic for {query}: {e}")
                
            if video_id:
                track.matched_youtube_id = video_id
                matched_count += 1
        else:
            matched_count += 1
            
        if video_id:
            video_ids.append(video_id)
            
    # Cache matched YouTube IDs to database
    db.commit()

    # Ensure YouTube Music Playlist exists and sync tracks
    yt_playlist_id = get_external_id(playlist, "ytmusic")
    playlist_exists = False
    
    if yt_playlist_id:
        try:
            # Check if playlist exists on YTMusic
            client.get_playlist(playlistId=yt_playlist_id, limit=1)
            playlist_exists = True
        except Exception:
            playlist_exists = False
            
    if not playlist_exists:
        try:
            yt_playlist_id = client.create_playlist(
                title=playlist.name,
                description="Created by SongBus Intelligence",
                video_ids=video_ids
            )
            set_external_id(playlist, "ytmusic", yt_playlist_id)
            db.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create YouTube Music playlist: {str(e)}")
    else:
        try:
            # Clear existing items
            pl_data = client.get_playlist(playlistId=yt_playlist_id, limit=None)
            existing_tracks = pl_data.get("tracks", [])
            if existing_tracks:
                to_remove = [{"videoId": t["videoId"], "setVideoId": t["setVideoId"]} for t in existing_tracks if "videoId" in t and "setVideoId" in t]
                if to_remove:
                    client.remove_playlist_items(yt_playlist_id, to_remove)
            
            # Add new items
            if video_ids:
                client.add_playlist_items(yt_playlist_id, videoIds=video_ids)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to sync YouTube Music playlist: {str(e)}")

    return {
        "message": "Playlist synced to YouTube Music!",
        "matched": matched_count,
        "total": len(tracks),
        "playlist_url": f"https://music.youtube.com/playlist?list={yt_playlist_id}"
    }

@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: int, current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = db.query(schema.Playlist).filter(schema.Playlist.id == playlist_id, schema.Playlist.owner_id == current_user.id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
        
    db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == playlist_id).delete()
    db.delete(playlist)
    db.commit()
    return {"message": "Playlist deleted"}

@router.get("/playlists/{playlist_id}/tracks")
def get_playlist_tracks(playlist_id: int, current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = db.query(schema.Playlist).filter(schema.Playlist.id == playlist_id, schema.Playlist.owner_id == current_user.id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
        
    tracks = db.query(schema.Track).join(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == playlist_id).all()
    return {
        "playlist_name": playlist.name,
        "tracks": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist,
                "thumbnail_url": t.thumbnail_url,
                "genre": t.genre,
                "mood": t.mood
            } for t in tracks
        ]
    }

class CustomPlaylistRequest(BaseModel):
    name: str
    genres: list[str] = []
    moods: list[str] = []
    
@router.post("/playlists/custom")
def create_custom_playlist(req: CustomPlaylistRequest, current_user: schema.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not req.name:
        raise HTTPException(status_code=400, detail="Playlist name is required")
        
    query = db.query(schema.Track).filter(schema.Track.owner_id == current_user.id)
    
    if req.genres:
        genre_filters = [schema.Track.genre.ilike(f"%{g}%") for g in req.genres]
        query = query.filter(or_(*genre_filters))
        
    if req.moods:
        mood_filters = [schema.Track.mood.ilike(f"%{m}%") for m in req.moods]
        query = query.filter(or_(*mood_filters))
        
    tracks = query.all()
    if not tracks:
        raise HTTPException(status_code=400, detail="No tracks match these rules.")
        
    playlist = schema.Playlist(
        name=req.name,
        source="custom_smart",
        owner_id=current_user.id
    )
    db.add(playlist)
    db.flush()
    
    for track in tracks:
        db.add(schema.PlaylistTrack(playlist_id=playlist.id, track_id=track.id))
        
    db.commit()
    return {"message": f"Created '{req.name}' with {len(tracks)} tracks!", "id": playlist.id}

@router.post("/export-all/{platform}")
def export_all_playlists(
    platform: str, 
    current_user: schema.User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Exports all of the user's smart/custom playlists to the selected platform in one pass."""
    if platform not in ("spotify", "ytmusic"):
        raise HTTPException(status_code=400, detail="Invalid platform. Choose 'spotify' or 'ytmusic'.")
        
    if platform == "spotify" and not current_user.spotify_access_token:
        raise HTTPException(status_code=400, detail="Spotify is not connected. Visit Settings.")
    if platform == "ytmusic" and not current_user.yt_access_token:
        raise HTTPException(status_code=400, detail="YouTube Music is not connected. Visit Settings.")

    # Get all smart and custom playlists owned by the user
    playlists = db.query(schema.Playlist).filter(
        schema.Playlist.owner_id == current_user.id,
        schema.Playlist.source.in_(("ai_generated", "custom_smart"))
    ).all()
    
    if not playlists:
        return {
            "message": "No smart or custom playlists found to export.",
            "results": [],
            "success_count": 0,
            "failed_count": 0
        }

    results = []
    success_count = 0
    failed_count = 0

    if platform == "spotify":
        spotify_service = SpotifyService()
        try:
            client = spotify_service.get_valid_client(current_user, db)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to authenticate with Spotify: {str(e)}")
            
        for pl in playlists:
            try:
                tracks = db.query(schema.Track).join(schema.PlaylistTrack).filter(
                    schema.PlaylistTrack.playlist_id == pl.id
                ).all()
                if not tracks:
                    results.append({
                        "playlist_name": pl.name,
                        "playlist_id": pl.id,
                        "status": "failed",
                        "message": "No tracks in playlist."
                    })
                    failed_count += 1
                    continue
                    
                sp_playlist_id = get_external_id(pl, "spotify")
                if not sp_playlist_id:
                    try:
                        sp_playlist = spotify_service.create_playlist(
                            client=client,
                            user_id=current_user.spotify_id,
                            name=pl.name,
                            description="Created by SongBus Intelligence"
                        )
                        if not sp_playlist:
                            raise Exception("Failed to get playlist ID from Spotify.")
                        sp_playlist_id = sp_playlist.get("id")
                    except Exception as e:
                        if hasattr(e, "http_status") and e.http_status == 403:
                            raise HTTPException(
                                status_code=403,
                                detail="Spotify returned 403 Forbidden. Your connection might lack playlist modification scopes. Please disconnect and reconnect Spotify in Settings."
                            )
                        raise e
                        
                    set_external_id(pl, "spotify", sp_playlist_id)
                    db.commit()
                    
                track_uris = []
                matched_count = 0
                for track in tracks:
                    uri = spotify_service.search_and_match_track(client, track)
                    if uri:
                        track_uris.append(uri)
                        matched_count += 1
                        if not track.spotify_uri:
                            track.spotify_uri = uri
                            
                if track_uris:
                    client.playlist_replace_items(sp_playlist_id, track_uris[:100])
                    if len(track_uris) > 100:
                        spotify_service.add_tracks_to_playlist(client, sp_playlist_id, track_uris[100:])
                        
                db.commit()
                results.append({
                    "playlist_name": pl.name,
                    "playlist_id": pl.id,
                    "status": "success",
                    "message": f"Successfully exported to Spotify.",
                    "playlist_url": f"https://open.spotify.com/playlist/{sp_playlist_id}",
                    "matched": matched_count,
                    "total": len(tracks)
                })
                success_count += 1
            except Exception as e:
                failed_count += 1
                results.append({
                    "playlist_name": pl.name,
                    "playlist_id": pl.id,
                    "status": "failed",
                    "message": str(e)
                })

    elif platform == "ytmusic":
        from app.api.youtube import get_valid_youtube_access_token, get_ytmusic_oauth_client
        try:
            get_valid_youtube_access_token(current_user, db)
            client = get_ytmusic_oauth_client(current_user)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to authenticate with YouTube Music: {str(e)}")
            
        for pl in playlists:
            try:
                tracks = db.query(schema.Track).join(schema.PlaylistTrack).filter(
                    schema.PlaylistTrack.playlist_id == pl.id
                ).all()
                if not tracks:
                    results.append({
                        "playlist_name": pl.name,
                        "playlist_id": pl.id,
                        "status": "failed",
                        "message": "No tracks in playlist."
                    })
                    failed_count += 1
                    continue
                    
                video_ids = []
                matched_count = 0
                for track in tracks:
                    video_id = track.matched_youtube_id
                    if not video_id:
                        query = f"{track.title} {track.artist}"
                        try:
                            results_search = client.search(query, filter="songs", limit=5)
                            for res in results_search:
                                if track.duration_ms and res.get("duration_seconds"):
                                    duration_diff = abs((res["duration_seconds"] * 1000) - track.duration_ms)
                                    if duration_diff > 15000:
                                        continue
                                video_id = res.get("videoId")
                                if video_id:
                                    break
                        except Exception:
                            pass
                            
                        if video_id:
                            track.matched_youtube_id = video_id
                            matched_count += 1
                    else:
                        matched_count += 1
                        
                    if video_id:
                        video_ids.append(video_id)
                        
                db.commit()
                
                yt_playlist_id = get_external_id(pl, "ytmusic")
                playlist_exists = False
                if yt_playlist_id:
                    try:
                        client.get_playlist(playlistId=yt_playlist_id, limit=1)
                        playlist_exists = True
                    except Exception:
                        playlist_exists = False
                        
                if not playlist_exists:
                    yt_playlist_id = client.create_playlist(
                        title=pl.name,
                        description="Created by SongBus Intelligence",
                        video_ids=video_ids
                    )
                    set_external_id(pl, "ytmusic", yt_playlist_id)
                    db.commit()
                else:
                    pl_data = client.get_playlist(playlistId=yt_playlist_id, limit=None)
                    existing_tracks = pl_data.get("tracks", [])
                    if existing_tracks:
                        to_remove = [{"videoId": t["videoId"], "setVideoId": t["setVideoId"]} for t in existing_tracks if "videoId" in t and "setVideoId" in t]
                        if to_remove:
                            client.remove_playlist_items(yt_playlist_id, to_remove)
                    if video_ids:
                        client.add_playlist_items(yt_playlist_id, videoIds=video_ids)
                        
                results.append({
                    "playlist_name": pl.name,
                    "playlist_id": pl.id,
                    "status": "success",
                    "message": f"Successfully exported to YouTube Music.",
                    "playlist_url": f"https://music.youtube.com/playlist?list={yt_playlist_id}",
                    "matched": matched_count,
                    "total": len(tracks)
                })
                success_count += 1
            except Exception as e:
                failed_count += 1
                results.append({
                    "playlist_name": pl.name,
                    "playlist_id": pl.id,
                    "status": "failed",
                    "message": str(e)
                })

    return {
        "message": f"Exported {success_count} playlist(s) successfully to {platform == 'spotify' and 'Spotify' or 'YouTube Music'} ({failed_count} failed).",
        "results": results,
        "success_count": success_count,
        "failed_count": failed_count
    }

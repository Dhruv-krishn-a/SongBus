import asyncio
from app.core.database import SessionLocal
from app.models import schema

def test():
    db = SessionLocal()
    # Create a user, track, playlist
    user = db.query(schema.User).first()
    
    t = schema.Track(title="Test Track", owner_id=user.id)
    p = schema.Playlist(name="Test Playlist", owner_id=user.id)
    db.add(t)
    db.add(p)
    db.commit()
    
    pt = schema.PlaylistTrack(playlist_id=p.id, track_id=t.id)
    db.add(pt)
    db.commit()
    
    print("Track ID before:", t.id)
    
    # Delete playlist
    db.query(schema.PlaylistTrack).filter(schema.PlaylistTrack.playlist_id == p.id).delete()
    db.delete(p)
    db.commit()
    
    # Check if track exists
    t_after = db.query(schema.Track).filter(schema.Track.id == t.id).first()
    print("Track exists after:", t_after is not None)

test()

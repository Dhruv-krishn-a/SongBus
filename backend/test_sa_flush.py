import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()
from app.models import schema

url = os.getenv("SQLALCHEMY_DATABASE_URL")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)
engine = create_engine(url)
Session = sessionmaker(bind=engine)
db = Session()

# get user
user = db.query(schema.User).first()
if user:
    playlist = schema.Playlist(name="Test Batch", source="test", owner_id=user.id)
    db.add(playlist)
    
    t1 = schema.Track(title="Test Track 1", artist="Artist 1", source="test", owner_id=user.id, external_id="test_ext_1")
    t2 = schema.Track(title="Test Track 2", artist="Artist 2", source="test", owner_id=user.id, external_id="test_ext_2")
    db.add(t1)
    db.add(t2)
    
    pt1 = schema.PlaylistTrack(playlist=playlist, track=t1)
    pt2 = schema.PlaylistTrack(playlist=playlist, track=t2)
    db.add(pt1)
    db.add(pt2)
    
    db.flush()
    print("Flush successful. t1.id =", t1.id)
    
    db.rollback()

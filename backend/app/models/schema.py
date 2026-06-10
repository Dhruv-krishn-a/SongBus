from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=True) # Nullable for OAuth-only users
    google_id = Column(String, unique=True, index=True, nullable=True)
    spotify_id = Column(String, unique=True, index=True, nullable=True)
    spotify_access_token = Column(String, nullable=True)
    spotify_refresh_token = Column(String, nullable=True)
    spotify_token_expiry = Column(DateTime, nullable=True)
    yt_access_token = Column(String, nullable=True)
    yt_refresh_token = Column(String, nullable=True)
    yt_token_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    playlists = relationship("Playlist", back_populates="owner")
    tracks = relationship("Track", back_populates="owner")

class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    source = Column(String) # e.g., "youtube", "spotify", "smart_generated"
    external_id = Column(String, nullable=True) # ID from YT/Spotify
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="playlists")
    tracks = relationship("PlaylistTrack", back_populates="playlist")

class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    album = Column(String, nullable=True)
    album_artist = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    genre = Column(String, nullable=True)
    mood = Column(String, nullable=True)
    language = Column(String, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    spotify_uri = Column(String, nullable=True)
    external_id = Column(String, nullable=True) # YT/Spotify ID
    source = Column(String) # e.g., "youtube"
    
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="tracks")
    playlists = relationship("PlaylistTrack", back_populates="track")

class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    playlist_id = Column(Integer, ForeignKey("playlists.id"), primary_key=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), primary_key=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    playlist = relationship("Playlist", back_populates="tracks")
    track = relationship("Track", back_populates="playlists")

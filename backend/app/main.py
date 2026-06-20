from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, music, integrations, youtube, playlists, tasks, transport
from dotenv import load_dotenv
import logging

load_dotenv()

# Configure logging so all songbus.* loggers output to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
# Set songbus loggers to DEBUG for maximum detail
logging.getLogger("songbus").setLevel(logging.DEBUG)

app = FastAPI(
    title="PlaylistIQ API",
    description="API for the PlaylistIQ application",
    version="1.0.0",
)

# Configure CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://localhost:5174",
        "https://localhost:5173",
        "https://localhost:5174"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(music.router, prefix="/api/music", tags=["music"])
app.include_router(playlists.router, prefix="/api/music", tags=["playlists_extra"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["integrations"])
app.include_router(youtube.router, prefix="/api/integrations", tags=["youtube"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(transport.router, prefix="/api/transport", tags=["transport"])

@app.get("/")
def read_root():
    return {"message": "Welcome to PlaylistIQ API!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

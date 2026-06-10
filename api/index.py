import sys
import os

# Add the backend folder to the path so we can import from app
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.main import app

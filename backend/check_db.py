from app.core.database import SessionLocal
from app.models import schema
db = SessionLocal()
task = db.query(schema.BackgroundTask).order_by(schema.BackgroundTask.created_at.desc()).first()
print(f"Task: {task.name}, Status: {task.status}, Progress: {task.progress}, Error: {task.error}")

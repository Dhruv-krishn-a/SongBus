from typing import Dict, Any, List
import uuid
import json
from datetime import datetime
from app.core.database import SessionLocal
from app.models import schema

def create_task(name: str, user_id: int, total: int = 0) -> str:
    db = SessionLocal()
    try:
        task_id = str(uuid.uuid4())
        db_task = schema.BackgroundTask(
            id=task_id,
            name=name,
            owner_id=user_id,
            status="pending",
            total=total,
            message="Starting...",
            progress=0
        )
        db.add(db_task)
        db.commit()
        return task_id
    finally:
        db.close()

def update_task(task_id: str, status: str = None, progress: int = None, total: int = None, message: str = None, result: Any = None, error: str = None):
    db = SessionLocal()
    try:
        db_task = db.query(schema.BackgroundTask).filter(schema.BackgroundTask.id == task_id).first()
        if db_task:
            if status is not None:
                db_task.status = status
            if progress is not None:
                db_task.progress = progress
            if total is not None:
                db_task.total = total
            if message is not None:
                db_task.message = message
            if result is not None:
                db_task.result = json.dumps(result)
            if error is not None:
                db_task.error = error
            db_task.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()

def get_task(task_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        db_task = db.query(schema.BackgroundTask).filter(schema.BackgroundTask.id == task_id).first()
        if not db_task:
            return None
        
        return {
            "id": db_task.id,
            "name": db_task.name,
            "status": db_task.status,
            "progress": db_task.progress,
            "total": db_task.total,
            "message": db_task.message,
            "result": json.loads(db_task.result) if db_task.result else None,
            "error": db_task.error,
            "updated_at": db_task.updated_at.isoformat() if db_task.updated_at else None
        }
    finally:
        db.close()

from datetime import datetime, timedelta

def get_active_tasks(user_id: int) -> List[Dict[str, Any]]:
    """Returns all running or pending tasks for a user. Cleans up zombie tasks."""
    db = SessionLocal()
    try:
        # Optimization: Fail tasks that haven't been updated in 2 minutes (Zombies)
        two_minutes_ago = datetime.utcnow() - timedelta(minutes=2)
        zombies = db.query(schema.BackgroundTask).filter(
            schema.BackgroundTask.owner_id == user_id,
            schema.BackgroundTask.status.in_(["running", "pending"]),
            schema.BackgroundTask.updated_at < two_minutes_ago
        ).all()
        
        for z in zombies:
            z.status = "failed"
            z.error = "Task timed out or backend restarted."
            z.updated_at = datetime.utcnow()
        
        if zombies:
            db.commit()

        active_tasks = db.query(schema.BackgroundTask).filter(
            schema.BackgroundTask.owner_id == user_id,
            schema.BackgroundTask.status.in_(["pending", "running"])
        ).order_by(schema.BackgroundTask.created_at.desc()).all()
        
        return [{
            "id": t.id,
            "name": t.name,
            "status": t.status,
            "progress": t.progress,
            "total": t.total,
            "message": t.message
        } for t in active_tasks]
    finally:
        db.close()

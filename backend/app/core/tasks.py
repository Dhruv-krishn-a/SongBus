from typing import Dict, Any
import uuid
from datetime import datetime

# Simple in-memory task registry
# In a real production app with multiple workers, use Redis/Celery.
_tasks: Dict[str, Dict[str, Any]] = {}

def create_task(name: str, total: int = 0) -> str:
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "id": task_id,
        "name": name,
        "status": "pending", # pending, running, completed, failed
        "progress": 0,
        "total": total,
        "message": "Starting...",
        "result": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    return task_id

def update_task(task_id: str, status: str = None, progress: int = None, total: int = None, message: str = None, result: Any = None, error: str = None):
    if task_id in _tasks:
        task = _tasks[task_id]
        if status is not None: task["status"] = status
        if progress is not None: task["progress"] = progress
        if total is not None: task["total"] = total
        if message is not None: task["message"] = message
        if result is not None: task["result"] = result
        if error is not None: task["error"] = error
        task["updated_at"] = datetime.utcnow().isoformat()

def get_task(task_id: str) -> Dict[str, Any]:
    return _tasks.get(task_id)

def get_all_tasks() -> Dict[str, Dict[str, Any]]:
    return _tasks

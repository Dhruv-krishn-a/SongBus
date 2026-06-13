from fastapi import APIRouter, HTTPException, Depends
from app.core import tasks
from app.models import schema
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/active")
def get_active_tasks(current_user: schema.User = Depends(get_current_user)):
    """Returns any running or pending tasks for the current user."""
    return {"tasks": tasks.get_active_tasks(current_user.id)}

@router.get("/{task_id}")
def get_task_status(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

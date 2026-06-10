from fastapi import APIRouter, HTTPException
from app.core import tasks

router = APIRouter()

@router.get("/{task_id}")
def get_task_status(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

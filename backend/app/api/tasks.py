from fastapi import APIRouter, HTTPException, Depends
from app.core import tasks
from app.models import schema
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/active")
def get_active_tasks(current_user: schema.User = Depends(get_current_user)):
    """Returns any running or pending tasks for the current user."""
    try:
        return {"tasks": tasks.get_active_tasks(current_user.id)}
    except Exception as e:
        print(f"DB Error while fetching active tasks: {e}")
        return {"tasks": []}

@router.get("/{task_id}")
def get_task_status(task_id: str):
    try:
        task = tasks.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Return a temporary 'running' state if the DB hiccups, so the UI doesn't fail the sync
        print(f"DB Error while fetching task {task_id}: {e}")
        return {
            "id": task_id,
            "status": "running",
            "progress": 0,
            "total": 0,
            "message": "Reconnecting to database...",
            "error": None
        }

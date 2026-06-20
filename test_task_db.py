import os
import time
from dotenv import load_dotenv
load_dotenv("backend/.env")
from backend.app.core.tasks import get_active_tasks

user_id = 3 # test3@example.com
print(get_active_tasks(user_id))

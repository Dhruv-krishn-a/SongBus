import requests
import time

while True:
    try:
        res = requests.get("http://127.0.0.1:8000/api/tasks/active")
        print(res.status_code, res.text)
    except Exception as e:
        print("Error", e)
    time.sleep(2)

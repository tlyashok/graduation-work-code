import requests
import time

for i in range(30):
    try:
        r = requests.get("http://127.0.0.1:8000/health", timeout=3)
        if r.status_code == 200 and r.json().get("model_loaded"):
            print(f"Сервис готов: {r.json()}")
            break
    except Exception:
        pass
    print(f"Ожидание... ({i+1})")
    time.sleep(5)
else:
    print("Превышено время ожидания")

from fastapi import FastAPI
from datetime import datetime

app = FastAPI()

def get_cpu_temp():
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        temp = int(f.read()) / 1000
    return temp

def get_uptime():
    with open("/proc/uptime") as f:
        uptime_seconds = float(f.readline().split()[0])
    return uptime_seconds

@app.get("/")
async def root():
    # return {"message": "hello"}
    return "<p>"

@app.get("/status")
async def time():
    now = datetime.now()
    return {
        "Time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "CPU Temp (C)": get_cpu_temp(),
        "UPTime (s)": get_uptime()
        }

# uvicorn fastapi-tutorial:app --host 0.0.0.0 --port 8000 --reload
# http://192.168.0.131:8000
"""Tiny workload to break on purpose. Behaviour is switched by env vars so chaos = `kubectl set env`."""
import os
import sys
import threading
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

app = FastAPI(title="demo-app")
REQS = Counter("http_requests_total", "HTTP requests", ["path", "status"])


def _on(name: str) -> bool:
    return os.getenv(name, "false").lower() == "true"


def _crash_soon() -> None:
    time.sleep(5)
    msg = os.getenv("CRASH_MESSAGE", "FATAL: CRASH_ON_START is enabled - simulated bad config, exiting 1")
    print(msg, flush=True)
    os._exit(1)


def _leak() -> None:
    hog, mb = [], 0
    while True:
        hog.append(bytearray(b"x") * (5 * 1024 * 1024))  # multiply forces pages to be touched
        mb += 5
        print(f"WARN: cache growing unbounded, {mb} MiB retained", flush=True)
        time.sleep(0.5)


@app.on_event("startup")
def startup() -> None:
    print("demo-app starting", flush=True)
    if _on("CRASH_ON_START"):
        threading.Thread(target=_crash_soon, daemon=True).start()
    if _on("LEAK_MEMORY"):
        threading.Thread(target=_leak, daemon=True).start()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index():
    REQS.labels("/", "200").inc()
    return {"app": "demo-app", "version": os.getenv("APP_VERSION", "1")}


@app.get("/burn")
def burn(ms: int = 100):
    """Consume `ms` of *CPU time* (not wall time) so load is meaningful under CPU limits."""
    ms = min(ms, 2000)
    start = time.thread_time()
    while (time.thread_time() - start) * 1000 < ms:
        pass
    REQS.labels("/burn", "200").inc()
    return {"burned_ms": ms}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
    sys.exit(0)

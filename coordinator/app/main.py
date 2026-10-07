"""Coordinator FastAPI app (skeleton)."""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from coordinator.app.routers import client, nodes

app = FastAPI(title="RAID1 Coordinator (skeleton)")
app.include_router(client.router)
app.include_router(nodes.router)

_static = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "frontend", "static")
if os.path.isdir(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "role": "coordinator"}

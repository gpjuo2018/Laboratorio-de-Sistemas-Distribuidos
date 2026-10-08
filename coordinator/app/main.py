"""Coordinator FastAPI app."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from coordinator.app.routers import client, nodes

app = FastAPI(title="RAID1 Coordinator")
# La consola puede abrirse desde otra IP (Tailscale) que el COORDINATOR_URL
# configurado: se permite CORS para que el navegador no bloquee X-API-Key.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(client.router)
app.include_router(nodes.router)

_static = os.path.join(os.path.dirname(__file__), "..", "..",
                       "frontend", "static")
if os.path.isdir(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "role": "coordinator"}

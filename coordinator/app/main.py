"""Coordinator FastAPI app."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
_static = os.path.normpath(_static)
if os.path.isdir(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/", include_in_schema=False)
def console():
    """Sirve la consola web en / (además de /static/index.html)."""
    index = os.path.join(_static, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, media_type="text/html")
    return {"detail": "consola no encontrada: falta frontend/static/index.html"}


@app.get("/health")
def health():
    return {"status": "ok", "role": "coordinator"}

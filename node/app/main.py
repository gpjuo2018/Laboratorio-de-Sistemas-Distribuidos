"""Storage node FastAPI app (skeleton)."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from node.app.routers import peers, store

app = FastAPI(title="RAID1 Node (skeleton)")
# La consola web (servida por el coordinador) llama a los nodos
# cross-origen con X-Internal-Key: sin CORS el navegador la bloquea.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(store.router)
app.include_router(peers.router)


@app.get("/health")
def health():
    return {"status": "ok", "role": "node",
            "node_id": os.getenv("NODE_ID", "node-1")}

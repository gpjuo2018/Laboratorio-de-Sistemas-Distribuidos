"""Storage node FastAPI app (skeleton)."""
import os
from fastapi import FastAPI

from node.app.routers import peers, store

app = FastAPI(title="RAID1 Node (skeleton)")
app.include_router(store.router)
app.include_router(peers.router)


@app.get("/health")
def health():
    return {"status": "ok", "role": "node",
            "node_id": os.getenv("NODE_ID", "node-1")}

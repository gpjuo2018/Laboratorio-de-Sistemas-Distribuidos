"""Shared constants. Reads env with defaults, no pydantic."""
import os

RF = int(os.getenv("RF", "2"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "10"))
DEAD_TIMEOUT = int(os.getenv("DEAD_TIMEOUT", "30"))
NODE_ID = os.getenv("NODE_ID", "node-1")
NODE_PORT = int(os.getenv("NODE_PORT", "8001"))
COORDINATOR_URL = os.getenv("COORDINATOR_URL", "http://127.0.0.1:8000")
X_INTERNAL_KEY = os.getenv("X_INTERNAL_KEY", "")
X_API_KEY = os.getenv("X_API_KEY", "")
PEERS_TTL = int(os.getenv("PEERS_TTL", os.getenv("HEARTBEAT_INTERVAL", "10")))
PEERS_TIMEOUT = int(os.getenv("PEERS_TIMEOUT", "3"))
PEERS_RETRIES = int(os.getenv("PEERS_RETRIES", "1"))
METADATA_DB_PATH = os.getenv("METADATA_DB_PATH", "./metadata.db")
APP_VERSION = "1.1.0"

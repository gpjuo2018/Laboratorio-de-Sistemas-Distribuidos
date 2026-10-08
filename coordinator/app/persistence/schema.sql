CREATE TABLE IF NOT EXISTS objects (
  name TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  replicas_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
  node_id TEXT PRIMARY KEY,
  base_url TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  disk_free INTEGER,
  files_stored INTEGER,
  uptime_secs REAL,
  version TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  node_id TEXT,
  detail TEXT
);

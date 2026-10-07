CREATE TABLE IF NOT EXISTS objects (
  name TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  replicas_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

# RAID1 Distributed File Storage (skeleton)

Stub-only monorepo. Every route beyond `/health` returns 501.

## Folders
- `coordinator/` - metadata (SQLite), placement RF=2, fan-out to nodes
- `node/` - local block store under `./data/`
- `common/` - shared config, hashing, auth headers, http client
- `frontend/static/` - static UI served by coordinator, talks only to coordinator

## Ports
| Role | Port |
|---|---|
| coordinator | 8000 |
| node 1 | 8001 |
| node 2 | 8002 |
| node 3 | 8003 |
| node 4 | 8004 |

## Run (Windows PowerShell)
```powershell
.\scripts\run_coordinator.ps1
.\scripts\run_node.ps1 -NodeId node-1 -Port 8001
copy .env.example .env  # then edit COORDINATOR_URL for Tailscale
```

## Notes
- RAID1 RF=2: full-file mirroring, dynamic pairs via rendezvous.
- Usable capacity 50%; repair = copy from survivor.
- Over Tailscale use plain HTTP with `COORDINATOR_URL` env; never hardcode IPs.

## Wave 5: observability + mesh
- `GET /nodes/map` — full network map: coordinator info (version, time, counts), live/dead node rows, files with replicas, last 10 events (shared dashboard for the demo).
- `GET /events?limit=50` (max 200) — newest-first death/recovery/repair event log visible to everyone.
- `GET /peers` (node) — node-to-node mesh awareness: coordinator reachability plus per-sibling probe (`reachable`, `detail`), always 200.
- Enriched heartbeats: register/heartbeat accept `disk_free, files_stored, uptime_secs, version`; stale→fresh heartbeat logs `node_up`, fresh death logs `node_down` (once), each `/check` with repairs/failures logs one `repair` summary.
- One command per node: `.\scripts\run_node.ps1 -NodeId node-1 -Port 8001` boots the node (background, log `logs\node-<id>-<port>.log`, waits for `/internal/health`) then runs the enriched heartbeat loop in the foreground (`-CoordinatorUrl`, `-IntervalSecs 10` optional).
- Ctrl+C stops both the heartbeat loop and the node process it started.

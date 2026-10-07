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

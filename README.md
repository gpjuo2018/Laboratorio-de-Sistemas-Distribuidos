# Almacenamiento RAID1 Distribuido

Monorepo del laboratorio. Todo lo que no sea `/health` devuelve 501 hasta que se implemente.

## EMPIEZA AQUI (leelo, son 2 minutos)

**Paso 0: instala lo necesario (una sola vez por máquina).** Cada uno hace esto en SU equipo, el `.venv` no se comparte:

```bash
git clone <URL-DEL-REPO>
cd <carpeta-del-proyecto>
python -m venv .venv
```

Actívalo (cada vez que abras una terminal nueva para trabajar):
- Windows: `.\.venv\Scripts\Activate.ps1`
- Mac/Linux: `source .venv/bin/activate`

E instala las dependencias (una vez, con el `.venv` activado):

```bash
pip install -r requirements.txt
```

Si el `pip install` falla, actualiza pip primero: `python -m pip install --upgrade pip` y reintenta.

**Paso 1: averigua tu IP de Tailscale.** Abre una terminal y ejecuta `tailscale ip -4`. Ese número es tu IP. El coordinador necesita la IP de cada nodo, y cada nodo necesita la IP del coordinador.

**Paso 2: crea tu `.env`.** Copia el bloque que te toque (coordinador o nodo) y cambia SOLO lo marcado con ⬅️.

Si eres el **coordinador**:

```ini
ROLE=coordinator
NODE_ID=node-0
NODE_PORT=8000
COORDINATOR_URL=http://127.0.0.1:8000
X_INTERNAL_KEY=REEMPLAZA-CON-VALOR-SEGURO-DE-32-CARACTERES ⬅️ mismo en todas las máquinas, ver Seguridad
X_API_KEY=REEMPLAZA-CON-VALOR-SEGURO-DE-32-CARACTERES ⬅️ mismo en todas las máquinas, ver Seguridad
HEARTBEAT_INTERVAL=10
DEAD_TIMEOUT=30
RF=2
DATA_DIR=./data
NODES=http://IP-NODO-1:8001,http://IP-NODO-2:8002 ⬅️ una entrada por nodo, separadas por coma
METADATA_DB_PATH=./metadata.db
```

Si eres un **nodo** (ejemplo nodo-2, cambia el número por el tuyo):

```ini
ROLE=node
NODE_ID=node-2 ⬅️ tu número
NODE_PORT=8002 ⬅️ 8000 + tu número
COORDINATOR_URL=http://IP-DEL-COORD:8000 ⬅️ la IP Tailscale del coordinador, NO 127.0.0.1
X_INTERNAL_KEY=REEMPLAZA-CON-VALOR-SEGURO-DE-32-CARACTERES (igual que el coordinador, no tocar)
X_API_KEY=REEMPLAZA-CON-VALOR-SEGURO-DE-32-CARACTERES (igual que el coordinador, no tocar)
HEARTBEAT_INTERVAL=10
DEAD_TIMEOUT=30
RF=2
DATA_DIR=./data-node-2 ⬅️ tu número, NO pongas ./data a secas
NODES=http://IP-NODO-1:8001,http://IP-NODO-2:8002 (igual que el coordinador, no tocar)
METADATA_DB_PATH=./metadata.db
```

**3 reglas, sin excepción:**
1. `X_INTERNAL_KEY`, `X_API_KEY` y `NODES` son IGUALES en todas las máquinas. No inventes valores.
2. `COORDINATOR_URL` en los nodos lleva la IP Tailscale del coordinador. `127.0.0.1` solo funciona en la máquina del coordinador.
3. `NODE_ID`, `NODE_PORT` y `DATA_DIR` son ÚNICOS por persona. Si dos ponen lo mismo, uno no arranca.

**Paso 3: corre el script SIN argumentos** (ya lee tu `.env` solo), desde la raíz del proyecto:
- Windows: `.\scripts\run_node.ps1` (o `.\scripts\run_coordinator.ps1` si eres coordinador)
- Mac/Linux: `./scripts/run_node.sh` (la primera vez: `chmod +x scripts/run_node.sh`)

**Si sale `PREFLIGHT FAIL: port busy`:** el script ya limpia solo los nodos viejos olvidados. Si el error persiste es otro programa: no cambies el puerto, mata ese proceso (Windows: `netstat -ano | findstr :TUPUERTO` y `taskkill /F /PID <número>`; Mac: `lsof -iTCP:TUPUERTO -sTCP:LISTEN` y `kill <número>`). Para apagar bien usa siempre **Ctrl+C**, no cierres la ventana. Si sale `register pending`, el coordinador no está arriba todavía: levanta primero el coordinador.

## Carpetas
- `coordinator/` - metadatos (SQLite), ubicación RF=2, réplicas hacia los nodos
- `node/` - guarda los bloques en `./data-<nodo>/`
- `common/` - configuración compartida, hashing, auth, cliente http
- `frontend/static/` - interfaz web, la sirve el coordinador y solo habla con él

## Puertos
| Rol | Puerto |
|---|---|
| coordinador | 8000 |
| nodo 1 | 8001 |
| nodo 2 | 8002 |
| nodo 3 | 8003 |
| nodo 4 | 8004 |

## Correr (avanzado, normalmente no hace falta)
```powershell
.\scripts\run_node.ps1 -NodeId node-1 -Port 8001
```
```bash
./scripts/run_node.sh node-1 8001
```
Lo que pases por argumento le gana al `.env`. Si no pasas `-Port`, se deduce de `NODES` según tu número (`node-2` -> puerto de la segunda URL).

## Notas
- RAID1 RF=2: cada archivo se copia entero en 2 nodos, las parejas se eligen por rendezvous.
- Capacidad útil 50%; la reparación es copiar desde el sobreviviente.
- Sobre Tailscale se usa HTTP plano con la variable `COORDINATOR_URL`; nunca pongas IPs en el código.

## Seguridad (X_API_KEY / X_INTERNAL_KEY)
- `X_API_KEY` = borde público: solo `PUT/GET/DELETE /files*` en coordinador. Sin header → `401`, valor distinto (comparación `hmac.compare_digest`) → `403`. Ver `common/security.py:require_api_key`.
- `X_INTERNAL_KEY` = plano interno: todo `/nodes/*` en coordinador + `PUT/GET/DELETE /store/*`, `GET /internal/health`, `GET /peers` en nodos. Misma semántica `401/403`. Ver `common/security.py:require_internal_key`.
- Públicos sin auth: `GET /health` x2, `/static/*`.
- Emisores internos envían `X-Internal-Key` desde env en cada llamada: `replication.py:replicate/fetch_verified`, `client.py:delete_file`, `peers.py:list_peers`, `scripts/run_node.ps1/.sh` (`register/heartbeat`, readiness a `/internal/health`).
- Nunca se loguean ni devuelven secretos en `detail`; mensajes genéricos `missing/invalid api/internal key`.
- Config: copia `.env.example` a `.env` y genera valores de 32+ caracteres. Rota las claves expuestas antes en `README` y purga historial (`git log -p -- README.md`), ya que `.env` está ignorado pero `README` las duplicaba.
- Pruebas: `tests/test_security.py` verifica matriz autorizado `200` vs sin clave `401` vs clave errónea `403` sin exponer secretos.

## Observabilidad + malla
- `GET /peers` (nodo, requiere `X-Internal-Key`) — descubrimiento vía `GET /nodes` del coordinador + sondeo secuencial `GET /internal/health` por hermano (timeout `PEERS_TIMEOUT=3s`, `PEERS_RETRIES=1` solo en timeout/conexión). Estado por peer: `available` (0 fallos) / `degraded` (1) / `disconnected` (≥2), `reachable=(status==available)` por compat, más `failures`, `last_seen`, `detail` sanitizado (sin secretos, máx 200). Caché TTL `PEERS_TTL=10s` (usa `HEARTBEAT_INTERVAL` si ausente); `?refresh=true` fuerza re-sondeo. Siempre `200`; `401/403` solo por auth. Valida `node_id` cuando el hermano lo devuelve (`node_id mismatch` → no alcanzable).
- `GET /nodes/map` — mapa completo de la red: datos del coordinador, nodos vivos/muertos, archivos con sus réplicas, últimos 10 eventos (el tablero de la demo).
- `GET /events?limit=50` (máx 200) — registro de eventos muerte/recuperación/reparación, lo nuevo primero.
- `GET /peers` — detalle arriba (contrato: siempre `200`, `reachable` por compat).
- Latidos enriquecidos: register/heartbeat aceptan `disk_free, files_stored, uptime_secs, version`; si un nodo vuelve se guarda `node_up`, si muere `node_down` (una vez), y cada `/check` con arreglos/fallos guarda un resumen `repair`.
- Un solo comando por nodo: `.\scripts\run_node.ps1` prende el nodo (en segundo plano, logs `logs\node-<id>-<puerto>.log` + `-err.log`, espera a `/internal/health`, se registra en el coordinador) y luego corre el loop de latidos en primer plano (si el coordinador lo desconoce, se re-registra solo).
- Ctrl+C detiene el loop de latidos Y el proceso del nodo que arrancó.

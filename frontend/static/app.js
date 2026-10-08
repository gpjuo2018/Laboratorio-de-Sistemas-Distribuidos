"use strict";
/* RAID1 frontend: solo habla con el coordinador y solo usa X-API-Key.
   Nunca pide ni envia X-Internal-Key (plano interno, no es para navegadores). */

const $ = (id) => document.getElementById(id);
const ipInput = $("coord-ip"), portInput = $("coord-port");
const keyInput = $("api-key"), rememberInput = $("remember");
const internalInput = $("internal-key");
const connStatus = $("conn-status"), connPill = $("conn-pill"), logBox = $("log");
const fileInput = $("file-input"), nameInput = $("file-name");
const uploadInfo = $("upload-info"), uploadResult = $("upload-result");
const filesBody = $("files-body");
const nodesBody = $("nodes-body"), nodesSummary = $("nodes-summary"), meshBox = $("mesh");
const autoInput = $("auto");
let autoTimer = null;

try {
  const savedKey = localStorage.getItem("raid1_api_key");
  if (savedKey) keyInput.value = savedKey;
  const savedIk = localStorage.getItem("raid1_internal_key");
  if (savedIk) internalInput.value = savedIk;
  const savedIp = localStorage.getItem("raid1_coord_ip");
  if (savedIp) ipInput.value = savedIp;
  const savedPort = localStorage.getItem("raid1_coord_port");
  if (savedPort) portInput.value = savedPort;
} catch { /* almacenamiento no disponible: se usa solo memoria */ }

function persist() {
  try {
    if (rememberInput.checked && keyInput.value) localStorage.setItem("raid1_api_key", keyInput.value);
    else localStorage.removeItem("raid1_api_key");
    if (rememberInput.checked && internalInput.value) localStorage.setItem("raid1_internal_key", internalInput.value);
    else localStorage.removeItem("raid1_internal_key");
    if (ipInput.value.trim()) localStorage.setItem("raid1_coord_ip", ipInput.value.trim());
    else localStorage.removeItem("raid1_coord_ip");
    if (portInput.value.trim()) localStorage.setItem("raid1_coord_port", portInput.value.trim());
    else localStorage.removeItem("raid1_coord_port");
  } catch { /* ignorar */ }
}
keyInput.addEventListener("change", persist);
internalInput.addEventListener("change", persist);
ipInput.addEventListener("change", persist);
portInput.addEventListener("change", persist);

function base() {
  let ip = ipInput.value.trim().replace(/^https?:\/\//i, "").replace(/\/+$/, "");
  if (!ip) {
    if (location.protocol === "file:") return "http://127.0.0.1:8000";
    return location.origin;
  }
  if (ip.includes(":")) return `http://${ip}`;
  const port = (portInput.value.trim() || "8000").replace(/\D/g, "") || "8000";
  return `http://${ip}:${port}`;
}
function apiKey() { return keyInput.value; }
function internalKey() { return internalInput.value; }
function setPill(text, cls) {
  connPill.textContent = text;
  connPill.className = `pill ${cls}`;
}
function log(msg, cls) {
  const line = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
  logBox.textContent += line;
  if (cls) { connStatus.textContent = msg; connStatus.className = cls; }
}
function errText(status) {
  if (status === 0 || status === undefined) return "sin conexión con el coordinador (¿encendido? ¿IP/puerto bien?)";
  return {400: "nombre inválido", 401: "falta X-API-Key", 403: "X-API-Key incorrecta",
          404: "no existe", 502: "réplicas no disponibles", 503: "sin nodos"}[status]
         || `HTTP ${status}`;
}
async function api(path, opts = {}) {
  const headers = Object.assign({"X-API-Key": apiKey()}, opts.headers || {});
  let r;
  try {
    r = await fetch(base() + path, Object.assign({}, opts, {headers}));
  } catch { throw {status: 0}; }
  if (!r.ok) throw {status: r.status, detail: await r.text().catch(() => "")};
  return r;
}
function badName(n) {
  if (!n || !n.trim() || n.includes("/") || n.includes("\\") || n.includes("..") || n.includes("%")) return true;
  for (const c of n) { const o = c.codePointAt(0); if (o < 32 || o === 127) return true; }
  return false;
}
async function sha256Hex(buf) {
  const d = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

fileInput.addEventListener("change", async () => {
  const f = fileInput.files[0];
  if (!f) { uploadInfo.textContent = ""; return; }
  if (!nameInput.value) nameInput.value = f.name;
  const buf = await f.arrayBuffer();
  uploadInfo.textContent = `local: ${f.name} (${f.size} bytes) sha256=${await sha256Hex(buf)}`;
});

$("upload-btn").addEventListener("click", async () => {
  const f = fileInput.files[0];
  if (!f) return log("elige un archivo primero", "err");
  const name = (nameInput.value || f.name).trim();
  if (badName(name)) return log(`nombre rechazado: ${name}`, "err");
  if (!apiKey()) return log("falta X-API-Key", "err");
  log(`subiendo ${name} (${f.size} bytes)…`);
  try {
    const buf = await f.arrayBuffer();
    const local = await sha256Hex(buf);
    const r = await api(`/files/${encodeURIComponent(name)}`,
                        {method: "PUT", body: f, headers: {"Content-Type": "application/octet-stream"}});
    const data = await r.json();
    const ok = data.sha256 === local && data.size === f.size
      && Array.isArray(data.replicas) && data.replicas.length === 2;
    uploadResult.innerHTML = `<code>${JSON.stringify(data)}</code>`;
    log(ok ? `subido ${name}: sha256 coincide, 2 réplicas`
           : `subido con advertencia: local ${local} vs servidor ${data.sha256}`,
        ok ? "ok" : "err");
    await refresh();
  } catch (e) { log(`subida falló: ${errText(e.status)}`, "err"); }
});

async function testConnection() {
  setPill("probando…", "idle");
  try {
    const r = await fetch(base() + "/health");
    if (!r.ok) throw {status: r.status};
    const data = await r.json().catch(() => ({}));
    setPill(`coordinador OK · ${data.version || data.role || "ok"}`, "ok");
    log(`coordinador responde: ${JSON.stringify(data)}`, "ok");
  } catch (e) {
    setPill("sin conexión", "err");
    log(`sin conexión: ${errText(e.status)} — revisa IP/puerto y que el coordinador esté encendido`, "err");
  }
}

async function refresh() {
  if (!apiKey()) { log("falta X-API-Key", "err"); return; }
  try {
    const r = await api("/files");
    const files = await r.json();
    connStatus.textContent = `coordinador OK · ${files.length} archivo(s)`;
    connStatus.className = "ok";
    setPill(`en línea · ${files.length}`, "ok");
    filesBody.innerHTML = "";
    if (!files.length) {
      filesBody.innerHTML = `<tr><td colspan="5" class="muted">vacío — sube tu primer archivo arriba</td></tr>`;
      return;
    }
    for (const o of files) {
      const tr = document.createElement("tr");
      const short = (o.sha256 || "").slice(0, 16) + "…";
      const n = (o.replicas || []).length;
      tr.innerHTML = `<td></td><td>${o.size}</td>` +
                     `<td class="mono" title="${o.sha256 || ""}">${short}</td>` +
                     `<td><span class="mirror">◐ ${n} ${n === 1 ? "réplica" : "réplicas"}</span></td><td></td>`;
      tr.children[0].textContent = o.name;
      const tdAct = tr.children[4];
      const btnD = document.createElement("button");
      btnD.textContent = "Descargar";
      btnD.addEventListener("click", () => download(o.name));
      const btnX = document.createElement("button");
      btnX.textContent = "Borrar";
      btnX.className = "danger";
      btnX.addEventListener("click", () => remove(o.name));
      tdAct.append(btnD, btnX);
      filesBody.append(tr);
    }
  } catch (e) { log(`lista falló: ${errText(e.status)}`, "err"); }
}

async function download(name) {
  log(`descargando ${name}…`);
  try {
    const r = await api(`/files/${encodeURIComponent(name)}`);
    const blob = await r.blob();
    const buf = await blob.arrayBuffer();
    log(`descargado ${name} (${blob.size} bytes) sha256=${await sha256Hex(buf)}`, "ok");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) { log(`descarga falló: ${errText(e.status)}`, "err"); }
}

async function remove(name) {
  if (!confirm(`¿Borrar ${name} del cluster?`)) return;
  try {
    const r = await api(`/files/${encodeURIComponent(name)}`, {method: "DELETE"});
    const data = await r.json().catch(() => ({}));
    log(data.deleted ? `borrado ${name}` : `borrado parcial de ${name}: ${JSON.stringify(data)}`,
        data.deleted ? "ok" : "err");
    await refresh();
  } catch (e) { log(`borrado falló: ${errText(e.status)}`, "err"); }
}

function internalErrText(status) {
  if (status === 0 || status === undefined) return "sin conexión (¿encendido? ¿IP/puerto bien?)";
  return {400: "petición inválida", 401: "falta X-Internal-Key", 403: "X-Internal-Key incorrecta",
          404: "no existe"}[status] || `HTTP ${status}`;
}
async function nodeApi(url, opts = {}) {
  const headers = Object.assign({"X-Internal-Key": internalKey()}, opts.headers || {});
  let r;
  try {
    r = await fetch(url, Object.assign({}, opts, {headers}));
  } catch { throw {status: 0}; }
  if (!r.ok) throw {status: r.status, detail: await r.text().catch(() => "")};
  return r;
}
function dot(cls) {
  const s = document.createElement("span");
  s.className = `dot ${cls}`;
  return s;
}

async function renderNodes() {
  if (!internalKey()) { log("pon tu X-Internal-Key para ver nodos", "err"); return; }
  nodesSummary.textContent = "consultando malla…";
  try {
    const map = await (await nodeApi(base() + "/nodes/map")).json();
    const live = map.live || [], dead = map.dead || [];
    nodesSummary.textContent =
      `coordinador v${map.coordinator.version} · ${live.length} vivos · ${dead.length} caídos · ${map.coordinator.objects} archivo(s)`;
    nodesBody.innerHTML = "";
    const row = (n, alive) => {
      const tr = document.createElement("tr");
      const st = document.createElement("span");
      st.className = `st ${alive ? "ok" : "err"}`;
      st.append(dot(alive ? "ok" : "err"), document.createTextNode(alive ? "vivo" : "caído"));
      tr.innerHTML = "<td></td><td class='mono'></td><td></td><td></td><td></td>";
      tr.children[0].textContent = n.node_id;
      tr.children[1].textContent = n.base_url;
      tr.children[2].append(st);
      tr.children[3].textContent = n.files_stored ?? "—";
      tr.children[4].textContent = n.version || "—";
      return tr;
    };
    live.forEach(n => nodesBody.append(row(n, true)));
    dead.forEach(n => nodesBody.append(row(n, false)));
    if (!live.length && !dead.length)
      nodesBody.innerHTML = `<tr><td colspan="5" class="muted">sin nodos registrados</td></tr>`;
    meshBox.innerHTML = "";
    for (const n of live) {
      const line = document.createElement("div");
      line.className = "muted";
      line.textContent = `${n.node_id} sondeando hermanos…`;
      meshBox.append(line);
      try {
        const pr = await nodeApi(`${n.base_url}/peers?refresh=true`);
        const data = await pr.json();
        line.textContent = "";
        const title = document.createElement("strong");
        title.textContent = `${n.node_id} ve: `;
        line.append(title);
        if (!data.peers.length) line.append(document.createTextNode("solo (sin hermanos alcanzables)"));
        for (const p of data.peers) {
          const chip = document.createElement("span");
          chip.className = `st ${p.reachable ? "ok" : "err"}`;
          chip.append(dot(p.reachable ? "ok" : p.status === "degraded" ? "warn" : "err"),
                      document.createTextNode(`${p.node_id}·${p.status || "?"} `));
          line.append(chip);
        }
      } catch (e) {
        line.textContent = `${n.node_id}: no responde (${internalErrText(e.status)})`;
      }
    }
    if (!live.length) meshBox.textContent = "sin nodos vivos que sondear";
    log(`malla: ${live.length} vivos, ${dead.length} caídos`, "ok");
  } catch (e) { log(`nodos falló: ${internalErrText(e.status)}`, "err"); }
}

autoInput.addEventListener("change", () => {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  if (autoInput.checked) {
    autoTimer = setInterval(() => {
      if (apiKey()) refresh().catch(() => {});
      if (internalKey()) renderNodes().catch(() => {});
    }, 10000);
    log("auto-actualizar cada 10s", "ok");
  }
});

$("nodes-btn").addEventListener("click", renderNodes);
$("refresh-btn").addEventListener("click", refresh);
$("test-btn").addEventListener("click", testConnection);

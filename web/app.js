/* Siesta local UI. No framework, no CDN, no network calls except to
   this app's own localhost server. */

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const backend = s.backend === "ollama" ? "Ollama (open-weight models, local)" : `${s.backend} backend`;
    $("#meta").textContent =
      `${backend} · watching ${s.files_watched} file(s) · ${s.files_processed} processed · ` +
      `${s.items_in_pantry} item(s) in the pantry · ${s.tokens.total_tokens} tokens spent`;
  } catch (err) {
    $("#meta").textContent = "cannot reach the local server";
  }
}

async function refreshDigest() {
  try {
    const { digest } = await api("/api/digests/latest");
    if (!digest) return;
    renderDigest(digest);
  } catch (err) { /* the first run has no digest yet */ }
}

function renderDigest(digest) {
  const markdown = digest.markdown || "";
  const lines = markdown.split("\n");
  const html = [];
  let inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { if (inList) { html.push("</ul>"); inList = false; } continue; }
    if (line.startsWith("## ")) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(`<h2>${esc(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      html.push(`<h1>${esc(line.slice(2))}</h1>`);
    } else if (line.startsWith("- ")) {
      if (!inList) { html.push("<ul>"); inList = true; }
      html.push(`<li>${esc(line.slice(2))}</li>`);
    } else if (line.startsWith("---") || line.startsWith("*") || line.startsWith("<sub")) {
      continue;
    } else {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(`<p>${esc(line)}</p>`);
    }
  }
  if (inList) html.push("</ul>");
  const el = $("#digest");
  el.classList.remove("empty");
  el.innerHTML = html.join("\n");
}

async function refreshItems() {
  try {
    const data = await api("/api/items");
    fillList("#use-first", (data.use_first || []).map((i) => `${i.name} — about ${i.expiry_days} day(s) left`));
    fillList("#shopping", (data.shopping_list || []).map((i) => i.name));
    fillList("#pantry", (data.items || []).map((i) =>
      `${i.name}${i.quantity ? ` × ${i.quantity}${i.unit ? " " + i.unit : ""}` : ""}` +
      `${i.expiry_days != null ? ` — ${i.expiry_days}d` : ""}`));
  } catch (err) { /* ignore */ }
}

function fillList(selector, values) {
  const el = $(selector);
  if (!values.length) {
    el.innerHTML = '<li class="muted">—</li>';
    return;
  }
  el.innerHTML = values.map((v) => `<li>${esc(v)}</li>`).join("");
}

async function refreshLedger() {
  try {
    const data = await api("/api/ledger");
    const rows = (data.by_phase || []).map((p) =>
      `<div class="row"><span>${esc(p.phase)} · ${esc(p.model || "local")}</span>` +
      `<span>${p.calls} call(s) · ${p.prompt_tokens + p.eval_tokens} tok · ${p.latency_ms} ms</span></div>`).join("");
    $("#ledger").innerHTML = rows || '<span class="muted">no model calls yet</span>';
    $("#ledger").classList.remove("muted");
  } catch (err) { /* ignore */ }
}

async function runScan() {
  const btn = $("#scan");
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    const report = await api("/api/scan?force=true", { method: "POST" });
    if (report.slept) {
      const el = $("#digest");
      el.classList.remove("empty");
      el.innerHTML = `<h1>🦥 ${esc(report.reason || "Still napping")}</h1>` +
        `<p class="meta">No model was called. That is the point.</p>`;
    } else {
      await refreshDigest();
    }
    await Promise.all([refreshStatus(), refreshItems(), refreshLedger()]);
  } catch (err) {
    $("#digest").classList.remove("empty");
    $("#digest").innerHTML = `<h1>Something went wrong</h1><p>${esc(err.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run a pass";
  }
}

async function runBench() {
  const btn = $("#bench");
  btn.disabled = true;
  btn.textContent = "Measuring…";
  try {
    const s = await api("/api/bench");
    $("#bench-out").classList.remove("muted");
    $("#bench-out").innerHTML = [
      `<div class="row"><span>files</span><span>${s.files}</span></div>`,
      `<div class="row"><span>naive tokens</span><span>${s.naive_tokens}</span></div>`,
      `<div class="row"><span>cascade tokens</span><span>${s.siesta_tokens}</span></div>`,
      `<div class="row"><span>tokens saved</span><span>${s.tokens_saved} (${s.tokens_saved_pct}%)</span></div>`,
      `<div class="row"><span>routed without a model</span><span>${s.routed_by_metadata}/${s.files}</span></div>`,
      `<div class="row"><span>escalations</span><span>${s.escalated}</span></div>`,
    ].join("");
  } catch (err) {
    $("#bench-out").textContent = `benchmark failed: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Measure";
  }
}

function setupDrop() {
  const drop = $("#drop");
  const note = $("#upload-note");
  const upload = async (files) => {
    for (const file of files) {
      // Raw body + filename in the query string: no multipart dependency.
      const res = await fetch(`/api/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      if (!res.ok) {
        note.textContent = `upload failed: ${res.status}`;
        continue;
      }
      const saved = await res.json();
      note.textContent = `saved ${saved.saved} — run a pass to process it`;
    }
  };
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => {
    const files = e.dataTransfer?.files;
    if (files?.length) upload([...files]);
  });
  drop.addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.onchange = () => upload([...input.files]);
    input.click();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("#scan").addEventListener("click", runScan);
  $("#bench").addEventListener("click", runBench);
  setupDrop();
  refreshStatus();
  refreshDigest();
  refreshItems();
  refreshLedger();
});

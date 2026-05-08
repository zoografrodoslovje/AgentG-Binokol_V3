const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
const MAX_GOAL_LENGTH = 100000;
const AGENT_NAMES = ["architect", "coder", "tester", "fixer", "debator"];
const deferredBlockState = new Map();

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text == null ? "" : String(text);
}

function setHtml(id, html) {
  const el = $(id);
  if (el) el.innerHTML = html == null ? "" : String(html);
}

function setOut(id, text) {
  const el = $(id);
  if (el) el.textContent = text == null ? "" : String(text);
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function safeJson(obj) {
  try { return JSON.stringify(obj, null, 2); } catch { return String(obj); }
}

function scheduleDeferredBlockRender(key, render, initialValue) {
  const current = deferredBlockState.get(key) || { version: 0, initialized: false, timer: null };
  if (!current.initialized && initialValue !== undefined) {
    render(initialValue);
    current.initialized = true;
  }
  current.version += 1;
  const version = current.version;
  if (current.timer) clearTimeout(current.timer);
  current.timer = setTimeout(() => {
    requestAnimationFrame(() => {
      const latest = deferredBlockState.get(key);
      if (!latest || latest.version !== version) return;
      render();
    });
  }, 30);
  deferredBlockState.set(key, current);
}

function updateTaskInputMeta() {
  const input = $("taskInput");
  if (!input) return;
  const length = input.value.length;
  setText("taskInputMeta", `${length} / ${MAX_GOAL_LENGTH}`);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${txt}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

let activeTaskId = null;
let activeDir = ".";
let activeQueueTaskId = null;
let activeAgentFilter = null;
let currentView = "overview";
let activeActivityTask = null;
let activeQueueTask = null;

let chatMessages = [];
let chatStreaming = false;
let chatLastAssistantEl = null;
let chatSelectedModel = null;
let chatPrimaryModel = null;
const DEFAULT_OUTPUT_DIR = "C:\\pinokio\\api\\agent_joko\\FINISHED_WORK";
let finishVisibilityInterval = null;
let finishAnimationTimers = [];

function setChatModelHint(text) {
  setText("chatModelHint", text || "Choose a local or fallback cloud model");
}

function clearFinishAnimationTimers() {
  finishAnimationTimers.forEach((timer) => clearTimeout(timer));
  finishAnimationTimers = [];
}

function playFinishAnimation() {
  clearFinishAnimationTimers();
  $("finishBtn")?.classList.remove("is-running", "is-complete");
}

function startFinishPresenceLoop() {
  const shell = $("finishPresence");
  if (!shell || finishVisibilityInterval) return;
  shell.classList.add("is-visible");
}

function showView(view) {
  currentView = view;
  ["viewOverview", "viewQueue", "viewChat", "viewSystem", "viewFailures"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.classList.toggle("active", id === `view${view[0].toUpperCase()}${view.slice(1)}`);
    el.classList.toggle("hidden", id !== `view${view[0].toUpperCase()}${view.slice(1)}`);
  });
}

function setPill(status) {
  const el = $("taskState");
  if (!el) return;
  el.classList.remove("good", "bad", "warn");
  const s = (status || "-").toString();
  el.textContent = s;
  if (s === "running") el.classList.add("warn");
  if (s === "completed") el.classList.add("good");
  if (s === "failed") el.classList.add("bad");
  if (s === "cancelled") el.classList.add("bad");
}

function setPullAgainState(task) {
  const btn = $("pullAgainBtn");
  if (!btn) return;
  if (!task) {
    btn.disabled = true;
    btn.textContent = "Pull again";
    return;
  }
  const rerunnable = ["failed", "completed", "cancelled"].includes(task.status);
  btn.disabled = !rerunnable;
  btn.textContent = task.status === "running" ? "Running..." : "Pull again";
}

function resetTaskStateUi() {
  activeTaskId = null;
  activeActivityTask = null;
  activeQueueTaskId = null;
  activeQueueTask = null;
  activeAgentFilter = null;

  const taskInput = $("taskInput");
  if (taskInput) taskInput.value = "";
  updateTaskInputMeta();

  const taskSelect = $("taskSelect");
  if (taskSelect) taskSelect.innerHTML = `<option value="">(no tasks)</option>`;

  setHtml("activity", `<div class="item muted">No tasks yet. Click Run.</div>`);
  setHtml("queueList", `<div class="item muted">Queue is empty.</div>`);
  setOut("queueGoal", "");
  setOut("queueResult", "");
  setHtml("queueEvents", `<div class="item muted">No task selected.</div>`);
  setHtml("queueMeta", "");
  setText("queueSelected", "-");
  setText("modelName", "-");
  setText("routeInfo", "-");
  setPill("-");
  setPullAgainState(null);
  setAgentLights();
}

function setAgentLights(agentActivity) {
  const activity = agentActivity || {};
  AGENT_NAMES.forEach((agent) => {
    const working = !!activity?.[agent]?.working;
    $$(`.agentLight[data-agent="${agent}"]`).forEach((light) => {
      light.classList.toggle("on", working);
    });
    $$(`.navItem[data-agent="${agent}"]`).forEach((btn) => {
      btn.classList.toggle("working", working);
      btn.setAttribute("aria-label", working ? `${agent} working` : `${agent} idle`);
    });
  });
}

function escapeHtml(value) {
  return (value == null ? "" : String(value))
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function eventHasDetail(event) {
  const msg = (event?.message || "").toLowerCase();
  return !!(
    event?.data?.error ||
    event?.type === "agent_fail" ||
    event?.type === "error" ||
    (event?.agent === "fixer" && msg.includes("failed"))
  );
}

function formatDetailData(data) {
  if (!data || Object.keys(data).length === 0) return "No additional structured data captured.";
  return safeJson(data);
}

function buildEventExplanation(task, event) {
  const error = event?.data?.error || "No explicit error text was captured for this event.";
  const lines = [
    "Summary",
    `${event?.agent || "agent"} hit ${event?.type || "event"} at ${fmtTime(event?.ts || Date.now() / 1000)}.`,
    `${event?.message || "No message was captured."}`,
    "",
    "Why It Failed",
    error,
    "",
    "Task Context",
    `Task: ${task?.id || "-"}`,
    `Workflow: ${task?.workflow || "-"}`,
    `Status: ${task?.status || "-"}`,
    `Goal: ${(task?.goal || "-").toString()}`,
    "",
    "Captured Data",
    formatDetailData(event?.data),
  ];
  const errorText = String(error).toLowerCase();
  if (errorText.includes("timeout")) {
    lines.push("", "Likely Cause", "The fixer timed out before it could finish the healing step.");
  } else if (errorText.includes("ollama") || errorText.includes("model")) {
    lines.push("", "Likely Cause", "The fixer appears to have failed while calling the local model backend.");
  } else if (errorText.includes("context") || errorText.includes("token")) {
    lines.push("", "Likely Cause", "The fixer likely exceeded the available context or token budget.");
  } else if (errorText.includes("traceback") || errorText.includes("exception") || errorText.includes("attribute")) {
    lines.push("", "Likely Cause", "The healing step ran into an application/runtime exception.");
  }
  return lines.join("\n");
}

function openEventModal(task, event) {
  const shell = $("eventModal");
  if (!shell) return;
  const agent = escapeHtml(event?.agent || "agent");
  const eventType = escapeHtml((event?.type || "event").toUpperCase());
  const taskId = escapeHtml(task?.id || "-");
  const workflow = escapeHtml(task?.workflow || "-");
  setHtml(
    "eventModalMeta",
    `<span class="failureAgent"><span class="failureAgentDot ${agent}"></span>${agent}</span><span>${eventType}</span><span>${taskId}</span><span>${workflow}</span><span>${fmtTime(event?.ts || Date.now() / 1000)}</span>`
  );
  setOut("eventModalBody", buildEventExplanation(task, event));
  shell.classList.remove("hidden");
  shell.setAttribute("aria-hidden", "false");
}

function closeEventModal() {
  const shell = $("eventModal");
  if (!shell) return;
  shell.classList.add("hidden");
  shell.setAttribute("aria-hidden", "true");
}

function renderActivityRow(event, eventIndex) {
  const tag = escapeHtml((event.type || "event").toUpperCase());
  const msg = escapeHtml((event.message || "").toString());
  const canView = eventHasDetail(event);
  return `<div class="row"><div class="ts">${fmtTime(event.ts)}</div><div class="tag">${tag}</div><div class="msg">${msg}</div><div class="rowActions">${canView ? `<button class="btn ghost viewBtn" data-event-index="${eventIndex}">View</button>` : ``}</div></div>`;
}

async function refreshOutputSettings() {
  const input = $("outputDir");
  const endpoints = ["/api/settings/output_dir", "/api/settings/output-dir", "/api/output_dir"];
  let lastError = null;
  for (const endpoint of endpoints) {
    try {
      const res = await api(endpoint);
      if (input && document.activeElement !== input) input.value = res.path || "";
      setText("outputResolved", res.resolved_path || "-");
      setText("outputStatus", "Auto-export enabled");
      return res;
    } catch (error) {
      lastError = error;
      if (!String(error?.message || "").startsWith("404")) throw error;
    }
  }
  const fallback = localStorage.getItem("agent_joko_output_dir") || DEFAULT_OUTPUT_DIR;
  if (input && document.activeElement !== input) input.value = fallback;
  setText("outputResolved", fallback);
  setText("outputStatus", "Output API unavailable. Restart dashboard backend.");
  return { path: fallback, resolved_path: fallback, unavailable: true, error: lastError?.message || "Not available" };
}

async function saveOutputSettings(pathOverride = null) {
  const input = $("outputDir");
  const path = (pathOverride ?? input?.value ?? "").trim();
  if (!path) throw new Error("Output path is required.");
  const btn = $("outputSave");
  const prev = btn?.textContent || "Save";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Saving...";
  }
  try {
    const endpoints = ["/api/settings/output_dir", "/api/settings/output-dir", "/api/output_dir"];
    let lastError = null;
    for (const endpoint of endpoints) {
      try {
        const res = await api(endpoint, {
          method: "POST",
          body: JSON.stringify({ path }),
        });
        localStorage.setItem("agent_joko_output_dir", res.path || path);
        if (input) input.value = res.path || path;
        setText("outputResolved", res.resolved_path || path);
        setText("outputStatus", "Saved");
        return res;
      } catch (error) {
        lastError = error;
        if (!String(error?.message || "").startsWith("404")) throw error;
      }
    }
    localStorage.setItem("agent_joko_output_dir", path);
    setText("outputResolved", path);
    setText("outputStatus", "Saved locally only. Restart dashboard backend.");
    return { path, resolved_path: path, unavailable: true, error: lastError?.message || "Not available" };
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }
}

async function refreshFailureLog() {
  const res = await api("/api/agent_failures?limit=120");
  const summary = res.summary || {};
  const items = res.items || [];
  scheduleDeferredBlockRender("failureSummary", () => {
    setHtml(
      "failureSummary",
      AGENT_NAMES.map((agent) => {
        const count = summary?.[agent] ?? 0;
        return `<div class="failureStat"><div class="label">${agent}</div><div class="value">${count}</div></div>`;
      }).join("")
    );
  }, "");
  scheduleDeferredBlockRender("failureList", () => {
    setHtml(
      "failureList",
      items.length
        ? items.map((item) => {
            const agent = (item.agent || "unknown").replaceAll("<", "&lt;");
            const eventType = (item.event_type || "").replaceAll("<", "&lt;");
            const taskId = (item.task_id || "").replaceAll("<", "&lt;");
            const workflow = (item.workflow || "").replaceAll("<", "&lt;");
            const message = (item.message || "").toString().replaceAll("<", "&lt;");
            const error = (item.error || "").toString().replaceAll("<", "&lt;");
            const goal = (item.goal_preview || "").toString().replaceAll("<", "&lt;");
            return `<div class="failureItem">
              <div class="failureMeta">
                <span class="failureAgent"><span class="failureAgentDot ${agent}"></span>${agent}</span>
                <span>${eventType}</span>
                <span>${taskId}</span>
                <span>${workflow}</span>
                <span>${fmtTime(item.ts)}</span>
              </div>
              <div class="failureMsg">${message}</div>
              ${error ? `<div class="failureErr">${error}</div>` : ""}
              ${goal ? `<div class="muted">Goal: ${goal}</div>` : ""}
            </div>`;
          }).join("")
        : `<div class="failureItem muted">No agent failures recorded.</div>`
    );
  }, `<div class="failureItem muted">Loading failure registry...</div>`);
}

async function refreshStatus() {
  const st = await api("/api/status");
  setText("sessionId", st.session_id || "-");
  setText("running", String(!!st.running));
  const qs = st.queue_stats || {};
  setText("queueStats", `${qs.pending ?? 0} pending, ${qs.completed ?? 0} completed`);

  const last = st.last_task || {};
  const routing = last.routing || null;
  setText("modelName", routing?.model || routing?.recommended_model || "-");
  if (routing?.task_type || routing?.complexity) {
    setText("routeInfo", `${routing.task_type || "-"} / ${routing.complexity || "-"}`);
  } else {
    setText("routeInfo", "-");
  }

  const ollama = st.ollama || {};
  const ok = !!ollama.ok;
  const localOk = !!ollama.local_ok;
  const remoteReady = !!ollama.remote_ready;
  const dot = $("ollamaDot");
  if (dot) {
    dot.classList.toggle("ok", ok);
    dot.classList.toggle("bad", !ok);
  }
  if (localOk) {
    const modelCount = Array.isArray(ollama.models) ? ollama.models.length : null;
    setText("ollamaStatus", modelCount == null ? "Local runtime ready" : `Local runtime ready (${modelCount} models)`);
  } else if (remoteReady) {
    setText("ollamaStatus", "Cloud fallback ready");
  } else {
    setText("ollamaStatus", ollama.error ? "Model runtime not reachable (see Status)" : "Model runtime not reachable");
  }

  const statusRaw = safeJson({ ollama, config: st.config || {} });
  const systemRaw = safeJson(st);
  scheduleDeferredBlockRender("statusRaw", () => setOut("statusRaw", statusRaw), "");
  scheduleDeferredBlockRender("systemOut", () => {
    if ($("systemOut")) setOut("systemOut", systemRaw);
  }, "");
  setAgentLights(st.agent_activity);

  const iq = st.inference_queue || {};
  if ($("chatQueue")) {
    setText(
      "chatQueue",
      `${iq.pending ?? 0} pending, ${iq.running ?? 0} running, ${iq.completed ?? 0} done, ${iq.failed ?? 0} failed`
    );
  }
}

async function refreshFiles() {
  setText("filesPath", activeDir);
  const up = $("filesUp");
  if (up) up.disabled = activeDir === "." || !activeDir;
  const res = await api(`/api/files/list?path=${encodeURIComponent(activeDir)}&recursive=false&include_dirs=true`);
  if (!res.success) {
    setText("files", res.error || "Failed to list files");
    return;
  }
  const items = res.files || [];
  scheduleDeferredBlockRender("files", () => {
    setHtml(
      "files",
      items
        .slice(0, 120)
        .map((f) => {
          const rel = (f.relative || f.name || f.path || "").toString();
          const isDir = !!f.is_dir;
          const label = isDir ? `${rel}/` : rel;
          const safe = label.replaceAll("<", "&lt;");
          const enc = encodeURIComponent(rel);
          return `<div class="item fileItem" data-path="${enc}" data-isdir="${isDir ? "1" : "0"}">${safe}</div>`;
        })
        .join("")
    );
  }, `<div class="item muted">Loading files...</div>`);
}

async function refreshMemory() {
  const res = await api("/api/memory/recent?count=15");
  const entries = res.entries || [];
  scheduleDeferredBlockRender("memory", () => {
    setHtml(
      "memory",
      entries
        .map((e) => {
          const preview = (e.content || "").toString().slice(0, 120).replaceAll("<", "&lt;");
          return `<div class="item"><div class="muted">[${e.type}]</div>${preview}</div>`;
        })
        .join("")
    );
  }, `<div class="item muted">Loading memory...</div>`);
}

function chatAdd(role, text) {
  const log = $("chatLog");
  if (!log) return null;
  const row = document.createElement("div");
  row.className = "chatMsg";
  const roleSpan = document.createElement("span");
  roleSpan.className = `chatRole ${role}`;
  roleSpan.textContent = role;
  const textSpan = document.createElement("span");
  textSpan.className = "chatText";
  textSpan.textContent = text || "";
  row.appendChild(roleSpan);
  row.appendChild(textSpan);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return textSpan;
}

function chatSetMeta(text) {
  setText("chatMeta", text || "");
}

async function refreshChatModels() {
  const sel = $("chatModel");
  if (!sel) return;
  try {
    const res = await api("/api/settings/chat_model");
    const models = Array.from(new Set(res.available_models || []));
    const primary = res.model || "";
    const preferred = chatSelectedModel || sel.value || primary;
    chatPrimaryModel = primary;
    const opts = models
      .map((m) => {
        const safe = escapeHtml(m);
        const suffix = m === primary ? "  | default" : "";
        return `<option value="${safe}">${safe}${suffix}</option>`;
      })
      .join("");
    sel.innerHTML = opts || `<option value="${escapeHtml(primary || "")}">${escapeHtml(primary || "(no models)")}</option>`;

    const nextValue =
      (preferred && models.includes(preferred) && preferred) ||
      (primary && models.includes(primary) && primary) ||
      models[0] ||
      "";

    sel.value = nextValue;
    chatSelectedModel = nextValue || null;
    const hint = chatPrimaryModel
      ? (nextValue === chatPrimaryModel ? `Default model: ${chatPrimaryModel}` : `Default: ${chatPrimaryModel} | Selected: ${nextValue}`)
      : (nextValue ? `Selected: ${nextValue}` : "Choose a local or fallback cloud model");
    setChatModelHint(hint);
    const saveBtn = $("chatModelSave");
    if (saveBtn) saveBtn.disabled = !nextValue || nextValue === chatPrimaryModel;
  } catch (e) {
    sel.innerHTML = `<option value="">(Ollama not reachable)</option>`;
    chatSelectedModel = null;
    chatPrimaryModel = null;
    setChatModelHint("No reachable model providers");
    const saveBtn = $("chatModelSave");
    if (saveBtn) saveBtn.disabled = true;
  }
}

async function saveChatModel() {
  const sel = $("chatModel");
  const saveBtn = $("chatModelSave");
  const model = (sel?.value || "").trim();
  if (!model) return;
  const prev = saveBtn?.textContent || "Set Default";
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
  }
  try {
    const res = await api("/api/settings/chat_model", {
      method: "POST",
      body: JSON.stringify({ model }),
    });
    chatPrimaryModel = res.model || model;
    chatSelectedModel = chatPrimaryModel;
    await refreshChatModels();
    chatSetMeta(`Default chat model saved: ${chatPrimaryModel}`);
  } finally {
    if (saveBtn) saveBtn.textContent = prev;
  }
}

async function refreshInferenceQueueList() {
  const box = $("chatQueueList");
  if (!box) return;
  const res = await api("/api/inference_queue?limit=50");
  const items = res.items || [];
  scheduleDeferredBlockRender("chatQueueList", () => {
    setHtml(
      "chatQueueList",
      items
        .map((it) => {
          const id = (it.id || "").replaceAll("<", "&lt;");
          const st = (it.status || "").replaceAll("<", "&lt;");
          const model = (it.model || "").replaceAll("<", "&lt;");
          const canCancel = st === "queued";
          return `<div class="queueRow queue4" data-id="${id}"><div class="id">${id}</div><div class="status">${st}</div><div class="wf">${model}</div>${
            canCancel ? `<div><button class="btn ghost miniCancel" data-id="${id}">Cancel</button></div>` : `<div></div>`
          }</div>`;
        })
        .join("") || `<div class="item muted">Queue is empty.</div>`
    );
  }, `<div class="item muted">Loading queue...</div>`);
}

async function sendChat() {
  if (chatStreaming) return;
  const input = $("chatInput");
  const sel = $("chatModel");
  const prompt = (input?.value || "").trim();
  if (!prompt) return;
  const model = sel?.value || "";
  chatSelectedModel = model || null;

  chatMessages.push({ role: "user", content: prompt });
  chatAdd("user", prompt);
  input.value = "";

  // Keep context small for lightweight models
  chatMessages = chatMessages.slice(-20);

  chatLastAssistantEl = chatAdd("assistant", "");
  chatSetMeta("Streaming...");
  chatStreaming = true;
  const started = performance.now();

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: chatMessages }),
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${txt}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let assistantText = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        let evt;
        try { evt = JSON.parse(line); } catch { continue; }
        if (evt.type === "queued") {
          chatSetMeta(`Queued offline: ${evt.id}`);
          refreshInferenceQueueList().catch(() => {});
          return;
        }
        if (evt.type === "delta") {
          assistantText += evt.content || "";
          if (chatLastAssistantEl) chatLastAssistantEl.textContent = assistantText;
        }
        if (evt.type === "error") {
          chatSetMeta(`Error: ${evt.error || "unknown"}`);
        }
        if (evt.type === "done") {
          assistantText = evt.content || assistantText;
          if (chatLastAssistantEl) chatLastAssistantEl.textContent = assistantText;
          const usage = evt.usage || {};
          const ms = Math.round(performance.now() - started);
          const toks = [usage.prompt_eval_count, usage.eval_count].every((x) => x != null)
            ? `tokens ${usage.prompt_eval_count}+${usage.eval_count}`
            : "";
          chatSetMeta(`Done in ${ms}ms ${toks}`.trim());
          refreshInferenceQueueList().catch(() => {});
        }
      }
    }

    if (assistantText) {
      chatMessages.push({ role: "assistant", content: assistantText });
      chatMessages = chatMessages.slice(-20);
    }
  } finally {
    chatStreaming = false;
  }
}

async function refreshActivity() {
  const tasks = await api("/api/tasks");
  const list = tasks.tasks || [];
  if (!activeTaskId) activeTaskId = list[0]?.id || null;
  renderTaskSelect(list);
  if (!activeTaskId) {
    scheduleDeferredBlockRender("activity", () => {
      setHtml("activity", `<div class="item muted">No tasks yet. Click Run.</div>`);
    }, `<div class="item muted">Loading activity...</div>`);
    setPill("-");
    setAgentLights();
    setPullAgainState(null);
    return;
  }
  const t = await api(`/api/tasks/${activeTaskId}`);
  activeActivityTask = t;
  const events = t.events || [];
  setPill(t.status);
  setPullAgainState(t);

  // Routing summary from task (preferred over status cache).
  setText("modelName", t.routing?.model || t.routing?.recommended_model || "-");
  if (t.routing?.task_type || t.routing?.complexity) {
    setText("routeInfo", `${t.routing.task_type || "-"} / ${t.routing.complexity || "-"}`);
  } else {
    setText("routeInfo", "-");
  }

  const filtered = activeAgentFilter ? events.filter((e) => e.agent === activeAgentFilter) : events;
  scheduleDeferredBlockRender("activity", () => {
    setHtml(
      "activity",
      filtered
        .slice(-40)
        .map((e, idx) => renderActivityRow(e, idx))
        .join("")
    );
  }, `<div class="item muted">Loading activity...</div>`);
}

function renderTaskSelect(tasks) {
  const sel = $("taskSelect");
  if (!sel) return;
  const opts = tasks
    .slice(0, 50)
    .map((t) => {
      const label = `${t.id} • ${t.status}`;
      const selected = t.id === activeTaskId ? "selected" : "";
      return `<option value="${t.id}" ${selected}>${label}</option>`;
    })
    .join("");
  sel.innerHTML = opts || `<option value="">(no tasks)</option>`;
}

async function runTask() {
  const goal = $("taskInput").value.trim();
  if (!goal) return;
  if (goal.length > MAX_GOAL_LENGTH) {
    throw new Error(`Task is too long: ${goal.length} characters. Maximum allowed is ${MAX_GOAL_LENGTH}.`);
  }
  const workflow = $("workflow").value;
  const btn = $("runBtn");
  const prev = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = workflow === "manual" ? "Queued" : "Running...";
  }
  try {
    const res = await api("/api/execute", { method: "POST", body: JSON.stringify({ goal, workflow }) });
    activeTaskId = res.task_id;
    $("taskInput").blur();
    await refreshActivity();
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prev || "Run";
    }
  }
}

async function stopAgents() {
  const btn = $("stopAgentsBtn");
  const prev = btn?.textContent || "Stop the Agents";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Stopping...";
  }
  try {
    await api("/api/agents/stop", { method: "POST" });
    await Promise.allSettled([refreshActivity(), refreshStatus(), refreshQueueView()]);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }
}

async function pullAgainTask() {
  if (!activeTaskId) return;
  const btn = $("pullAgainBtn");
  const prev = btn?.textContent || "Pull again";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Pulling...";
  }
  try {
    const res = await api(`/api/tasks/${encodeURIComponent(activeTaskId)}/retry`, { method: "POST" });
    activeTaskId = res.task_id || activeTaskId;
    await refreshActivity();
    await refreshStatus();
  } finally {
    if (btn) btn.textContent = prev;
  }
}

async function clearTaskState() {
  const btn = $("clearBtn");
  const prev = btn?.textContent || "Clear";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Clearing...";
  }
  try {
    await api("/api/tasks/clear", { method: "POST" });
    resetTaskStateUi();
    await Promise.allSettled([refreshStatus(), refreshOutputSettings()]);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }
}

async function runPython() {
  const code = $("pyCode").value.trim();
  if (!code) return;
  const btn = $("pyRun");
  if (btn) btn.disabled = true;
  const res = await api("/api/tools/python", { method: "POST", body: JSON.stringify({ code }) });
  if (res.success) {
    const body = (res.stdout || "") + (res.stderr ? "\n" + res.stderr : "");
    setOut("pyOut", body || "(no output)");
  } else {
    const details = [
      "Python execution failed.",
      res.error ? `Error: ${res.error}` : null,
      res.stderr ? `Stderr:\n${res.stderr}` : null,
      res.stdout ? `Stdout:\n${res.stdout}` : null,
    ].filter(Boolean).join("\n");
    setOut("pyOut", details);
  }
  if (btn) btn.disabled = false;
}

async function previewFile(relPath) {
  if (!relPath) return;
  const full = activeDir === "." ? relPath : `${activeDir}/${relPath}`;
  const res = await api(`/api/files/read?path=${encodeURIComponent(full)}&limit=200&offset=0`);
  if (!res.success) {
    setOut("filePreview", res.error || "Failed to read file");
    return;
  }
  setOut("filePreview", res.content || "(empty)");
}

async function searchMemory() {
  const q = ($("memQuery")?.value || "").trim();
  if (!q) return refreshMemory();
  const res = await api(`/api/memory/search?q=${encodeURIComponent(q)}&max_results=30`);
  const entries = res.entries || [];
  scheduleDeferredBlockRender("memory", () => {
    setHtml(
      "memory",
      entries
        .map((e) => {
          const preview = (e.content || "").toString().slice(0, 200).replaceAll("<", "&lt;");
          return `<div class="item"><div class="muted">[${e.type}]</div>${preview}</div>`;
        })
        .join("")
    );
  }, `<div class="item muted">Searching memory...</div>`);
}

function bind() {
  $("runBtn")?.addEventListener("click", () => runTask().catch((e) => alert(e.message)));
  $("stopAgentsBtn")?.addEventListener("click", () => stopAgents().catch((e) => alert(e.message)));
  $("pullAgainBtn")?.addEventListener("click", () => pullAgainTask().catch((e) => alert(e.message)));
  $("finishBtn")?.addEventListener("click", () => playFinishAnimation());
  $("clearBtn")?.addEventListener("click", () => clearTaskState().catch((e) => alert(e.message)));
  $("pyRun")?.addEventListener("click", () => runPython().catch((e) => alert(e.message)));
  $("memSearch")?.addEventListener("click", () => searchMemory().catch((e) => alert(e.message)));
  $("memRefresh")?.addEventListener("click", () => refreshMemory().catch((e) => alert(e.message)));
  $("filesRefresh")?.addEventListener("click", () => refreshFiles().catch((e) => alert(e.message)));
  $("outputSave")?.addEventListener("click", () => saveOutputSettings().catch((e) => alert(e.message)));
  $("outputUseCurrent")?.addEventListener("click", () => {
    const nextPath = DEFAULT_OUTPUT_DIR;
    if ($("outputDir")) $("outputDir").value = nextPath;
    saveOutputSettings(nextPath).catch((e) => alert(e.message));
  });
  $("chatSend")?.addEventListener("click", () => sendChat().catch((e) => alert(e.message)));
  $("chatModelSave")?.addEventListener("click", () => saveChatModel().catch((e) => alert(e.message)));
  $("chatModel")?.addEventListener("change", (e) => {
    chatSelectedModel = e.target.value || null;
    const selected = chatSelectedModel || "";
    const saveBtn = $("chatModelSave");
    if (saveBtn) saveBtn.disabled = !selected || selected === chatPrimaryModel;
    const hint = chatPrimaryModel
      ? (selected === chatPrimaryModel ? `Default model: ${chatPrimaryModel}` : `Default: ${chatPrimaryModel} | Selected: ${selected}`)
      : (selected ? `Selected: ${selected}` : "Choose a local or fallback cloud model");
    setChatModelHint(hint);
  });
  $("chatClear")?.addEventListener("click", () => {
    chatMessages = [];
    chatLastAssistantEl = null;
    chatSetMeta("");
    setHtml("chatLog", "");
  });
  $("chatQueueRefresh")?.addEventListener("click", () => refreshInferenceQueueList().catch((e) => alert(e.message)));
  $("chatInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendChat().catch((err) => alert(err.message));
  });
  $("filesUp")?.addEventListener("click", () => {
    if (activeDir === "." || !activeDir) return;
    const parts = activeDir.split("/").filter(Boolean);
    parts.pop();
    activeDir = parts.length ? parts.join("/") : ".";
    refreshFiles().catch((e) => alert(e.message));
  });
  $("taskSelect")?.addEventListener("change", (e) => {
    const id = e.target.value;
    activeTaskId = id || null;
    refreshActivity().catch(() => {});
  });
  $("activity")?.addEventListener("click", (e) => {
    const btn = e.target.closest?.(".viewBtn");
    if (!btn || !activeActivityTask) return;
    const visibleEvents = (activeAgentFilter
      ? (activeActivityTask.events || []).filter((item) => item.agent === activeAgentFilter)
      : (activeActivityTask.events || [])
    ).slice(-40);
    const event = visibleEvents[Number(btn.dataset.eventIndex)];
    if (!event) return;
    openEventModal(activeActivityTask, event);
  });
  $("queueEvents")?.addEventListener("click", (e) => {
    const btn = e.target.closest?.(".viewBtn");
    if (!btn || !activeQueueTask) return;
    const visibleEvents = (activeQueueTask.events || []).slice(-120);
    const event = visibleEvents[Number(btn.dataset.eventIndex)];
    if (!event) return;
    openEventModal(activeQueueTask, event);
  });
  $("queueRefresh")?.addEventListener("click", () => refreshQueueView().catch((e) => alert(e.message)));
  $("queueStart")?.addEventListener("click", () => startQueueTask().catch((e) => alert(e.message)));
  $("queueCancel")?.addEventListener("click", () => cancelQueueTask().catch((e) => alert(e.message)));
  $("queueRetry")?.addEventListener("click", () => retryQueueTask().catch((e) => alert(e.message)));
  $("systemRefresh")?.addEventListener("click", () => refreshStatus().catch((e) => alert(e.message)));
  $("failureRefresh")?.addEventListener("click", () => refreshFailureLog().catch((e) => alert(e.message)));
  $("failureClear")?.addEventListener("click", async () => {
    await api("/api/agent_failures/clear", { method: "POST" });
    await refreshFailureLog();
  });
  $("eventModalClose")?.addEventListener("click", () => closeEventModal());
  $("eventModalBackdrop")?.addEventListener("click", () => closeEventModal());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeEventModal();
  });

  $("queueList")?.addEventListener("click", (e) => {
    const row = e.target.closest?.(".queueRow");
    if (!row) return;
    activeQueueTaskId = row.dataset.id || null;
    refreshQueueSelected().catch(() => {});
  });

  $("taskInput")?.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      runTask().catch((err) => alert(err.message));
    }
  });
  $("taskInput")?.addEventListener("input", () => updateTaskInputMeta());

  $("files")?.addEventListener("click", (e) => {
    const item = e.target.closest?.(".fileItem");
    if (!item) return;
    const isDir = item.dataset.isdir === "1";
    const rel = decodeURIComponent(item.dataset.path || "");
    if (isDir) {
      activeDir = activeDir === "." ? rel : `${activeDir}/${rel}`;
      setOut("filePreview", "");
      refreshFiles().catch(() => {});
      return;
    }
    previewFile(rel).catch((err) => alert(err.message));
  });

  $$(".navItem").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".navItem").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view || "overview";
      activeAgentFilter = btn.dataset.agent || null;
      if (view === "queue") {
        showView("queue");
        refreshQueueView().catch(() => {});
        return;
      }
      if (view === "chat") {
        showView("chat");
        refreshChatModels().catch(() => {});
        refreshInferenceQueueList().catch(() => {});
        return;
      }
      if (view === "status") {
        showView("system");
        refreshStatus().catch(() => {});
        return;
      }
      if (view === "failures") {
        showView("failures");
        refreshFailureLog().catch(() => {});
        return;
      }
      showView("overview");
      const target = btn.dataset.target;
      const el = target ? document.getElementById(target) : null;
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  $("chatQueueList")?.addEventListener("click", async (e) => {
    const btn = e.target.closest?.(".miniCancel");
    if (!btn) return;
    const id = btn.dataset.id;
    if (!id) return;
    await api(`/api/inference_queue/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    await refreshInferenceQueueList();
    await refreshStatus();
  });
}

async function refreshQueueView() {
  const tasks = await api("/api/tasks");
  const list = tasks.tasks || [];
  if (!activeQueueTaskId || !list.some((item) => item.id === activeQueueTaskId)) {
    activeQueueTaskId = list[0]?.id || null;
  }

  scheduleDeferredBlockRender("queueList", () => {
    setHtml(
      "queueList",
      list
        .map((t) => {
          const active = t.id === activeQueueTaskId ? "active" : "";
          const safeId = (t.id || "").replaceAll("<", "&lt;");
          const safeStatus = (t.status || "").replaceAll("<", "&lt;");
          const safeWf = (t.workflow || "").replaceAll("<", "&lt;");
          const safePriority = (t.priority || "normal").replaceAll("<", "&lt;");
          return `<div class="queueRow ${active}" data-id="${safeId}"><div class="id">${safeId}</div><div class="status">${safeStatus}</div><div class="wf">${safeWf}</div><div class="wf">${safePriority}</div></div>`;
        })
        .join("") || `<div class="item muted">No tasks.</div>`
    );
  }, `<div class="item muted">Loading tasks...</div>`);

  await refreshQueueSelected();
}

function renderQueueMeta(task) {
  const artifacts = Array.isArray(task?.result?.artifacts) ? task.result.artifacts : [];
  const items = [
    ["Queue ID", task?.queue_id || "-"],
    ["Priority", task?.priority || "-"],
    ["Source", task?.source || "-"],
    ["Dependencies", task?.dependencies?.length ? task.dependencies.join(", ") : "none"],
    ["Retry Of", task?.retry_of || "-"],
    ["Artifacts", artifacts.length ? String(artifacts.length) : "0"],
  ];
  scheduleDeferredBlockRender("queueMeta", () => {
    setHtml(
      "queueMeta",
      items
        .map(([label, value]) => {
          const safeLabel = escapeHtml(label);
          const safeValue = escapeHtml(value);
          return `<div class="queueMetaItem"><div class="label">${safeLabel}</div><div class="value">${safeValue}</div></div>`;
        })
        .join("")
    );
  }, "");
}

async function refreshQueueSelected() {
  if (!activeQueueTaskId) {
    setText("queueSelected", "-");
    scheduleDeferredBlockRender("queueMeta", () => setHtml("queueMeta", ""), "");
    scheduleDeferredBlockRender("queueGoal", () => setOut("queueGoal", ""), "");
    scheduleDeferredBlockRender("queueEvents", () => setHtml("queueEvents", ""), "");
    scheduleDeferredBlockRender("queueResult", () => setOut("queueResult", ""), "");
    if ($("queueStart")) $("queueStart").disabled = true;
    if ($("queueCancel")) $("queueCancel").disabled = true;
    if ($("queueRetry")) $("queueRetry").disabled = true;
    return;
  }
  const t = await api(`/api/tasks/${activeQueueTaskId}`);
  activeQueueTask = t;
  if ($("queueStart")) $("queueStart").disabled = !t.can_start;
  if ($("queueCancel")) $("queueCancel").disabled = !t.can_cancel;
  if ($("queueRetry")) $("queueRetry").disabled = !t.can_retry;
  setText("queueSelected", `${t.id} | ${t.status} | ${t.workflow} | ${t.priority || "normal"}`);
  renderQueueMeta(t);
  scheduleDeferredBlockRender("queueGoal", () => setOut("queueGoal", t.goal || ""), "");
  const events = t.events || [];
  scheduleDeferredBlockRender("queueEvents", () => {
    setHtml(
      "queueEvents",
      events
        .slice(-120)
        .map((e, idx) => renderActivityRow(e, idx))
        .join("")
    );
  }, `<div class="item muted">Loading events...</div>`);
  scheduleDeferredBlockRender(
    "queueResult",
    () => setOut("queueResult", safeJson(t.result || { error: t.error || null, routing: t.routing || null })),
    ""
  );
}

async function startQueueTask() {
  if (!activeQueueTaskId) return;
  await api(`/api/tasks/${activeQueueTaskId}/start`, { method: "POST" });
  await refreshQueueView();
}

async function cancelQueueTask() {
  if (!activeQueueTaskId) return;
  await api(`/api/tasks/${activeQueueTaskId}/cancel`, { method: "POST" });
  await refreshQueueView();
}

async function retryQueueTask() {
  if (!activeQueueTaskId) return;
  const res = await api(`/api/tasks/${activeQueueTaskId}/retry`, { method: "POST" });
  activeQueueTaskId = res.task_id || activeQueueTaskId;
  await refreshQueueView();
}

async function refreshAll() {
  if (currentView === "system") return refreshStatus();
  if (currentView === "queue") return refreshQueueView();
  if (currentView === "failures") return refreshFailureLog();
  if (currentView === "chat") return Promise.allSettled([refreshStatus(), refreshChatModels(), refreshInferenceQueueList()]);
  await Promise.allSettled([refreshStatus(), refreshFiles(), refreshMemory(), refreshActivity(), refreshOutputSettings()]);
}

bind();
updateTaskInputMeta();
refreshAll();
setInterval(() => refreshAll().catch(() => {}), 2500);

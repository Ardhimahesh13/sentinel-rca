(() => {
  "use strict";

  // ---------- API base: relative when served by FastAPI, else localhost:8000 ----------
  const isFile = location.protocol === "file:";
  const isOtherDevServer =
    ["localhost", "127.0.0.1"].includes(location.hostname) &&
    location.port !== "" && location.port !== "8000";
  const API = isFile || isOtherDevServer ? "http://127.0.0.1:8000" : "";

  // ---------- Samples ----------
  const SAMPLES = [
    { label: "PostgreSQL Pool Exhaustion (P1)", log:
`2026-11-24 02:14:07 ERROR [orders-api] FATAL: remaining connection slots are reserved for non-replication superuser connections
2026-11-24 02:14:07 ERROR [orders-api] psycopg2.OperationalError: connection pool exhausted (max=50, in_use=50, waiting=212)
2026-11-24 02:14:09 WARN  [orders-api] checkout latency p99=14.2s (SLO 800ms)
2026-11-24 02:14:12 ERROR [payments-api] could not obtain connection from pool within 30s
2026-11-24 02:14:15 ALERT pg_stat_activity: 198 sessions "idle in transaction" older than 10 min
2026-11-24 02:14:20 ERROR HTTP 503 rate 41% on /v1/checkout` },
    { label: "Nginx 502 Upstream Timeout", log:
`2026/11/24 11:03:41 [error] 2217#2217: *88431 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 10.2.4.18, server: api.acme.io, request: "GET /v1/reports/export HTTP/1.1", upstream: "http://10.0.3.21:8080/v1/reports/export"
2026/11/24 11:03:44 [error] 2217#2217: *88502 connect() failed (111: Connection refused) while connecting to upstream, upstream: "http://10.0.3.22:8080"
2026/11/24 11:03:50 [warn] 2217#2217: *88610 upstream server temporarily disabled
10.2.4.18 - - [24/Nov/2026:11:03:41 +0000] "GET /v1/reports/export" 502 157 "-" "Mozilla/5.0"
Alert: 502 rate 23% for 6 minutes on api.acme.io` },
    { label: "JWT 401 Key Rotation Spike", log:
`2026-11-24T08:00:03Z auth-gateway WARN  JWT verification failed: signature mismatch kid=2026-10-key
2026-11-24T08:00:03Z auth-gateway ERROR 401 Unauthorized POST /v1/session (reason=invalid_signature)
2026-11-24T08:00:10Z auth-gateway INFO  JWKS cache refreshed at 2026-11-24T07:30:00Z (ttl=24h)
2026-11-24T08:00:14Z identity-svc INFO  signing key rotated: new kid=2026-11-key at 07:58:41Z
2026-11-24T08:01:00Z metrics 401 rate jumped 0.2% -> 38% within 2 minutes
2026-11-24T08:01:22Z mobile-bff WARN  token validation failed for 14,203 active sessions` },
    { label: "Docker OOMKilled (Exit 137)", log:
`Nov 24 05:41:12 node-7 kernel: Memory cgroup out of memory: Killed process 31877 (java) total-vm:6291456kB, anon-rss:2097012kB
Nov 24 05:41:12 node-7 dockerd: container 9f3a1c2b7d10 (ingest-worker) exited with code 137 (OOMKilled=true)
Nov 24 05:41:15 node-7 kubelet: Back-off restarting failed container ingest-worker (CrashLoopBackOff)
$ docker inspect ingest-worker --format '{{.HostConfig.Memory}}'
2147483648
ingest-worker: heap usage 1.96GiB / limit 2.00GiB before kill, restarts=9 in 40m` },
  ];

  // ---------- DOM helpers ----------
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const show = (n, on = true) => { n.hidden = !on; };
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const dom = {
    rawLog: $("rawLog"), analyze: $("analyzeBtn"), reset: $("resetBtn"), charCount: $("charCount"),
    samples: $("samples"), error: $("errorBox"), pipeCard: $("pipelineCard"), results: $("results"),
    gate: $("gate"), reportCard: $("reportCard"), report: $("report"),
    traceLog: $("traceLog"), traceCount: $("traceCount"),
    incId: $("incId"), thrId: $("thrId"),
  };

  // ---------- State ----------
  const NODES = ["triage", "retrieve_runbooks", "parse_signals", "rca_synthesis", "safety_critic", "human"];
  const EDGES = { e1: ["retrieve_runbooks", "parse_signals"], e2: ["rca_synthesis"], e3: ["safety_critic"], e4: ["human"] };
  const nodeState = {};
  let S = {};              // merged incident data
  let threadId = null;
  let running = false;
  let controller = null;
  const seenTrace = new Set();

  // ---------- Health ----------
  async function ping() {
    const box = $("status"), txt = $("statusText");
    try {
      const r = await fetch(API + "/health", { cache: "no-store" });
      const j = await r.json();
      if (!r.ok || j.status !== "ok") throw new Error();
      box.className = "status ok"; txt.textContent = (j.app || "Backend") + " online";
    } catch {
      box.className = "status down"; txt.textContent = "Backend offline";
    }
  }

  // ---------- Pipeline ----------
  function setNode(id, state) {
    nodeState[id] = state;
    const n = $("n-" + id);
    n.classList.remove("active", "done", "error");
    if (state) n.classList.add(state);
    refreshEdges();
  }
  function refreshEdges() {
    for (const [eid, targets] of Object.entries(EDGES)) {
      const e = $(eid);
      const states = targets.map((t) => nodeState[t]);
      e.classList.remove("flow", "done");
      if (states.includes("active")) e.classList.add("flow");
      else if (states.every((s) => s === "done")) e.classList.add("done");
    }
  }
  function resetPipeline() {
    NODES.forEach((n) => { nodeState[n] = ""; $("n-" + n).className = "node"; });
    refreshEdges();
  }
  function advance(node) {
    // called when a node finishes
    setNode(node, "done");
    if (node === "triage") { setNode("retrieve_runbooks", "active"); setNode("parse_signals", "active"); }
    if ((node === "retrieve_runbooks" || node === "parse_signals") &&
        nodeState.retrieve_runbooks === "done" && nodeState.parse_signals === "done") setNode("rca_synthesis", "active");
    if (node === "rca_synthesis") setNode("safety_critic", "active");
  }

  // ---------- Trace ----------
  function trace(msg, tag) {
    const d = el("div");
    const t = new Date().toLocaleTimeString([], { hour12: false });
    d.append(document.createTextNode(t + "  "));
    if (tag) { const em = el("em", null, "[" + tag + "] "); d.append(em); }
    d.append(document.createTextNode(msg));
    dom.traceLog.append(d);
    dom.traceLog.scrollTop = dom.traceLog.scrollHeight;
    dom.traceCount.textContent = dom.traceLog.children.length + " events";
  }
  function traceList(list) {
    if (!Array.isArray(list)) return;
    list.forEach((line) => { if (!seenTrace.has(line)) { seenTrace.add(line); trace(String(line)); } });
  }

  // ---------- Rendering ----------
  function sevClass(sev) {
    const s = String(sev || "").toLowerCase();
    if (/p1|crit|sev ?1/.test(s)) return "p1";
    if (/p2|high|sev ?2/.test(s)) return "p2";
    if (/p3|med|sev ?3/.test(s)) return "p3";
    return "";
  }
  const empty = (msg) => el("p", "empty", msg);

  function copyText(text, btn, label = "Copy") {
    const done = () => { btn.textContent = "Copied ✓"; setTimeout(() => (btn.textContent = label), 1400); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    } else fallbackCopy(text, done);
  }
  function fallbackCopy(text, done) {
    const ta = el("textarea"); ta.value = text; ta.style.cssText = "position:fixed;opacity:0";
    document.body.append(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch { /* ignore */ }
    ta.remove();
  }

  function renderResults() {
    const hasAny = ["severity", "domain", "triage_summary", "parsed_signals", "retrieved_runbooks", "root_cause", "remediation_steps", "proposed_commands"]
      .some((k) => S[k] && (!Array.isArray(S[k]) || S[k].length));
    show(dom.results, hasAny);

    // triage
    const pills = $("triagePills"); pills.replaceChildren();
    if (S.severity) pills.append(el("span", "badge " + sevClass(S.severity), S.severity));
    if (S.domain) pills.append(el("span", "badge dom", S.domain));
    $("triageSummary").textContent = S.triage_summary || "";
    if (!S.triage_summary && !S.severity) $("triageSummary").textContent = "Waiting for triage…";

    // signals
    const sg = $("signals"); sg.replaceChildren();
    const p = S.parsed_signals;
    if (p && typeof p === "object") {
      const dl = el("dl", "kv");
      const add = (k, v) => { dl.append(el("dt", null, k)); const dd = el("dd"); dd.append(v); dl.append(dd); };
      add("Error type", document.createTextNode(p.error_type ?? "—"));
      add("Affected service", document.createTextNode(p.affected_service ?? "—"));
      const ind = p.key_indicators;
      const tags = el("div", "tags");
      (Array.isArray(ind) ? ind : ind ? [ind] : []).forEach((i) => tags.append(el("span", null, typeof i === "string" ? i : JSON.stringify(i))));
      add("Key indicators", tags.children.length ? tags : document.createTextNode("—"));
      sg.append(dl);
    } else sg.append(empty("Waiting for log parser…"));

    // runbooks
    const rb = $("runbooks"); rb.replaceChildren();
    if (Array.isArray(S.retrieved_runbooks) && S.retrieved_runbooks.length) {
      S.retrieved_runbooks.forEach((r) => {
        const row = el("div", "rb"), head = el("div", "rb-head");
        head.append(el("b", null, r.title || r.id || "Runbook"));
        const sc = Number(r.score);
        const label = isNaN(sc) ? "n/a" : sc <= 1 ? (sc * 100).toFixed(0) + "% match" : sc.toFixed(2);
        head.append(el("span", "badge ok", label));
        row.append(head);
        if (r.domain) row.append(el("span", "badge dom", r.domain));
        if (r.text) row.append(el("p", null, r.text));
        rb.append(row);
      });
    } else rb.append(empty("Waiting for runbook retrieval…"));

    // root cause
    $("rootCause").textContent = S.root_cause || "Waiting for RCA synthesis…";

    // steps
    const st = $("steps"); st.replaceChildren();
    if (Array.isArray(S.remediation_steps) && S.remediation_steps.length)
      S.remediation_steps.forEach((s) => st.append(el("li", null, s)));
    else { const li = el("li", "empty", "Waiting for remediation plan…"); li.style.counterIncrement = "none"; st.append(li); st.classList.add("pending"); }

    // commands
    const cm = $("commands"); cm.replaceChildren();
    if (Array.isArray(S.proposed_commands) && S.proposed_commands.length) {
      S.proposed_commands.forEach((c) => {
        const box = el("div", "cmd"), code = el("code", null, c), b = el("button", "copy", "Copy");
        b.type = "button"; b.addEventListener("click", () => copyText(c, b));
        box.append(code, b); cm.append(box);
      });
    } else cm.append(empty("Waiting for proposed commands…"));
  }

  function renderGate() {
    show(dom.gate, true);
    const ok = S.safety_approved === true;
    const badge = $("safetyBadge");
    badge.className = "badge " + (S.safety_approved === null || S.safety_approved === undefined ? "" : ok ? "ok" : "bad");
    badge.textContent = S.safety_approved == null ? "Safety review pending" : ok ? "✓ Safety approved" : "⚠ Safety flagged";
    $("safetyFeedback").textContent = S.safety_feedback || "No feedback from the Safety Critic.";
    $("approveBtn").disabled = false; $("rejectBtn").disabled = false;
  }

  // tiny, safe markdown: headings, bullets, bold, inline code
  function renderMarkdown(md) {
    const inline = (t) => escapeHtml(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    let html = "", list = false;
    String(md).split(/\r?\n/).forEach((line) => {
      const li = line.match(/^\s*[-*]\s+(.*)/), h = line.match(/^(#{1,4})\s+(.*)/);
      if (li) { if (!list) { html += "<ul>"; list = true; } html += "<li>" + inline(li[1]) + "</li>"; return; }
      if (list) { html += "</ul>"; list = false; }
      if (h) html += "<h" + (h[1].length < 3 ? 3 : 4) + ">" + inline(h[2]) + "</h" + (h[1].length < 3 ? 3 : 4) + ">";
      else if (line.trim()) html += "<p>" + inline(line) + "</p>";
    });
    return html + (list ? "</ul>" : "");
  }
  function renderReport() {
    if (!S.final_report) return;
    dom.report.innerHTML = renderMarkdown(S.final_report);
    show(dom.reportCard, true);
    dom.reportCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showError(msg) {
    dom.error.textContent = msg; show(dom.error, true);
  }

  // ---------- Applying server data ----------
  function mergeData(data) {
    if (!data || typeof data !== "object") return;
    for (const [k, v] of Object.entries(data)) {
      if (k === "agent_trace") { traceList(v); continue; }
      if (v !== undefined) S[k] = v;
    }
  }

  function applyFinal(resp) {
    mergeData(resp);
    renderResults();
    if (resp.status === "awaiting_approval") {
      ["triage", "retrieve_runbooks", "parse_signals", "rca_synthesis", "safety_critic"].forEach((n) => (nodeState[n] = "done"));
      NODES.slice(0, 5).forEach((n) => setNode(n, "done"));
      setNode("human", "active");
      renderGate();
    } else {
      NODES.forEach((n) => setNode(n, "done"));
      show(dom.gate, false);
      renderReport();
    }
  }

  // ---------- SSE over fetch ----------
  function handleEvent(type, data) {
    switch (type) {
      case "started":
        threadId = data.thread_id; S.incident_id = data.incident_id; S.thread_id = data.thread_id;
        dom.incId.textContent = data.incident_id; dom.thrId.textContent = "thread " + String(data.thread_id).slice(0, 8);
        trace("Incident accepted — " + data.incident_id, "started");
        setNode("triage", "active");
        break;
      case "node_update": {
        const node = data.node;
        trace("Node completed", node);
        mergeData(data.data);
        if (NODES.includes(node)) advance(node);
        renderResults();
        break;
      }
      case "paused":
        trace(data.status === "awaiting_approval" ? "Waiting for human approval" : "Run completed", "paused");
        applyFinal(data);
        break;
      case "error":
        trace(data.detail || "Unknown error", "error");
        NODES.forEach((n) => { if (nodeState[n] === "active") setNode(n, "error"); });
        showError("Analysis failed: " + (data.detail || "unknown error"));
        break;
    }
  }

  function parseBlock(block) {
    let type = "message"; const dataLines = [];
    block.split("\n").forEach((line) => {
      if (line.startsWith("event:")) type = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    });
    if (!dataLines.length) return;
    try { handleEvent(type, JSON.parse(dataLines.join("\n"))); }
    catch (e) { console.error("Bad SSE payload", e, block); }
  }

  async function analyze() {
    const raw = dom.rawLog.value.trim();
    if (raw.length < 10) { showError("Paste at least 10 characters of logs or ticket text."); return; }
    startRun();
    controller = new AbortController();
    try {
      const res = await fetch(API + "/api/v1/incidents/analyze/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ raw_log: raw }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        let detail = "HTTP " + res.status;
        try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
        throw new Error(detail);
      }
      const reader = res.body.getReader(), decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          parseBlock(buf.slice(0, idx)); buf = buf.slice(idx + 2);
        }
      }
      if (buf.trim()) parseBlock(buf);
    } catch (err) {
      if (err.name !== "AbortError") {
        NODES.forEach((n) => { if (nodeState[n] === "active") setNode(n, "error"); });
        showError("Could not reach the analysis stream: " + err.message);
      }
    } finally {
      running = false; dom.analyze.disabled = false; dom.analyze.textContent = "Analyze Incident";
    }
  }

  function startRun() {
    running = true; threadId = null; S = {}; seenTrace.clear();
    dom.traceLog.replaceChildren(); dom.traceCount.textContent = "0 events";
    show(dom.error, false); show(dom.results, false); show(dom.gate, false); show(dom.reportCard, false);
    dom.incId.textContent = "INC-…"; dom.thrId.textContent = "thread…";
    resetPipeline(); show(dom.pipeCard, true);
    dom.analyze.disabled = true; dom.analyze.textContent = "Analyzing…";
    dom.pipeCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- Human review ----------
  async function review(approved) {
    if (!threadId) return;
    const a = $("approveBtn"), r = $("rejectBtn");
    a.disabled = r.disabled = true;
    show(dom.error, false);
    trace(approved ? "Engineer approved the plan" : "Engineer rejected / escalated", "review");
    try {
      const res = await fetch(API + "/api/v1/incidents/" + encodeURIComponent(threadId) + "/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved, feedback: $("notes").value.trim() }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : "HTTP " + res.status);
      applyFinal(j);
      trace("Final report generated", "completed");
    } catch (err) {
      a.disabled = r.disabled = false;
      showError("Review failed: " + err.message);
    }
  }

 // ---------- Reset ----------
  function resetAll() {
    if (controller) controller.abort();
    running = false; threadId = null; S = {}; seenTrace.clear();
    dom.rawLog.value = ""; updateCount(); $("notes").value = "";
    dom.traceLog.replaceChildren(); dom.traceCount.textContent = "0 events";
    dom.incId.textContent = "INC-…"; dom.thrId.textContent = "thread…";
    dom.report.innerHTML = "";
    resetPipeline();
    renderResults();
    [dom.error, dom.pipeCard, dom.results, dom.gate, dom.reportCard].forEach((n) => show(n, false));
    dom.analyze.disabled = false; dom.analyze.textContent = "Analyze Incident";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateCount() { dom.charCount.textContent = dom.rawLog.value.length.toLocaleString() + " characters"; }

  // ---------- Init ----------
  SAMPLES.forEach((s) => {
    const b = el("button", "sample", s.label); b.type = "button";
    b.addEventListener("click", () => { dom.rawLog.value = s.log; updateCount(); dom.rawLog.focus(); });
    dom.samples.append(b);
  });
  dom.rawLog.addEventListener("input", updateCount);
  dom.analyze.addEventListener("click", () => { if (!running) analyze(); });
  dom.reset.addEventListener("click", resetAll);
  $("approveBtn").addEventListener("click", () => review(true));
  $("rejectBtn").addEventListener("click", () => review(false));
  $("copyReport").addEventListener("click", (e) => copyText(S.final_report || "", e.currentTarget, "Copy Report"));
  ping(); setInterval(ping, 15000);
})();

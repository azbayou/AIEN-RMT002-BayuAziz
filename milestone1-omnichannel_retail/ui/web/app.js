/* ==========================================================================
   Omnichannel Retail Lakehouse — Interactive Control Plane Application
   Zero hardcoded tokens; optional session creds stored strictly in sessionStorage.
   ========================================================================== */

(function (global) {
  "use strict";

  const DATA = global.MEDALLION_DATA;
  if (!DATA) {
    return;
  }

  const API_BASE = (window.MEDALLION_API_BASE || "").replace(/\/$/, "");
  const IS_EMBEDDED_NO_API = !API_BASE && !window.location.protocol.startsWith("http");
  const SESSION_DEMO_KEY = "medallion_demo_token";
  const SESSION_BYOK_KEY = "medallion_byok_creds";

  const state = {
    stack: "databricks",
    perspective: "business",
    lang: "en",
    xrayStageId: "raw_volume",
    xrayOrderId: "ORD-000007",
    selectedTaskKey: "setup_schemas",
    controlStatus: {
      connected: true,
      read_ready: false,
      live_ready: false,
      requires_passcode: false,
      auth_mode: "simulation_only",
      workspace_host: DATA.DEFAULTS.workspaceHost,
      org_id: DATA.DEFAULTS.orgId,
      catalog: DATA.DEFAULTS.catalog,
      warehouse_id: DATA.DEFAULTS.warehouseId,
      job_id: DATA.DEFAULTS.jobId,
      workspace_url: DATA.DEFAULTS.workspaceUrl,
      job_url: DATA.DEFAULTS.jobUrl,
      latest_verified_run_id: DATA.DEFAULTS.verifiedRunId,
      latest_verified_run_url: DATA.DEFAULTS.verifiedRunUrl,
    },
    latestRuns: [DATA.VERIFIED_RUN_SNAPSHOT],
    activeRun: buildRunStateFromPayload(DATA.VERIFIED_RUN_SNAPSHOT, "snapshot"),
    metrics: JSON.parse(JSON.stringify(DATA.VERIFIED_METRICS_SNAPSHOT)),
    copilot: {
      activeQuestion: DATA.COPILOT_BENCHMARKS[0].question,
      result: formatBenchmarkResult(DATA.COPILOT_BENCHMARKS[0], "en"),
      source: "snapshot",
      sortCol: null,
      sortDir: "desc",
    },
    pollTimer: null,
    simTimers: [],
    isSimulating: false,
    modalTab: "sso",
  };

  function buildRunStateFromPayload(runPayload, sourceLabel) {
    const taskStates = {};
    (runPayload.tasks || []).forEach((t) => {
      taskStates[t.task_key] = {
        status: (t.status || "IDLE").toUpperCase(),
        durationMs: typeof t.execution_duration_ms === "number" ? t.execution_duration_ms : null,
        stateMessage: t.state_message || "",
        runPageUrl: t.run_page_url || runPayload.run_page_url || DATA.DEFAULTS.jobUrl,
      };
    });
    return {
      run_id: runPayload.run_id || DATA.DEFAULTS.verifiedRunId,
      job_id: runPayload.job_id || DATA.DEFAULTS.jobId,
      source: sourceLabel || "snapshot",
      overall_status: (runPayload.overall_status || "SUCCESS").toUpperCase(),
      run_duration_ms: runPayload.run_duration_ms || null,
      run_page_url: runPayload.run_page_url || DATA.DEFAULTS.verifiedRunUrl,
      taskStates,
    };
  }

  function formatBenchmarkResult(bench, lang) {
    return {
      question: bench.question,
      answer: typeof bench.explanation === "string" ? bench.explanation : bench.explanation[lang] || bench.explanation.en,
      sql: bench.sql,
      columns: bench.columns,
      rows: bench.rows,
      visualization: bench.visualization,
      tables_used: bench.tables_used,
      execution_ms: bench.execution_ms,
      warnings: [],
    };
  }

  /* ------------------------------------------------------------------------
     Session Storage Auth Helpers (sessionStorage ONLY)
     ------------------------------------------------------------------------ */
  function getDemoToken() {
    try {
      return global.sessionStorage.getItem(SESSION_DEMO_KEY) || "";
    } catch (_err) {
      return "";
    }
  }

  function setDemoToken(token) {
    try {
      if (token) {
        global.sessionStorage.setItem(SESSION_DEMO_KEY, token);
      } else {
        global.sessionStorage.removeItem(SESSION_DEMO_KEY);
      }
    } catch (_err) {
      // Ignore storage errors in restricted iframes
    }
  }

  function getByokCreds() {
    try {
      const raw = global.sessionStorage.getItem(SESSION_BYOK_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_err) {
      return null;
    }
  }

  function setByokCreds(creds) {
    try {
      if (creds) {
        global.sessionStorage.setItem(SESSION_BYOK_KEY, JSON.stringify(creds));
      } else {
        global.sessionStorage.removeItem(SESSION_BYOK_KEY);
      }
    } catch (_err) {
      // Ignore storage errors in restricted iframes
    }
  }

  function buildAuthHeaders() {
    const headers = {};
    const demoToken = getDemoToken();
    if (demoToken) {
      headers["X-Demo-Auth"] = demoToken;
    }
    const byok = getByokCreds();
    if (byok && byok.host && byok.token) {
      headers["X-Databricks-Host"] = byok.host;
      headers["X-Databricks-Token"] = byok.token;
      if (byok.job_id) headers["X-Databricks-Job-Id"] = String(byok.job_id);
      if (byok.warehouse_id) headers["X-Databricks-Warehouse-Id"] = String(byok.warehouse_id);
    }
    return headers;
  }

  async function apiFetch(path, options) {
    const opts = options || {};
    const headers = Object.assign({}, buildAuthHeaders(), opts.headers || {});
    if (opts.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const response = await global.fetch(`${API_BASE}${path}`, Object.assign({}, opts, { headers }));
    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = await response.json();
    } else {
      const text = await response.text();
      payload = { detail: text };
    }
    if (!response.ok) {
      const err = new Error((payload && payload.detail) || `HTTP ${response.status}`);
      err.status = response.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  /* ------------------------------------------------------------------------
     Formatting & Safe Escaping Helpers
     ------------------------------------------------------------------------ */
  function t(key) {
    const dict = DATA.I18N[state.lang] || DATA.I18N.en;
    return dict[key] || DATA.I18N.en[key] || key;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatCurrency(num, decimals) {
    const n = Number(num);
    if (!Number.isFinite(n)) return String(num);
    const digits = typeof decimals === "number" ? decimals : 2;
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function formatCompactCurrency(num) {
    const n = Number(num);
    if (!Number.isFinite(n)) return String(num);
    if (Math.abs(n) >= 1_000_000) return "$" + (n / 1_000_000).toFixed(2) + "M";
    if (Math.abs(n) >= 1_000) return "$" + (n / 1_000).toFixed(1) + "k";
    return formatCurrency(n, 2);
  }

  function formatInt(num) {
    const n = Number(num);
    if (!Number.isFinite(n)) return String(num);
    return Math.round(n).toLocaleString("en-US");
  }

  function formatDuration(ms) {
    if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0) return "—";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    const sec = ms / 1000;
    if (sec < 60) return `${sec.toFixed(1)}s`;
    const mins = Math.floor(sec / 60);
    const remSec = Math.round(sec % 60);
    return `${mins}m ${remSec}s`;
  }

  function highlightCode(rawCode) {
    const text = String(rawCode || "");
    const tokenRe =
      /(--[^\n]*|#[^\n]*|\/\/[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:SELECT|FROM|WHERE|JOIN|LEFT|ON|GROUP BY|ORDER BY|HAVING|WITH|AS|AND|OR|NOT|CASE|WHEN|THEN|ELSE|END|MERGE INTO|USING|MATCHED|UPDATE|SET|INSERT|VALUES|CREATE|SCHEMA|CATALOG|VOLUME|TABLE|IF|EXISTS|DELTA|def|return|for|in|if|else|raise|with|from|import|True|False|None|ROUND|SUM|COUNT|AVG|COALESCE|NULLIF|ROW_NUMBER|OVER|PARTITION BY|DESC|ASC)\b|\b\d+(?:\.\d+)?\b)/g;
    let out = "";
    let lastIdx = 0;
    let match;
    while ((match = tokenRe.exec(text)) !== null) {
      if (match.index > lastIdx) {
        out += escapeHtml(text.slice(lastIdx, match.index));
      }
      const tok = match[0];
      let cls = "tok-kw";
      if (tok.startsWith("--") || tok.startsWith("#") || tok.startsWith("//")) {
        cls = "tok-cmt";
      } else if (tok.startsWith('"') || tok.startsWith("'")) {
        cls = "tok-str";
      } else if (/^\d/.test(tok)) {
        cls = "tok-num";
      }
      out += `<span class="${cls}">${escapeHtml(tok)}</span>`;
      lastIdx = tokenRe.lastIndex;
    }
    if (lastIdx < text.length) {
      out += escapeHtml(text.slice(lastIdx));
    }
    return out;
  }

  function utcNowStr() {
    const d = new Date();
    return d.toISOString().slice(11, 19) + " UTC";
  }

  function appendLog(tag, message) {
    const consoleEl = document.getElementById("telemetryConsole");
    if (!consoleEl) return;
    const row = document.createElement("div");
    row.className = "log-line";
    const tagLower = String(tag || "info").toLowerCase();
    row.innerHTML = `<span class="log-ts">[${utcNowStr()}]</span><span class="log-tag-${escapeHtml(tagLower)}">[${escapeHtml(
      tag.toUpperCase()
    )}]</span><span class="log-msg">${escapeHtml(message)}</span>`;
    consoleEl.appendChild(row);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  function showToast(message, variant) {
    const host = document.getElementById("toastContainer");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `toast ${variant ? `toast-${variant}` : ""}`;
    el.textContent = message;
    host.appendChild(el);
    global.setTimeout(() => {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 4200);
  }

  /* ------------------------------------------------------------------------
     Translation & Header Controls Rendering
     ------------------------------------------------------------------------ */
  function applyStaticTranslations() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (key) el.textContent = t(key);
    });
    const copilotInput = document.getElementById("copilotInput");
    if (copilotInput) {
      copilotInput.placeholder = t("copilot.placeholder");
    }
  }

  function renderHeaderAndHero() {
    const status = state.controlStatus;
    const catalog = status.catalog || DATA.DEFAULTS.catalog;
    const badgeEl = document.getElementById("catalogBadge");
    if (badgeEl) {
      badgeEl.textContent = `${catalog} · Unity Catalog`;
    }

    const activeRunUrl =
      (state.activeRun && state.activeRun.run_page_url) || status.job_url || status.workspace_url || DATA.DEFAULTS.jobUrl;
    const openBtn = document.getElementById("openDatabricksBtn");
    if (openBtn) {
      openBtn.href = activeRunUrl;
    }

    const modalWsLink = document.getElementById("modalWorkspacePortalLink");
    const modalJobLink = document.getElementById("modalJobPortalLink");
    if (modalWsLink) modalWsLink.href = status.workspace_url || DATA.DEFAULTS.workspaceUrl;
    if (modalJobLink) modalJobLink.href = status.job_url || DATA.DEFAULTS.jobUrl;

    const authBtn = document.getElementById("authStatusBtn");
    const authLabel = document.getElementById("authStatusLabel");
    const modalBannerText = document.getElementById("modalStatusText");
    if (authBtn && authLabel) {
      authBtn.classList.remove("is-live", "is-locked", "is-simulation");
      let labelText = t("auth.simulation");
      if (status.live_ready) {
        authBtn.classList.add("is-live");
        if (status.auth_mode === "passcode_unlocked") labelText = t("auth.passcodeUnlocked");
        else if (status.auth_mode === "byok_session") labelText = t("auth.byokConnected");
        else labelText = t("auth.liveReady");
      } else if (IS_EMBEDDED_NO_API && status.read_ready) {
        authBtn.classList.add("is-simulation");
        labelText = "Streamlit In-Process Cloud · Live Read-Only";
      } else if (status.read_ready && (status.requires_passcode || status.auth_mode === "locked")) {
        authBtn.classList.add("is-locked");
        labelText = state.lang === "id" ? "Live Read-Only · Buka Eksekusi" : "Live Read-Only · Unlock Trigger";
      } else if (status.requires_passcode || status.auth_mode === "locked") {
        authBtn.classList.add("is-locked");
        labelText = t("auth.locked");
      } else {
        authBtn.classList.add("is-simulation");
        labelText = t("auth.simulation");
      }
      authLabel.textContent = labelText;
      if (modalBannerText) {
        const byok = getByokCreds();
        const extra = byok && byok.user_name ? ` — ${byok.user_name}` : "";
        modalBannerText.textContent = `${labelText} (${status.auth_mode || "simulation"})${extra}`;
      }
    }

    const pitchEl = document.getElementById("heroPitch");
    if (pitchEl) {
      pitchEl.textContent = state.perspective === "business" ? t("hero.pitchBusiness") : t("hero.pitchEngineer");
    }

    const jobEl = document.getElementById("heroJobId");
    const whEl = document.getElementById("heroWarehouseId");
    if (jobEl) jobEl.textContent = String(status.job_id || DATA.DEFAULTS.jobId);
    if (whEl) whEl.textContent = String(status.warehouse_id || DATA.DEFAULTS.warehouseId);
  }

  function renderTelemetryRibbon() {
    const s = (state.metrics && state.metrics.summary) || DATA.VERIFIED_METRICS_SNAPSHOT.summary;
    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    setText("kpiRawEvents", formatInt(s.bronze_raw_records || 158770));
    setText("kpiSilverRows", formatInt(s.silver_clean_records || 135805));
    setText("kpiRejected", formatInt(s.silver_rejected_records ?? 1));
    setText("kpiDeltaTables", formatInt(s.delta_tables || 25));
    setText("kpiDrift", formatCurrency(s.reconciliation_diff ?? 0.0, 2));
    setText("kpiBenchmark", s.benchmark_passed || "25/25");
  }

  /* ------------------------------------------------------------------------
     Section 2: Medallion Architecture & Interactive Record X-Ray
     ------------------------------------------------------------------------ */
  function renderXRay() {
    const picker = document.getElementById("xrayOrderPicker");
    if (picker) {
      picker.innerHTML = "";
      DATA.XRAY_ORDERS.forEach((ord) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `preset-btn ${ord.id === state.xrayOrderId ? "is-active" : ""}`;
        btn.textContent = ord.label;
        btn.addEventListener("click", () => {
          state.xrayOrderId = ord.id;
          renderXRay();
        });
        picker.appendChild(btn);
      });
    }

    const rail = document.getElementById("medallionRail");
    if (rail) {
      rail.innerHTML = "";
      DATA.XRAY_STAGES.forEach((stage) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `rail-stage-btn ${stage.id === state.xrayStageId ? "is-active" : ""}`;
        btn.setAttribute("data-stage", stage.id);
        btn.setAttribute("role", "tab");
        btn.setAttribute("aria-selected", String(stage.id === state.xrayStageId));
        btn.innerHTML = `
          <div class="rail-stage-top">
            <span class="rail-stage-index">${escapeHtml(stage.index)}</span>
            <span class="rail-stage-count">${escapeHtml(stage.summary[state.lang] || stage.summary.en)}</span>
          </div>
          <div class="rail-stage-name">${escapeHtml(stage.name[state.lang] || stage.name.en)}</div>
          <div class="rail-stage-summary mono" title="${escapeHtml(stage.location)}">${escapeHtml(stage.location)}</div>
        `;
        btn.addEventListener("click", () => {
          state.xrayStageId = stage.id;
          renderXRay();
        });
        rail.appendChild(btn);
      });
    }

    const activeStage = DATA.XRAY_STAGES.find((s) => s.id === state.xrayStageId) || DATA.XRAY_STAGES[0];
    const activeOrder = DATA.XRAY_ORDERS.find((o) => o.id === state.xrayOrderId) || DATA.XRAY_ORDERS[0];
    const stageTrace = activeOrder.stages[activeStage.id];

    const stagePill = document.getElementById("xrayStagePill");
    if (stagePill) {
      stagePill.className = `layer-pill ${activeStage.pillClass || ""}`;
      stagePill.textContent = `${activeStage.index} ${activeStage.name[state.lang] || activeStage.name.en}`;
    }

    const locEl = document.getElementById("xrayStageLocation");
    const headEl = document.getElementById("xrayStageHeading");
    const analogyEl = document.getElementById("xrayStageAnalogy");
    if (locEl) locEl.textContent = activeStage.location;
    if (headEl) headEl.textContent = activeStage.heading[state.lang] || activeStage.heading.en;
    if (analogyEl) {
      const pKey = state.perspective === "engineer" ? "engineer" : "business";
      analogyEl.textContent = activeStage.analogy[pKey][state.lang] || activeStage.analogy[pKey].en;
    }

    const contractsEl = document.getElementById("xrayContractBadges");
    if (contractsEl) {
      contractsEl.innerHTML = activeStage.contracts
        .map((c) => `<span class="contract-badge">${escapeHtml(c)}</span>`)
        .join("");
    }

    const tablesEl = document.getElementById("xrayLayerTables");
    if (tablesEl) {
      tablesEl.innerHTML = activeStage.tables
        .map((tbl) => `<span class="table-chip">${escapeHtml(tbl)}</span>`)
        .join("");
    }

    const orderTitle = document.getElementById("xrayOrderTitle");
    const verdictEl = document.getElementById("xrayOrderVerdict");
    const noteEl = document.getElementById("xrayMutationNote");
    const fileEl = document.getElementById("xrayPayloadFilename");
    const codeEl = document.getElementById("xrayPayloadCode");

    if (orderTitle) orderTitle.textContent = activeOrder.id;
    if (verdictEl) {
      verdictEl.className = `xray-verdict-badge ${activeOrder.isQuarantine ? "is-quarantine" : ""}`;
      verdictEl.textContent = activeOrder.verdict[state.lang] || activeOrder.verdict.en;
    }
    if (noteEl && stageTrace) noteEl.textContent = stageTrace.note[state.lang] || stageTrace.note.en;
    if (fileEl && stageTrace) fileEl.textContent = stageTrace.file;
    if (codeEl && stageTrace) {
      codeEl.dataset.raw = stageTrace.code;
      codeEl.innerHTML = highlightCode(stageTrace.code);
    }
  }

  /* ------------------------------------------------------------------------
     Section 3: Pipeline DAG Canvas & Split Inspector
     ------------------------------------------------------------------------ */
  function getActiveStackTasks() {
    return (DATA.STACKS[state.stack] || DATA.STACKS.databricks).tasks;
  }

  function getTaskRuntimeState(task) {
    if (state.stack === "databricks" && state.activeRun && state.activeRun.taskStates) {
      const found = state.activeRun.taskStates[task.task_key];
      if (found) return found;
      if (state.activeRun.source === "live_databricks") {
        return {
          status: "PENDING",
          durationMs: null,
          stateMessage: "Queued in Databricks Lakeflow",
        };
      }
    }
    if (state.activeRun && state.activeRun.taskStates && state.activeRun.taskStates[task.task_key]) {
      return state.activeRun.taskStates[task.task_key];
    }
    return {
      status: "IDLE",
      durationMs: task.defaultDurationMs,
      stateMessage: "",
    };
  }

  function stateBadgeClass(status) {
    const s = String(status || "IDLE").toUpperCase();
    if (s === "SUCCESS") return "state-success";
    if (s === "RUNNING") return "state-running";
    if (s === "FAILED") return "state-failed";
    if (s === "PENDING") return "state-pending";
    return "state-idle";
  }

  function renderLatestRunsSelect() {
    const sel = document.getElementById("latestRunsSelect");
    if (!sel) return;
    sel.innerHTML = "";
    const runs = state.latestRuns.length ? state.latestRuns : [DATA.VERIFIED_RUN_SNAPSHOT];
    runs.forEach((run) => {
      const opt = document.createElement("option");
      opt.value = String(run.run_id);
      const dur = formatDuration(run.run_duration_ms);
      opt.textContent = `Run #${run.run_id} · ${run.overall_status || "SUCCESS"} (${dur})`;
      if (state.activeRun && String(state.activeRun.run_id) === String(run.run_id)) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
  }

  function drawDagConnectors() {
    const stageEl = document.getElementById("dagStage");
    const svgEl = document.getElementById("dagSvgLayer");
    const nodesRow = document.getElementById("dagNodesRow");
    if (!stageEl || !svgEl || !nodesRow) return;

    const cards = Array.from(nodesRow.querySelectorAll(".dag-node-card"));
    if (cards.length < 2) {
      svgEl.innerHTML = "";
      return;
    }

    const stageRect = stageEl.getBoundingClientRect();
    const width = Math.max(stageEl.scrollWidth, stageRect.width);
    const height = Math.max(stageEl.scrollHeight, stageRect.height);
    svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svgEl.setAttribute("width", String(width));
    svgEl.setAttribute("height", String(height));

    const paths = [];
    for (let i = 0; i < cards.length - 1; i++) {
      const a = cards[i].getBoundingClientRect();
      const b = cards[i + 1].getBoundingClientRect();
      const srcStatus = cards[i].dataset.status || "IDLE";
      let stroke = "rgba(148, 163, 184, 0.35)";
      if (srcStatus === "SUCCESS") stroke = "#10B981";
      else if (srcStatus === "RUNNING") stroke = "#06B6D4";
      else if (srcStatus === "FAILED") stroke = "#F43F5E";

      const sameRow = Math.abs(a.top - b.top) < 16 && b.left >= a.right - 4;
      if (sameRow) {
        const x1 = a.right - stageRect.left;
        const y1 = a.top + a.height / 2 - stageRect.top;
        const x2 = b.left - stageRect.left;
        const y2 = b.top + b.height / 2 - stageRect.top;
        const cx = (x1 + x2) / 2;
        paths.push(
          `<path d="M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" />`
        );
        paths.push(`<circle cx="${x2 - 2}" cy="${y2}" r="3" fill="${stroke}" />`);
      } else {
        const ax = a.left + a.width / 2 - stageRect.left;
        const ay = a.bottom - stageRect.top;
        const bx = b.left + b.width / 2 - stageRect.left;
        const by = b.top - stageRect.top;
        const midY = (ay + by) / 2;
        paths.push(
          `<path d="M ${ax.toFixed(1)} ${ay.toFixed(1)} L ${ax.toFixed(1)} ${midY.toFixed(1)} L ${bx.toFixed(
            1
          )} ${midY.toFixed(1)} L ${bx.toFixed(1)} ${by.toFixed(1)}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />`
        );
        paths.push(`<circle cx="${bx.toFixed(1)}" cy="${(by - 2).toFixed(1)}" r="3" fill="${stroke}" />`);
      }
    }
    svgEl.innerHTML = paths.join("");
  }

  function renderDag() {
    const stackMeta = DATA.STACKS[state.stack] || DATA.STACKS.databricks;
    const tasks = stackMeta.tasks;
    if (!tasks.some((tk) => tk.task_key === state.selectedTaskKey)) {
      state.selectedTaskKey = tasks[0].task_key;
    }

    const subEl = document.getElementById("dagSubtitle");
    if (subEl) {
      subEl.textContent = stackMeta.subtitle[state.lang] || stackMeta.subtitle.en;
    }

    const sourceChip = document.getElementById("dagRunSourceChip");
    const runIdChip = document.getElementById("dagRunIdChip");
    const overallPill = document.getElementById("dagOverallStatePill");
    const durationChip = document.getElementById("dagTotalDurationChip");

    if (sourceChip) sourceChip.textContent = String(state.activeRun.source || "snapshot").toUpperCase();
    if (runIdChip) {
      runIdChip.textContent = state.stack === "airflow" ? `DAG Run · ${state.activeRun.run_id}` : `Run #${state.activeRun.run_id}`;
    }
    if (overallPill) {
      const ov = state.activeRun.overall_status || "IDLE";
      overallPill.className = `state-pill ${stateBadgeClass(ov)}`;
      overallPill.textContent = ov;
    }
    if (durationChip) {
      durationChip.textContent = formatDuration(state.activeRun.run_duration_ms);
    }

    const row = document.getElementById("dagNodesRow");
    if (row) {
      row.innerHTML = "";
      tasks.forEach((task, index) => {
        const rt = getTaskRuntimeState(task);
        const stLower = String(rt.status || "IDLE").toLowerCase();
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `dag-node-card node-${stLower} ${task.task_key === state.selectedTaskKey ? "is-selected" : ""}`;
        btn.dataset.taskKey = task.task_key;
        btn.dataset.status = rt.status;
        btn.innerHTML = `
          <div class="dag-node-top">
            <span class="dag-node-idx">0${index + 1} · ${escapeHtml(task.layer)}</span>
            <span class="state-pill ${stateBadgeClass(rt.status)}">${escapeHtml(rt.status)}</span>
          </div>
          <div>
            <div class="dag-node-key">${escapeHtml(task.task_key)}</div>
            <div class="dag-node-sub">${escapeHtml(task.shortLabel[state.lang] || task.shortLabel.en)}</div>
          </div>
          <div class="dag-node-foot">
            <span>${escapeHtml(task.filePath.split("/").pop())}</span>
            <span>${escapeHtml(formatDuration(rt.durationMs))}</span>
          </div>
        `;
        btn.addEventListener("click", () => {
          state.selectedTaskKey = task.task_key;
          renderDag();
          renderInspector();
        });
        row.appendChild(btn);
      });
    }

    global.requestAnimationFrame(drawDagConnectors);
    global.setTimeout(drawDagConnectors, 120);
    renderInspector();
    renderHeaderAndHero();
  }

  function renderInspector() {
    const tasks = getActiveStackTasks();
    const task = tasks.find((tk) => tk.task_key === state.selectedTaskKey) || tasks[0];
    const rt = getTaskRuntimeState(task);

    const layerEl = document.getElementById("inspTaskLayer");
    const titleEl = document.getElementById("inspTaskTitle");
    const stateEl = document.getElementById("inspTaskState");
    const descEl = document.getElementById("inspTaskDesc");
    const pointsEl = document.getElementById("inspRecruiterPoints");
    const bizBox = document.getElementById("inspBusinessBox");
    const engBox = document.getElementById("inspEngineerBox");
    const bizText = document.getElementById("inspBusinessText");
    const engText = document.getElementById("inspEngineerText");
    const tagsEl = document.getElementById("inspTags");
    const pathEl = document.getElementById("inspFilePath");
    const codeEl = document.getElementById("inspCodeContent");

    if (layerEl) {
      layerEl.className = `layer-pill ${task.pillClass || ""}`;
      layerEl.textContent = task.layer;
    }
    if (titleEl) titleEl.textContent = task.task_key;
    if (stateEl) {
      stateEl.className = `state-pill ${stateBadgeClass(rt.status)}`;
      stateEl.textContent = rt.status;
    }
    if (descEl) {
      const msg = rt.stateMessage ? ` — ${rt.stateMessage}` : "";
      descEl.textContent = (task.desc[state.lang] || task.desc.en) + msg;
    }
    if (pointsEl) {
      const pts = task.recruiterPoints[state.lang] || task.recruiterPoints.en;
      pointsEl.innerHTML = pts.map((p) => `<li>${escapeHtml(p)}</li>`).join("");
    }
    if (bizText) bizText.textContent = task.businessImpact[state.lang] || task.businessImpact.en;
    if (engText) engText.textContent = task.engineerNotes[state.lang] || task.engineerNotes.en;
    if (bizBox && engBox) {
      bizBox.classList.toggle("is-emphasized", state.perspective === "business");
      engBox.classList.toggle("is-emphasized", state.perspective === "engineer");
    }
    if (tagsEl) {
      tagsEl.innerHTML = task.tags.map((tg) => `<span class="contract-badge">${escapeHtml(tg)}</span>`).join("");
    }
    if (pathEl) pathEl.textContent = task.filePath;
    if (codeEl) {
      codeEl.dataset.raw = task.code;
      codeEl.innerHTML = highlightCode(task.code);
    }
  }

  /* ------------------------------------------------------------------------
     Simulation, Quality Gate Failure & Live Databricks Execution
     ------------------------------------------------------------------------ */
  function clearTimers() {
    if (state.pollTimer) {
      global.clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    state.simTimers.forEach((id) => global.clearTimeout(id));
    state.simTimers = [];
    state.isSimulating = false;
  }

  function resetDagToVerifiedSnapshot() {
    clearTimers();
    if (state.stack === "databricks") {
      const latest = state.latestRuns[0] || DATA.VERIFIED_RUN_SNAPSHOT;
      state.activeRun = buildRunStateFromPayload(latest, "snapshot");
    } else {
      const idleStates = {};
      DATA.STACKS.airflow.tasks.forEach((tk) => {
        idleStates[tk.task_key] = { status: "IDLE", durationMs: tk.defaultDurationMs, stateMessage: "" };
      });
      state.activeRun = {
        run_id: "airflow_local_ready",
        source: "local_dag",
        overall_status: "IDLE",
        run_duration_ms: null,
        run_page_url: state.controlStatus.job_url || DATA.DEFAULTS.jobUrl,
        taskStates: idleStates,
      };
    }
    renderDag();
    appendLog("info", "Pipeline DAG canvas reset.");
  }

  function runSimulatedPipeline(failQualityGate) {
    clearTimers();
    state.isSimulating = true;
    const tasks = getActiveStackTasks();
    const simRunId = failQualityGate ? `sim_gate_fail_${Date.now().toString().slice(-5)}` : `sim_${Date.now().toString().slice(-5)}`;
    const taskStates = {};
    tasks.forEach((tk) => {
      taskStates[tk.task_key] = { status: "PENDING", durationMs: null, stateMessage: "" };
    });

    state.activeRun = {
      run_id: simRunId,
      source: failQualityGate ? "gate_test" : "simulation",
      overall_status: "RUNNING",
      run_duration_ms: 0,
      run_page_url: state.controlStatus.job_url || DATA.DEFAULTS.jobUrl,
      taskStates,
    };
    renderDag();
    appendLog(
      failQualityGate ? "gate" : "info",
      failQualityGate
        ? `Started Quality Gate failure drill on ${state.stack} stack (injecting quantity = -2 into clean Silver)...`
        : `Started interactive ${state.stack} simulation (${tasks.length} tasks)...`
    );

    const gateKey = state.stack === "databricks" ? "silver_quality_gate" : "quality_gate";
    let elapsed = 0;
    let totalAccumulatedMs = 0;
    let halted = false;

    tasks.forEach((task) => {
      if (halted) return;
      const startAt = elapsed;
      const stepMs = 750;
      const finishAt = startAt + stepMs;
      elapsed = finishAt + 120;

      const t1 = global.setTimeout(() => {
        state.activeRun.taskStates[task.task_key] = {
          status: "RUNNING",
          durationMs: null,
          stateMessage: "Executing...",
        };
        state.selectedTaskKey = task.task_key;
        renderDag();
        appendLog("info", `Task '${task.task_key}' -> RUNNING (${task.filePath})`);
      }, startAt);

      const isGateFailure = failQualityGate && task.task_key === gateKey;
      const t2 = global.setTimeout(() => {
        const simTaskDur = Math.max(900, Math.round((task.defaultDurationMs || 4000) * (failQualityGate ? 0.45 : 1)));
        totalAccumulatedMs += simTaskDur;
        if (isGateFailure) {
          state.activeRun.taskStates[task.task_key] = {
            status: "FAILED",
            durationMs: simTaskDur,
            stateMessage: "ValueError: no_negative_qty_in_clean failed (1 negative row)",
          };
          state.activeRun.overall_status = "FAILED";
          state.activeRun.run_duration_ms = totalAccumulatedMs;
          state.selectedTaskKey = task.task_key;
          state.isSimulating = false;
          renderDag();
          appendLog(
            "error",
            `Task '${task.task_key}' FAILED: no_negative_qty_in_clean detected quantity <= 0 in silver.order_items. Downstream Gold tasks blocked!`
          );
          showToast("Quality Gate halted pipeline before Gold layer!", "error");
        } else {
          state.activeRun.taskStates[task.task_key] = {
            status: "SUCCESS",
            durationMs: simTaskDur,
            stateMessage: "Completed",
          };
          state.activeRun.run_duration_ms = totalAccumulatedMs;
          const isLast = task.task_key === tasks[tasks.length - 1].task_key;
          if (isLast) {
            state.activeRun.overall_status = "SUCCESS";
            state.isSimulating = false;
            appendLog("success", `Simulation ${simRunId} completed SUCCESS (${formatDuration(totalAccumulatedMs)}). $0.00 drift.`);
            showToast("Pipeline simulation completed successfully.", "success");
          } else {
            appendLog("success", `Task '${task.task_key}' -> SUCCESS (${formatDuration(simTaskDur)})`);
          }
          renderDag();
        }
      }, finishAt);

      state.simTimers.push(t1, t2);
      if (isGateFailure) {
        halted = true;
      }
    });
  }

  async function triggerLiveDatabricksRun() {
    const byok = getByokCreds();
    if (IS_EMBEDDED_NO_API && !(byok && byok.token)) {
      const msg =
        state.lang === "id"
          ? 'Mode Streamlit In-Process Cloud: gunakan bar "⚡ Live Databricks Cloud Control" tepat di atas kanvas untuk membuka & memicu job, atau atur Engine URL / kredensial BYOK.'
          : 'Streamlit In-Process Cloud: use the "⚡ Live Databricks Cloud Control" bar directly above this canvas to unlock & trigger runs, or enter BYOK credentials in #authModal.';
      appendLog("cloud", msg);
      showToast(msg, "success");
      return;
    }

    if (!state.controlStatus.live_ready) {
      const preferredTab = state.controlStatus.requires_passcode ? "passcode" : "credentials";
      openAuthModal(preferredTab);
      appendLog("gate", "Live Databricks trigger requires workspace authentication or demo passcode unlock.");
      return;
    }

    if (state.stack !== "databricks") {
      state.stack = "databricks";
      updateSegmentedButtons("stack", "databricks");
    }

    clearTimers();
    appendLog("cloud", `Calling POST /v1/control/jobs/run for Job #${state.controlStatus.job_id}...`);

    try {
      const res = await apiFetch("/v1/control/jobs/run", { method: "POST" });
      const runId = res.run_id;
      const runUrl = res.run_page_url || state.controlStatus.job_url;

      if (res.already_running) {
        appendLog("cloud", `Concurrent Run Guard attached to active Databricks Run #${runId}.`);
        showToast(`Attached to active Run #${runId}`, "success");
      } else {
        appendLog("cloud", `Triggered new Databricks Lakeflow Run #${runId}.`);
        showToast(`Triggered Run #${runId} on Databricks`, "success");
      }

      const initialStates = {};
      DATA.STACKS.databricks.tasks.forEach((tk) => {
        initialStates[tk.task_key] = { status: "PENDING", durationMs: null, stateMessage: "" };
      });
      state.activeRun = {
        run_id: runId,
        job_id: res.job_id || state.controlStatus.job_id,
        source: "live_databricks",
        overall_status: "PENDING",
        run_duration_ms: 0,
        run_page_url: runUrl,
        taskStates: initialStates,
      };
      renderDag();
      await pollLiveRun(runId);
      state.pollTimer = global.setInterval(() => {
        pollLiveRun(runId);
      }, 3000);
    } catch (err) {
      appendLog("error", `Failed to trigger live Databricks run: ${err.message}`);
      showToast(err.message, "error");
      if (err.status === 401) {
        openAuthModal(state.controlStatus.requires_passcode ? "passcode" : "credentials");
      }
    }
  }

  async function pollLiveRun(runId) {
    try {
      const payload = await apiFetch(`/v1/control/jobs/runs/${encodeURIComponent(runId)}`);
      const nextRun = buildRunStateFromPayload(payload, payload.source || "live_databricks");
      state.activeRun = nextRun;

      const runningTask = (payload.tasks || []).find((tk) => tk.status === "RUNNING");
      if (runningTask) {
        state.selectedTaskKey = runningTask.task_key;
      }

      renderDag();
      appendLog("cloud", `Polled Run #${runId} -> ${nextRun.overall_status} (${formatDuration(nextRun.run_duration_ms)})`);

      if (["SUCCESS", "FAILED", "CANCELED", "TIMEDOUT", "INTERNAL_ERROR"].includes(nextRun.overall_status)) {
        clearTimers();
        if (nextRun.overall_status === "SUCCESS") {
          showToast(`Databricks Run #${runId} succeeded!`, "success");
          fetchLatestRuns();
          fetchMetrics(true);
        } else {
          showToast(`Databricks Run #${runId} ended: ${nextRun.overall_status}`, "error");
        }
      }
    } catch (err) {
      appendLog("error", `Polling Run #${runId} failed: ${err.message}`);
      clearTimers();
    }
  }

  /* ------------------------------------------------------------------------
     Section 4: Gold BI Charts, Quality Table & Embedded NL-to-SQL Copilot
     ------------------------------------------------------------------------ */
  function attachTooltipHandlers(hostEl, items) {
    const tip = document.createElement("div");
    tip.className = "chart-tooltip";
    tip.hidden = true;
    hostEl.appendChild(tip);

    items.forEach((node) => {
      node.addEventListener("mouseenter", () => {
        tip.textContent = node.getAttribute("data-tip") || "";
        tip.hidden = false;
      });
      node.addEventListener("mousemove", (evt) => {
        const rect = hostEl.getBoundingClientRect();
        const x = Math.min(rect.width - 170, Math.max(8, evt.clientX - rect.left + 12));
        const y = Math.max(8, evt.clientY - rect.top - 34);
        tip.style.left = `${x}px`;
        tip.style.top = `${y}px`;
      });
      node.addEventListener("mouseleave", () => {
        tip.hidden = true;
      });
    });
  }

  function renderTrendChart() {
    const host = document.getElementById("trendChartHost");
    if (!host) return;
    const rows = (state.metrics && state.metrics.daily_trend) || DATA.VERIFIED_METRICS_SNAPSHOT.daily_trend;
    if (!rows.length) {
      host.innerHTML = `<div class="muted-text">No daily trend data available.</div>`;
      return;
    }

    const w = 540;
    const h = 220;
    const pad = { top: 20, right: 20, bottom: 36, left: 64 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const vals = rows.map((r) => Number(r.net_revenue || 0));
    const minVal = Math.min(...vals) * 0.85;
    const maxVal = Math.max(...vals) * 1.08 || 1;
    const xStep = rows.length > 1 ? cw / (rows.length - 1) : cw / 2;

    const coords = rows.map((r, i) => {
      const x = rows.length > 1 ? pad.left + i * xStep : pad.left + cw / 2;
      const ratio = (Number(r.net_revenue || 0) - minVal) / (maxVal - minVal || 1);
      const y = pad.top + ch - ratio * ch;
      return { x, y, row: r };
    });

    const linePath = coords.map((c, idx) => `${idx === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
    const areaPath = `${linePath} L ${coords[coords.length - 1].x.toFixed(1)} ${(pad.top + ch).toFixed(1)} L ${coords[0].x.toFixed(
      1
    )} ${(pad.top + ch).toFixed(1)} Z`;

    const gridLines = [0, 0.5, 1]
      .map((frac) => {
        const y = pad.top + ch - frac * ch;
        const val = minVal + frac * (maxVal - minVal);
        return `
          <line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${w - pad.right}" y2="${y.toFixed(1)}" stroke="rgba(148,163,184,0.12)" />
          <text x="${pad.left - 8}" y="${(y + 4).toFixed(1)}" fill="#64748B" font-size="10" font-family="JetBrains Mono, monospace" text-anchor="end">${escapeHtml(
            formatCompactCurrency(val)
          )}</text>
        `;
      })
      .join("");

    const points = coords
      .map((c) => {
        const label = c.row.metric_date.slice(5);
        const tip = `${c.row.metric_date}: ${formatCurrency(c.row.net_revenue)} (${formatInt(c.row.total_orders)} orders)`;
        return `
          <text x="${c.x.toFixed(1)}" y="${h - 10}" fill="#94A3B8" font-size="10" font-family="JetBrains Mono, monospace" text-anchor="middle">${escapeHtml(
            label
          )}</text>
          <circle class="chart-hit" data-tip="${escapeHtml(tip)}" cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(
            1
          )}" r="5" fill="#EAB308" stroke="#090B10" stroke-width="2" style="cursor:pointer" />
        `;
      })
      .join("");

    host.innerHTML = `
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="220" role="img" aria-label="7-Day Net Revenue Trend">
        <defs>
          <linearGradient id="goldAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#EAB308" stop-opacity="0.34" />
            <stop offset="100%" stop-color="#EAB308" stop-opacity="0.02" />
          </linearGradient>
        </defs>
        ${gridLines}
        <path d="${areaPath}" fill="url(#goldAreaGrad)" />
        <path d="${linePath}" fill="none" stroke="#EAB308" stroke-width="2.4" stroke-linejoin="round" />
        ${points}
      </svg>
    `;
    attachTooltipHandlers(host, Array.from(host.querySelectorAll(".chart-hit")));
  }

  function renderChannelChart() {
    const host = document.getElementById("channelChartHost");
    if (!host) return;
    const rows = (state.metrics && state.metrics.channels) || DATA.VERIFIED_METRICS_SNAPSHOT.channels;
    const maxRev = Math.max(...rows.map((r) => Number(r.net_revenue || 0)), 1);
    const palette = ["#FF3621", "#06B6D4", "#EAB308", "#10B981"];

    const w = 540;
    const h = 220;
    const leftPad = 104;
    const rightPad = 92;
    const barW = w - leftPad - rightPad;
    const rowH = 44;

    const bars = rows
      .map((r, idx) => {
        const y = 20 + idx * rowH;
        const pct = Math.max(0.04, Number(r.net_revenue || 0) / maxRev);
        const bw = pct * barW;
        const color = palette[idx % palette.length];
        const tip = `${r.sales_channel}: ${formatCurrency(r.net_revenue)} · ${formatInt(r.orders)} orders · Refunded ${formatCurrency(
          r.refunded
        )}`;
        return `
          <g class="chart-hit" data-tip="${escapeHtml(tip)}" style="cursor:pointer">
            <text x="${leftPad - 10}" y="${y + 18}" fill="#E2E8F0" font-size="11" font-weight="600" font-family="JetBrains Mono, monospace" text-anchor="end">${escapeHtml(
              r.sales_channel
            )}</text>
            <rect x="${leftPad}" y="${y + 4}" width="${barW}" height="20" rx="5" fill="rgba(148,163,184,0.09)" />
            <rect x="${leftPad}" y="${y + 4}" width="${bw.toFixed(1)}" height="20" rx="5" fill="${color}" />
            <text x="${leftPad + barW + 10}" y="${y + 18}" fill="#F8FAFC" font-size="11" font-family="JetBrains Mono, monospace">${escapeHtml(
              formatCompactCurrency(r.net_revenue)
            )}</text>
          </g>
        `;
      })
      .join("");

    host.innerHTML = `
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="220" role="img" aria-label="Omnichannel Net Revenue Split">
        ${bars}
      </svg>
    `;
    attachTooltipHandlers(host, Array.from(host.querySelectorAll(".chart-hit")));
  }

  function renderBiDashboard() {
    const m = state.metrics || DATA.VERIFIED_METRICS_SNAPSHOT;
    const s = m.summary || DATA.VERIFIED_METRICS_SNAPSHOT.summary;
    const isLive = m.source === "live_databricks";

    const badge = document.getElementById("metricsSourceBadge");
    if (badge) {
      badge.className = `source-badge ${isLive ? "is-live" : ""}`;
      badge.textContent = isLive ? t("bi.sourceLive") : t("bi.sourceSnapshot");
    }

    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    setText("biNetRevenue", formatCurrency(s.net_revenue));
    setText("biGrossRevenue", `Gross: ${formatCurrency(s.gross_revenue)}`);
    setText("biTotalOrders", formatInt(s.total_orders));
    setText("biDaysWindow", `${formatInt(s.days)} active days · 0 duplicates`);
    setText("biAov", formatCurrency(s.average_order_value));
    setText("biRefundRate", `Refund Rate: ${(Number(s.refund_rate || 0) * 100).toFixed(2)}%`);
    setText("biRepeatRate", `${(Number(s.repeat_customer_rate || 0) * 100).toFixed(2)}%`);
    setText("biStockoutRate", `Stockout Rate: ${(Number(s.stockout_rate || 0) * 100).toFixed(2)}%`);

    renderTrendChart();
    renderChannelChart();

    const checks = m.quality_checks || DATA.VERIFIED_METRICS_SNAPSHOT.quality_checks;
    const passedCount = checks.filter((c) => c.passed).length;
    setText("reconGateCount", `${passedCount} / ${checks.length} PASSED`);
    setText("reconRevDiff", `Revenue Diff: ${formatCurrency(s.reconciliation_diff ?? 0.0, 2)}`);
    setText("reconRefDiff", "Refund Diff: $0.00");

    const tbody = document.getElementById("qualityChecksBody");
    if (tbody) {
      tbody.innerHTML = checks
        .map((chk) => {
          const detailsObj = chk.details || chk.details_json || {};
          const detailsStr = typeof detailsObj === "string" ? detailsObj : JSON.stringify(detailsObj);
          const stageClass = chk.check_stage === "silver_gate" ? "pill-silver" : "pill-gold";
          const statusClass = chk.passed ? "state-success" : "state-failed";
          const statusLabel = chk.passed ? "PASSED" : "FAILED";
          return `
            <tr>
              <td class="mono">${escapeHtml(chk.check_name)}</td>
              <td><span class="layer-pill ${stageClass}">${escapeHtml(chk.check_stage)}</span></td>
              <td><span class="state-pill ${statusClass}">${statusLabel}</span></td>
              <td class="mono muted-text">${escapeHtml(detailsStr)}</td>
            </tr>
          `;
        })
        .join("");
    }
  }

  function renderCopilotChips() {
    const host = document.getElementById("copilotChips");
    if (!host) return;
    host.innerHTML = "";
    DATA.COPILOT_BENCHMARKS.forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `chip-btn ${state.copilot.activeQuestion === b.question ? "is-active" : ""}`;
      btn.textContent = b.question;
      btn.addEventListener("click", () => {
        const input = document.getElementById("copilotInput");
        if (input) input.value = b.question;
        runCopilotQuestion(b.question);
      });
      host.appendChild(btn);
    });
  }

  function renderCopilotChart(result) {
    const host = document.getElementById("copilotChartHost");
    if (!host) return;
    const rows = Array.isArray(result.rows) ? result.rows : [];
    const cols = Array.isArray(result.columns) ? result.columns : [];
    if (!rows.length || cols.length < 2) {
      host.innerHTML = `<div class="muted-text">No tabular chart series returned.</div>`;
      return;
    }

    const spec = result.visualization || {};
    const xKey = spec.x && cols.includes(spec.x) ? spec.x : cols[0];
    const yKey =
      Array.isArray(spec.y) && spec.y.length && cols.includes(spec.y[0])
        ? spec.y[0]
        : cols.find((c) => c !== xKey && Number.isFinite(Number(rows[0][c]))) || cols[1];

    const slice = rows.slice(0, 12);
    const values = slice.map((r) => Number(r[yKey] || 0));
    const maxVal = Math.max(...values, 0.0001);
    const w = 560;
    const h = 216;
    const pad = { top: 18, right: 16, bottom: 44, left: 40 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;
    const maxLabelLen = slice.length <= 5 ? 15 : slice.length <= 7 ? 12 : 9;
    const labelFontSize = slice.length <= 5 ? "10.5" : slice.length <= 7 ? "9.5" : "8.5";

    if (spec.kind === "line") {
      const xStep = slice.length > 1 ? cw / (slice.length - 1) : cw / 2;
      const pts = slice.map((r, i) => {
        const x = slice.length > 1 ? pad.left + i * xStep : pad.left + cw / 2;
        const y = pad.top + ch - (Number(r[yKey] || 0) / maxVal) * ch;
        return { x, y, label: String(r[xKey] ?? ""), val: Number(r[yKey] || 0) };
      });
      const d = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
      const dots = pts
        .map(
          (p) => `
          <text x="${p.x.toFixed(1)}" y="${h - 14}" fill="#94A3B8" font-size="${labelFontSize}" font-family="JetBrains Mono, monospace" text-anchor="middle">${escapeHtml(
            p.label.slice(-5)
          )}</text>
          <circle class="chart-hit" data-tip="${escapeHtml(`${p.label}: ${p.val.toLocaleString("en-US")}`)}" cx="${p.x.toFixed(
            1
          )}" cy="${p.y.toFixed(1)}" r="4.5" fill="#06B6D4" stroke="#090B10" stroke-width="2" style="cursor:pointer" />
        `
        )
        .join("");

      host.innerHTML = `
        <svg viewBox="0 0 ${w} ${h}" width="100%" height="216">
          <line x1="${pad.left}" y1="${pad.top + ch}" x2="${w - pad.right}" y2="${pad.top + ch}" stroke="rgba(148,163,184,0.18)" />
          <path d="${d}" fill="none" stroke="#06B6D4" stroke-width="2.2" />
          ${dots}
        </svg>
      `;
    } else {
      const slot = cw / slice.length;
      const bw = Math.min(62, Math.max(16, slot * 0.56));
      const bars = slice
        .map((r, i) => {
          const val = Number(r[yKey] || 0);
          const bh = Math.max(2, (val / maxVal) * ch);
          const x = pad.left + i * slot + (slot - bw) / 2;
          const y = pad.top + ch - bh;
          const lbl = String(r[xKey] ?? "");
          const displayLbl = lbl.length > maxLabelLen ? lbl.slice(0, maxLabelLen - 1) + "…" : lbl;
          const tip = `${lbl}: ${val.toLocaleString("en-US")}`;
          return `
            <g class="chart-hit" data-tip="${escapeHtml(tip)}" style="cursor:pointer">
              <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="4" fill="#06B6D4" />
              <text x="${(x + bw / 2).toFixed(1)}" y="${h - 14}" fill="#94A3B8" font-size="${labelFontSize}" font-family="JetBrains Mono, monospace" text-anchor="middle">${escapeHtml(
                displayLbl
              )}</text>
            </g>
          `;
        })
        .join("");

      host.innerHTML = `
        <svg viewBox="0 0 ${w} ${h}" width="100%" height="216">
          <line x1="${pad.left}" y1="${pad.top + ch}" x2="${w - pad.right}" y2="${pad.top + ch}" stroke="rgba(148,163,184,0.18)" />
          ${bars}
        </svg>
      `;
    }

    attachTooltipHandlers(host, Array.from(host.querySelectorAll(".chart-hit")));
  }

  function formatCell(colName, val) {
    if (val === null || val === undefined) return "—";
    const num = Number(val);
    if (typeof val === "number" || (typeof val === "string" && /^-?\d+(\.\d+)?$/.test(val.trim()) && colName !== "campaign_id")) {
      if (/(revenue|amount|refund|spend|value)/i.test(colName)) {
        return formatCurrency(num, 2);
      }
      if (/(rate)/i.test(colName)) {
        return (num * 100).toFixed(2) + "%";
      }
      if (/(roas)/i.test(colName)) {
        return num.toFixed(2) + "x";
      }
      return num.toLocaleString("en-US");
    }
    return String(val);
  }

  function renderCopilotResult() {
    const res = state.copilot.result;
    if (!res) return;

    const srcBadge = document.getElementById("copilotSourceBadge");
    const execEl = document.getElementById("copilotExecMs");
    const tablesEl = document.getElementById("copilotTablesUsed");
    const ansEl = document.getElementById("copilotAnswerText");
    const sqlEl = document.getElementById("copilotSqlCode");
    const tableWrap = document.getElementById("copilotTableWrap");

    if (srcBadge) {
      const live = state.copilot.source === "live";
      srcBadge.className = `source-badge ${live ? "is-live" : ""}`;
      srcBadge.textContent = live ? "Live Engine (/v1/analyze)" : t("bi.sourceSnapshot");
    }
    if (execEl) execEl.textContent = `${res.execution_ms ?? "—"} ms`;
    if (tablesEl) {
      tablesEl.innerHTML = (res.tables_used || [])
        .map((tbl) => `<span class="table-chip">${escapeHtml(tbl)}</span>`)
        .join("");
    }
    if (ansEl) {
      let answerText = res.answer || "";
      if (IS_EMBEDDED_NO_API && res.columns && res.columns.length) {
        const suffix =
          state.lang === "id"
            ? " (Gunakan Tab 2 💬 AI NL-to-SQL Copilot untuk kueri kustom live ke Databricks SQL Warehouse.)"
            : " (Use Tab 2 💬 AI NL-to-SQL Copilot above for live custom Databricks SQL Warehouse queries.)";
        answerText += suffix;
      }
      ansEl.textContent = answerText;
    }
    if (sqlEl) {
      sqlEl.dataset.raw = res.sql || "";
      sqlEl.innerHTML = highlightCode(res.sql || "");
    }

    renderCopilotChart(res);

    if (tableWrap) {
      const cols = res.columns || [];
      let rows = Array.isArray(res.rows) ? res.rows.slice() : [];
      if (state.copilot.sortCol && cols.includes(state.copilot.sortCol)) {
        const sc = state.copilot.sortCol;
        const dir = state.copilot.sortDir === "asc" ? 1 : -1;
        rows.sort((a, b) => {
          const av = a[sc];
          const bv = b[sc];
          const an = Number(av);
          const bn = Number(bv);
          if (Number.isFinite(an) && Number.isFinite(bn)) return (an - bn) * dir;
          return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
        });
      }

      if (!cols.length || !rows.length) {
        tableWrap.innerHTML = `<div class="muted-text" style="padding:12px;">No rows returned.</div>`;
      } else {
        const ths = cols
          .map((c) => {
            const arrow = state.copilot.sortCol === c ? (state.copilot.sortDir === "asc" ? " ▲" : " ▼") : "";
            return `<th class="is-sortable" data-sort-col="${escapeHtml(c)}">${escapeHtml(c + arrow)}</th>`;
          })
          .join("");
        const trs = rows
          .map(
            (r) =>
              `<tr>${cols.map((c) => `<td class="mono">${escapeHtml(formatCell(c, r[c]))}</td>`).join("")}</tr>`
          )
          .join("");
        tableWrap.innerHTML = `<table class="data-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;

        tableWrap.querySelectorAll("th[data-sort-col]").forEach((th) => {
          th.addEventListener("click", () => {
            const col = th.getAttribute("data-sort-col");
            if (state.copilot.sortCol === col) {
              state.copilot.sortDir = state.copilot.sortDir === "asc" ? "desc" : "asc";
            } else {
              state.copilot.sortCol = col;
              state.copilot.sortDir = "desc";
            }
            renderCopilotResult();
          });
        });
      }
    }
  }

  async function runCopilotQuestion(questionText) {
    const q = (questionText || "").trim();
    if (q.length < 3) return;
    state.copilot.activeQuestion = q;
    state.copilot.sortCol = null;
    renderCopilotChips();

    const submitBtn = document.getElementById("copilotSubmitBtn");
    if (submitBtn) submitBtn.disabled = true;

    const normQ = q.toLowerCase().replace(/\s+/g, " ");
    const findBenchmark = () =>
      DATA.COPILOT_BENCHMARKS.find((b) => b.question.toLowerCase() === normQ);

    if (IS_EMBEDDED_NO_API) {
      const bench = findBenchmark();
      if (bench) {
        state.copilot.result = formatBenchmarkResult(bench, state.lang);
        state.copilot.source = "snapshot";
        renderCopilotResult();
        appendLog(
          "info",
          `Served verified benchmark snapshot for "${q}". Use Tab 2 (💬 AI NL-to-SQL Copilot) for live custom Databricks SQL queries.`
        );
      } else {
        state.copilot.result = {
          question: q,
          answer:
            state.lang === "id"
              ? "Mode kanvas tertanam menjalankan 6 kueri benchmark terverifikasi dari snapshot. Buka Tab 2 (💬 AI NL-to-SQL Copilot) di bagian atas untuk menjalankan pertanyaan kustom live langsung ke Databricks SQL Warehouse."
              : "Embedded canvas mode serves verified benchmark queries from snapshot. Switch to Tab 2 (💬 AI NL-to-SQL Copilot) at the top to run custom live queries directly against Databricks SQL Warehouse.",
          sql: "-- Open Tab 2 (💬 AI NL-to-SQL Copilot) for live in-process custom Gold SQL execution.",
          columns: [],
          rows: [],
          tables_used: ["gold.order_360"],
          execution_ms: 0,
        };
        state.copilot.source = "snapshot";
        renderCopilotResult();
      }
      if (submitBtn) submitBtn.disabled = false;
      return;
    }

    try {
      const payload = await apiFetch("/v1/analyze", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          history: [],
          max_rows: 100,
          visualization: "auto",
        }),
      });
      state.copilot.result = payload;
      state.copilot.source = "live";
      renderCopilotResult();
      appendLog("success", `NL-to-SQL analyzed "${q}" via live engine (${payload.execution_ms}ms).`);
    } catch (err) {
      const bench = findBenchmark();
      if (bench) {
        state.copilot.result = formatBenchmarkResult(bench, state.lang);
        state.copilot.source = "snapshot";
        renderCopilotResult();
        appendLog("info", `Served verified benchmark snapshot for "${q}" (live engine offline: ${err.message}).`);
      } else {
        state.copilot.result = {
          question: q,
          answer:
            state.lang === "id"
              ? `Engine analitik live tidak terjangkau (${err.message}). Pilih salah satu dari 6 kueri benchmark terverifikasi di atas untuk melihat hasil snapshot.`
              : `Live analytics engine is offline (${err.message}). Select one of the 6 verified benchmark chips above to inspect verified snapshot results.`,
          sql: "-- Live POST /v1/analyze required for custom ad-hoc queries.",
          columns: [],
          rows: [],
          tables_used: ["gold.order_360"],
          execution_ms: 0,
        };
        state.copilot.source = "snapshot";
        renderCopilotResult();
        showToast(err.message, "error");
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------------
     API Hydration & Modal Logic
     ------------------------------------------------------------------------ */
  const inflightRequests = {};

  function dedupRequest(key, loaderFn) {
    if (inflightRequests[key]) {
      return inflightRequests[key];
    }
    const promise = Promise.resolve()
      .then(loaderFn)
      .finally(() => {
        delete inflightRequests[key];
      });
    inflightRequests[key] = promise;
    return promise;
  }

  function hydrateFromBootState(boot) {
    if (!boot || typeof boot !== "object") return false;
    let applied = false;
    if (boot.status && typeof boot.status === "object") {
      state.controlStatus = boot.status;
      applied = true;
    }
    const bootRuns = boot.latest_runs && Array.isArray(boot.latest_runs.runs) ? boot.latest_runs.runs : null;
    if (bootRuns && bootRuns.length) {
      state.latestRuns = bootRuns;
      state.activeRun = buildRunStateFromPayload(bootRuns[0], boot.latest_runs.source || "snapshot");
      applied = true;
    }
    if (boot.metrics && boot.metrics.summary) {
      state.metrics = boot.metrics;
      applied = true;
    }
    return applied;
  }

  async function fetchControlStatus() {
    if (IS_EMBEDDED_NO_API) {
      renderHeaderAndHero();
      return;
    }
    return dedupRequest("controlStatus", async () => {
      try {
        const status = await apiFetch("/v1/control/status");
        state.controlStatus = status;
        renderHeaderAndHero();
      } catch (_err) {
        renderHeaderAndHero();
      }
    });
  }

  async function fetchLatestRuns() {
    if (IS_EMBEDDED_NO_API) {
      renderLatestRunsSelect();
      return;
    }
    return dedupRequest("latestRuns", async () => {
      try {
        const data = await apiFetch("/v1/control/jobs/latest");
        if (data && Array.isArray(data.runs) && data.runs.length) {
          state.latestRuns = data.runs;
          if (!state.pollTimer && !state.isSimulating && state.stack === "databricks") {
            state.activeRun = buildRunStateFromPayload(data.runs[0], data.source || "snapshot");
            renderDag();
          }
          renderLatestRunsSelect();
        }
      } catch (_err) {
        renderLatestRunsSelect();
      }
    });
  }

  async function fetchMetrics(refresh) {
    if (IS_EMBEDDED_NO_API) {
      if (refresh) {
        const msg =
          state.lang === "id"
            ? 'Gunakan tombol "Refresh Live Telemetry" pada bar ⚡ Live Databricks Cloud Control di atas kanvas.'
            : 'Use "Refresh Live Telemetry" in the ⚡ Live Databricks Cloud Control bar above this canvas.';
        appendLog("info", msg);
        showToast(msg, "success");
      }
      return;
    }
    const reqKey = refresh ? "metricsRefresh" : "metricsInitial";
    return dedupRequest(reqKey, async () => {
      const btn = document.getElementById("refreshMetricsBtn");
      if (btn && refresh) btn.disabled = true;
      try {
        const data = await apiFetch(`/v1/control/metrics${refresh ? "?refresh=true" : ""}`);
        if (data && data.summary) {
          state.metrics = data;
          renderTelemetryRibbon();
          renderBiDashboard();
          if (refresh) {
            appendLog("info", `Refreshed Gold BI metrics (${data.source || "snapshot"}).`);
            showToast(
              data.source === "live_databricks" ? "Loaded live SQL Warehouse metrics." : "Verified snapshot metrics synced.",
              "success"
            );
          }
        }
      } catch (_err) {
        if (refresh) showToast("Using verified snapshot metrics (live warehouse unreachable).", "error");
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  function switchModalTab(tabId) {
    state.modalTab = tabId;
    document.querySelectorAll(".modal-tab").forEach((btn) => {
      const active = btn.getAttribute("data-tab") === tabId;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".modal-panel").forEach((panel) => {
      const active = panel.id === `modalPanel-${tabId}`;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
  }

  function openAuthModal(tabId) {
    const modal = document.getElementById("authModal");
    if (!modal) return;
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    switchModalTab(tabId || state.modalTab || "sso");
    renderHeaderAndHero();
  }

  function closeAuthModal() {
    const modal = document.getElementById("authModal");
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
  }

  function updateSegmentedButtons(attrName, activeValue) {
    document.querySelectorAll(`[data-${attrName}]`).forEach((btn) => {
      btn.classList.toggle("is-active", btn.getAttribute(`data-${attrName}`) === activeValue);
    });
  }

  function bindCopyButton(btnId, codeElId) {
    const btn = document.getElementById(btnId);
    const codeEl = document.getElementById(codeElId);
    if (!btn || !codeEl) return;
    btn.addEventListener("click", async () => {
      const text = codeEl.dataset.raw || codeEl.textContent || "";
      try {
        await global.navigator.clipboard.writeText(text);
        btn.textContent = t("common.copied");
        global.setTimeout(() => {
          btn.textContent = t("common.copy");
        }, 1600);
      } catch (_err) {
        showToast("Clipboard unavailable in this context.", "error");
      }
    });
  }

  function wireEvents() {
    document.querySelectorAll("[data-stack]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextStack = btn.getAttribute("data-stack");
        if (!nextStack || nextStack === state.stack) return;
        state.stack = nextStack;
        updateSegmentedButtons("stack", nextStack);
        resetDagToVerifiedSnapshot();
      });
    });

    document.querySelectorAll("[data-perspective]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextPersp = btn.getAttribute("data-perspective");
        if (!nextPersp || nextPersp === state.perspective) return;
        state.perspective = nextPersp;
        updateSegmentedButtons("perspective", nextPersp);
        renderHeaderAndHero();
        renderXRay();
        renderInspector();
      });
    });

    document.querySelectorAll("[data-lang]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextLang = btn.getAttribute("data-lang");
        if (!nextLang || nextLang === state.lang) return;
        state.lang = nextLang;
        updateSegmentedButtons("lang", nextLang);
        applyStaticTranslations();
        renderHeaderAndHero();
        renderXRay();
        renderDag();
        renderBiDashboard();
        if (state.copilot.source === "snapshot") {
          const bench = DATA.COPILOT_BENCHMARKS.find((b) => b.question === state.copilot.activeQuestion);
          if (bench) state.copilot.result = formatBenchmarkResult(bench, state.lang);
        }
        renderCopilotResult();
      });
    });

    const authStatusBtn = document.getElementById("authStatusBtn");
    if (authStatusBtn) authStatusBtn.addEventListener("click", () => openAuthModal("sso"));

    const closeBtn = document.getElementById("closeAuthModalBtn");
    if (closeBtn) closeBtn.addEventListener("click", closeAuthModal);

    const modalEl = document.getElementById("authModal");
    if (modalEl) {
      modalEl.addEventListener("click", (evt) => {
        if (evt.target === modalEl) closeAuthModal();
      });
    }
    global.addEventListener("keydown", (evt) => {
      if (evt.key === "Escape") closeAuthModal();
    });

    document.querySelectorAll(".modal-tab").forEach((tabBtn) => {
      tabBtn.addEventListener("click", () => switchModalTab(tabBtn.getAttribute("data-tab")));
    });

    const topRunBtn = document.getElementById("topRunLiveBtn");
    const dagRunBtn = document.getElementById("dagRunLiveBtn");
    if (topRunBtn) topRunBtn.addEventListener("click", triggerLiveDatabricksRun);
    if (dagRunBtn) dagRunBtn.addEventListener("click", triggerLiveDatabricksRun);

    const simBtn = document.getElementById("simulateBtn");
    const gateBtn = document.getElementById("testGateBtn");
    const resetBtn = document.getElementById("resetDagBtn");
    if (simBtn) simBtn.addEventListener("click", () => runSimulatedPipeline(false));
    if (gateBtn) gateBtn.addEventListener("click", () => runSimulatedPipeline(true));
    if (resetBtn) resetBtn.addEventListener("click", resetDagToVerifiedSnapshot);

    const runsSelect = document.getElementById("latestRunsSelect");
    if (runsSelect) {
      runsSelect.addEventListener("change", () => {
        const chosen = state.latestRuns.find((r) => String(r.run_id) === runsSelect.value);
        if (chosen) {
          clearTimers();
          state.stack = "databricks";
          updateSegmentedButtons("stack", "databricks");
          state.activeRun = buildRunStateFromPayload(chosen, chosen.source || "snapshot");
          renderDag();
          appendLog("info", `Loaded Run #${chosen.run_id} (${chosen.overall_status}).`);
        }
      });
    }

    const clearLogBtn = document.getElementById("clearLogBtn");
    if (clearLogBtn) {
      clearLogBtn.addEventListener("click", () => {
        const consoleEl = document.getElementById("telemetryConsole");
        if (consoleEl) consoleEl.innerHTML = "";
      });
    }

    const refreshMetricsBtn = document.getElementById("refreshMetricsBtn");
    if (refreshMetricsBtn) refreshMetricsBtn.addEventListener("click", () => fetchMetrics(true));

    const copilotForm = document.getElementById("copilotForm");
    if (copilotForm) {
      copilotForm.addEventListener("submit", (evt) => {
        evt.preventDefault();
        const inp = document.getElementById("copilotInput");
        if (inp) runCopilotQuestion(inp.value);
      });
    }

    const passcodeForm = document.getElementById("passcodeForm");
    if (passcodeForm) {
      passcodeForm.addEventListener("submit", async (evt) => {
        evt.preventDefault();
        const inp = document.getElementById("passcodeInput");
        const fb = document.getElementById("passcodeFeedback");
        const passcode = inp ? inp.value.trim() : "";
        if (!passcode) return;
        if (IS_EMBEDDED_NO_API) {
          if (fb) {
            fb.className = "form-feedback is-error";
            fb.textContent =
              state.lang === "id"
                ? 'Gunakan kolom passcode pada bar "⚡ Live Databricks Cloud Control" di atas kanvas ini.'
                : 'Use the passcode input in the "⚡ Live Databricks Cloud Control" bar directly above this canvas.';
          }
          return;
        }
        try {
          const res = await apiFetch("/v1/control/auth/verify", {
            method: "POST",
            body: JSON.stringify({ mode: "passcode", passcode }),
          });
          if (res.demo_token) setDemoToken(res.demo_token);
          if (fb) {
            fb.className = "form-feedback is-success";
            fb.textContent = "Unlocked live cloud execution for this browser session.";
          }
          if (inp) inp.value = "";
          await fetchControlStatus();
          await fetchLatestRuns();
          showToast("Live Databricks cloud unlocked.", "success");
        } catch (err) {
          if (fb) {
            fb.className = "form-feedback is-error";
            fb.textContent = err.message;
          }
        }
      });
    }

    const clearDemoBtn = document.getElementById("clearDemoTokenBtn");
    if (clearDemoBtn) {
      clearDemoBtn.addEventListener("click", async () => {
        setDemoToken("");
        const fb = document.getElementById("passcodeFeedback");
        if (fb) {
          fb.className = "form-feedback";
          fb.textContent = "Session passcode token cleared.";
        }
        await fetchControlStatus();
      });
    }

    const credsForm = document.getElementById("credentialsForm");
    if (credsForm) {
      credsForm.addEventListener("submit", async (evt) => {
        evt.preventDefault();
        const host = (document.getElementById("byokHostInput")?.value || "").trim();
        const token = (document.getElementById("byokTokenInput")?.value || "").trim();
        const jobRaw = (document.getElementById("byokJobInput")?.value || "").trim();
        const wh = (document.getElementById("byokWarehouseInput")?.value || "").trim();
        const fb = document.getElementById("credsFeedback");
        if (IS_EMBEDDED_NO_API) {
          if (fb) {
            fb.className = "form-feedback is-error";
            fb.textContent =
              state.lang === "id"
                ? "Verifikasi BYOK memerlukan Engine URL HTTP di sidebar Streamlit atau hosting FastAPI/Vercel."
                : "BYOK credential verification requires an HTTP Engine URL in the Streamlit sidebar or FastAPI/Vercel host.";
          }
          return;
        }
        try {
          const res = await apiFetch("/v1/control/auth/verify", {
            method: "POST",
            body: JSON.stringify({
              mode: "credentials",
              host,
              token,
              job_id: jobRaw ? Number(jobRaw) : null,
              warehouse_id: wh || null,
            }),
          });
          setByokCreds({
            host: res.host || host,
            token,
            job_id: res.job_id || (jobRaw ? Number(jobRaw) : null),
            warehouse_id: res.warehouse_id || wh || null,
            user_name: res.user_name || "Databricks User",
          });
          const tokenEl = document.getElementById("byokTokenInput");
          if (tokenEl) tokenEl.value = "";
          if (fb) {
            fb.className = "form-feedback is-success";
            fb.textContent = `Connected as ${res.user_name || "Databricks User"}.`;
          }
          await fetchControlStatus();
          await fetchLatestRuns();
          showToast(`Connected workspace as ${res.user_name || "Databricks User"}.`, "success");
        } catch (err) {
          if (fb) {
            fb.className = "form-feedback is-error";
            fb.textContent = err.message;
          }
        }
      });
    }

    const disconnectByokBtn = document.getElementById("disconnectByokBtn");
    if (disconnectByokBtn) {
      disconnectByokBtn.addEventListener("click", async () => {
        setByokCreds(null);
        const fb = document.getElementById("credsFeedback");
        if (fb) {
          fb.className = "form-feedback";
          fb.textContent = "Custom workspace credentials disconnected.";
        }
        await fetchControlStatus();
      });
    }

    bindCopyButton("copyXrayBtn", "xrayPayloadCode");
    bindCopyButton("copyCodeBtn", "inspCodeContent");
    bindCopyButton("copySqlBtn", "copilotSqlCode");

    global.addEventListener("resize", () => {
      global.requestAnimationFrame(drawDagConnectors);
    });
  }

  function init() {
    if (global.__medallionControlInitialized) {
      return;
    }
    global.__medallionControlInitialized = true;

    const hydratedBoot = hydrateFromBootState(global.MEDALLION_BOOT_STATE);

    applyStaticTranslations();
    renderHeaderAndHero();
    renderTelemetryRibbon();
    renderXRay();
    renderLatestRunsSelect();
    renderDag();
    renderBiDashboard();
    renderCopilotChips();
    renderCopilotResult();
    wireEvents();

    if (IS_EMBEDDED_NO_API && hydratedBoot) {
      appendLog(
        "info",
        `Hydrated Streamlit In-Process Cloud state (Run #${state.activeRun.run_id}, source: ${state.metrics.source || "snapshot"}).`
      );
      return;
    }

    appendLog(
      "info",
      "Initialized Omnichannel Retail Lakehouse Control Plane (Verified Run #647116123722071 loaded)."
    );

    if (!IS_EMBEDDED_NO_API) {
      fetchControlStatus();
      fetchLatestRuns();
      fetchMetrics(false);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);

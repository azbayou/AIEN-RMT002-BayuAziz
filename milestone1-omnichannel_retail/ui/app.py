"""Modern Enterprise Streamlit wrapper for the Medallion Control Plane and NL-to-SQL Copilot.

Supports both separated HTTP Engine mode (when ENGINE_URL is configured) and standalone
in-process execution (ideal for Streamlit Community Cloud and Databricks Apps).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SECRET_ENV_KEYS: tuple[str, ...] = (
    "ANALYTICS_DB_TARGET",
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_WAREHOUSE_ID",
    "DATABRICKS_CATALOG",
    "DATABRICKS_ORG_ID",
    "DATABRICKS_JOB_ID",
    "DEMO_PASSCODE",
    "NL2SQL_PROVIDER",
    "OPENAI_API_KEY",
    "ENGINE_URL",
)


def _hydrate_env_from_streamlit_secrets() -> None:
    """Populate os.environ from Streamlit secrets if present without exposing values."""

    try:
        secrets = st.secrets
        for key in _SECRET_ENV_KEYS:
            if key in secrets:
                raw_val = secrets[key]
                if isinstance(raw_val, str) and raw_val.strip():
                    os.environ.setdefault(key, raw_val.strip())
                elif isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
                    os.environ.setdefault(key, str(raw_val))
    except Exception:
        return


_hydrate_env_from_streamlit_secrets()
load_dotenv(PROJECT_ROOT / ".env")

from engine.api.control_plane import (  # noqa: E402
    get_inprocess_boot_state,
    get_inprocess_run_status,
    trigger_inprocess_job,
    verify_passcode_value,
)
from engine.api.models import AnalysisRequest, ChatMessage  # noqa: E402
from engine.core.orchestrator import analyze  # noqa: E402
from engine.llm.providers import build_provider  # noqa: E402
from ui.api_client import EngineClient, EngineUnavailableError  # noqa: E402
from ui.renderers import build_figure  # noqa: E402

DEFAULT_DATABRICKS_HOST = "https://dbc-118afc22-e599.cloud.databricks.com"
DEFAULT_DATABRICKS_ORG_ID = "7474648823106559"
DEFAULT_DATABRICKS_JOB_ID = "1033864740434224"
DEFAULT_DATABRICKS_CATALOG = "retail_analytics"
WEB_DIR = Path(__file__).resolve().parent / "web"

STARTER_QUESTIONS: tuple[str, ...] = (
    "What is total net revenue by sales channel?",
    "Which product categories generated the most revenue?",
    "Which campaigns had the best roas?",
    "What was the daily net revenue?",
    "What was the daily stockout rate?",
    "Which channels have the most repeat customers?",
)

_CSS_LINK_RE = re.compile(
    r'<link\b[^>]*href=["\'](?:\./|/)?assets/styles\.css(?:\?[^"\']*)?["\'][^>]*>',
    re.IGNORECASE,
)
_DATA_SCRIPT_RE = re.compile(
    r'<script\b[^>]*src=["\'](?:\./|/)?assets/data\.js(?:\?[^"\']*)?["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)
_APP_SCRIPT_RE = re.compile(
    r'<script\b[^>]*src=["\'](?:\./|/)?assets/app\.js(?:\?[^"\']*)?["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)

_STATUS_BADGE_MAP: dict[str, str] = {
    "SUCCESS": "🟢 SUCCESS",
    "RUNNING": "🟡 RUNNING",
    "PENDING": "⚪ PENDING",
    "FAILED": "🔴 FAILED",
}

_ENTERPRISE_DARK_CSS = """
<style>
  :root {
    --medallion-bg: #090b10;
    --medallion-surface: #111520;
    --medallion-card: #161b29;
    --medallion-border: rgba(148, 163, 184, 0.14);
    --medallion-lava: #ff3621;
    --medallion-cyan: #06b6d4;
  }

  .stApp {
    background-color: var(--medallion-bg);
    color: #f8fafc;
  }

  [data-testid="stHeader"] {
    background: rgba(9, 11, 16, 0.72);
    backdrop-filter: blur(8px);
  }

  .block-container {
    padding-top: 1.5rem;
    padding-bottom: 1.5rem;
    max-width: 100%;
  }

  [data-testid="stSidebar"] {
    background-color: var(--medallion-surface);
    border-right: 1px solid var(--medallion-border);
  }

  [data-testid="stSidebar"] .stButton > button,
  [data-testid="stSidebar"] [data-testid="stLinkButton"] > a {
    background-color: var(--medallion-card);
    border: 1px solid var(--medallion-border);
    border-radius: 8px;
    color: #f1f5f9;
    transition: border-color 0.15s ease, background-color 0.15s ease;
  }

  [data-testid="stSidebar"] .stButton > button:hover,
  [data-testid="stSidebar"] [data-testid="stLinkButton"] > a:hover {
    border-color: var(--medallion-cyan);
    background-color: #1c2233;
  }

  .stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    background-color: var(--medallion-surface);
    border: 1px solid var(--medallion-border);
    border-radius: 10px;
    padding: 0.3rem;
  }

  .stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 0.5rem 1rem;
    color: #94a3b8;
    font-weight: 500;
  }

  .stTabs [aria-selected="true"] {
    background-color: var(--medallion-card);
    color: #f8fafc;
    border: 1px solid rgba(255, 54, 33, 0.45);
  }

  .stTabs [data-baseweb="tab-highlight"] {
    background-color: var(--medallion-lava);
  }

  [data-testid="stExpander"] {
    background-color: var(--medallion-surface);
    border: 1px solid var(--medallion-border);
    border-radius: 8px;
  }
</style>
"""


def _normalize_host(raw_host: str) -> str:
    cleaned = raw_host.strip().rstrip("/")
    if not cleaned:
        return DEFAULT_DATABRICKS_HOST
    if not cleaned.startswith(("http://", "https://")):
        return f"https://{cleaned}"
    return cleaned


def _build_databricks_urls() -> tuple[str, str, str]:
    host = _normalize_host(os.getenv("DATABRICKS_HOST", DEFAULT_DATABRICKS_HOST))
    org_id = os.getenv("DATABRICKS_ORG_ID", DEFAULT_DATABRICKS_ORG_ID).strip()
    job_id = (
        os.getenv("DATABRICKS_JOB_ID", DEFAULT_DATABRICKS_JOB_ID).strip()
        or DEFAULT_DATABRICKS_JOB_ID
    )
    workspace_url = f"{host}/?o={org_id}" if org_id else host
    job_url = f"{workspace_url}#job/{job_id}"
    return workspace_url, job_url, job_id


def _inject_before_closing_tag(html: str, tag_name: str, block: str) -> str:
    lower_html = html.lower()
    closing_tag = f"</{tag_name.lower()}>"
    idx = lower_html.rfind(closing_tag)
    if idx != -1:
        return f"{html[:idx]}{block}\n{html[idx:]}"
    return f"{html}\n{block}"


def _escape_inline_script(raw_text: str) -> str:
    return re.sub(r"</script", lambda _m: r"<\/script", raw_text, flags=re.IGNORECASE)


def build_medallion_html(
    engine_url: str,
    web_dir: Path | None = None,
    boot_state: dict[str, object] | None = None,
) -> str | None:
    """Bundle `ui/web/*` into a self-contained HTML document with injected API base and boot state."""

    target_dir = web_dir or WEB_DIR
    index_path = target_dir / "index.html"
    css_path = target_dir / "styles.css"
    data_js_path = target_dir / "data.js"
    app_js_path = target_dir / "app.js"

    if not all(path.is_file() for path in (index_path, css_path, data_js_path, app_js_path)):
        return None

    html = index_path.read_text(encoding="utf-8")
    css_text = css_path.read_text(encoding="utf-8")
    data_js_text = data_js_path.read_text(encoding="utf-8")
    app_js_text = app_js_path.read_text(encoding="utf-8")

    safe_css = re.sub(r"</style", lambda _m: r"<\/style", css_text, flags=re.IGNORECASE)
    safe_data_js = _escape_inline_script(data_js_text)
    safe_app_js = _escape_inline_script(app_js_text)

    api_base = engine_url.strip().rstrip("/")
    style_block = f"<style>\n{safe_css}\n</style>"
    boot_state_block = ""
    if boot_state is not None:
        safe_boot_json = _escape_inline_script(json.dumps(boot_state, default=str))
        boot_state_block = f"\n<script>window.MEDALLION_BOOT_STATE = {safe_boot_json};</script>"
    api_base_block = (
        f"<script>window.MEDALLION_API_BASE = {json.dumps(api_base)};</script>{boot_state_block}"
    )
    data_script_block = f"<script>\n{safe_data_js}\n</script>"
    app_script_block = f"<script>\n{safe_app_js}\n</script>"

    html, css_count = _CSS_LINK_RE.subn(lambda _m: style_block, html)
    if css_count == 0:
        html = _inject_before_closing_tag(html, "head", style_block)

    head_end = html.lower().find("</head>")
    data_match = _DATA_SCRIPT_RE.search(html)

    # If script tags live inside <head> (e.g. with defer), strip them and place inline
    # scripts right before </body> so the DOM exists before execution.
    if data_match is not None and head_end != -1 and data_match.start() < head_end:
        html = _DATA_SCRIPT_RE.sub("", html)
        data_inlined = False
    elif data_match is not None:
        html = _DATA_SCRIPT_RE.sub(
            lambda _m: f"{api_base_block}\n{data_script_block}",
            html,
            count=1,
        )
        data_inlined = True
    else:
        data_inlined = False

    head_end = html.lower().find("</head>")
    app_match = _APP_SCRIPT_RE.search(html)
    if app_match is not None and head_end != -1 and app_match.start() < head_end:
        html = _APP_SCRIPT_RE.sub("", html)
        app_inlined = False
    elif app_match is not None:
        if data_inlined:
            replacement = app_script_block
        else:
            replacement = f"{api_base_block}\n{data_script_block}\n{app_script_block}"
            data_inlined = True
        html = _APP_SCRIPT_RE.sub(lambda _m: replacement, html, count=1)
        app_inlined = True
    else:
        app_inlined = False

    if not data_inlined and not app_inlined:
        combined = f"{api_base_block}\n{data_script_block}\n{app_script_block}"
        html = _inject_before_closing_tag(html, "body", combined)
    elif not data_inlined:
        html = _inject_before_closing_tag(html, "body", f"{api_base_block}\n{data_script_block}")
    elif not app_inlined:
        html = _inject_before_closing_tag(html, "body", app_script_block)

    return html


def _render_assistant(result: dict[str, object]) -> None:
    st.markdown(str(result.get("answer", "")))
    figure = build_figure(result)
    if figure is not None:
        st.plotly_chart(figure, use_container_width=True)
    rows = result.get("rows", [])
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    warnings = result.get("warnings", [])
    for warning in warnings if isinstance(warnings, list) else []:
        st.warning(str(warning))
    with st.expander("Show SQL and provenance"):
        st.code(str(result.get("sql", "")), language="sql")
        tables_used = result.get("tables_used", [])
        tables_label = (
            ", ".join(str(table) for table in tables_used)
            if isinstance(tables_used, list)
            else ""
        )
        st.caption(f"Tables: {tables_label}")
        st.caption(f"Execution: {result.get('execution_ms', '?')} ms")


def _load_boot_state(unlocked: bool, refresh_metrics: bool = False) -> dict[str, Any] | None:
    try:
        return get_inprocess_boot_state(unlocked=unlocked, refresh_metrics=refresh_metrics)
    except Exception:
        return None


def _render_cloud_control_bar(
    workspace_url: str,
    job_url: str,
    job_id: str,
) -> dict[str, Any] | None:
    unlocked = bool(st.session_state.get("cloud_unlocked", False))
    if st.session_state.get("medallion_boot_state") is None:
        st.session_state.medallion_boot_state = _load_boot_state(
            unlocked=unlocked,
            refresh_metrics=False,
        )

    boot_state: dict[str, Any] | None = st.session_state.get("medallion_boot_state")
    status = boot_state.get("status", {}) if isinstance(boot_state, dict) else {}
    latest_runs = (
        boot_state.get("latest_runs", {}).get("runs", [])
        if isinstance(boot_state, dict) and isinstance(boot_state.get("latest_runs"), dict)
        else []
    )
    read_ready = bool(status.get("read_ready", False))
    live_ready = bool(status.get("live_ready", False))
    requires_passcode = bool(status.get("requires_passcode", False))
    auth_mode = str(status.get("auth_mode", "simulation_only"))
    effective_ws_url = str(status.get("workspace_url") or workspace_url)
    effective_job_url = str(status.get("job_url") or job_url)

    with st.expander(
        f"⚡ Live Databricks Cloud Control — Serverless Job #{job_id}",
        expanded=True,
    ):
        col_status, col_refresh, col_ws = st.columns([2.2, 1.3, 1.3])
        read_badge = "🟢 Live Read-Ready" if read_ready else "🟡 Simulation Mode"
        trigger_badge = "⚡ Trigger Ready" if live_ready else "🔒 Trigger Locked"
        col_status.markdown(
            f"**Workspace Status:** {read_badge} · {trigger_badge} · Mode: `{auth_mode}`"
        )
        if col_refresh.button("🔄 Refresh Live Telemetry", use_container_width=True):
            refreshed = _load_boot_state(unlocked=unlocked, refresh_metrics=True)
            if refreshed is not None:
                st.session_state.medallion_boot_state = refreshed
                boot_state = refreshed
                status = boot_state.get("status", {})
                latest_runs = boot_state.get("latest_runs", {}).get("runs", [])
                read_ready = bool(status.get("read_ready", False))
                live_ready = bool(status.get("live_ready", False))
                requires_passcode = bool(status.get("requires_passcode", False))
                st.toast("Live Databricks telemetry refreshed.", icon="🔄")
        col_ws.link_button(
            "Open Databricks Workspace ↗",
            effective_ws_url,
            use_container_width=True,
        )

        if requires_passcode and not unlocked:
            col_pw, col_unlock = st.columns([2.5, 1.2])
            passcode_attempt = col_pw.text_input(
                "Demo Passcode",
                type="password",
                key="cloud_demo_passcode",
                label_visibility="collapsed",
                placeholder="Enter Demo Passcode to unlock live job trigger...",
            )
            if col_unlock.button("🔓 Unlock Live Trigger", use_container_width=True):
                if verify_passcode_value(passcode_attempt):
                    st.session_state.cloud_unlocked = True
                    st.session_state.medallion_boot_state = _load_boot_state(
                        unlocked=True,
                        refresh_metrics=False,
                    )
                    st.success("Live Databricks job trigger unlocked for this session.")
                    st.rerun()
                else:
                    st.error("Invalid demo passcode.")
        else:
            default_run_id = latest_runs[0].get("run_id") if latest_runs else None
            poll_run_id = st.session_state.get("active_run_id") or default_run_id
            col_trig, col_poll, col_runlink = st.columns([1.6, 1.4, 1.4])
            if col_trig.button(
                "⚡ Trigger Live Run on Databricks",
                type="primary",
                use_container_width=True,
                disabled=not live_ready,
            ):
                try:
                    trigger_res = trigger_inprocess_job(unlocked=True)
                    run_id = trigger_res.get("run_id")
                    run_url = str(trigger_res.get("run_page_url") or effective_job_url)
                    st.session_state.active_run_id = run_id
                    st.session_state.active_run_url = run_url
                    if trigger_res.get("already_running"):
                        st.info(
                            f"Concurrent Run Guard: Run #{run_id} is already running on Databricks."
                        )
                    else:
                        st.success(f"Triggered Serverless Lakeflow Run #{run_id}!")
                    if run_id is not None:
                        st.session_state.active_run_detail = get_inprocess_run_status(int(run_id))
                    st.session_state.medallion_boot_state = _load_boot_state(
                        unlocked=True,
                        refresh_metrics=False,
                    )
                    boot_state = st.session_state.medallion_boot_state
                except Exception as exc:
                    st.error(f"Could not trigger Databricks job: {exc}")

            if col_poll.button(
                "🔄 Poll Active Run Status",
                use_container_width=True,
                disabled=poll_run_id is None,
            ):
                try:
                    run_detail = get_inprocess_run_status(int(poll_run_id))
                    st.session_state.active_run_id = run_detail.get("run_id", poll_run_id)
                    st.session_state.active_run_url = str(
                        run_detail.get("run_page_url") or effective_job_url
                    )
                    st.session_state.active_run_detail = run_detail
                except Exception as exc:
                    st.error(f"Could not poll run status: {exc}")

            active_url = str(st.session_state.get("active_run_url") or effective_job_url)
            active_label = (
                f"Open Run #{st.session_state['active_run_id']} ↗"
                if st.session_state.get("active_run_id")
                else f"Open Lakeflow Job {job_id} ↗"
            )
            col_runlink.link_button(active_label, active_url, use_container_width=True)

        active_detail = st.session_state.get("active_run_detail")
        if isinstance(active_detail, dict) and active_detail.get("tasks"):
            overall = str(active_detail.get("overall_status", "UNKNOWN"))
            run_id_val = active_detail.get("run_id", "?")
            run_url_val = str(active_detail.get("run_page_url") or effective_job_url)
            st.caption(
                f"Run `#{run_id_val}` · Status: `{overall}` · "
                f"[Inspect in Databricks ↗]({run_url_val})"
            )
            tasks = active_detail["tasks"]
            task_cols = st.columns(len(tasks))
            for idx, task in enumerate(tasks):
                task_key = str(task.get("task_key", f"task_{idx}"))
                task_status = str(task.get("status", "UNKNOWN"))
                badge = _STATUS_BADGE_MAP.get(task_status, task_status)
                dur_ms = task.get("execution_duration_ms") or 0
                dur_label = f"{round(float(dur_ms) / 1000, 1)}s" if dur_ms else "—"
                task_cols[idx].markdown(
                    f"**`{task_key}`**\n\n{badge} · `{dur_label}`"
                )

    return boot_state


def _execute_copilot_query(
    engine_url: str,
    question: str,
    history: list[dict[str, str]],
    max_rows: int,
    visualization: str,
) -> dict[str, Any]:
    cleaned_url = engine_url.strip()
    if cleaned_url:
        try:
            return EngineClient(cleaned_url).analyze(
                question,
                history,
                max_rows,
                visualization,
            )
        except EngineUnavailableError as exc:
            st.toast(f"Engine URL unreachable ({exc}); running in-process fallback.", icon="⚠️")

    chat_history = [
        ChatMessage(role=item["role"], content=item["content"])
        for item in history[-6:]
        if item.get("role") in {"user", "assistant"} and str(item.get("content", "")).strip()
    ]
    request = AnalysisRequest(
        question=question,
        history=chat_history,
        max_rows=max_rows,
        visualization=visualization,  # type: ignore[arg-type]
    )
    return analyze(request, build_provider()).model_dump()


def main() -> None:
    st.set_page_config(
        page_title="Omnichannel Retail Lakehouse | Medallion Control Plane",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _hydrate_env_from_streamlit_secrets()
    st.markdown(_ENTERPRISE_DARK_CSS, unsafe_allow_html=True)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    workspace_url, job_url, job_id = _build_databricks_urls()
    active_target = os.getenv("ANALYTICS_DB_TARGET", "neon")
    active_catalog = os.getenv("DATABRICKS_CATALOG", DEFAULT_DATABRICKS_CATALOG)

    with st.sidebar:
        st.markdown("### Lakehouse Control")
        st.link_button(
            "Open Databricks Workspace ↗",
            workspace_url,
            use_container_width=True,
        )
        st.link_button(
            f"Open Lakeflow Job {job_id} ↗",
            job_url,
            use_container_width=True,
        )
        st.caption(f"Active target (`ANALYTICS_DB_TARGET`): `{active_target}`")
        st.caption(f"Unity Catalog: `{active_catalog}`")
        engine_url = st.text_input(
            "Engine URL",
            os.getenv("ENGINE_URL", ""),
            placeholder="http://localhost:8000 (blank = in-process)",
            help="Leave blank to run the NL-to-SQL engine directly in-process.",
        )

        st.divider()
        st.header("Conversation")
        if st.button("New conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        max_rows = st.slider(
            "Maximum rows",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
        )
        visualization = st.selectbox(
            "Visualization",
            ["auto", "table_only", "chart_only"],
        )

    tab_control, tab_copilot = st.tabs(
        [
            "🏗️ Medallion Architecture & Live Databricks Control",
            "💬 AI NL-to-SQL Copilot",
        ]
    )

    with tab_control:
        boot_state = _render_cloud_control_bar(workspace_url, job_url, job_id)
        bundled_html = build_medallion_html(engine_url, boot_state=boot_state)
        if bundled_html is None:
            st.info(
                "Medallion web assets (`ui/web/index.html`, `styles.css`, `data.js`, `app.js`) "
                "are not present on disk yet. Once available, the interactive Medallion control "
                "plane will render here automatically."
            )
        else:
            components.html(bundled_html, height=1500, scrolling=True)

    with tab_copilot:
        st.subheader("AI NL-to-SQL Copilot")
        st.caption(
            "Ask questions about the Gold layer. The engine generates safe read-only SQL "
            "and chooses a chart when useful."
        )

        selected_question: str | None = None
        st.caption("Starter benchmark questions:")
        starter_cols = st.columns(3)
        for idx, starter in enumerate(STARTER_QUESTIONS):
            if starter_cols[idx % 3].button(
                starter,
                key=f"starter_question_{idx}",
                use_container_width=True,
            ):
                selected_question = starter

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.markdown(message["content"])
                else:
                    _render_assistant(message["result"])

        typed_question = st.chat_input(
            "Ask about revenue, customers, products, inventory, or campaigns"
        )
        question = typed_question or selected_question
        if not question:
            return

        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        history = [
            {"role": message["role"], "content": message["content"]}
            for message in st.session_state.messages[:-1]
            if message["role"] in {"user", "assistant"}
        ]
        with st.chat_message("assistant"):
            with st.spinner("Analyzing the Gold layer…"):
                try:
                    result = _execute_copilot_query(
                        engine_url,
                        question,
                        history,
                        max_rows,
                        visualization,
                    )
                except Exception as exc:
                    st.error(f"Analytics engine error: {exc}")
                    return
            _render_assistant(result)
        st.session_state.messages.append(
            {"role": "assistant", "content": result.get("answer", ""), "result": result}
        )


if __name__ == "__main__":
    main()

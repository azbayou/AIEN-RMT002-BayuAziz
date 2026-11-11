"""Global UI configuration, theme state, and brand assets for Miyo HR Assistant."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
GUNUNGAN_LOGO = str(BASE_DIR / "public" / "img" / "gunungan.png")
MIYO_LOGO = str(BASE_DIR / "public" / "img" / "miyo.png")
STYLE_CSS_PATH = BASE_DIR / "public" / "style.css"


def init_page_and_theme() -> None:
    """Initialize page configuration, session state keys, and dynamic Tailwind theme."""
    st.set_page_config(
        page_title="Miyo — Asisten HR Nusantara Digital",
        page_icon=MIYO_LOGO if os.path.exists(MIYO_LOGO) else None,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Core session state initialization
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if "active_persona" not in st.session_state:
        st.session_state["active_persona"] = None
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []
    if "confirmed_proposals" not in st.session_state:
        st.session_state["confirmed_proposals"] = set()
    if "ui_theme" not in st.session_state:
        st.session_state["ui_theme"] = "dark"

    # Inject base CSS and active theme CSS variables directly (Zero Script tags)
    current_theme = st.session_state.get("ui_theme", "dark")
    if STYLE_CSS_PATH.exists():
        css_content = STYLE_CSS_PATH.read_text(encoding="utf-8")
        if current_theme == "light":
            theme_vars = """
            :root, .stApp, [data-testid="stAppViewContainer"] {
                --bg-app: #f8fafc;
                --bg-surface: #ffffff;
                --bg-surface-elevated: #f1f5f9;
                --bg-card: #ffffff;
                --bg-card-hover: #f8fafc;
                --border-subtle: #cbd5e1;
                --border-focus: #0284c7;
                --text-primary: #0f172a;
                --text-secondary: #334155;
                --text-muted: #64748b;
                --accent-sky: #0284c7;
                --accent-sky-dark: #0369a1;
                --accent-emerald: #059669;
                --accent-rose: #e11d48;
                --accent-violet: #9333ea;
                --accent-amber: #d97706;
            }
            .stApp, [data-testid="stAppViewContainer"], .main {
                background-color: #f8fafc !important;
                color: #0f172a !important;
            }
            [data-testid="stSidebar"] {
                background-color: #f1f5f9 !important;
                color: #0f172a !important;
                border-right: 1px solid #cbd5e1 !important;
            }
            [data-testid="stHeader"] {
                background-color: #f8fafc !important;
            }
            .stMarkdown, .stText, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span {
                color: #0f172a !important;
            }
            [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
                color: #0f172a !important;
            }
            [data-testid="stExpander"] {
                background-color: #ffffff !important;
                border: 1px solid #cbd5e1 !important;
                border-radius: 8px !important;
            }
            [data-testid="stExpander"] details summary span {
                color: #0f172a !important;
            }
            div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="select"] > div {
                background-color: #ffffff !important;
                border: 1px solid #cbd5e1 !important;
                color: #0f172a !important;
            }
            div[data-baseweb="input"] input, div[data-baseweb="base-input"] input, textarea {
                color: #0f172a !important;
            }
            """
        else:
            theme_vars = """
            :root, .stApp, [data-testid="stAppViewContainer"] {
                --bg-app: #090d16;
                --bg-surface: #0f172a;
                --bg-surface-elevated: #1e293b;
                --bg-card: #1e293b;
                --bg-card-hover: #273549;
                --border-subtle: #334155;
                --border-focus: #38bdf8;
                --text-primary: #f8fafc;
                --text-secondary: #cbd5e1;
                --text-muted: #94a3b8;
                --accent-sky: #38bdf8;
                --accent-sky-dark: #0284c7;
                --accent-emerald: #10b981;
                --accent-rose: #f43f5e;
                --accent-violet: #a855f7;
                --accent-amber: #f59e0b;
            }
            .stApp, [data-testid="stAppViewContainer"], .main {
                background-color: #090d16 !important;
                color: #f8fafc !important;
            }
            [data-testid="stSidebar"] {
                background-color: #0f172a !important;
                color: #f8fafc !important;
                border-right: 1px solid #334155 !important;
            }
            [data-testid="stHeader"] {
                background-color: #090d16 !important;
            }
            .stMarkdown, .stText, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span {
                color: #f8fafc !important;
            }
            [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
                color: #f8fafc !important;
            }
            [data-testid="stExpander"] {
                background-color: #1e293b !important;
                border: 1px solid #334155 !important;
                border-radius: 8px !important;
            }
            [data-testid="stExpander"] details summary span {
                color: #f8fafc !important;
            }
            div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="select"] > div {
                background-color: #1e293b !important;
                border: 1px solid #334155 !important;
                color: #f8fafc !important;
            }
            div[data-baseweb="input"] input, div[data-baseweb="base-input"] input, textarea {
                color: #f8fafc !important;
            }
            """
        st.markdown(f"<style>\n{css_content}\n{theme_vars}\n</style>", unsafe_allow_html=True)

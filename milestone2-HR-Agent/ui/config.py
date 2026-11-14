"""Global UI configuration, theme state, and brand assets for Miyo HR Assistant."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
_public_dir = BASE_DIR / "ui" / "public"
GUNUNGAN_LOGO = str(_public_dir / "img" / "gunungan.png")
MIYO_LOGO = str(_public_dir / "img" / "miyo.png")
STYLE_CSS_PATH = _public_dir / "style.css"


def init_page_and_theme() -> None:
    """Initialize page configuration, session state keys, and dynamic Claude Tailwind theme."""
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
    if "active_tab" not in st.session_state:
        st.session_state["active_tab"] = "Asisten Kebijakan"

    # Inject base CSS and active theme CSS variables directly (Zero Script tags)
    current_theme = st.session_state.get("ui_theme", "dark")
    if STYLE_CSS_PATH.exists():
        css_content = STYLE_CSS_PATH.read_text(encoding="utf-8")
        if current_theme == "light":
            theme_vars = """
            :root, .stApp, [data-testid="stAppViewContainer"] {
                --bg-app: #faf9f5;
                --bg-surface: #f4f3ee;
                --bg-surface-elevated: #ffffff;
                --bg-card: #ffffff;
                --bg-card-hover: #f9f8f4;
                --border-subtle: #e5e4de;
                --border-focus: #ea580c;
                --text-primary: #191816;
                --text-secondary: #57564f;
                --text-muted: #8c8a82;
                --accent-orange: #ea580c;
                --accent-orange-hover: #c2410c;
                --accent-orange-subtle: rgba(234, 88, 12, 0.08);
                --accent-emerald: #059669;
                --accent-rose: #e11d48;
                --accent-amber: #d97706;
                --accent-violet: #9333ea;
            }
            .stApp, [data-testid="stAppViewContainer"], .main {
                background-color: #faf9f5 !important;
                color: #191816 !important;
            }
            [data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {
                background-color: #faf9f5 !important;
                background: #faf9f5 !important;
            }
            [data-testid="stSidebar"] {
                background-color: #f4f3ee !important;
                color: #191816 !important;
                border-right: 1px solid #e5e4de !important;
            }
            [data-testid="stHeader"] {
                background-color: #faf9f5 !important;
            }
            .stMarkdown, .stText, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span {
                color: #191816 !important;
            }
            [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
                color: #191816 !important;
            }
            [data-testid="stExpander"] {
                background-color: #ffffff !important;
                border: 1px solid #e5e4de !important;
                border-radius: 8px !important;
            }
            [data-testid="stExpander"] details summary span {
                color: #191816 !important;
            }
            div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="select"] > div {
                background-color: #ffffff !important;
                border: 1px solid #e5e4de !important;
                color: #191816 !important;
            }
            div[data-baseweb="input"] input, div[data-baseweb="base-input"] input, textarea {
                color: #191816 !important;
            }
            """
        else:
            theme_vars = """
            :root, .stApp, [data-testid="stAppViewContainer"] {
                --bg-app: #141311;
                --bg-surface: #1c1b18;
                --bg-surface-elevated: #262522;
                --bg-card: #21201d;
                --bg-card-hover: #2c2b26;
                --border-subtle: #33322c;
                --border-focus: #da7756;
                --text-primary: #f4f3ee;
                --text-secondary: #b5b3aa;
                --text-muted: #7e7c74;
                --accent-orange: #da7756;
                --accent-orange-hover: #e28a6c;
                --accent-orange-subtle: rgba(218, 119, 86, 0.12);
                --accent-emerald: #10b981;
                --accent-rose: #f43f5e;
                --accent-amber: #f59e0b;
                --accent-violet: #a855f7;
            }
            .stApp, [data-testid="stAppViewContainer"], .main {
                background-color: #141311 !important;
                color: #f4f3ee !important;
            }
            [data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {
                background-color: #141311 !important;
                background: #141311 !important;
            }
            [data-testid="stSidebar"] {
                background-color: #1c1b18 !important;
                color: #f4f3ee !important;
                border-right: 1px solid #33322c !important;
            }
            [data-testid="stHeader"] {
                background-color: #141311 !important;
            }
            .stMarkdown, .stText, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span {
                color: #f4f3ee !important;
            }
            [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
                color: #f4f3ee !important;
            }
            [data-testid="stExpander"] {
                background-color: #262522 !important;
                border: 1px solid #33322c !important;
                border-radius: 8px !important;
            }
            [data-testid="stExpander"] details summary span {
                color: #f4f3ee !important;
            }
            div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="select"] > div {
                background-color: #262522 !important;
                border: 1px solid #33322c !important;
                color: #f4f3ee !important;
            }
            div[data-baseweb="input"] input, div[data-baseweb="base-input"] input, textarea {
                color: #f4f3ee !important;
            }
            """
        st.markdown(f"<style>\n{css_content}\n{theme_vars}\n</style>", unsafe_allow_html=True)

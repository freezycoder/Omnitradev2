from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from textwrap import dedent

import altair as alt
import pandas as pd
import streamlit as st


THEME = {
    "background": "#0b0c10",
    "surface": "#0e1118",
    "surface_alt": "#131820",
    "surface_soft": "#181e28",
    "text": "#cdd4df",
    "muted": "#6a7687",
    "muted_soft": "#3c4a5c",
    "border": "#1a2130",
    "border_strong": "#222c3c",
    "accent": "oklch(75% 0.14 82)",
    "accent_soft": "oklch(75% 0.14 82 / 0.10)",
    "accent_glow": "oklch(75% 0.14 82 / 0.06)",
    "positive": "oklch(68% 0.17 155)",
    "positive_soft": "oklch(68% 0.17 155 / 0.10)",
    "watch": "oklch(75% 0.14 82)",
    "watch_soft": "oklch(75% 0.14 82 / 0.08)",
    "neutral": "#6a7687",
    "neutral_soft": "oklch(65% 0.14 240 / 0.08)",
    "negative": "oklch(62% 0.20 22)",
    "negative_soft": "oklch(62% 0.20 22 / 0.10)",
    "price_line": "#cdd4df",
    "ma_fast": "oklch(75% 0.14 82)",
    "ma_slow": "#6a7687",
    "rsi_line": "oklch(75% 0.14 82)",
    "macd_line": "oklch(68% 0.17 155)",
    "macd_signal": "oklch(62% 0.20 22)",
    "grid": "#1a2130",
}

TONE_META = {
    "positive": {"text": "oklch(68% 0.17 155)", "bg": "oklch(68% 0.17 155 / 0.10)", "border": "oklch(68% 0.17 155 / 0.35)"},
    "watch":    {"text": "oklch(75% 0.14 82)",  "bg": "oklch(75% 0.14 82 / 0.08)",  "border": "oklch(75% 0.14 82 / 0.35)"},
    "neutral":  {"text": "#6a7687",              "bg": "oklch(65% 0.14 240 / 0.06)", "border": "oklch(32% 0.020 240)"},
    "negative": {"text": "oklch(62% 0.20 22)",   "bg": "oklch(62% 0.20 22 / 0.10)",  "border": "oklch(62% 0.20 22 / 0.35)"},
}

ASCII_HEADER = ""


def inject_styles() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,500;0,600;1,300&display=swap');

        :root {{
            --bg:            oklch(9%  0.008 240);
            --bg1:           oklch(12% 0.010 240);
            --bg2:           oklch(15% 0.012 240);
            --bg3:           oklch(18% 0.012 240);
            --border:        oklch(25% 0.015 240);
            --border-bright: oklch(32% 0.020 240);
            --text:          oklch(88% 0.010 240);
            --text-dim:      oklch(55% 0.010 240);
            --text-muted:    oklch(38% 0.010 240);
            --amber:         oklch(75% 0.14 82);
            --amber-dim:     oklch(55% 0.10 82);
            --green:         oklch(68% 0.17 155);
            --green-dim:     oklch(45% 0.12 155);
            --red:           oklch(62% 0.20 22);
            --red-dim:       oklch(42% 0.14 22);
            --blue:          oklch(65% 0.14 240);
            --purple:        oklch(65% 0.14 290);
        }}

        /* ── Global ──────────────────────────────────────────────── */
        * {{
            font-family: 'IBM Plex Mono', ui-monospace, 'Courier New', monospace !important;
            box-sizing: border-box !important;
        }}

        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] *,
        .rank-sheet-row,
        .feature-panel,
        .detail-box,
        .research-box,
        .signal-card,
        .trade-card,
        .terminal-box {{
            word-break: normal !important;
            overflow-wrap: normal !important;
            hyphens: none !important;
        }}

        /* ── App background ──────────────────────────────────────── */
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"] {{
            background: var(--bg) !important;
            background-image: none !important;
            color: var(--text) !important;
        }}

        /* ── Sidebar ─────────────────────────────────────────────── */
        [data-testid="stSidebar"],
        section[data-testid="stSidebar"] {{
            background: var(--bg1) !important;
            background-image: none !important;
            border-right: 1px solid var(--border) !important;
            box-shadow: none !important;
        }}

        [data-testid="stSidebar"] .stButton > button {{
            justify-content: flex-start !important;
            min-height: 2.4rem !important;
            border-radius: 0 !important;
            padding: 0.44rem 0.875rem !important;
            border: none !important;
            border-left: 2px solid transparent !important;
            background: transparent !important;
            background-image: none !important;
            color: var(--text-dim) !important;
            font-size: 10px !important;
            font-weight: 400 !important;
            letter-spacing: 0.02em !important;
            text-transform: none !important;
            box-shadow: none !important;
            transition: background 0.15s, color 0.15s, border-color 0.15s !important;
        }}

        [data-testid="stSidebar"] .stButton > button:hover {{
            background: var(--bg2) !important;
            background-image: none !important;
            color: var(--text) !important;
            border-left-color: transparent !important;
            box-shadow: none !important;
            transform: none !important;
        }}

        [data-testid="stSidebar"] [data-testid="baseButton-primary"] {{
            background: oklch(75% 0.14 82 / 0.08) !important;
            background-image: none !important;
            border-left-color: var(--amber) !important;
            color: var(--amber) !important;
            box-shadow: none !important;
        }}

        [data-testid="stSidebar"] [data-testid="baseButton-primary"]:hover {{
            background: oklch(75% 0.14 82 / 0.12) !important;
            color: var(--amber) !important;
        }}

        /* Sidebar radio buttons */
        [data-testid="stSidebar"] [data-testid="stRadio"] label {{
            font-size: 10px !important;
            color: var(--text-dim) !important;
        }}
        [data-testid="stSidebar"] [data-testid="stRadio"] span {{
            font-size: 10px !important;
        }}

        /* ── Layout ──────────────────────────────────────────────── */
        .block-container {{
            max-width: min(1560px, calc(100vw - 2rem)) !important;
            padding-top: 0.75rem !important;
            padding-bottom: 2rem !important;
        }}

        /* ── Scrollbar ───────────────────────────────────────────── */
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-track {{ background: var(--bg); }}
        ::-webkit-scrollbar-thumb {{ background: var(--border-bright); border-radius: 0; }}
        ::-webkit-scrollbar-thumb:hover {{ background: var(--amber-dim); }}

        /* ── Inputs ──────────────────────────────────────────────── */
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
        [data-testid="stNumberInput"] input {{
            background: var(--bg2) !important;
            border: 1px solid var(--border-bright) !important;
            border-radius: 0 !important;
            color: var(--text) !important;
            font-size: 11px !important;
            min-height: 36px !important;
            box-shadow: none !important;
        }}
        [data-testid="stTextInput"] input:focus,
        [data-testid="stSelectbox"] [data-baseweb="select"] > div:focus {{
            border-color: var(--amber) !important;
            box-shadow: none !important;
        }}
        [data-testid="stSlider"] [role="slider"] {{
            background: var(--amber) !important;
            box-shadow: 0 0 8px oklch(75% 0.14 82 / 0.5) !important;
        }}

        /* ── Main buttons ────────────────────────────────────────── */
        .stButton > button,
        [data-testid="baseButton-secondary"] {{
            background: transparent !important;
            background-image: none !important;
            border: 1px solid var(--border-bright) !important;
            border-radius: 2px !important;
            color: var(--text-dim) !important;
            font-size: 10px !important;
            font-weight: 500 !important;
            letter-spacing: 0.02em !important;
            text-transform: uppercase !important;
            min-height: 2rem !important;
            line-height: 1.1 !important;
            padding: 0.44rem 0.75rem !important;
            white-space: nowrap !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
            box-shadow: none !important;
            transition: border-color 0.2s, color 0.2s, background 0.2s !important;
        }}
        .stButton > button p,
        [data-testid="baseButton-secondary"] p {{
            white-space: nowrap !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
            line-height: 1.1 !important;
        }}
        .stButton > button:hover,
        [data-testid="baseButton-secondary"]:hover {{
            border-color: var(--amber) !important;
            color: var(--amber) !important;
            background: oklch(75% 0.14 82 / 0.06) !important;
            background-image: none !important;
            transform: none !important;
            box-shadow: none !important;
        }}

        /* ── Tabs ────────────────────────────────────────────────── */
        [data-testid="stTabs"] [role="tablist"] {{
            border-bottom: 1px solid var(--border) !important;
            gap: 0 !important;
        }}
        [data-testid="stTabs"] button {{
            background: transparent !important;
            border: none !important;
            border-bottom: 2px solid transparent !important;
            border-radius: 0 !important;
            color: var(--text-muted) !important;
            font-size: 10px !important;
            font-weight: 500 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
            padding: 0.5rem 0.75rem 0.6rem !important;
        }}
        [data-testid="stTabs"] button:hover {{ color: var(--text-dim) !important; }}
        [data-testid="stTabs"] button[aria-selected="true"] {{
            color: var(--amber) !important;
            border-bottom-color: var(--amber) !important;
        }}

        /* ── Alerts ──────────────────────────────────────────────── */
        [data-testid="stAlert"] {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            color: var(--text-dim) !important;
            font-size: 11px !important;
        }}

        /* ── DataFrames ──────────────────────────────────────────── */
        [data-testid="stDataFrame"] {{
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            overflow: auto !important;
            max-width: 100% !important;
            background: var(--bg1) !important;
            background-image: none !important;
        }}
        [data-testid="stDataFrame"] > div {{
            overflow: auto !important;
            max-width: 100% !important;
        }}
        [data-testid="stDataFrame"] [role="grid"] {{
            font-size: 10px !important;
            background: var(--bg1) !important;
        }}
        [data-testid="stDataFrame"] th {{
            background: var(--bg2) !important;
            color: var(--text-muted) !important;
            font-size: 9px !important;
            letter-spacing: 0.10em !important;
            text-transform: uppercase !important;
        }}

        /* ── Metrics ─────────────────────────────────────────────── */
        div[data-testid="stMetric"] {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            padding: 10px 12px !important;
            min-height: 64px !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            transition: background 0.2s, border-color 0.2s !important;
        }}
        div[data-testid="stMetric"]:hover {{
            background: var(--bg2) !important;
            border-color: var(--border-bright) !important;
            transform: none !important;
        }}
        div[data-testid="stMetricLabel"] p {{
            font-size: 9px !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase !important;
            color: var(--text-muted) !important;
            font-weight: 400 !important;
        }}
        div[data-testid="stMetricValue"] {{
            font-size: 24px !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
            color: var(--text) !important;
            line-height: 1 !important;
        }}
        div[data-testid="stMetricDelta"] {{
            font-size: 10px !important;
            font-weight: 300 !important;
        }}

        /* ── Container borders ───────────────────────────────────── */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            transition: border-color 0.2s !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
            border-color: var(--border-bright) !important;
            transform: none !important;
        }}

        /* ── Live dot ────────────────────────────────────────────── */
        @keyframes pulse-dot {{
            0%,100% {{ opacity:1; box-shadow:0 0 0 0 oklch(68% 0.17 155 / 0.6); }}
            50%      {{ opacity:0.8; box-shadow:0 0 0 4px oklch(68% 0.17 155 / 0); }}
        }}
        .live-dot {{
            width: 5px; height: 5px; border-radius: 50%;
            background: var(--green);
            animation: pulse-dot 2s ease-in-out infinite;
            display: inline-block;
        }}

        /* ── Status strip ────────────────────────────────────────── */
        .status-strip {{
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 6px !important;
            margin: 0 0 16px !important;
            padding: 0 !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
        }}

        /* ── Tags / badges ───────────────────────────────────────── */
        .tag {{
            display: inline-flex !important;
            align-items: center !important;
            gap: 6px !important;
            padding: 3px 8px !important;
            border-radius: 2px !important;
            font-size: 9px !important;
            font-weight: 500 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
            border: 1px solid transparent !important;
            background: transparent !important;
            box-shadow: none !important;
            transition: none !important;
        }}

        /* Tone variants */
        .tone-positive,
        .tag-emphasis-positive {{
            background: oklch(68% 0.17 155 / 0.10) !important;
            border-color: oklch(68% 0.17 155 / 0.35) !important;
            color: var(--green) !important;
        }}
        .tone-watch,
        .tag-emphasis-watch {{
            background: oklch(75% 0.14 82 / 0.08) !important;
            border-color: oklch(75% 0.14 82 / 0.35) !important;
            color: var(--amber) !important;
        }}
        .tone-neutral {{
            background: oklch(65% 0.14 240 / 0.06) !important;
            border-color: oklch(65% 0.14 240 / 0.25) !important;
            color: var(--blue) !important;
        }}
        .tone-negative,
        .tag-emphasis-negative {{
            background: oklch(62% 0.20 22 / 0.10) !important;
            border-color: oklch(62% 0.20 22 / 0.35) !important;
            color: var(--red) !important;
        }}

        /* Status-specific tags (for status-strip / render_status_strip) */
        .tag-live    {{ background: oklch(68% 0.17 155 / 0.10) !important; border-color: oklch(68% 0.17 155 / 0.35) !important; color: var(--green) !important; }}
        .tag-updated {{ background: oklch(75% 0.14 82  / 0.08) !important; border-color: oklch(75% 0.14 82  / 0.30) !important; color: var(--amber) !important; }}
        .tag-uni     {{ background: oklch(65% 0.14 240 / 0.08) !important; border-color: oklch(65% 0.14 240 / 0.25) !important; color: var(--blue) !important; }}
        .tag-count   {{ background: oklch(62% 0.2  22  / 0.10) !important; border-color: oklch(62% 0.2  22  / 0.35) !important; color: var(--red) !important; }}

        /* ── Page section intro ──────────────────────────────────── */
        .page-section {{
            margin: 0 0 12px !important;
        }}
        .page-title {{
            font-size: 14px !important;
            font-weight: 500 !important;
            color: var(--text) !important;
            letter-spacing: 0 !important;
            margin: 0 0 8px !important;
            padding-bottom: 8px !important;
            border-bottom: 1px solid var(--border) !important;
        }}
        .page-copy {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            font-weight: 300 !important;
            line-height: 1.6 !important;
            margin-top: 4px !important;
        }}

        /* ── Header panel (ticker overview) ──────────────────────── */
        .header-panel {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            padding: 16px 20px !important;
            margin-bottom: 12px !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            overflow: visible !important;
        }}
        .header-panel::before, .header-panel::after {{
            display: none !important;
        }}
        .header-grid {{
            display: grid !important;
            grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) !important;
            gap: 20px !important;
            align-items: start !important;
        }}
        .entity-name {{
            font-size: 20px !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
            color: var(--text) !important;
            margin: 0 !important;
            text-shadow: none !important;
        }}
        .entity-meta {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            letter-spacing: 0.04em !important;
            margin-top: 2px !important;
        }}

        /* ── Stat grid ───────────────────────────────────────────── */
        .stat-grid {{
            display: grid !important;
            grid-template-columns: repeat(4, 1fr) !important;
            gap: 1px !important;
            background: var(--border) !important;
            border: 1px solid var(--border) !important;
            margin-bottom: 12px !important;
        }}
        .stat-block {{
            background: var(--bg1) !important;
            background-image: none !important;
            padding: 10px 12px !important;
            min-height: 60px !important;
            overflow: visible !important;
            border: none !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            transition: background 0.2s !important;
        }}
        .stat-block::after {{ display: none !important; }}
        .stat-block:hover {{
            background: var(--bg2) !important;
            border-color: transparent !important;
            transform: none !important;
            box-shadow: none !important;
        }}
        .stat-label {{
            font-size: 9px !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase !important;
            color: var(--text-muted) !important;
            margin-bottom: 8px !important;
            font-weight: 400 !important;
        }}
        .stat-value {{
            font-size: 24px !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
            color: var(--text) !important;
            line-height: 1 !important;
            margin-top: 0 !important;
        }}
        .stat-meta {{
            font-size: 10px !important;
            color: var(--text-dim) !important;
            font-weight: 300 !important;
            margin-top: 4px !important;
        }}

        /* ── Summary grid (2-col score cards) ────────────────────── */
        .summary-grid {{
            display: grid !important;
            grid-template-columns: repeat(2, 1fr) !important;
            gap: 1px !important;
            background: var(--border) !important;
            margin-bottom: 12px !important;
        }}
        .summary-card {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 14px 16px !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            overflow: visible !important;
            transition: background 0.2s !important;
        }}
        .summary-card::before, .summary-card::after {{ display: none !important; }}
        .summary-card:hover {{
            background: var(--bg2) !important;
            transform: none !important;
            border-color: transparent !important;
            box-shadow: none !important;
        }}
        .summary-row {{
            display: flex !important;
            justify-content: space-between !important;
            align-items: flex-start !important;
            gap: 12px !important;
            margin-bottom: 0 !important;
        }}
        .summary-label {{
            font-size: 9px !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase !important;
            color: var(--text-muted) !important;
            margin-bottom: 8px !important;
        }}
        .summary-score {{
            font-size: 28px !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
            color: var(--amber) !important;
            line-height: 1 !important;
            text-shadow: none !important;
        }}
        .summary-subtle {{
            font-size: 10px !important;
            color: var(--text-dim) !important;
            font-weight: 300 !important;
            margin-top: 4px !important;
        }}

        /* ── Rank sheet rows ─────────────────────────────────────── */
        .terminal-table-head {{
            display: grid !important;
            grid-template-columns: 80px 1fr auto !important;
            padding: 5px 16px !important;
            border-bottom: 1px solid var(--border) !important;
            margin-bottom: 6px !important;
            color: var(--text-muted) !important;
            font-size: 9px !important;
            font-weight: 400 !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase !important;
        }}
        .rank-sheet-row {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            padding: 12px 14px !important;
            margin-bottom: 4px !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            overflow: visible !important;
            transition: border-color 0.2s, box-shadow 0.2s !important;
        }}
        .rank-sheet-row::before, .rank-sheet-row::after {{ display: none !important; }}
        .rank-sheet-row:hover {{
            border-color: var(--border-bright) !important;
            box-shadow: 0 4px 24px oklch(0% 0 0 / 0.4) !important;
            transform: none !important;
        }}

        /* ── Rank number (the 01/02 badge) ───────────────────────── */
        .rank-number {{
            width: 42px !important;
            height: 42px !important;
            border-radius: 0 !important;
            background: transparent !important;
            background-image: none !important;
            border: none !important;
            color: var(--amber) !important;
            font-size: 14px !important;
            font-weight: 600 !important;
            box-shadow: none !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }}
        .rank-ticker {{
            font-size: 18px !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
            color: var(--text) !important;
            line-height: 1 !important;
        }}
        .rank-subtitle {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            letter-spacing: 0.04em !important;
            margin-top: 2px !important;
            font-weight: 300 !important;
        }}
        .rank-meta-strip {{
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 4px !important;
            margin-top: 8px !important;
        }}
        .feature-header {{
            display: flex !important;
            justify-content: space-between !important;
            align-items: flex-start !important;
            gap: 12px !important;
            flex-wrap: wrap !important;
        }}
        .feature-identity {{
            display: flex !important;
            gap: 12px !important;
            align-items: center !important;
        }}

        /* ── Feature grid (score + analysis) ────────────────────── */
        .feature-grid {{
            display: grid !important;
            grid-template-columns: minmax(150px, 0.45fr) minmax(260px, 1.55fr) !important;
            gap: 1px !important;
            background: var(--border) !important;
            margin-top: 10px !important;
        }}
        .feature-panel {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 12px 14px !important;
            min-height: auto !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
        }}
        .feature-panel::before, .feature-panel::after {{ display: none !important; }}
        .feature-panel:hover {{
            background: var(--bg2) !important;
            transform: none !important;
        }}
        .feature-panel-score {{
            background: oklch(75% 0.14 82 / 0.03) !important;
            background-image: none !important;
            border-left: 2px solid var(--amber-dim) !important;
        }}
        .feature-panel-title,
        .detail-box-title,
        .research-title,
        .trade-title,
        .signal-title,
        .terminal-box-title {{
            font-size: 9px !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase !important;
            color: var(--text-muted) !important;
            margin-bottom: 8px !important;
            font-weight: 400 !important;
        }}
        .feature-score-value {{
            font-size: 30px !important;
            font-weight: 600 !important;
            letter-spacing: -0.03em !important;
            color: var(--amber) !important;
            line-height: 1 !important;
            text-shadow: none !important;
        }}
        .feature-score-meta {{
            font-size: 9px !important;
            color: var(--text-muted) !important;
            margin-top: 4px !important;
            letter-spacing: 0.08em !important;
        }}
        .feature-summary {{
            margin-top: 8px !important;
            padding: 8px 12px !important;
            background: oklch(75% 0.14 82 / 0.03) !important;
            background-image: none !important;
            border: none !important;
            border-left: 2px solid var(--amber-dim) !important;
            border-radius: 0 !important;
            color: var(--text-dim) !important;
            font-size: 10px !important;
            font-style: italic !important;
            font-weight: 300 !important;
            line-height: 1.45 !important;
            box-shadow: none !important;
        }}

        /* ── Rank details grid ───────────────────────────────────── */
        .rank-details {{
            display: grid !important;
            grid-template-columns: repeat(4, minmax(140px, 1fr)) !important;
            gap: 1px !important;
            background: var(--border) !important;
            margin-top: 8px !important;
        }}
        .detail-box {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 10px 12px !important;
            box-shadow: none !important;
        }}
        .detail-box::before, .detail-box::after {{ display: none !important; }}
        .detail-box-body {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            line-height: 1.6 !important;
            font-weight: 300 !important;
        }}
        .detail-box-body ul {{
            padding-left: 14px !important;
            margin: 0 !important;
        }}
        .detail-box-body li {{ margin-bottom: 2px !important; }}

        /* ── Research / signal / trade cards ─────────────────────── */
        .research-box,
        .signal-card,
        .trade-card {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            transition: border-color 0.2s !important;
        }}
        .research-box::before, .research-box::after,
        .signal-card::before, .signal-card::after,
        .trade-card::before, .trade-card::after {{ display: none !important; }}
        .research-box:hover,
        .signal-card:hover,
        .trade-card:hover {{
            border-color: var(--border-bright) !important;
            transform: none !important;
            box-shadow: none !important;
        }}
        .research-box {{ padding: 10px 12px !important; min-height: auto !important; }}
        .signal-card  {{ padding: 9px 11px !important; min-height: auto !important; }}
        .trade-card   {{ padding: 9px 11px !important; min-height: auto !important; }}
        .research-body {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            line-height: 1.6 !important;
            font-weight: 300 !important;
        }}
        .research-body ul {{ padding-left: 14px !important; margin: 2px 0 0 !important; }}
        .signal-value {{
            font-size: 14px !important;
            font-weight: 500 !important;
            color: var(--text) !important;
            margin-top: 4px !important;
        }}
        .signal-meta {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            font-weight: 300 !important;
            margin-top: 3px !important;
            line-height: 1.45 !important;
        }}
        .trade-copy {{
            font-size: 10px !important;
            color: var(--text-dim) !important;
            font-weight: 300 !important;
            line-height: 1.6 !important;
        }}

        /* Tone-tinted cards */
        .tone-positive.rank-sheet-row,
        .tone-positive.signal-card,
        .tone-positive.trade-card,
        .tone-positive.research-box {{
            border-color: oklch(68% 0.17 155 / 0.25) !important;
        }}
        .tone-watch.rank-sheet-row,
        .tone-watch.signal-card,
        .tone-watch.trade-card,
        .tone-watch.research-box {{
            border-color: oklch(75% 0.14 82 / 0.25) !important;
        }}
        .tone-negative.rank-sheet-row,
        .tone-negative.signal-card,
        .tone-negative.trade-card,
        .tone-negative.research-box {{
            border-color: oklch(62% 0.20 22 / 0.25) !important;
        }}

        /* ── Terminal box ────────────────────────────────────────── */
        .terminal-box {{
            background: var(--bg1) !important;
            background-image: none !important;
            border: 1px solid var(--border) !important;
            border-radius: 0 !important;
            padding: 12px 14px !important;
            color: var(--text-dim) !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
        }}
        .terminal-box::before, .terminal-box::after {{ display: none !important; }}
        .terminal-box:hover {{
            border-color: var(--border-bright) !important;
            transform: none !important;
        }}
        .terminal-box-content {{
            font-size: 10px !important;
            color: var(--text-muted) !important;
            font-weight: 300 !important;
            line-height: 1.6 !important;
        }}

        /* ── Change indicators ───────────────────────────────────── */
        .change-up   {{ color: var(--green) !important; text-shadow: none !important; }}
        .change-down {{ color: var(--red) !important;   text-shadow: none !important; }}

        /* ── Action line ─────────────────────────────────────────── */
        .action-line {{
            margin: 4px 0 10px !important;
            padding: 10px 12px !important;
            border-radius: 0 !important;
            border: 1px solid var(--border) !important;
            background: var(--bg1) !important;
            background-image: none !important;
            color: var(--text-dim) !important;
            font-size: 10px !important;
            line-height: 1.5 !important;
        }}
        .action-line strong {{ color: var(--text) !important; }}
        .action-positive {{ border-color: oklch(68% 0.17 155 / 0.30) !important; border-left: 2px solid oklch(68% 0.17 155 / 0.60) !important; }}
        .action-watch    {{ border-color: oklch(75% 0.14 82  / 0.30) !important; border-left: 2px solid oklch(75% 0.14 82  / 0.60) !important; }}
        .action-negative {{ border-color: oklch(62% 0.20 22  / 0.30) !important; border-left: 2px solid oklch(62% 0.20 22  / 0.60) !important; }}

        /* ── Trade state panel ───────────────────────────────────── */
        .trade-state-panel {{
            margin-bottom: 6px !important;
            padding: 10px 12px !important;
            border-radius: 0 !important;
            border: 1px solid var(--border) !important;
            background: var(--bg2) !important;
            background-image: none !important;
        }}
        .trade-state-label {{
            font-size: 9px !important;
            color: var(--text-muted) !important;
            letter-spacing: 0.10em !important;
            text-transform: uppercase !important;
        }}
        .trade-state-value {{
            font-size: 16px !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
            color: var(--text) !important;
            margin-top: 4px !important;
            line-height: 1 !important;
        }}
        .trade-state-meta  {{ font-size: 10px !important; color: var(--text-muted) !important; margin-top: 3px !important; }}
        .trade-state-action {{ font-size: 10px !important; color: var(--text-dim) !important; margin-top: 6px !important; line-height: 1.4 !important; }}
        .trade-state-positive {{ border-color: oklch(68% 0.17 155 / 0.25) !important; }}
        .trade-state-watch    {{ border-color: oklch(75% 0.14 82  / 0.25) !important; }}
        .trade-state-negative {{ border-color: oklch(62% 0.20 22  / 0.25) !important; }}

        /* ── Recommendation focus ────────────────────────────────── */
        .recommendation-focus .tag {{
            width: 100% !important;
            justify-content: center !important;
            padding: 8px 12px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            letter-spacing: 0.06em !important;
            border-radius: 2px !important;
        }}

        /* ── Misc ────────────────────────────────────────────────── */
        .overview-stack-gap {{ height: 10px !important; }}
        .col-section-title {{
            font-size: 14px !important;
            font-weight: 500 !important;
            color: var(--text) !important;
            margin-bottom: 10px !important;
            padding-bottom: 8px !important;
            border-bottom: 1px solid var(--border) !important;
        }}

        @media (max-width: 1100px) {{
            .header-grid {{ grid-template-columns: 1fr !important; }}
            .feature-grid {{ grid-template-columns: 1fr !important; }}
            .stat-grid {{ grid-template-columns: repeat(2, 1fr) !important; }}
            .rank-details {{ grid-template-columns: repeat(2, minmax(180px, 1fr)) !important; }}
        }}
        @media (max-width: 760px) {{
            .summary-grid, .rank-details, .stat-grid {{ grid-template-columns: 1fr !important; }}
            .stButton > button,
            [data-testid="baseButton-secondary"] {{
                white-space: normal !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def format_currency(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def format_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def format_large_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    return f"{value:,.0f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_timestamp(value: str | None) -> str:
    if not value:
        return "No completed scan yet"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def format_age_badge(value: str | None) -> str:
    if not value:
        return "No timestamp"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Unknown age"
    now = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = now - parsed.astimezone(timezone.utc)
    total_minutes = max(int(delta.total_seconds() // 60), 0)
    if total_minutes < 60:
        return f"{total_minutes}m old"
    total_hours = total_minutes // 60
    if total_hours < 24:
        return f"{total_hours}h old"
    return f"{total_hours // 24}d old"


def age_badge_tone(value: str | None) -> str:
    if not value:
        return "negative"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "negative"
    now = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = now - parsed.astimezone(timezone.utc)
    total_minutes = max(int(delta.total_seconds() // 60), 0)
    if total_minutes < 60:
        return "positive"
    if total_minutes < 24 * 60:
        return "watch"
    return "negative"


def tone_class(tone: str) -> str:
    return f"tone-{tone}"


def emphasis_class(text: str) -> str:
    normalized = text.strip().upper()
    bullish_tokens = (
        "STRONG BUY",
        "STRONG SETUP",
        "HIGH CONVICTION",
        "ENTER NOW",
        "CONFIRMED BREAKOUT",
    )
    watch_tokens = (
        "WAIT FOR PULLBACK",
        "BREAKOUT WATCH",
    )
    bearish_tokens = (
        "AVOID",
        "SELL",
        "CONFIRMED BREAKDOWN",
        "BREAKDOWN WATCH",
    )
    if any(token in normalized for token in bullish_tokens):
        return "tag-emphasis-positive"
    if any(token in normalized for token in watch_tokens):
        return "tag-emphasis-watch"
    if any(token in normalized for token in bearish_tokens):
        return "tag-emphasis-negative"
    return ""


def recommendation_pill(text: str, tone: str) -> str:
    extra = emphasis_class(text)
    classes = f"tag {tone_class(tone)}"
    if extra:
        classes += f" {extra}"
    return f"<span class='{classes}'>{escape(text)}</span>"


def render_status_strip(items: list[tuple[str, str]]) -> None:
    badges = "".join(recommendation_pill(text, tone) for text, tone in items)
    st.markdown(f"<div class='status-strip'>{badges}</div>", unsafe_allow_html=True)


def render_macro_strip(items: list[dict[str, str]]) -> None:
    cards = "".join(
        dedent(
            f"""
            <div class="stat-block">
                <div class="stat-label">{escape(item['label'])}</div>
                <div class="stat-value">{item['value']}</div>
                <div class="stat-meta">{escape(item.get('meta', ''))}</div>
            </div>
            """
        ).strip()
        for item in items
    )
    st.markdown(f"<div class='stat-grid'>{cards}</div>", unsafe_allow_html=True)


def render_section_intro(label: str, title: str, copy: str) -> None:
    copy_html = f"<p class='page-copy'>{escape(copy)}</p>" if copy else ""
    st.markdown(
        f"""
        <div class="page-section">
            <h2 class="page-title">{escape(title)}</h2>
            {copy_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_fundamentals(fundamentals: dict) -> None:
    display_rows = [
        ("Market Cap", format_large_number(fundamentals.get("marketCap"))),
        ("Trailing P/E", format_number(fundamentals.get("trailingPE"))),
        ("Forward P/E", format_number(fundamentals.get("forwardPE"))),
        ("Dividend Yield", format_percent(fundamentals.get("dividendYield"))),
        ("Revenue Growth", format_percent(fundamentals.get("revenueGrowth"))),
        ("Profit Margin", format_percent(fundamentals.get("profitMargins"))),
        ("Debt / Equity", format_number(fundamentals.get("debtToEquity"))),
        ("52W Range", fundamentals.get("fiftyTwoWeekRange") or "N/A"),
    ]
    non_empty_rows = [row for row in display_rows if row[1] != "N/A"]
    if not non_empty_rows:
        st.info("Fundamentals were not available for this ticker.")
        return
    fundamentals_df = pd.DataFrame(non_empty_rows, columns=["Metric", "Value"])
    st.dataframe(fundamentals_df, use_container_width=True, hide_index=True)


def build_price_chart(chart_window: pd.DataFrame) -> alt.Chart:
    plot_df = chart_window.reset_index()
    melted = plot_df.melt(
        id_vars="Date",
        value_vars=["Close", "MA20", "MA50"],
        var_name="Series",
        value_name="Price",
    )
    color_scale = alt.Scale(
        domain=["Close", "MA20", "MA50"],
        range=[THEME["price_line"], THEME["ma_fast"], THEME["ma_slow"]],
    )
    return (
        alt.Chart(melted)
        .mark_line(strokeWidth=2.4)
        .encode(
            x=alt.X("Date:T", axis=alt.Axis(title=None, labelColor=THEME["muted"], grid=False)),
            y=alt.Y("Price:Q", axis=alt.Axis(title=None, gridColor=THEME["grid"], labelColor=THEME["muted"])),
            color=alt.Color("Series:N", scale=color_scale, legend=alt.Legend(title=None, orient="top", labelColor=THEME["muted"])),
            strokeDash=alt.StrokeDash(
                "Series:N",
                scale=alt.Scale(domain=["Close", "MA20", "MA50"], range=[[1, 0], [6, 4], [2, 3]]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Series:N", title="Series"),
                alt.Tooltip("Price:Q", title="Price", format=",.2f"),
            ],
        )
        .properties(height=336)
        .configure_view(strokeOpacity=0)
        .configure(background="transparent")
    )


def build_volume_chart(chart_window: pd.DataFrame) -> alt.Chart:
    plot_df = chart_window.reset_index()
    plot_df["SessionUp"] = plot_df["Close"] >= plot_df["Open"]
    return (
        alt.Chart(plot_df)
        .mark_bar(opacity=0.82)
        .encode(
            x=alt.X("Date:T", axis=alt.Axis(title=None, labelColor=THEME["muted"], grid=False)),
            y=alt.Y("Volume:Q", axis=alt.Axis(title=None, gridColor=THEME["grid"], labelColor=THEME["muted"])),
            color=alt.condition(alt.datum.SessionUp, alt.value(THEME["positive"]), alt.value(THEME["negative"])),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Volume:Q", title="Volume", format=",.0f"),
            ],
        )
        .properties(height=210)
        .configure_view(strokeOpacity=0)
        .configure(background="transparent")
    )


def build_rsi_chart(chart_window: pd.DataFrame) -> alt.Chart:
    plot_df = chart_window.reset_index()
    rsi_line = (
        alt.Chart(plot_df)
        .mark_line(color=THEME["rsi_line"], strokeWidth=2.4)
        .encode(
            x=alt.X("Date:T", axis=alt.Axis(title=None, labelColor=THEME["muted"], grid=False)),
            y=alt.Y("RSI:Q", axis=alt.Axis(title=None, gridColor=THEME["grid"], labelColor=THEME["muted"]), scale=alt.Scale(domain=[0, 100])),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("RSI:Q", title="RSI", format=".2f"),
            ],
        )
    )
    thresholds = pd.DataFrame({"value": [30, 50, 70], "tone": ["edge", "mid", "edge"]})
    rules = alt.Chart(thresholds).mark_rule(strokeDash=[4, 6], strokeWidth=1.1).encode(
        y="value:Q",
        color=alt.Color("tone:N", scale=alt.Scale(domain=["edge", "mid"], range=[THEME["negative"], THEME["neutral"]]), legend=None),
    )
    return (rules + rsi_line).properties(height=210).configure_view(strokeOpacity=0).configure(background="transparent")


def build_macd_chart(chart_window: pd.DataFrame) -> alt.Chart:
    plot_df = chart_window.reset_index()
    bars = (
        alt.Chart(plot_df)
        .mark_bar(opacity=0.65)
        .encode(
            x=alt.X("Date:T", axis=alt.Axis(title=None, labelColor=THEME["muted"], grid=False)),
            y=alt.Y("MACD_HIST:Q", axis=alt.Axis(title=None, gridColor=THEME["grid"], labelColor=THEME["muted"])),
            color=alt.condition(alt.datum.MACD_HIST >= 0, alt.value(THEME["positive"]), alt.value(THEME["negative"])),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("MACD_HIST:Q", title="Histogram", format=".3f"),
            ],
        )
    )
    lines_df = plot_df.melt(
        id_vars="Date",
        value_vars=["MACD", "MACD_SIGNAL"],
        var_name="Series",
        value_name="Value",
    )
    lines = (
        alt.Chart(lines_df)
        .mark_line(strokeWidth=2.1)
        .encode(
            x=alt.X("Date:T"),
            y=alt.Y("Value:Q"),
            color=alt.Color(
                "Series:N",
                scale=alt.Scale(domain=["MACD", "MACD_SIGNAL"], range=[THEME["macd_line"], THEME["macd_signal"]]),
                legend=alt.Legend(title=None, orient="top", labelColor=THEME["muted"]),
            ),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Series:N", title="Series"),
                alt.Tooltip("Value:Q", title="Value", format=".3f"),
            ],
        )
    )
    return alt.layer(bars, lines).properties(height=228).configure_view(strokeOpacity=0).configure(background="transparent")


def render_overview_hero(
    ticker: str,
    company_name: str,
    sector: str,
    snapshot: dict[str, float | None],
    long_term_view,
    short_term_view,
    long_rec,
    short_rec,
    source_badge_html: str = "",
) -> None:
    change_class = "change-up" if (snapshot.get("daily_change_abs") or 0) >= 0 else "change-down"
    current_volume = snapshot.get("volume")
    avg_volume = snapshot.get("avg_volume_20")
    rsi_display = f"{snapshot['rsi']:.2f}" if snapshot.get("rsi") is not None else "N/A"
    st.markdown(
        f"""
        <section class="header-panel">
            <div class="header-grid">
                <div>
                    <h1 class="entity-name">{escape(ticker)} <span style="color:{THEME["text"]}; font-weight:500; opacity:0.78;">{escape(company_name)}</span></h1>
                    <div class="entity-meta">{escape(sector or "N/A")}</div>
                    <div class="rank-meta-strip" style="margin-top:0.75rem;">
                        {source_badge_html}
                        {recommendation_pill(f"Long {long_rec.label}", long_rec.tone)}
                        {recommendation_pill(f"Short {short_rec.label}", short_rec.tone)}
                    </div>
                </div>
                <div class="stat-grid" style="grid-template-columns: repeat(4, 1fr); gap:0.55rem; margin-top:0;">
                    <div class="stat-block">
                        <div class="stat-label">Price</div>
                        <div class="stat-value">{format_currency(snapshot.get("current_price"))}</div>
                        <div class="stat-meta {change_class}">{snapshot.get("daily_change_pct", 0):+.2f}%</div>
                    </div>
                    <div class="stat-block">
                        <div class="stat-label">Long score</div>
                        <div class="stat-value">{long_term_view.score}/100</div>
                        <div class="stat-meta">{escape(long_rec.label)}</div>
                    </div>
                    <div class="stat-block">
                        <div class="stat-label">Short score</div>
                        <div class="stat-value">{short_term_view.score}/100</div>
                        <div class="stat-meta">{escape(short_rec.label)}</div>
                    </div>
                    <div class="stat-block">
                        <div class="stat-label">RSI / Volume</div>
                        <div class="stat-value">{rsi_display}</div>
                        <div class="stat-meta">{format_large_number(current_volume)} / {format_large_number(avg_volume)}</div>
                    </div>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_recommendation_summary(long_term_view, short_term_view, long_rec, short_rec) -> None:
    st.markdown(
        f"""
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-row">
                    <div>
                        <div class="summary-label">Long-term</div>
                        <div class="summary-score">{long_term_view.score}/100</div>
                        <div class="summary-subtle">{escape(long_rec.label)} • {escape(long_rec.confidence)}</div>
                    </div>
                    <div>{recommendation_pill(long_rec.label, long_rec.tone)}</div>
                </div>
            </div>
            <div class="summary-card">
                <div class="summary-row">
                    <div>
                        <div class="summary-label">Short-term</div>
                        <div class="summary-score">{short_term_view.score}/100</div>
                        <div class="summary-subtle">{escape(short_rec.setup_type)} • {escape(short_rec.confidence)}</div>
                    </div>
                    <div>{recommendation_pill(short_rec.label, short_rec.tone)}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_rank_sheet_header(title: str) -> None:
    st.markdown(
        f"""
        <div class="terminal-table-head">
            <div>Rank</div>
            <div>Security</div>
            <div>{escape(title)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_signal_card(title: str, value: str, meta: str = "", tone: str = "neutral") -> None:
    st.markdown(
        f"""
        <div class="signal-card {tone_class(tone)}">
            <div class="signal-title">{escape(title)}</div>
            <div class="signal-value">{escape(str(value))}</div>
            {f'<div class="signal-meta">{escape(meta)}</div>' if meta else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_trade_card(title: str, content: str) -> None:
    st.markdown(
        f"""
        <div class="trade-card">
            <div class="trade-title">{escape(title)}</div>
            <div class="trade-copy">{escape(content)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_research_box(title: str, content, tone: str = "neutral") -> None:
    if isinstance(content, list):
        body = "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in content) + "</ul>"
    else:
        body = f"<p>{escape(str(content))}</p>"
    st.markdown(
        f"""
        <div class="research-box {tone_class(tone)}">
            <div class="research-title">{escape(title)}</div>
            <div class="research-body">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(title: str = "No Data", message: str = "Nothing is available yet.") -> None:
    st.markdown(
        f"""
        <div class="terminal-box" style="text-align:center; padding:2rem 1rem;">
            <div class="terminal-box-title">{escape(title)}</div>
            <div class="terminal-box-content">{escape(message)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_terminal_box(title: str, content: str) -> None:
    st.markdown(
        f"""
        <div class="terminal-box">
            <div class="terminal-box-title">{escape(title)}</div>
            <div class="terminal-box-content">{content}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

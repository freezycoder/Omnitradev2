from __future__ import annotations

import streamlit as st

from application.calibration_service import CalibrationService
from application.long_term_performance_service import LongTermPerformanceService
from application.performance_lab_service import PerformanceLabService
from application.scan_service import run_scan
from application.ticker_service import build_ticker_analysis
from config.labels import DATA_MODE_LABELS, NAV_PAGES
from config.settings import SOURCE_CONFIG, settings
from config.universe import UNIVERSE_REGISTRY
from storage.sqlite import bootstrap_database
from stock_dashboard.pages import (
    render_calibration_page,
    render_home_page,
    render_international_page,
    render_long_term_page,
    render_long_term_performance_page,
    render_performance_lab_page,
    render_portfolio_page,
    render_short_term_page,
    render_ticker_page,
    render_watchlist_page,
)
from stock_dashboard.ui import format_timestamp, inject_styles, render_status_strip


st.set_page_config(page_title="OmniTrade // Quantum Analytics", layout="wide")

# Centralised schema bootstrap. Idempotent across reruns, so safe inside
# Streamlit's hot-reload model. Must run before any service or repository
# that touches the SQLite performance database.
bootstrap_database()


NAV_BUTTONS = [
    ("Overview", "▣"),
    ("Long-Term Recommendations", "◰"),
    ("Long-Term Performance", "◧"),
    ("Short-Term Recommendations", "◱"),
    ("International Markets", "◎"),
    ("Ticker Analysis", "⌕"),
    ("Performance Lab", "◫"),
    ("Portfolio", "◩"),
    ("Calibration", "◬"),
    ("Watchlist", "★"),
]


@st.cache_data(ttl=1800, show_spinner=False)
def load_scan_results(refresh_nonce: int, data_mode: str, universe_key: str) -> dict:
    universe_config = UNIVERSE_REGISTRY[universe_key]
    return run_scan(
        universe=universe_config["tickers"],
        data_mode=data_mode,
        universe_name=universe_config["name"],
        cache_key=universe_key,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def load_ticker_analysis(ticker: str, data_mode: str):
    return build_ticker_analysis(ticker, data_mode=data_mode)


@st.cache_data(ttl=300, show_spinner=False)
def load_performance_lab(refresh_nonce: int) -> dict:
    return PerformanceLabService().build_dashboard_payload()


@st.cache_data(ttl=300, show_spinner=False)
def load_calibration_lab(refresh_nonce: int) -> dict:
    return CalibrationService().build_dashboard_payload()


@st.cache_data(ttl=300, show_spinner=False)
def load_long_term_performance(refresh_nonce: int) -> dict:
    return LongTermPerformanceService().build_dashboard_payload()


def main() -> None:
    inject_styles()

    default_page = settings.default_page
    default_ticker = settings.default_ticker
    default_data_mode_label = settings.default_data_mode_label
    if default_page not in NAV_PAGES:
        default_page = "Overview"
    if default_data_mode_label not in DATA_MODE_LABELS:
        default_data_mode_label = "Auto"

    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = default_page
    if "selected_ticker" not in st.session_state:
        st.session_state["selected_ticker"] = default_ticker
    if "scan_refresh_nonce" not in st.session_state:
        st.session_state["scan_refresh_nonce"] = 0
    if "data_mode_label" not in st.session_state:
        st.session_state["data_mode_label"] = default_data_mode_label

    st.sidebar.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            border-right: 1px solid oklch(25% 0.015 240);
            background: oklch(12% 0.010 240);
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 0.75rem;
            padding-bottom: 0.75rem;
        }
        section[data-testid="stSidebar"] div.stButton:nth-of-type(-n+10) > button {
            justify-content: flex-start;
            min-height: 2.4rem;
            border-radius: 0;
            padding: 0.44rem 0.875rem;
            border: none;
            border-left: 2px solid transparent;
            background: transparent;
            color: oklch(55% 0.010 240);
            font-size: 10px;
            font-weight: 400;
            letter-spacing: 0.02em;
            box-shadow: none;
            transition: background 0.15s, color 0.15s, border-color 0.15s;
        }
        section[data-testid="stSidebar"] div.stButton:nth-of-type(-n+10) > button:hover {
            background: oklch(15% 0.012 240);
            color: oklch(88% 0.010 240);
            border-left-color: transparent;
        }
        section[data-testid="stSidebar"] div.stButton:nth-of-type(-n+10) > button[kind="primary"] {
            background: oklch(75% 0.14 82 / 0.08);
            border-left-color: oklch(75% 0.14 82);
            color: oklch(75% 0.14 82);
            box-shadow: none;
        }
        section[data-testid="stSidebar"] div.stButton:nth-of-type(-n+10) > button p {
            font-size: 10px;
            font-weight: 400;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        """<div style="padding:0.1rem 0 0.85rem; border-bottom:1px solid oklch(25% 0.015 240); margin-bottom:0.85rem;">
            <div style="display:flex; align-items:center; gap:10px; padding:14px 14px 0;">
                <div style="width:30px; height:30px; background:oklch(75% 0.14 82 / 0.15); border:1px solid oklch(75% 0.14 82 / 0.4); display:flex; align-items:center; justify-content:center; font-size:14px; color:oklch(75% 0.14 82); flex-shrink:0;">◆</div>
                <div>
                    <div style="font-size:12px; font-weight:600; color:oklch(88% 0.010 240); letter-spacing:0.02em;">OmniTrade</div>
                    <div style="font-size:9px; color:oklch(38% 0.010 240); letter-spacing:0.06em;">RESEARCH PLATFORM</div>
                </div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        """<div style="color:var(--text-dim); font-size:0.74rem; margin:0.2rem 0 0.55rem; font-weight:500; letter-spacing:0.08em; text-transform:uppercase;">
            Modules
        </div>""",
        unsafe_allow_html=True,
    )
    for page_name, icon in NAV_BUTTONS:
        is_active = st.session_state["nav_page"] == page_name
        if st.sidebar.button(
            f"{icon}  {page_name}",
            key=f"nav-{page_name}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["nav_page"] = page_name
            st.rerun()
    selected_page = st.session_state["nav_page"]

    st.sidebar.markdown(
        """<div style="color:var(--text-dim); font-size:0.74rem; margin:1.2rem 0 0.5rem; font-weight:500; letter-spacing:0.08em; text-transform:uppercase;">
            Data
        </div>""",
        unsafe_allow_html=True,
    )

    selected_mode_label = st.sidebar.radio(
        "Data Mode",
        list(DATA_MODE_LABELS.keys()),
        index=list(DATA_MODE_LABELS.keys()).index(st.session_state["data_mode_label"]),
    )
    st.session_state["data_mode_label"] = selected_mode_label
    data_mode = DATA_MODE_LABELS[selected_mode_label]

    st.sidebar.markdown("")

    if st.sidebar.button("Refresh Scanner", use_container_width=True):
        st.session_state["scan_refresh_nonce"] += 1
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown(
        """<div style="color:var(--text-dim); font-size:0.74rem; margin:1.2rem 0 0.5rem; font-weight:500; letter-spacing:0.08em; text-transform:uppercase;">
            Status
        </div>""",
        unsafe_allow_html=True,
    )

    render_status_strip(
        [
            (selected_page, "neutral"),
            ("Universe International" if selected_page == "International Markets" else "Universe Global", "neutral"),
            (f"Mode {selected_mode_label}", "watch" if selected_mode_label == "Auto" else "negative"),
        ]
    )

    scan_results = {}
    active_universe_key = "international" if selected_page == "International Markets" else "global"
    if selected_page == "Watchlist":
        active_universe_key = "global"
    _SB_LABEL = "color:var(--text-muted); font-size:0.62rem; margin:1rem 0 0.2rem; text-transform:uppercase; letter-spacing:0.08em;"
    _SB_VALUE = "color:var(--text); font-size:0.80rem;"

    if selected_page not in {"Ticker Analysis", "Performance Lab", "Long-Term Performance", "Portfolio", "Calibration"}:
        with st.spinner("Running scan..."):
            scan_results = load_scan_results(st.session_state["scan_refresh_nonce"], data_mode, active_universe_key)
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Last Scan</div>
            <div style="{_SB_VALUE}">{format_timestamp(scan_results.get('updated_at'))}</div>""",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Data Source</div>
            <div style="{_SB_VALUE}">{SOURCE_CONFIG.get(scan_results.get('source', 'demo'), SOURCE_CONFIG['demo']).label}</div>""",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Universe</div>
            <div style="{_SB_VALUE}">{scan_results.get('universe_name', 'N/A')}</div>""",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Scan Results</div>
            <div style="{_SB_VALUE}">
                <span style="color:var(--green);">{scan_results.get('market_stats', {}).get('scanned_count', 0)}</span> scanned
                | <span style="color:var(--text-dim);">{len(scan_results.get('long_term', []))}</span> long
                | <span style="color:var(--text-dim);">{len(scan_results.get('short_term', []))}</span> short
            </div>""",
            unsafe_allow_html=True,
        )
    elif selected_page == "Ticker Analysis":
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Analysis Mode</div>
            <div style="{_SB_VALUE}">Single-ticker deep dive</div>""",
            unsafe_allow_html=True,
        )
    elif selected_page == "Performance Lab":
        performance_results = load_performance_lab(st.session_state["scan_refresh_nonce"])
        overall = performance_results.get("overall")
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Performance Lab</div>
            <div style="{_SB_VALUE}">Short-term measurement loop</div>""",
            unsafe_allow_html=True,
        )
        if overall is not None:
            st.sidebar.markdown(
                f"""<div style="{_SB_LABEL}">Logged Signals</div>
                <div style="{_SB_VALUE}">{overall.total_signals} total | {overall.resolved_signals} resolved</div>""",
                unsafe_allow_html=True,
            )
    elif selected_page == "Long-Term Performance":
        long_term_results = load_long_term_performance(st.session_state["scan_refresh_nonce"])
        overall = long_term_results.get("overall", {})
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Long-Term Performance</div>
            <div style="{_SB_VALUE}">3M / 6M / 12M measurement</div>""",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Tracked Signals</div>
            <div style="{_SB_VALUE}">{overall.get('total_signals', 0)} total | {overall.get('resolved_signals', 0)} resolved</div>""",
            unsafe_allow_html=True,
        )
    elif selected_page == "Portfolio":
        performance_results = load_performance_lab(st.session_state["scan_refresh_nonce"])
        portfolio_summary = performance_results.get("strategy_v1_portfolio", {}).get("summary", {})
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Portfolio</div>
            <div style="{_SB_VALUE}">Triggered allocation engine</div>""",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Holdings</div>
            <div style="{_SB_VALUE}">{portfolio_summary.get('holdings_count', 0)} names | {portfolio_summary.get('eligible_signals_count', 0)} eligible</div>""",
            unsafe_allow_html=True,
        )
    else:
        calibration_results = load_calibration_lab(st.session_state["scan_refresh_nonce"])
        summary = calibration_results.get("summary", {})
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Calibration</div>
            <div style="{_SB_VALUE}">Score reliability diagnostics</div>""",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown(
            f"""<div style="{_SB_LABEL}">Resolved Sample</div>
            <div style="{_SB_VALUE}">{summary.get('resolved_signals', 0)} signals | {summary.get('bucket_count', 0)} active buckets</div>""",
            unsafe_allow_html=True,
        )

    if selected_page == "Overview":
        render_home_page(scan_results)
    elif selected_page == "Long-Term Recommendations":
        render_long_term_page(scan_results)
    elif selected_page == "Long-Term Performance":
        render_long_term_performance_page(load_long_term_performance(st.session_state["scan_refresh_nonce"]))
    elif selected_page == "Short-Term Recommendations":
        render_short_term_page(scan_results)
    elif selected_page == "International Markets":
        render_international_page(scan_results)
    elif selected_page == "Ticker Analysis":
        render_ticker_page(load_ticker_analysis, data_mode)
    elif selected_page == "Performance Lab":
        render_performance_lab_page(load_performance_lab(st.session_state["scan_refresh_nonce"]))
    elif selected_page == "Portfolio":
        render_portfolio_page(load_performance_lab(st.session_state["scan_refresh_nonce"]))
    elif selected_page == "Calibration":
        render_calibration_page(load_calibration_lab(st.session_state["scan_refresh_nonce"]))
    elif selected_page == "Watchlist":
        if not scan_results:
            with st.spinner("Loading latest scan context for the watchlist..."):
                scan_results = load_scan_results(st.session_state["scan_refresh_nonce"], data_mode, "global")
        render_watchlist_page(scan_results)


if __name__ == "__main__":
    main()

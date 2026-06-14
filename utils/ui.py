import html

import pandas as pd
import streamlit as st


STATUS_LABELS = {
    "scheduled": "Programado",
    "in_play": "En vivo",
    "live": "En vivo",
    "finished": "Finalizado",
    "postponed": "Aplazado",
    "cancelled": "Cancelado",
}


def clean(value):
    return None if pd.isna(value) else value


def madrid_datetime(value):
    value = clean(value)
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Europe/Madrid")
    return timestamp.tz_convert("Europe/Madrid")


def kickoff_text(value) -> str:
    kickoff = madrid_datetime(value)
    if kickoff is None:
        return "Fecha por confirmar"
    return kickoff.strftime("%d/%m/%Y · %H:%M")


def calendar_date(value) -> str:
    kickoff = madrid_datetime(value)
    if kickoff is None:
        return "Por confirmar"
    return kickoff.strftime("%d/%m/%Y")


def venue_text(row) -> str:
    values = [clean(row.get(key)) for key in ("venue", "city", "country")]
    return " · ".join(str(value) for value in values if value) or "-"


def status_label(value) -> str:
    return STATUS_LABELS.get(str(clean(value) or "").lower(), str(clean(value) or "-"))


def status_badge(value) -> str:
    status = str(clean(value) or "").lower()
    css_class = {
        "scheduled": "scheduled",
        "in_play": "live",
        "live": "live",
        "finished": "finished",
    }.get(status, "neutral")
    return f'<span class="status-badge {css_class}">{html.escape(status_label(value))}</span>'


def inject_app_css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f7f5f0; color: #1e2320; }
        [data-testid="stSidebar"] { background: #ece7dc; }
        div[data-testid="stMetric"] {
            background: #fffaf0; border: 1px solid #ded6c5;
            padding: 14px; border-radius: 8px;
        }
        .status-badge {
            border-radius: 999px; display: inline-block; font-size: .78rem;
            font-weight: 700; padding: 3px 8px; white-space: nowrap;
        }
        .status-badge.scheduled { background: #eef1f4; color: #4a5560; }
        .status-badge.live { background: #fff0f0; color: #b42318; }
        .status-badge.finished { background: #ecf8ef; color: #18733a; }
        .status-badge.neutral { background: #f5efe3; color: #665f54; }
        .soft-panel {
            border: 1px solid #ded6c5; background: #fffdf8;
            border-radius: 8px; padding: 14px 16px; margin: 8px 0;
        }
        .home-hero {
            background: #172b20; border-radius: 14px; color: #f7f2e8;
            margin-bottom: 14px; overflow: hidden; padding: 28px 30px;
            position: relative;
        }
        .home-hero::after {
            background: #d9b95b; border-radius: 999px; content: "";
            height: 150px; opacity: .16; position: absolute; right: -34px;
            top: -70px; width: 150px;
        }
        .home-hero h1 {
            color: #fffaf0; font-size: clamp(2rem, 5vw, 3.5rem);
            letter-spacing: -.04em; margin: 5px 0 8px;
        }
        .home-hero p { color: #dce5dd; margin: 0; max-width: 650px; }
        .home-kicker {
            color: #e3c66d; font-size: .74rem; font-weight: 850;
            letter-spacing: .13em;
        }
        .home-match-card {
            background: #fffdf8; border: 1px solid #ded6c5;
            border-radius: 10px; margin: 14px 0 7px; padding: 16px 18px;
        }
        .home-match-top {
            align-items: flex-start; display: flex; gap: 16px;
            justify-content: space-between;
        }
        .home-match-number {
            color: #7c745f; font-size: .68rem; font-weight: 850;
            letter-spacing: .1em; margin-bottom: 6px;
        }
        .home-match-title { font-size: 1.08rem; font-weight: 820; }
        .home-match-vs { color: #8a867c; font-size: .78rem; margin: 0 7px; }
        .home-match-meta { color: #62675f; font-size: .8rem; margin-top: 7px; }
        .home-match-result {
            align-items: flex-end; display: flex; flex-direction: column; gap: 7px;
            white-space: nowrap;
        }
        .home-match-result strong { color: #1d3928; font-size: 1.05rem; }
        .team-label { display: inline-flex; align-items: center; gap: 6px; }
        .team-label span:last-child { overflow-wrap: anywhere; }
        .flag { font-size: 1.1rem; line-height: 1; }
        .flag-img {
            width: 22px; height: 16px; object-fit: cover;
            border: 1px solid rgba(30, 35, 32, .16); border-radius: 2px;
        }
        .bracket-scroll {
            overflow-x: auto; padding: 6px 2px 12px; margin: 4px 0 14px;
        }
        .bracket-grid {
            display: grid; grid-template-columns: repeat(6, minmax(188px, 1fr));
            gap: 10px; min-width: 1210px; align-items: stretch;
        }
        .bracket-round {
            background: rgba(255, 253, 248, .58); border: 1px solid #e2dbc9;
            border-radius: 8px; padding: 8px;
        }
        .bracket-round-title {
            color: #3d493f; font-size: .82rem; font-weight: 800;
            margin: 0 0 8px; text-transform: uppercase;
        }
        .bracket-round-cards {
            display: flex; flex-direction: column; gap: 7px;
            height: calc(100% - 24px); justify-content: space-around;
        }
        .bracket-card {
            background: #fffdf8; border: 1px solid #ded6c5;
            border-radius: 6px; padding: 7px; min-height: 64px;
        }
        .bracket-card-locked { background: #f2f0eb; color: #69706b; }
        .bracket-match-meta {
            color: #6b726c; display: flex; font-size: .7rem;
            font-weight: 750; justify-content: space-between; margin-bottom: 5px;
        }
        .bracket-score { color: #28322b; font-size: .72rem; }
        .bracket-team {
            align-items: center; display: flex; font-size: .76rem;
            gap: 4px; justify-content: space-between; padding: 3px 4px;
        }
        .bracket-team .flag-img { height: 12px; width: 17px; }
        .bracket-winner {
            background: #eaf5ec; border-radius: 4px; color: #175d34;
            font-weight: 800;
        }
        .bracket-advance {
            background: #d6ebdb; border-radius: 999px; font-size: .58rem;
            font-weight: 800; padding: 1px 4px; text-transform: uppercase;
        }
        .bracket-pending { color: #6c746e; font-size: .77rem; font-weight: 750; }
        .bracket-source { color: #7b827d; font-size: .66rem; margin-top: 4px; }
        .bracket-warning {
            background: #fff6e6; border-radius: 4px; color: #815400;
            font-size: .64rem; margin-top: 4px; padding: 4px;
        }
        .bracket-round-champion { display: flex; flex-direction: column; }
        .bracket-champion {
            align-items: center; background: #f3f7ed; border: 1px solid #cfdcbc;
            border-radius: 6px; display: flex; flex-direction: column;
            gap: 8px; justify-content: center; min-height: 180px;
            padding: 12px; text-align: center;
        }
        .bracket-trophy { font-size: 1.65rem; }
        .bracket-champion-title { color: #3c503e; font-size: .76rem; font-weight: 800; }
        .bracket-champion-team { color: #1b472b; font-size: .88rem; font-weight: 850; }
        .mobile-only { display: none; }
        .mobile-round {
            border: 1px solid #ded6c5; background: #fffdf8;
            border-radius: 8px; margin: 8px 0; padding: 0 10px;
        }
        .mobile-round summary {
            color: #3d493f; cursor: pointer; font-size: .88rem;
            font-weight: 800; padding: 12px 0; text-transform: uppercase;
        }
        .mobile-round .bracket-card { margin-bottom: 9px; }
        .mobile-list-card {
            background: #fffdf8; border: 1px solid #ded6c5;
            border-radius: 8px; margin: 8px 0; padding: 11px 12px;
        }
        .mobile-list-head {
            align-items: flex-start; display: flex; gap: 8px;
            justify-content: space-between; margin-bottom: 7px;
        }
        .mobile-list-title { font-size: .95rem; font-weight: 780; }
        .mobile-list-meta { color: #62675f; font-size: .82rem; line-height: 1.45; }
        .mobile-list-points { color: #1b472b; font-size: 1rem; font-weight: 850; }
        .summary-points-positive { color: #18733a; }
        .summary-points-zero { color: #74746d; }
        @media (max-width: 768px) {
            .block-container {
                padding-left: .75rem !important; padding-right: .75rem !important;
                padding-top: 1rem !important; padding-bottom: 2rem !important;
            }
            h1 { font-size: 1.65rem !important; }
            h2 { font-size: 1.35rem !important; }
            h3 { font-size: 1.12rem !important; }
            p, li, label, [data-testid="stMarkdownContainer"] { line-height: 1.42; }
            div.stButton > button,
            div[data-testid="stFormSubmitButton"] > button,
            div[data-testid="stDownloadButton"] > button {
                min-height: 44px; width: 100% !important;
            }
            div[data-testid="stHorizontalBlock"] {
                align-items: stretch; flex-wrap: wrap; gap: .5rem;
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
            div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                flex: 1 1 100% !important; min-width: 0 !important;
                width: 100% !important;
            }
            div[data-testid="stMetric"] { padding: 10px 12px; }
            [data-testid="stMetricLabel"] { font-size: .8rem; }
            [data-testid="stMetricValue"] { font-size: 1.25rem; }
            [data-testid="stDataFrame"] { max-width: 100%; overflow-x: auto; }
            [data-testid="stTable"] { max-width: 100%; overflow-x: auto; }
            [data-testid="stForm"] { padding: .65rem !important; }
            [data-testid="stExpander"] details summary { min-height: 44px; }
            .desktop-only { display: none !important; }
            .mobile-only { display: block !important; }
            .soft-panel, .match-card, .bracket-card, .summary-card {
                margin-bottom: .65rem !important; padding: .75rem !important;
            }
            .match-head, .result-card-layout {
                align-items: flex-start !important; flex-direction: column;
            }
            .home-hero { border-radius: 10px; padding: 21px 18px; }
            .home-match-top { flex-direction: column; }
            .home-match-result { align-items: flex-start; }
            .match-title { font-size: .96rem !important; line-height: 1.5; }
            .match-meta { gap: 5px !important; }
            .pill { white-space: normal !important; }
            .team-label { align-items: flex-start; white-space: normal !important; }
            .flag-img { flex: 0 0 auto; margin-top: 2px; }
            .bracket-scroll { display: none !important; }
            .stTabs [data-baseweb="tab-list"] { overflow-x: auto; }
            .stTabs [data-baseweb="tab"] { min-height: 44px; white-space: nowrap; }
            [data-testid="stSegmentedControl"] { overflow-x: auto; }
        }
        @media (min-width: 769px) {
            .mobile-only { display: none !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

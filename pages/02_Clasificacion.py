import html

import streamlit as st

from auth import current_user
from db import fetch_df
from utils.payments import SHOW_PAID_BADGE, player_display_name
from utils.ui import inject_app_css


st.set_page_config(page_title="Clasificación", layout="wide")
if not current_user():
    st.warning("Inicia sesión para ver la clasificación.")
    st.stop()

inject_app_css()
st.title("Clasificación")
try:
    leaderboard = fetch_df("SELECT * FROM leaderboard ORDER BY total_points DESC, exact_scores DESC, correct_results DESC")
except Exception as exc:
    st.error(f"No se pudo leer la view leaderboard: {exc}")
    st.stop()

paid_by_id = {}
paid_by_email = {}
if SHOW_PAID_BADGE:
    try:
        paid_players = fetch_df("SELECT id, email, paid FROM players")
        paid_by_id = {str(row["id"]): bool(row["paid"]) for row in paid_players.to_dict("records")}
        paid_by_email = {str(row["email"]).lower(): bool(row["paid"]) for row in paid_players.to_dict("records")}
    except Exception:
        paid_by_id = {}
        paid_by_email = {}


def leaderboard_player_is_paid(player) -> bool:
    player_id = player.get("player_id") or player.get("id")
    email = str(player.get("email") or "").lower()
    return paid_by_id.get(str(player_id), False) or paid_by_email.get(email, False)


def leaderboard_player_name(player) -> str:
    return player_display_name(
        name=player.get("name"),
        email=player.get("email"),
        paid=leaderboard_player_is_paid(player),
        show_badge=SHOW_PAID_BADGE,
    )


def render_mobile_leaderboard_cards(players) -> None:
    cards = []
    for index, (_, player) in enumerate(players.iterrows(), start=1):
        rank = player.get("rank") or index
        name = html.escape(leaderboard_player_name(player))
        points = int(player.get("total_points") or 0)
        exact = int(player.get("exact_scores") or 0)
        results = int(player.get("correct_results") or 0)
        advancing = int(player.get("correct_advancing_teams") or 0)
        cards.append(
            '<div class="mobile-list-card">'
            '<div class="mobile-list-head">'
            f'<div class="mobile-list-title">#{rank} · {name}</div>'
            f'<div class="mobile-list-points">{points} pts</div>'
            "</div>"
            '<div class="mobile-list-meta">'
            f"Exactos: {exact} · Signos: {results} · Avanzan: {advancing}"
            "</div>"
            "</div>"
        )
    st.markdown('<div class="mobile-only">' + "".join(cards) + "</div>", unsafe_allow_html=True)


if leaderboard.empty:
    st.info("Todavía no hay puntuaciones.")
else:
    preferred = [
        "rank",
        "name",
        "email",
        "total_points",
        "match_points",
        "group_points",
        "special_points",
        "exact_scores",
        "correct_results",
        "correct_advancing_teams",
    ]
    columns = [column for column in preferred if column in leaderboard.columns]
    display_leaderboard = leaderboard.copy()
    if "name" in display_leaderboard.columns:
        display_leaderboard["name"] = [leaderboard_player_name(player) for _, player in leaderboard.iterrows()]

    leader = leaderboard.iloc[0]
    metric_cols = st.columns(3)
    metric_cols[0].metric("Jugadores", len(leaderboard))
    metric_cols[1].metric("Líder actual", leaderboard_player_name(leader))
    metric_cols[2].metric("Puntos del líder", int(leader.get("total_points") or 0))

    st.subheader("Podio")
    medals = ["🥇", "🥈", "🥉"]
    podium_cols = st.columns(3)
    for idx, (_, player) in enumerate(leaderboard.head(3).iterrows()):
        name = leaderboard_player_name(player)
        points = int(player.get("total_points") or 0)
        podium_cols[idx].markdown(
            f"""
            <div class="soft-panel">
                <div style="font-size:1.45rem">{medals[idx]}</div>
                <div style="font-weight:750">{name}</div>
                <div style="color:#62675f">{points} puntos</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Clasificación completa")
    render_mobile_leaderboard_cards(leaderboard)
    with st.expander("Ver tabla completa", expanded=False):
        st.dataframe(display_leaderboard[columns], width="stretch", hide_index=True)
    st.download_button(
        "Descargar clasificación CSV",
        data=leaderboard[columns].to_csv(index=False).encode("utf-8-sig"),
        file_name="leaderboard.csv",
        mime="text/csv",
        width="stretch",
    )

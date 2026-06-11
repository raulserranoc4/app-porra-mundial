import html
from datetime import datetime

import streamlit as st

from auth import current_user, login, logout, register
from db import app_timezone, fetch_df, get_global_lock_at, predictions_are_open, require_invite_code
from utils.flags import team_label_html
from utils.ui import clean, inject_app_css, kickoff_text, status_badge, venue_text


st.set_page_config(page_title="Porra Mundial 2026", page_icon="⚽", layout="wide")

inject_app_css()
st.markdown(
    "<style>.status-open { color: #146c43; font-weight: 700; } .status-closed { color: #9f1239; font-weight: 700; }</style>",
    unsafe_allow_html=True,
)


def lock_banner() -> None:
    lock_at = get_global_lock_at()
    if predictions_are_open():
        st.markdown(f"<span class='status-open'>Apuestas abiertas</span> hasta {lock_at:%d/%m/%Y %H:%M %Z}.", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='status-closed'>Apuestas cerradas</span> desde {lock_at:%d/%m/%Y %H:%M %Z}.", unsafe_allow_html=True)


def auth_view() -> None:
    st.title("Porra Mundial 2026")
    lock_banner()
    login_tab, register_tab = st.tabs(["Entrar", "Registro"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Iniciar sesión", width="stretch")
        if submitted:
            ok, message = login(email, password)
            if ok:
                st.success(message)
                st.rerun()
            st.error(message)

    with register_tab:
        with st.form("register_form"):
            name = st.text_input("Nombre")
            email = st.text_input("Email", key="register_email")
            password = st.text_input("Contraseña", type="password", key="register_password")
            invite_code = st.text_input("Código de invitación") if require_invite_code() else None
            submitted = st.form_submit_button("Crear cuenta", width="stretch")
        if submitted:
            ok, message = register(name, email, password, invite_code)
            if ok:
                st.success(message)
            else:
                st.error(message)


def load_todays_group_predictions():
    return fetch_df(
        """
        SELECT
            m.id AS match_id,
            m.match_number,
            m.group_letter,
            m.kickoff_time,
            m.venue,
            m.city,
            m.country,
            m.status,
            m.home_score,
            m.away_score,
            ht.name AS home_team,
            at.name AS away_team,
            pl.id AS player_id,
            COALESCE(NULLIF(pl.name, ''), pl.email) AS player_name,
            p.predicted_home_score,
            p.predicted_away_score
        FROM matches m
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        CROSS JOIN players pl
        LEFT JOIN predictions p
            ON p.match_id = m.id
           AND p.player_id = pl.id
        WHERE m.stage = 'group'
          AND (m.kickoff_time AT TIME ZONE 'Europe/Madrid')::date
              = (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Madrid')::date
        ORDER BY m.kickoff_time, m.match_number, pl.name, pl.email
        """
    )


def score_text(home_score, away_score, empty_text: str = "Sin apuesta") -> str:
    home_score = clean(home_score)
    away_score = clean(away_score)
    if home_score is None or away_score is None:
        return empty_text
    return f"{int(home_score)} - {int(away_score)}"


def render_daily_match(match_rows, user: dict, reveal_all: bool) -> None:
    match = match_rows.iloc[0]
    real_score = score_text(match.get("home_score"), match.get("away_score"), "Pendiente")
    metadata = " · ".join(
        value
        for value in (
            kickoff_text(match.get("kickoff_time")),
            f"Grupo {match.get('group_letter')}",
            venue_text(match) if venue_text(match) != "-" else "",
        )
        if value
    )
    st.markdown(
        f"""
        <div class="home-match-card">
            <div class="home-match-top">
                <div>
                    <div class="home-match-number">PARTIDO {int(match.get("match_number"))}</div>
                    <div class="home-match-title">
                        {team_label_html(match.get("home_team"))}
                        <span class="home-match-vs">vs</span>
                        {team_label_html(match.get("away_team"))}
                    </div>
                    <div class="home-match-meta">{html.escape(metadata)}</div>
                </div>
                <div class="home-match-result">
                    {status_badge(match.get("status"))}
                    <strong>{html.escape(real_score)}</strong>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    visible = match_rows if reveal_all else match_rows[match_rows["player_id"] == user["id"]]
    predictions = [
        {
            "Jugador": prediction.get("player_name"),
            "Pronóstico": score_text(
                prediction.get("predicted_home_score"),
                prediction.get("predicted_away_score"),
            ),
        }
        for _, prediction in visible.iterrows()
    ]
    if predictions:
        st.dataframe(predictions, width="stretch", hide_index=True)
    else:
        st.caption("Todavía no hay apuestas guardadas para este partido.")


def home_view() -> None:
    user = current_user()
    if not user:
        auth_view()
        return

    today = datetime.now(app_timezone()).date()
    st.markdown(
        f"""
        <div class="home-hero">
            <div class="home-kicker">MUNDIAL 2026 · {today:%d/%m/%Y}</div>
            <h1>Hola, {html.escape(user.get('name') or user.get('email') or 'participante')}</h1>
            <p>Los partidos de grupos de hoy y todas las apuestas, en un solo vistazo.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    lock_banner()

    try:
        today_rows = load_todays_group_predictions()
    except Exception as exc:
        st.error(f"No se pudieron cargar los partidos de hoy: {exc}")
        return

    reveal_all = not predictions_are_open()
    matches_today = int(today_rows["match_id"].nunique()) if not today_rows.empty else 0
    saved_predictions = int(today_rows["predicted_home_score"].notna().sum()) if not today_rows.empty else 0
    players_today = int(today_rows["player_id"].nunique()) if not today_rows.empty else 0
    metric_cols = st.columns(3)
    metric_cols[0].metric("Partidos de grupos hoy", matches_today)
    metric_cols[1].metric("Apuestas guardadas", saved_predictions)
    metric_cols[2].metric("Jugadores", players_today)

    st.subheader("Partidos de hoy")
    if today_rows.empty:
        st.info("Hoy no hay partidos de fase de grupos.")
        return
    if not reveal_all:
        st.info("Mientras las apuestas estén abiertas solo puedes ver tus propios pronósticos.")

    for match_id in today_rows["match_id"].drop_duplicates():
        render_daily_match(today_rows[today_rows["match_id"] == match_id], user, reveal_all)


navigation = st.navigation(
    [
        st.Page(home_view, title="Inicio", default=True),
        st.Page("pages/05_Reglas.py", title="Reglas"),
        st.Page("pages/01_Apuestas.py", title="Mis Apuestas"),
        st.Page("pages/02_Clasificacion.py", title="Clasificación"),
        st.Page("pages/03_Resultados.py", title="Resultados"),
        st.Page("pages/04_Admin.py", title="Admin"),
    ]
)

user = current_user()
if user:
    with st.sidebar:
        st.write(f"**{user.get('name') or user.get('email')}**")
        st.caption("Admin" if user.get("is_admin") else "Participante")
        if st.button("Cerrar sesión", width="stretch"):
            logout()
            st.rerun()

navigation.run()

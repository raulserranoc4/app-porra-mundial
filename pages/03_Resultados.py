import html

import pandas as pd
import streamlit as st

from auth import current_user
from db import fetch_df, table_columns
from utils.flags import team_label_html
from utils.ui import calendar_date, clean, inject_app_css, kickoff_text, status_badge, status_label, venue_text


st.set_page_config(page_title="Resultados", layout="wide")
user = current_user()
if not user:
    st.warning("Inicia sesion para ver resultados.")
    st.stop()

inject_app_css()


def result_text(row) -> str:
    home = clean(row.get("home_score"))
    away = clean(row.get("away_score"))
    if home is None or away is None:
        return "-"
    result = f"{int(home)} - {int(away)}"
    home_pen = clean(row.get("home_score_penalties"))
    away_pen = clean(row.get("away_score_penalties"))
    if home_pen is not None or away_pen is not None:
        result += f" (pen. {int(home_pen or 0)} - {int(away_pen or 0)})"
    return result


def render_visual_matches(matches) -> None:
    if matches.empty:
        st.info("No hay partidos en esta vista.")
        return
    for _, row in matches.iterrows():
        metadata = " · ".join(
            value
            for value in [
                kickoff_text(row.get("kickoff_time")),
                f"Grupo {row.get('group_letter')}" if clean(row.get("group_letter")) else str(clean(row.get("stage")) or ""),
                venue_text(row) if venue_text(row) != "-" else "",
            ]
            if value
        )
        st.markdown(
            f"""
            <div class="soft-panel">
                <div class="result-card-layout" style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
                    <div>
                        <div style="font-weight:750">
                            {team_label_html(row.get("home_team"))}
                            <span style="color:#777;margin:0 6px">vs</span>
                            {team_label_html(row.get("away_team"))}
                        </div>
                        <div style="color:#62675f;font-size:.86rem;margin-top:5px">{html.escape(metadata)}</div>
                    </div>
                    <div style="text-align:right">
                        {status_badge(row.get("status"))}
                        <div style="font-weight:750;margin-top:6px">{html.escape(result_text(row))}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def load_matches():
    stage_col = "phase" if "phase" in table_columns("matches") else "stage"
    return fetch_df(
        f"""
        SELECT
            m.id,
            m.match_number,
            m.{stage_col} AS stage,
            m.group_letter,
            m.kickoff_time,
            m.venue,
            m.city,
            m.country,
            m.status,
            m.home_score,
            m.away_score,
            m.home_score_penalties,
            m.away_score_penalties,
            COALESCE(ht.name, m.home_placeholder, 'Local por definir') AS home_team,
            COALESCE(at.name, m.away_placeholder, 'Visitante por definir') AS away_team
        FROM matches m
        LEFT JOIN teams ht ON ht.id = m.home_team_id
        LEFT JOIN teams at ON at.id = m.away_team_id
        ORDER BY COALESCE(m.kickoff_time, '2099-01-01'::timestamp), m.match_number, m.id
        """
    )


st.title("Resultados")
st.caption("Calendario y resultados del Mundial 2026 en hora de Madrid.")

try:
    matches = load_matches()
except Exception as exc:
    st.error(f"No se pudieron cargar los partidos: {exc}")
    st.stop()

if matches.empty:
    st.info("No hay partidos disponibles.")
else:
    matches["Fecha"] = matches["kickoff_time"].apply(calendar_date)
    matches["Fecha y hora"] = matches["kickoff_time"].apply(kickoff_text)
    matches["Estado"] = matches["status"].apply(status_label)
    matches["Resultado"] = matches.apply(result_text, axis=1)
    matches["Sede"] = matches.apply(venue_text, axis=1)
    matches["Local"] = matches["home_team"]
    matches["Visitante"] = matches["away_team"]
    try:
        matches_summary_export = fetch_df("SELECT * FROM matches_summary")
        st.download_button(
            "Descargar matches_summary CSV",
            data=matches_summary_export.to_csv(index=False).encode("utf-8-sig"),
            file_name="matches_summary.csv",
            mime="text/csv",
            width="stretch",
        )
    except Exception as exc:
        st.info(f"No se pudo preparar la exportación matches_summary: {exc}")

    filter_cols = st.columns(5)
    selected_date = filter_cols[0].selectbox("Fecha", ["Todas"] + sorted(matches["Fecha"].dropna().unique().tolist()))
    selected_group = filter_cols[1].selectbox(
        "Grupo",
        ["Todos"] + sorted([str(value) for value in matches["group_letter"].dropna().unique()]),
    )
    selected_stage = filter_cols[2].selectbox(
        "Fase",
        ["Todas"] + sorted([str(value) for value in matches["stage"].dropna().unique()]),
    )
    selected_status = filter_cols[3].selectbox(
        "Estado",
        ["Todos"] + sorted([str(value) for value in matches["status"].dropna().unique()]),
    )
    team_names = sorted(set(matches["home_team"].dropna()) | set(matches["away_team"].dropna()))
    selected_team = filter_cols[4].selectbox("Equipo", ["Todos"] + team_names)

    filtered = matches.copy()
    if selected_date != "Todas":
        filtered = filtered[filtered["Fecha"] == selected_date]
    if selected_group != "Todos":
        filtered = filtered[filtered["group_letter"].astype(str) == selected_group]
    if selected_stage != "Todas":
        filtered = filtered[filtered["stage"].astype(str) == selected_stage]
    if selected_status != "Todos":
        filtered = filtered[filtered["status"].astype(str) == selected_status]
    if selected_team != "Todos":
        filtered = filtered[
            (filtered["home_team"] == selected_team) | (filtered["away_team"] == selected_team)
        ]

    status_tabs = st.tabs(["Todos", "Programados", "En vivo", "Finalizados"])
    status_filters = [None, "scheduled", "in_play", "finished"]
    display_columns = [
        "match_number",
        "Fecha y hora",
        "stage",
        "group_letter",
        "Local",
        "Visitante",
        "Estado",
        "Resultado",
        "Sede",
    ]
    for tab, status_filter in zip(status_tabs, status_filters):
        with tab:
            visible = filtered if status_filter is None else filtered[filtered["status"] == status_filter]
            render_visual_matches(visible)
            if not visible.empty:
                with st.expander("Ver tabla detallada"):
                    st.dataframe(visible[display_columns], width="stretch", hide_index=True)

if user.get("is_admin"):
    with st.expander("Vista previa de banderas"):
        st.markdown(
            " ".join(
                team_label_html(team)
                for team in ["México", "Sudáfrica", "España", "Argentina"]
            ),
            unsafe_allow_html=True,
        )

st.subheader("Grupos")
try:
    standings = fetch_df("SELECT * FROM group_standings_summary")
    with st.expander("Ver clasificación detallada de grupos", expanded=False):
        st.dataframe(standings, width="stretch", hide_index=True)
except Exception as exc:
    st.info(f"No se pudo leer group_standings_summary: {exc}")

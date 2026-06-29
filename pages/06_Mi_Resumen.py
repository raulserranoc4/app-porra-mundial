import html

import pandas as pd
import streamlit as st

from auth import current_user
from db import fetch_df
from utils.flags import team_label
from utils.ui import clean, inject_app_css, kickoff_text


st.set_page_config(page_title="Mi Resumen", page_icon="📋", layout="wide")

user = current_user()
if not user:
    st.warning("Inicia sesión para ver tu resumen.")
    st.stop()

inject_app_css()

STAGE_LABELS = {
    "group": "Fase de grupos",
    "round_of_32": "Dieciseisavos",
    "round_of_16": "Octavos",
    "quarter_final": "Cuartos",
    "semi_final": "Semifinales",
    "third_place": "Tercer puesto",
    "final": "Final",
}

TECHNICAL_FLAGS = (
    ("exact_score", "Marcador exacto"),
    ("correct_result", "Signo correcto"),
    ("correct_goal_difference", "Diferencia correcta"),
    ("correct_home_goals", "Goles local correctos"),
    ("correct_away_goals", "Goles visitante correctos"),
    ("correct_advancing_team", "Equipo que avanza correcto"),
    ("correct_penalties", "Penales correctos"),
)


def load_player_match_summary(player_id):
    return fetch_df(
        """
        WITH match_scores AS (
            SELECT
                se.player_id,
                se.match_id,
                SUM(se.points)::integer AS points,
                STRING_AGG(se.reason, ' ' ORDER BY se.calculated_at) AS reason,
                BOOL_OR(COALESCE((se.reason_json ->> 'exact_score')::boolean, false))
                    AS exact_score,
                BOOL_OR(COALESCE((se.reason_json ->> 'correct_result')::boolean, false))
                    AS correct_result,
                BOOL_OR(COALESCE((se.reason_json ->> 'correct_goal_difference')::boolean, false))
                    AS correct_goal_difference,
                BOOL_OR(COALESCE((se.reason_json ->> 'correct_home_goals')::boolean, false))
                    AS correct_home_goals,
                BOOL_OR(COALESCE((se.reason_json ->> 'correct_away_goals')::boolean, false))
                    AS correct_away_goals,
                BOOL_OR(COALESCE((se.reason_json ->> 'correct_advancing_team')::boolean, false))
                    AS correct_advancing_team,
                BOOL_OR(COALESCE((se.reason_json ->> 'correct_penalties')::boolean, false))
                    AS correct_penalties
            FROM score_events se
            WHERE se.category = 'match'
              AND se.player_id = :player_id
            GROUP BY se.player_id, se.match_id
        )
        SELECT
            m.id AS match_id,
            m.match_number,
            m.stage,
            m.group_letter,
            m.kickoff_time,
            m.home_score,
            m.away_score,
            ht.name AS home_team,
            at.name AS away_team,
            pr.predicted_home_score,
            pr.predicted_away_score,
            adv.name AS predicted_advancing_team,
            COALESCE(ms.points, 0) AS points,
            COALESCE(ms.reason, 'Pendiente de recálculo.') AS reason,
            COALESCE(ms.exact_score, false) AS exact_score,
            COALESCE(ms.correct_result, false) AS correct_result,
            COALESCE(ms.correct_goal_difference, false) AS correct_goal_difference,
            COALESCE(ms.correct_home_goals, false) AS correct_home_goals,
            COALESCE(ms.correct_away_goals, false) AS correct_away_goals,
            COALESCE(ms.correct_advancing_team, false) AS correct_advancing_team,
            COALESCE(ms.correct_penalties, false) AS correct_penalties
        FROM predictions pr
        JOIN matches m ON m.id = pr.match_id
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        LEFT JOIN teams adv ON adv.id = pr.predicted_advancing_team_id
        LEFT JOIN match_scores ms
            ON ms.player_id = pr.player_id
           AND ms.match_id = pr.match_id
        WHERE pr.player_id = :player_id
          AND m.status = 'finished'
          AND m.home_score IS NOT NULL
          AND m.away_score IS NOT NULL
        ORDER BY m.match_number
        """,
        {"player_id": player_id},
    )


def load_player_score_breakdown(player_id):
    rows = fetch_df(
        """
        SELECT
            COALESCE(SUM(points), 0)::integer AS total_points,
            COALESCE(SUM(points) FILTER (WHERE category = 'match'), 0)::integer AS match_points,
            COALESCE(SUM(points) FILTER (WHERE category = 'group'), 0)::integer AS group_points,
            COALESCE(SUM(points) FILTER (WHERE category = 'special'), 0)::integer AS special_points,
            COALESCE(SUM(points) FILTER (WHERE category = 'bonus'), 0)::integer AS bonus_points,
            COALESCE(SUM(points) FILTER (WHERE category = 'manual_adjustment'), 0)::integer AS manual_adjustment_points
        FROM score_events
        WHERE player_id = :player_id
        """,
        {"player_id": player_id},
    )
    if rows.empty:
        return {
            "total_points": 0,
            "match_points": 0,
            "group_points": 0,
            "special_points": 0,
            "bonus_points": 0,
            "manual_adjustment_points": 0,
        }
    return {key: int(rows.iloc[0].get(key) or 0) for key in rows.columns}


def load_player_group_score_summary(player_id):
    return fetch_df(
        """
        SELECT
            reason_json ->> 'group_letter' AS group_letter,
            points,
            reason
        FROM score_events
        WHERE player_id = :player_id
          AND category = 'group'
        ORDER BY reason_json ->> 'group_letter', calculated_at
        """,
        {"player_id": player_id},
    )


def finished_match_count() -> int:
    rows = fetch_df(
        """
        SELECT COUNT(*)::integer AS total
        FROM matches
        WHERE status = 'finished'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        """
    )
    return int(rows.iloc[0]["total"]) if not rows.empty else 0


def score_text(home_score, away_score) -> str:
    home_score = clean(home_score)
    away_score = clean(away_score)
    if home_score is None or away_score is None:
        return "-"
    return f"{int(home_score)} - {int(away_score)}"


def prepare_summary(rows: pd.DataFrame) -> pd.DataFrame:
    prepared = rows.copy()
    prepared["stage_label"] = prepared["stage"].map(STAGE_LABELS).fillna(prepared["stage"])
    prepared["real_match"] = prepared.apply(
        lambda row: f"{team_label(row['home_team'])} vs {team_label(row['away_team'])}",
        axis=1,
    )
    prepared["real_score"] = prepared.apply(
        lambda row: score_text(row["home_score"], row["away_score"]),
        axis=1,
    )
    prepared["predicted_score"] = prepared.apply(
        lambda row: score_text(row["predicted_home_score"], row["predicted_away_score"]),
        axis=1,
    )
    prepared["kickoff_label"] = prepared["kickoff_time"].apply(kickoff_text)
    return prepared


def render_mobile_cards(rows: pd.DataFrame) -> None:
    cards = []
    for _, row in rows.iterrows():
        points = int(row.get("points") or 0)
        points_class = "summary-points-positive" if points > 0 else "summary-points-zero"
        group = f" · Grupo {html.escape(str(row['group_letter']))}" if clean(row.get("group_letter")) else ""
        advance = (
            f"<br>Avanza: {html.escape(str(row['predicted_advancing_team']))}"
            if clean(row.get("predicted_advancing_team"))
            else ""
        )
        cards.append(
            '<div class="mobile-list-card">'
            '<div class="mobile-list-head">'
            f'<div class="mobile-list-title">#{int(row["match_number"])} · {html.escape(row["real_match"])}</div>'
            f'<div class="mobile-list-points {points_class}">{points} pts</div>'
            "</div>"
            '<div class="mobile-list-meta">'
            f'{html.escape(str(row["stage_label"]))}{group}<br>'
            f'Real: {html.escape(row["real_score"])} · Mi apuesta: {html.escape(row["predicted_score"])}'
            f'{advance}<br>{html.escape(str(row["reason"]))}'
            "</div>"
            "</div>"
        )
    st.markdown("".join(cards), unsafe_allow_html=True)


st.title("📋 Mi Resumen")
st.caption("Consulta los puntos obtenidos en cada partido finalizado.")

try:
    summary = prepare_summary(load_player_match_summary(user["id"]))
    score_breakdown = load_player_score_breakdown(user["id"])
    group_score_summary = load_player_group_score_summary(user["id"])
    total_finished_matches = finished_match_count()
except Exception as exc:
    st.error(f"No se pudo cargar tu resumen: {exc}")
    st.stop()

if summary.empty and score_breakdown["total_points"] == 0:
    if total_finished_matches == 0:
        st.info("Todavía no hay partidos finalizados.")
    else:
        st.info("Todavía no tienes puntuación en partidos finalizados.")
    st.stop()

metric_cols = st.columns(5)
metric_cols[0].metric("Total clasificación", score_breakdown["total_points"])
metric_cols[1].metric("Partidos", score_breakdown["match_points"])
metric_cols[2].metric("Grupos", score_breakdown["group_points"])
metric_cols[3].metric("Especiales", score_breakdown["special_points"])
metric_cols[4].metric("Otros", score_breakdown["bonus_points"] + score_breakdown["manual_adjustment_points"])

if score_breakdown["group_points"] or score_breakdown["special_points"]:
    st.caption(
        "El total coincide con la clasificación general. La tabla inferior muestra solo el detalle partido a partido."
    )

if not group_score_summary.empty:
    with st.expander("Ver puntos de clasificación de grupos", expanded=False):
        display_group_scores = group_score_summary.rename(
            columns={
                "group_letter": "Grupo",
                "points": "Puntos",
                "reason": "Motivo",
            }
        )
        st.dataframe(
            display_group_scores[["Grupo", "Puntos", "Motivo"]],
            width="stretch",
            hide_index=True,
            column_config={"Puntos": st.column_config.NumberColumn("Puntos", format="%d pts")},
        )

if summary.empty:
    st.info("No tienes detalle de partidos finalizados, pero sí puntuación en otras categorías.")
    st.stop()

match_metric_cols = st.columns(4)
match_metric_cols[0].metric("Partidos con apuesta", len(summary))
match_metric_cols[1].metric("Marcadores exactos", int(summary["exact_score"].sum()))
match_metric_cols[2].metric("Signos correctos", int(summary["correct_result"].sum()))
match_metric_cols[3].metric("Equipos que avanzan", int(summary["correct_advancing_team"].sum()))

filter_cols = st.columns(4)
stage_options = ["Todas"] + sorted(summary["stage_label"].dropna().unique().tolist())
group_options = ["Todos"] + sorted(summary["group_letter"].dropna().astype(str).unique().tolist())
selected_stage = filter_cols[0].selectbox("Fase", stage_options)
selected_group = filter_cols[1].selectbox("Grupo", group_options)
team_search = filter_cols[2].text_input("Buscar equipo", placeholder="España, Brasil...")
only_points = filter_cols[3].checkbox("Solo partidos con puntos")
only_exact = st.checkbox("Solo marcadores exactos")

filtered = summary.copy()
if selected_stage != "Todas":
    filtered = filtered[filtered["stage_label"] == selected_stage]
if selected_group != "Todos":
    filtered = filtered[filtered["group_letter"].astype(str) == selected_group]
if team_search.strip():
    query = team_search.strip().casefold()
    filtered = filtered[
        filtered["home_team"].astype(str).str.casefold().str.contains(query, regex=False)
        | filtered["away_team"].astype(str).str.casefold().str.contains(query, regex=False)
    ]
if only_points:
    filtered = filtered[filtered["points"] > 0]
if only_exact:
    filtered = filtered[filtered["exact_score"]]

if filtered.empty:
    st.info("No hay partidos que coincidan con los filtros seleccionados.")
else:
    display = filtered.rename(
        columns={
            "match_number": "Nº partido",
            "stage_label": "Fase",
            "group_letter": "Grupo",
            "real_match": "Partido real",
            "real_score": "Resultado real",
            "predicted_score": "Mi apuesta",
            "predicted_advancing_team": "Equipo que avanza",
            "points": "Puntos",
            "reason": "Motivo",
            "kickoff_label": "Fecha y hora",
        }
    )
    display_columns = [
        "Nº partido",
        "Fase",
        "Grupo",
        "Partido real",
        "Resultado real",
        "Mi apuesta",
        "Equipo que avanza",
        "Puntos",
        "Motivo",
        "Fecha y hora",
    ]
    st.dataframe(
        display[display_columns],
        width="stretch",
        hide_index=True,
        column_config={
            "Puntos": st.column_config.NumberColumn("Puntos", format="%d pts"),
        },
    )

    with st.expander("Ver en formato tarjetas"):
        render_mobile_cards(filtered)

    if st.toggle("Mostrar detalle técnico por partido"):
        for _, row in filtered.iterrows():
            with st.expander(
                f"Partido {int(row['match_number'])} · {row['home_team']} vs {row['away_team']} · {int(row['points'])} pts"
            ):
                st.write(row["reason"])
                detail_rows = [
                    {"Comprobación": label, "Acierto": "Sí" if bool(row[key]) else "No"}
                    for key, label in TECHNICAL_FLAGS
                ]
                st.dataframe(detail_rows, width="stretch", hide_index=True)

csv_columns = {
    "match_number": "match_number",
    "stage": "stage",
    "group_letter": "group_letter",
    "home_team": "home_team",
    "away_team": "away_team",
    "real_score": "real_score",
    "predicted_score": "predicted_score",
    "points": "points",
    "reason": "reason",
}
csv_summary = filtered[list(csv_columns)].rename(columns=csv_columns)
st.download_button(
    "Descargar mi resumen CSV",
    data=csv_summary.to_csv(index=False).encode("utf-8-sig"),
    file_name="mi_resumen.csv",
    mime="text/csv",
    width="stretch",
)

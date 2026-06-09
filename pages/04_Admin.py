import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from api_client import get_provider
from auth import current_user
from db import db_session, fetch_df, insert_dynamic, table_columns, update_dynamic
from real_tournament import (
    RealTournamentError,
    get_tournament_diagnostics,
    recalculate_real_group_standings,
    update_real_knockout_next_rounds,
    update_real_round_of_32_from_group_standings,
    update_tournament_results_from_real_knockout,
    validate_real_match_result,
    winner_team_id_from_score,
)
from scoring import recalculate_all_scores, recalculate_group_scores, recalculate_match_scores, recalculate_special_scores
from utils.payments import paid_status_label
from utils.ui import inject_app_css


st.set_page_config(page_title="Admin", layout="wide")

user = current_user()
if not user:
    st.warning("Inicia sesion.")
    st.stop()
if not user.get("is_admin"):
    st.error("Solo administradores.")
    st.stop()

st.title("Admin")
inject_app_css()
st.info("Para administración avanzada se recomienda usar una pantalla grande.")

st.markdown(
    """
    <style>
    .admin-note {
        border: 1px solid #ded6c5;
        background: #fffaf0;
        border-radius: 8px;
        padding: 12px 14px;
        color: #4c514b;
        margin-bottom: 16px;
    }
    .section-copy {
        color: #62675f;
        margin-top: -6px;
        margin-bottom: 12px;
        font-size: 0.92rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def clean_value(value):
    return None if pd.isna(value) else value


def int_or_zero(value) -> int:
    return 0 if pd.isna(value) else int(value)


def text_or_all(value):
    return None if value in {"Todos", "Todas", ""} else value


def count_rows(table: str) -> int:
    try:
        df = fetch_df(f"SELECT COUNT(*) AS total FROM {table}")
        return int(df.iloc[0]["total"])
    except Exception:
        return 0


def status_options(current_status=None) -> list[str]:
    options = ["scheduled", "in_play", "finished", "postponed", "cancelled"]
    if current_status and current_status not in options:
        options.append(current_status)
    return options


def stage_column() -> str:
    return "phase" if "phase" in table_columns("matches") else "stage"


def stage_label(value) -> str:
    labels = {
        "group": "Fase de grupos",
        "round_of_32": "Dieciseisavos",
        "round_of_16": "Octavos",
        "quarter_final": "Cuartos",
        "semi_final": "Semifinales",
        "third_place": "Tercer puesto",
        "final": "Final",
    }
    key = str(clean_value(value) or "").lower()
    return labels.get(key, str(clean_value(value) or "Sin fase"))


def load_teams():
    teams = fetch_df("SELECT id, name FROM teams ORDER BY name")
    team_names = [""] + teams["name"].tolist() if not teams.empty else [""]
    team_ids = dict(zip(teams["name"], teams["id"])) if not teams.empty else {}
    return teams, team_names, team_ids


def update_match(match: dict, payload: dict) -> None:
    with db_session() as conn:
        update_dynamic(conn, "matches", payload, "id = :id", {"id": match["id"]})


def update_player_paid_status(conn, player_id, paid: bool) -> None:
    update_dynamic(conn, "players", {"paid": bool(paid)}, "id = :id", {"id": player_id})


def render_diagnostics() -> None:
    st.subheader("Diagnostico de torneo")
    cols = st.columns(4)
    cols[0].metric("Jugadores", count_rows("players"))
    cols[1].metric("Partidos", count_rows("matches"))
    cols[2].metric("Apuestas", count_rows("predictions"))
    cols[3].metric("Score events", count_rows("score_events"))

    try:
        diagnostics = get_tournament_diagnostics()
    except Exception as exc:
        st.info(f"No se pudo cargar el diagnostico avanzado: {exc}")
        return

    group_finished = diagnostics["group_matches_finished"]
    group_total = diagnostics["group_matches_total"]
    st.progress(
        group_finished / group_total if group_total else 0,
        text=f"Partidos de grupo finalizados: {group_finished}/{group_total}",
    )

    round_labels = {
        "round_of_32": "Dieciseisavos",
        "round_of_16": "Octavos",
        "quarter_final": "Cuartos",
        "semi_final": "Semifinales",
    }
    round_cols = st.columns(4)
    for index, (key, label) in enumerate(round_labels.items()):
        data = diagnostics[key]
        round_cols[index].metric(
            label,
            f"{data['defined']}/{data['total']} definidos",
            f"{data['finished']}/{data['total']} finalizados",
        )

    final_data = diagnostics["final"]
    status_cols = st.columns(4)
    status_cols[0].metric("Final definida", "Si" if final_data["defined"] else "No")
    status_cols[1].metric("Final finalizada", "Si" if final_data["finished"] else "No")
    status_cols[2].metric("group_standings", "Si" if diagnostics["group_standings_updated"] else "No")
    status_cols[3].metric("leaderboard", "Si" if diagnostics["leaderboard_generated"] else "No")


def render_payments_tab() -> None:
    st.subheader("Jugadores y pagos")
    st.markdown(
        '<div class="section-copy">Revisa los pagos y guarda todos los cambios pendientes en una sola transaccion.</div>',
        unsafe_allow_html=True,
    )

    try:
        players = fetch_df(
            """
            SELECT id, name, email, is_admin, paid, created_at
            FROM players
            ORDER BY LOWER(name), LOWER(email)
            """
        )
    except Exception as exc:
        st.error(f"No se pudieron cargar los jugadores: {exc}")
        return

    if players.empty:
        st.info("Todavia no hay jugadores registrados.")
        return

    players["paid"] = players["paid"].fillna(False).astype(bool)
    total_players = len(players)
    paid_players = int(players["paid"].sum())
    pending_players = total_players - paid_players
    paid_percentage = (paid_players / total_players) * 100 if total_players else 0

    metric_cols = st.columns(4)
    metric_cols[0].metric("Total jugadores", total_players)
    metric_cols[1].metric("Pagados", paid_players)
    metric_cols[2].metric("Pendientes", pending_players)
    metric_cols[3].metric("% pagado", f"{paid_percentage:.0f}%")

    selected_filter = st.selectbox(
        "Estado de pago",
        ["Todos", "Pagados", "Pendientes de pago"],
        key="payments_filter",
    )
    filtered = players.copy()
    if selected_filter == "Pagados":
        filtered = filtered[filtered["paid"]]
    elif selected_filter == "Pendientes de pago":
        filtered = filtered[~filtered["paid"]]

    visual_table = filtered[["name", "email", "is_admin", "paid", "created_at"]].copy()
    visual_table["is_admin"] = visual_table["is_admin"].map(lambda value: "✅ Si" if value else "No")
    visual_table["paid"] = visual_table["paid"].map(paid_status_label)
    visual_table = visual_table.rename(
        columns={
            "name": "Nombre",
            "email": "Email",
            "is_admin": "Admin",
            "paid": "Pagado",
            "created_at": "Fecha de creacion",
        }
    )
    with st.expander("Ver tabla de jugadores", expanded=False):
        st.dataframe(visual_table, width="stretch", hide_index=True)

    if filtered.empty:
        st.info("No hay jugadores con ese filtro.")
        return

    st.markdown("#### Editar pagos")
    with st.form("payments_batch_form"):
        for player in filtered.to_dict("records"):
            paid_key = f"paid_{player['id']}"
            if paid_key not in st.session_state:
                st.session_state[paid_key] = bool(player["paid"])
            row_cols = st.columns([3.2, 1.1])
            admin_label = " · Admin" if player.get("is_admin") else ""
            row_cols[0].markdown(
                f"**{player.get('name') or '-'}**{admin_label}<br>"
                f"<small>{player.get('email') or '-'}</small>",
                unsafe_allow_html=True,
            )
            row_cols[1].checkbox("Pagado", key=paid_key)

        submitted = st.form_submit_button("Guardar cambios de pagos", width="stretch")

    if not submitted:
        return

    changes = []
    for player in players.to_dict("records"):
        paid_key = f"paid_{player['id']}"
        if paid_key not in st.session_state:
            continue
        new_paid = bool(st.session_state[paid_key])
        if new_paid != bool(player["paid"]):
            changes.append((player["id"], new_paid))

    if not changes:
        st.info("No hay cambios de pagos pendientes.")
        return

    try:
        with db_session() as conn:
            for player_id, paid in changes:
                update_player_paid_status(conn, player_id, paid)
        st.success(f"Estado de pago actualizado correctamente. Jugadores actualizados: {len(changes)}.")
        st.caption("Las metricas y la tabla se refrescaran en la siguiente interaccion.")
    except Exception as exc:
        st.error(f"No se pudo actualizar el estado de pago: {exc}")


def render_matches_tab(team_names: list[str], team_ids: dict) -> None:
    st.subheader("Resultados de partidos")
    st.markdown('<div class="section-copy">Filtra, selecciona un partido y actualiza el resultado manualmente.</div>', unsafe_allow_html=True)

    stage_col = stage_column()
    try:
        matches = fetch_df(
            f"""
            SELECT m.*, m.{stage_col} AS display_stage, ht.name AS home_team, at.name AS away_team
            FROM matches m
            LEFT JOIN teams ht ON ht.id = m.home_team_id
            LEFT JOIN teams at ON at.id = m.away_team_id
            ORDER BY COALESCE(m.kickoff_time, '2099-01-01'::timestamp), m.match_number, m.id
            """
        )
    except Exception as exc:
        st.error(f"No se pudieron cargar partidos: {exc}")
        return

    if matches.empty:
        st.info("No hay partidos.")
        return

    filter_cols = st.columns(3)
    stage_values = sorted([str(value) for value in matches["display_stage"].dropna().unique()])
    group_values = sorted([str(value) for value in matches["group_letter"].dropna().unique()])
    status_values = sorted([str(value) for value in matches["status"].dropna().unique()])
    selected_stage = filter_cols[0].selectbox("Fase", ["Todas"] + stage_values)
    selected_group = filter_cols[1].selectbox("Grupo", ["Todos"] + group_values)
    selected_status = filter_cols[2].selectbox("Estado", ["Todos"] + status_values)

    filtered = matches.copy()
    if text_or_all(selected_stage):
        filtered = filtered[filtered["display_stage"].astype(str) == selected_stage]
    if text_or_all(selected_group):
        filtered = filtered[filtered["group_letter"].astype(str) == selected_group]
    if text_or_all(selected_status):
        filtered = filtered[filtered["status"].astype(str) == selected_status]

    visible_cols = [
        column
        for column in [
            "match_number",
            "display_stage",
            "group_letter",
            "home_team",
            "away_team",
            "status",
            "home_score",
            "away_score",
            "home_score_penalties",
            "away_score_penalties",
        ]
        if column in filtered.columns
    ]
    with st.expander("Ver tabla de partidos filtrados", expanded=False):
        st.dataframe(filtered[visible_cols], width="stretch", hide_index=True)

    if filtered.empty:
        st.info("No hay partidos con esos filtros.")
        return

    labels = {
        f"{row.get('match_number') or '-'} · {stage_label(row.get('display_stage'))} · {row.get('home_team') or 'Local'} vs {row.get('away_team') or 'Visitante'}": row
        for row in filtered.to_dict("records")
    }
    selected_label = st.selectbox("Editar partido", list(labels.keys()))
    match = labels[selected_label]

    with st.form(f"match_admin_{match['id']}"):
        status_values_for_match = status_options(match.get("status"))
        status = st.selectbox(
            "Estado",
            status_values_for_match,
            index=status_values_for_match.index(match.get("status")) if match.get("status") in status_values_for_match else 0,
        )
        score_cols = st.columns(2)
        home_score = score_cols[0].number_input("Goles local", min_value=0, max_value=30, value=int_or_zero(match.get("home_score")))
        away_score = score_cols[1].number_input("Goles visitante", min_value=0, max_value=30, value=int_or_zero(match.get("away_score")))
        penalty_cols = st.columns(2)
        home_pen = penalty_cols[0].number_input("Penales local", min_value=0, max_value=30, value=int_or_zero(match.get("home_score_penalties")))
        away_pen = penalty_cols[1].number_input("Penales visitante", min_value=0, max_value=30, value=int_or_zero(match.get("away_score_penalties")))

        home_team_name = match.get("home_team") or "Local"
        away_team_name = match.get("away_team") or "Visitante"
        derived_winner_id = winner_team_id_from_score(match, int(home_score), int(away_score))
        if derived_winner_id == match.get("home_team_id"):
            st.caption(f"Ganador calculado automaticamente: {home_team_name}")
        elif derived_winner_id == match.get("away_team_id"):
            st.caption(f"Ganador calculado automaticamente: {away_team_name}")
        else:
            st.caption("Ganador calculado automaticamente: empate")

        advancing_name = ""
        if str(match.get("display_stage") or "").lower() != "group":
            if int(home_score) > int(away_score):
                advancing_options = [home_team_name]
                st.caption(f"Equipo que avanza calculado automaticamente: {home_team_name}")
            elif int(away_score) > int(home_score):
                advancing_options = [away_team_name]
                st.caption(f"Equipo que avanza calculado automaticamente: {away_team_name}")
            else:
                advancing_options = [home_team_name, away_team_name]
            advancing_name = st.selectbox(
                "Equipo que avanza",
                advancing_options,
                index=next(
                    (
                        idx
                        for idx, name in enumerate(advancing_options)
                        if team_ids.get(name) == clean_value(match.get("advancing_team_id"))
                    ),
                    0,
                ),
                disabled=len(advancing_options) == 1,
            )
        submitted = st.form_submit_button("Guardar resultado", width="stretch")

    if submitted:
        try:
            payload = validate_real_match_result(
                match=match,
                status=status,
                home_score=int(home_score),
                away_score=int(away_score),
                home_score_penalties=int(home_pen) if int(home_pen) else None,
                away_score_penalties=int(away_pen) if int(away_pen) else None,
                advancing_team_id=clean_value(team_ids.get(advancing_name)),
            )
            update_match(
                match,
                payload,
            )
            st.success("Resultado guardado.")
            st.session_state["last_saved_match_id"] = match["id"]
        except RealTournamentError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"No se pudo guardar el resultado: {exc}")

    recalc_disabled = st.session_state.get("last_saved_match_id") != match["id"]
    if st.button(
        "Recalcular puntos de este partido",
        key="matches_recalculate_selected_match",
        disabled=recalc_disabled,
        width="stretch",
    ):
        try:
            recalculate_match_scores(match["id"])
            st.success("Puntos del partido recalculados.")
        except Exception as exc:
            st.error(f"No se pudieron recalcular los puntos del partido: {exc}")

    if recalc_disabled:
        st.caption("Guarda el resultado seleccionado para habilitar el recálculo de ese partido.")

    if str(match.get("display_stage") or "").lower() == "group":
        group_action_cols = st.columns(2)
        if group_action_cols[0].button(
            "Recalcular clasificaciones de grupos",
            key="matches_recalculate_group_standings",
            width="stretch",
        ):
            try:
                result = recalculate_real_group_standings()
                st.success(f"Clasificaciones recalculadas: {result['updated']} filas en {result['groups']} grupos.")
            except Exception as exc:
                st.error(f"No se pudieron recalcular las clasificaciones: {exc}")
        if group_action_cols[1].button(
            "Recalcular standings + puntos",
            key="matches_recalculate_group_standings_and_scores",
            width="stretch",
        ):
            try:
                recalculate_real_group_standings()
                recalculate_group_scores()
                st.success("Standings reales y puntos de grupo recalculados.")
            except Exception as exc:
                st.error(f"No se pudieron recalcular standings y puntos: {exc}")


def render_group_standings_tab() -> None:
    st.subheader("Group standings")
    st.markdown('<div class="section-copy">Edita la tabla existente. No se crea ni modifica schema.</div>', unsafe_allow_html=True)

    try:
        standings = fetch_df(
            """
            SELECT gs.*, t.name AS team_name
            FROM group_standings gs
            LEFT JOIN teams t ON t.id = gs.team_id
            ORDER BY gs.group_letter, gs.position, t.name
            """
        )
    except Exception as exc:
        st.error(f"No se pudo cargar group_standings: {exc}")
        return

    if standings.empty:
        st.info("No hay clasificacion de grupos.")
        return

    with st.expander("Editar tabla de grupos", expanded=False):
        edited = st.data_editor(standings, width="stretch", num_rows="fixed", key="group_standings_editor")
    action_cols = st.columns(2)
    if action_cols[0].button("Guardar group_standings", key="groups_save_standings", width="stretch"):
        try:
            with db_session() as conn:
                for row in edited.to_dict("records"):
                    if pd.isna(row.get("id")):
                        continue
                    payload = {key: clean_value(value) for key, value in row.items() if key != "team_name"}
                    update_dynamic(conn, "group_standings", payload, "id = :id", {"id": row["id"]})
            st.success("Group standings guardado.")
        except Exception as exc:
            st.error(f"No se pudo guardar group_standings: {exc}")

    if action_cols[1].button("Recalcular puntos de grupos", key="groups_recalculate_scores", width="stretch"):
        try:
            recalculate_group_scores()
            st.success("Puntos de grupos recalculados.")
        except Exception as exc:
            st.error(f"No se pudieron recalcular los puntos de grupos: {exc}")

    if st.button(
        "Recalcular clasificaciones de grupos",
        key="groups_recalculate_real_standings",
        width="stretch",
    ):
        try:
            result = recalculate_real_group_standings()
            st.success(f"Clasificaciones recalculadas: {result['updated']} filas en {result['groups']} grupos.")
        except Exception as exc:
            st.error(f"No se pudieron recalcular las clasificaciones: {exc}")


def render_tournament_tab() -> None:
    st.subheader("Tournament results")
    st.markdown('<div class="section-copy">Actualiza campeon, subcampeon, semifinalistas, goleador y MVP en la tabla existente.</div>', unsafe_allow_html=True)

    try:
        results = fetch_df("SELECT * FROM tournament_results ORDER BY id")
    except Exception as exc:
        st.error(f"No se pudo cargar tournament_results: {exc}")
        return

    with st.expander("Editar resultados del torneo", expanded=False):
        edited_results = st.data_editor(results, width="stretch", num_rows="dynamic", key="tournament_results_editor")
    action_cols = st.columns(2)
    if action_cols[0].button("Guardar tournament_results", key="tournament_save_results", width="stretch"):
        try:
            with db_session() as conn:
                for row in edited_results.to_dict("records"):
                    payload = {key: clean_value(value) for key, value in row.items()}
                    if payload.get("id"):
                        update_dynamic(conn, "tournament_results", payload, "id = :id", {"id": payload["id"]})
                    else:
                        insert_dynamic(conn, "tournament_results", payload)
            st.success("Tournament results guardado.")
        except Exception as exc:
            st.error(f"No se pudo guardar tournament_results: {exc}")

    if action_cols[1].button("Recalcular especiales", key="tournament_recalculate_specials", width="stretch"):
        try:
            recalculate_special_scores()
            st.success("Puntos especiales recalculados.")
        except Exception as exc:
            st.error(f"No se pudieron recalcular los especiales: {exc}")

    if st.button(
        "Actualizar resultados finales del torneo",
        key="tournament_update_final_results",
        width="stretch",
    ):
        try:
            result = update_tournament_results_from_real_knockout()
            st.success("Tournament results actualizado desde eliminatorias reales.")
            st.caption(", ".join(result["updated_fields"]))
        except Exception as exc:
            st.error(f"No se pudieron actualizar los resultados finales: {exc}")


def render_tools_tab() -> None:
    st.subheader("Herramientas")
    st.markdown(
        '<div class="admin-note">Las acciones de recálculo borran y regeneran score_events segun la funcion elegida. No se borran tablas ni se modifica el schema.</div>',
        unsafe_allow_html=True,
    )

    if st.button("Recalcular todos los puntos", key="tools_recalculate_all_scores", width="stretch"):
        try:
            recalculate_all_scores()
            st.success("Todos los puntos recalculados.")
        except Exception as exc:
            st.error(f"No se pudieron recalcular todos los puntos: {exc}")

    tool_cols = st.columns(3)
    if tool_cols[0].button(
        "Actualizar dieciseisavos reales desde clasificaciones",
        key="tools_update_real_round_of_32",
        width="stretch",
    ):
        try:
            result = update_real_round_of_32_from_group_standings()
            st.success(f"Dieciseisavos actualizados: {result['updated']} partidos. Clave terceros: {result['third_place_key']}.")
        except Exception as exc:
            st.error(f"No se pudieron actualizar los dieciseisavos reales: {exc}")
    if tool_cols[1].button(
        "Actualizar siguientes rondas reales",
        key="tools_update_real_next_rounds",
        width="stretch",
    ):
        try:
            result = update_real_knockout_next_rounds()
            st.success(f"Siguientes rondas actualizadas: {result['updated']} partidos.")
            if result["missing_sources"]:
                st.info(f"Faltan ganadores previos para {len(result['missing_sources'])} partidos.")
        except Exception as exc:
            st.error(f"No se pudieron actualizar las siguientes rondas: {exc}")
    if tool_cols[2].button(
        "Recalcular standings + cuadro real + puntos",
        key="tools_recalculate_full_tournament_flow",
        width="stretch",
    ):
        try:
            recalculate_real_group_standings()
            update_real_round_of_32_from_group_standings()
            update_real_knockout_next_rounds()
            update_tournament_results_from_real_knockout()
            recalculate_all_scores()
            st.success("Standings, cuadro real, resultados finales y puntos recalculados.")
        except Exception as exc:
            st.error(f"No se pudo ejecutar el flujo completo: {exc}")

    st.divider()
    st.subheader("Exportaciones CSV")
    try:
        leaderboard = fetch_df("SELECT * FROM leaderboard ORDER BY total_points DESC")
        predictions = fetch_df(
            """
            SELECT
                p.id,
                p.player_id,
                pl.name AS player_name,
                pl.email AS player_email,
                p.match_id,
                m.match_number,
                p.predicted_home_score,
                p.predicted_away_score,
                p.predicted_result,
                p.predicted_advancing_team_id,
                p.predicted_goes_to_penalties,
                p.created_at,
                p.updated_at
            FROM predictions p
            JOIN players pl ON pl.id = p.player_id
            JOIN matches m ON m.id = p.match_id
            ORDER BY pl.name, m.match_number
            """
        )
        score_events = fetch_df("SELECT * FROM score_events ORDER BY calculated_at, id")
        export_cols = st.columns(3)
        export_cols[0].download_button(
            "Descargar leaderboard",
            data=leaderboard.to_csv(index=False).encode("utf-8-sig"),
            file_name="leaderboard.csv",
            mime="text/csv",
            width="stretch",
        )
        export_cols[1].download_button(
            "Descargar apuestas",
            data=predictions.to_csv(index=False).encode("utf-8-sig"),
            file_name="all_predictions.csv",
            mime="text/csv",
            width="stretch",
        )
        export_cols[2].download_button(
            "Descargar score_events",
            data=score_events.to_csv(index=False).encode("utf-8-sig"),
            file_name="score_events.csv",
            mime="text/csv",
            width="stretch",
        )
    except Exception as exc:
        st.error(f"No se pudieron preparar las exportaciones: {exc}")

    st.divider()
    st.subheader("Provider")
    provider_name = st.selectbox("Provider", ["manual", "mock", "api-football"])
    if st.button("Ejecutar provider seleccionado", key="provider_run_selected", width="stretch"):
        try:
            result = get_provider(provider_name).sync()
            st.json(result)
            with db_session() as conn:
                insert_dynamic(
                    conn,
                    "provider_sync_logs",
                    {
                        "provider": provider_name,
                        "status": "ok",
                        "payload": json.dumps(result, default=str),
                    },
                )
            st.success("Provider ejecutado.")
        except Exception as exc:
            st.error(f"No se pudo ejecutar el provider: {exc}")


_, team_names, team_ids = load_teams()
render_diagnostics()

tab_players, tab_matches, tab_groups, tab_tournament, tab_tools = st.tabs(
    ["Jugadores y pagos", "Partidos", "Grupos", "Torneo", "Herramientas"]
)

with tab_players:
    render_payments_tab()

with tab_matches:
    render_matches_tab(team_names, team_ids)

with tab_groups:
    render_group_standings_tab()

with tab_tournament:
    render_tournament_tab()

with tab_tools:
    render_tools_tab()

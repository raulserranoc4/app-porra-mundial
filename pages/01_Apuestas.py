import html

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth import current_user
from bracket import (
    BracketProjectionError,
    MissingThirdPlaceAssignmentError,
    build_full_projected_knockout_bracket,
    get_projected_bracket_for_player,
    save_knockout_round_predictions,
    validate_knockout_prediction,
)
from db import (
    db_session,
    fetch_df,
    fetch_one,
    get_engine,
    get_global_lock_at,
    insert_dynamic,
    predictions_are_open,
    table_columns,
    update_dynamic,
)
from derived_predictions import (
    get_derived_group_order_for_player,
    get_derived_specials_from_bracket,
    sync_derived_group_predictions,
    sync_derived_special_predictions,
)
from utils.flags import team_label_html
from utils.bracket_visual import render_projected_bracket_summary
from utils.prediction_state import (
    get_or_init_pending_match_ids,
    get_progress_counts,
    init_prediction_widget_value,
    load_user_predictions_cached_or_state,
    mark_prediction_saved,
    reset_pending_match_ids,
)
from utils.ui import inject_app_css, madrid_datetime, kickoff_text, status_badge, venue_text


st.set_page_config(page_title="Apuestas", layout="wide")

user = current_user()
if not user:
    st.warning("Inicia sesion para apostar.")
    st.stop()

is_open = predictions_are_open()
lock_at = get_global_lock_at()
inject_app_css()

st.markdown(
    """
    <style>
    .bet-banner {
        border: 1px solid #d8d0bf;
        background: #fffaf0;
        border-radius: 8px;
        padding: 14px 16px;
        margin: 8px 0 18px;
    }
    .bet-banner.open {
        border-color: #9bc7a8;
        background: #f1fbf3;
    }
    .bet-banner.closed {
        border-color: #e4a3af;
        background: #fff4f6;
    }
    .bet-banner-title {
        font-weight: 750;
        font-size: 1rem;
        margin-bottom: 2px;
    }
    .bet-banner-copy {
        color: #5a5f5a;
        font-size: 0.92rem;
    }
    .match-card {
        border: 1px solid #ded6c5;
        background: #fffdf8;
        border-radius: 8px;
        padding: 14px 16px 12px;
        margin: 10px 0 12px;
    }
    .match-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 10px;
    }
    .match-title {
        font-size: 1.02rem;
        font-weight: 760;
        color: #1f251f;
    }
    .match-meta {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        color: #60645f;
        font-size: 0.86rem;
        margin-top: 4px;
    }
    .pill {
        border: 1px solid #d8d0bf;
        border-radius: 999px;
        padding: 2px 8px;
        background: #f8f3e8;
        white-space: nowrap;
    }
    .current-bet {
        color: #4d514b;
        font-size: 0.9rem;
        margin-bottom: 8px;
    }
    .save-state {
        border-radius: 6px;
        display: inline-block;
        font-size: .86rem;
        font-weight: 700;
        margin-top: 9px;
        padding: 4px 8px;
    }
    .save-state.saved { background: #ecf8ef; color: #18733a; }
    .save-state.pending { background: #fff6e5; color: #8a5a00; }
    .save-updated {
        color: #62675f;
        font-size: .82rem;
        margin-top: 4px;
    }
    .position-label {
        font-weight: 700;
        color: #30362f;
        margin-top: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def clean(value):
    return None if pd.isna(value) else value


def text_or_dash(value) -> str:
    value = clean(value)
    if value is None or value == "":
        return "-"
    return str(value)


def h(value) -> str:
    return html.escape(text_or_dash(value))


def format_updated_at(value) -> str | None:
    value = clean(value)
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%d/%m/%Y %H:%M")


def render_saved_badge(
    saved: bool,
    updated_at=None,
    saved_label: str = "✅ Apuesta guardada",
    pending_label: str = "⚠️ Sin apuesta guardada",
) -> str:
    if not saved:
        return f'<div class="save-state pending">{h(pending_label)}</div>'
    updated_text = format_updated_at(updated_at)
    timestamp_html = (
        f'<div class="save-updated">Última actualización: {h(updated_text)}</div>'
        if updated_text
        else ""
    )
    return f'<div class="save-state saved">{h(saved_label)}</div>{timestamp_html}'


def stage_label(value) -> str:
    labels = {
        "group": "Fase de grupos",
        "round_of_32": "Dieciseisavos",
        "round_of_16": "Octavos",
        "quarter_final": "Cuartos",
        "quarterfinal": "Cuartos",
        "semi_final": "Semifinales",
        "semifinal": "Semifinales",
        "third_place": "Tercer puesto",
        "final": "Final",
    }
    key = str(clean(value) or "").lower()
    return labels.get(key, text_or_dash(value))


def is_group_stage(stage) -> bool:
    return str(clean(stage) or "").lower() in {"group", "groups", "group_stage", "fase de grupos"}


def team_options() -> dict[str, object]:
    df = fetch_df("SELECT id, name FROM teams ORDER BY name")
    return {row["name"]: row["id"] for row in df.to_dict("records")}


def _valid_score(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 30


def save_group_match_predictions(
    session,
    player_id,
    group_letter: str | None,
    predictions_payload: list[dict],
) -> int:
    if not player_id:
        raise RuntimeError("Debes iniciar sesión para guardar apuestas.")
    if not predictions_are_open():
        raise RuntimeError("Las apuestas están cerradas.")
    if not predictions_payload:
        raise RuntimeError("No hay apuestas para guardar.")

    match_ids = [payload.get("match_id") for payload in predictions_payload]
    if any(not match_id for match_id in match_ids) or len(set(match_ids)) != len(match_ids):
        raise RuntimeError("El grupo contiene partidos duplicados o no válidos.")
    for payload in predictions_payload:
        if not _valid_score(payload.get("predicted_home_score")) or not _valid_score(
            payload.get("predicted_away_score")
        ):
            raise RuntimeError("Los marcadores deben ser enteros entre 0 y 30.")

    rows = session.execute(
        text(
            """
            SELECT id, group_letter
            FROM matches
            WHERE stage = 'group'
              AND id = ANY(:match_ids)
            """
        ),
        {"match_ids": match_ids},
    ).mappings().all()
    valid_matches = {row["id"]: row for row in rows}
    if len(valid_matches) != len(match_ids):
        raise RuntimeError("Solo se pueden guardar aquí partidos de fase de grupos.")
    if group_letter and any(row["group_letter"] != group_letter for row in rows):
        raise RuntimeError(f"Hay partidos que no pertenecen al Grupo {group_letter}.")

    for payload in predictions_payload:
        match_id = payload["match_id"]
        values = {
            "player_id": player_id,
            "match_id": match_id,
            "predicted_home_score": payload["predicted_home_score"],
            "predicted_away_score": payload["predicted_away_score"],
            "predicted_advancing_team_id": None,
            "predicted_goes_to_penalties": False,
        }
        existing = session.execute(
            text(
                """
                SELECT id
                FROM predictions
                WHERE player_id = :player_id
                  AND match_id = :match_id
                """
            ),
            {"player_id": player_id, "match_id": match_id},
        ).mappings().first()
        if existing:
            update_dynamic(session, "predictions", values, "id = :id", {"id": existing["id"]})
        else:
            insert_dynamic(session, "predictions", values)
    return len(predictions_payload)


def remember_save(message: str, match_number=None, group_letter=None) -> None:
    st.session_state["last_save_message"] = message
    if match_number is not None:
        st.session_state["last_saved_match_number"] = match_number
    if group_letter is not None:
        st.session_state["last_saved_group_letter"] = group_letter


def saved_label_for_match(match_number) -> str:
    if st.session_state.get("save_status_by_match", {}).get(match_number) == "saved":
        return "✅ Guardado ahora"
    return "✅ Apuesta guardada"


def group_score_key(side: str, match_number) -> str:
    return f"group_{side}_{user['id']}_{match_number}"


def render_user_export() -> None:
    match_predictions = fetch_df(
        """
        SELECT
            'match' AS prediction_type,
            m.match_number,
            m.stage,
            m.group_letter,
            ht.name AS home_team,
            at.name AS away_team,
            p.predicted_home_score,
            p.predicted_away_score,
            advancing.name AS predicted_advancing_team,
            p.predicted_goes_to_penalties
        FROM predictions p
        JOIN matches m ON m.id = p.match_id
        LEFT JOIN teams ht ON ht.id = m.home_team_id
        LEFT JOIN teams at ON at.id = m.away_team_id
        LEFT JOIN teams advancing ON advancing.id = p.predicted_advancing_team_id
        WHERE p.player_id = :player_id
        ORDER BY COALESCE(m.kickoff_time, '2099-01-01'::timestamp), m.match_number
        """,
        {"player_id": user["id"]},
    )
    group_predictions = fetch_df(
        """
        SELECT
            'group' AS prediction_type,
            gp.group_letter,
            first_team.name AS predicted_first_team,
            second_team.name AS predicted_second_team,
            third_team.name AS predicted_third_team,
            fourth_team.name AS predicted_fourth_team
        FROM group_predictions gp
        LEFT JOIN teams first_team ON first_team.id = gp.predicted_first_team_id
        LEFT JOIN teams second_team ON second_team.id = gp.predicted_second_team_id
        LEFT JOIN teams third_team ON third_team.id = gp.predicted_third_team_id
        LEFT JOIN teams fourth_team ON fourth_team.id = gp.predicted_fourth_team_id
        WHERE gp.player_id = :player_id
        ORDER BY gp.group_letter
        """,
        {"player_id": user["id"]},
    )
    special_predictions = fetch_df(
        """
        SELECT
            'special' AS prediction_type,
            champion.name AS champion,
            runner_up.name AS runner_up,
            semifinalist_1.name AS semifinalist_1,
            semifinalist_2.name AS semifinalist_2,
            semifinalist_3.name AS semifinalist_3,
            semifinalist_4.name AS semifinalist_4,
            sp.top_scorer_name,
            sp.mvp_name
        FROM special_predictions sp
        LEFT JOIN teams champion ON champion.id = sp.champion_team_id
        LEFT JOIN teams runner_up ON runner_up.id = sp.runner_up_team_id
        LEFT JOIN teams semifinalist_1 ON semifinalist_1.id = sp.semifinalist_1_team_id
        LEFT JOIN teams semifinalist_2 ON semifinalist_2.id = sp.semifinalist_2_team_id
        LEFT JOIN teams semifinalist_3 ON semifinalist_3.id = sp.semifinalist_3_team_id
        LEFT JOIN teams semifinalist_4 ON semifinalist_4.id = sp.semifinalist_4_team_id
        WHERE sp.player_id = :player_id
        """,
        {"player_id": user["id"]},
    )
    export_df = pd.concat(
        [match_predictions, group_predictions, special_predictions],
        ignore_index=True,
        sort=False,
    )
    st.download_button(
        "Descargar mis apuestas CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="mis_apuestas.csv",
        mime="text/csv",
        width="stretch",
    )


def render_lock_banner() -> None:
    if is_open:
        title = "Apuestas abiertas"
        copy = f"Puedes crear y editar tus apuestas hasta {lock_at:%d/%m/%Y %H:%M %Z}."
        kind = "open"
    else:
        title = "Apuestas cerradas"
        copy = f"El cierre global fue el {lock_at:%d/%m/%Y %H:%M %Z}. Los formularios estan deshabilitados."
        kind = "closed"
    st.markdown(
        f"""
        <div class="bet-banner {kind}">
            <div class="bet-banner-title">{title}</div>
            <div class="bet-banner-copy">{copy}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def current_prediction_text(prediction: dict, teams_by_id: dict) -> str:
    if not prediction:
        return "Apuesta actual: sin guardar"
    home = clean(prediction.get("predicted_home_score"))
    away = clean(prediction.get("predicted_away_score"))
    parts = []
    if home is not None and away is not None:
        parts.append(f"{int(home)} - {int(away)}")
    advancing = clean(prediction.get("predicted_advancing_team_id"))
    if advancing:
        parts.append(f"avanza {teams_by_id.get(advancing, 'equipo seleccionado')}")
    if prediction.get("predicted_goes_to_penalties"):
        parts.append("con penales")
    return "Apuesta actual: " + (", ".join(parts) if parts else "sin guardar")


def knockout_prediction_warning(prediction: dict, projected_match: dict) -> str | None:
    if not prediction:
        return None
    home_score = clean(prediction.get("predicted_home_score"))
    away_score = clean(prediction.get("predicted_away_score"))
    if home_score is None or away_score is None:
        return None
    is_valid, _ = validate_knockout_prediction(
        home_score=int(home_score),
        away_score=int(away_score),
        home_team_id=projected_match.get("home_team_id"),
        away_team_id=projected_match.get("away_team_id"),
        advancing_team_id=clean(prediction.get("predicted_advancing_team_id")),
        goes_to_penalties=bool(prediction.get("predicted_goes_to_penalties")),
    )
    if is_valid:
        return None
    return "Esta apuesta guardada es inconsistente con el marcador. Corrígela y vuelve a guardar."


def projection_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Posición": row["position"],
                "Equipo": row["name"],
                "PJ": row["played"],
                "PG": row["won"],
                "PE": row["drawn"],
                "PP": row["lost"],
                "GF": row["goals_for"],
                "GC": row["goals_against"],
                "DG": row["goal_difference"],
                "Pts": row["points"],
            }
            for row in rows
        ]
    )


KNOCKOUT_STAGE_LABELS = {
    "round_of_32": "Dieciseisavos",
    "round_of_16": "Octavos",
    "quarter_final": "Cuartos",
    "semi_final": "Semifinales",
    "third_place": "Tercer puesto",
    "final": "Final",
}


def render_unavailable_knockout_match(projected_match: dict) -> None:
    st.markdown(
        f"""
        <div class="match-card" style="background:#f1f1ef;color:#68706a">
            <div class="match-title">
                Match {projected_match["match_number"]} · {h(KNOCKOUT_STAGE_LABELS[projected_match["stage"]])}
            </div>
            <div class="current-bet">{h(projected_match["missing_reason"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_knockout_match_fields(projected_match: dict) -> tuple[dict | None, bool]:
    if not projected_match["is_available"]:
        render_unavailable_knockout_match(projected_match)
        return None, False
    prediction = projected_match.get("existing_prediction") or {}
    home_team = projected_match["home_team_name"]
    away_team = projected_match["away_team_name"]
    match_number = projected_match["match_number"]
    teams_by_id = {
        projected_match["home_team_id"]: home_team,
        projected_match["away_team_id"]: away_team,
    }
    st.markdown(
        f"""
        <div class="match-card">
            <div class="match-head">
                <div>
                    <div class="match-title">
                        Match {match_number} · {h(KNOCKOUT_STAGE_LABELS[projected_match["stage"]])}
                    </div>
                    <div class="match-title">
                        {team_label_html(home_team)}
                        <span class="versus">vs</span>
                        {team_label_html(away_team)}
                    </div>
                </div>
            </div>
            <div class="current-bet">{h(current_prediction_text(prediction, teams_by_id))}</div>
            {render_saved_badge(
                bool(prediction),
                prediction.get("updated_at"),
                saved_label=saved_label_for_match(match_number),
            )}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if projected_match.get("warning"):
        st.warning(projected_match["warning"])
    saved_warning = knockout_prediction_warning(prediction, projected_match)
    if saved_warning:
        st.warning(saved_warning)
    if projected_match["stage"] == "final":
        st.info("El equipo que avanza en la final será tu campeón proyectado.")

    ids_by_name = {
        home_team: projected_match["home_team_id"],
        away_team: projected_match["away_team_id"],
    }
    current_team = next(
        (
            name
            for name, team_id in ids_by_name.items()
            if team_id == clean(prediction.get("predicted_advancing_team_id"))
        ),
        None,
    )
    cols = st.columns([1, 1, 1.8, 1, 1.1])
    home_key = f"ko_home_{user['id']}_{match_number}"
    away_key = f"ko_away_{user['id']}_{match_number}"
    init_prediction_widget_value(
        st.session_state,
        home_key,
        clean(prediction.get("predicted_home_score")),
    )
    init_prediction_widget_value(
        st.session_state,
        away_key,
        clean(prediction.get("predicted_away_score")),
    )
    home_score = cols[0].number_input(
        "Goles local",
        min_value=0,
        max_value=30,
        key=home_key,
        disabled=not is_open,
    )
    away_score = cols[1].number_input(
        "Goles visitante",
        min_value=0,
        max_value=30,
        key=away_key,
        disabled=not is_open,
    )
    if home_score > away_score:
        options = [home_team]
    elif away_score > home_score:
        options = [away_team]
    else:
        options = [home_team, away_team]
    if saved_warning:
        options = [""] + options
    advancing_name = cols[2].selectbox(
        "Equipo que avanza",
        options,
        index=options.index(current_team) if current_team in options else 0,
        key=f"ko_advancing_{user['id']}_{match_number}",
        format_func=lambda name: name if name else "Selecciona un equipo",
        disabled=not is_open,
    )
    penalties_key = f"ko_penalties_{user['id']}_{match_number}"
    if penalties_key not in st.session_state:
        st.session_state[penalties_key] = (
            bool(prediction.get("predicted_goes_to_penalties"))
            if home_score == away_score
            else False
        )
    elif home_score != away_score:
        st.session_state[penalties_key] = False
    penalties = cols[3].checkbox(
        "Se decide por penales",
        key=penalties_key,
        disabled=(not is_open or home_score != away_score),
    )
    if home_score == away_score and not penalties:
        st.caption(
            "Si hay empate a 90 minutos, normalmente debes indicar que se "
            "decide por penales o prórroga."
        )
    submitted = cols[4].form_submit_button(
        "Guardar partido",
        disabled=not is_open,
        width="stretch",
        key=f"save_ko_match_{user['id']}_{match_number}",
    )
    return (
        {
            "match_number": match_number,
            "predicted_home_score": int(home_score),
            "predicted_away_score": int(away_score),
            "predicted_advancing_team_id": ids_by_name.get(advancing_name),
            "predicted_goes_to_penalties": bool(penalties),
        },
        submitted,
    )


KNOCKOUT_BATCH_LABELS = {
    "round_of_32": "Guardar todos los dieciseisavos",
    "round_of_16": "Guardar todos los octavos",
    "quarter_final": "Guardar todos los cuartos",
    "semi_final": "Guardar semifinales",
    "third_place": "Guardar tercer puesto",
    "final": "Guardar final",
}


def render_knockout_round(stage: str, projected_matches: list[dict]) -> bool:
    available_matches = [match for match in projected_matches if match["is_available"]]
    saved_matches = sum(bool(match.get("existing_prediction")) for match in projected_matches)
    stage_total = len(projected_matches)
    progress_cols = st.columns([1, 3])
    progress_metric = progress_cols[0].empty()
    progress_metric.metric("Guardadas", f"{saved_matches} / {stage_total}")
    progress_bar = progress_cols[1].progress((saved_matches / stage_total) if stage_total else 0.0)
    if not is_open:
        st.warning("🔒 Apuestas cerradas")
    elif saved_matches == stage_total:
        st.success("✅ Ronda completa")
    else:
        st.warning("⚠️ Ronda pendiente")
    if len(available_matches) != stage_total:
        st.info("Completa primero la ronda anterior para desbloquear estos partidos.")
    if st.session_state.get("last_saved_knockout_stage") == stage:
        st.success(st.session_state.get("last_save_message", "Ronda guardada correctamente."))

    payloads = []
    individual_submits = {}
    with st.form(f"knockout_round_{user['id']}_{stage}"):
        for projected_match in projected_matches:
            payload, submitted = render_knockout_match_fields(projected_match)
            if payload:
                payloads.append(payload)
                individual_submits[payload["match_number"]] = submitted
        batch_submitted = st.form_submit_button(
            KNOCKOUT_BATCH_LABELS[stage],
            disabled=(not is_open or not payloads),
            width="stretch",
            key=f"save_round_{user['id']}_{stage}",
        )

    selected_payload = next(
        (
            payload
            for payload in payloads
            if individual_submits.get(payload["match_number"])
        ),
        None,
    )
    if not batch_submitted and not selected_payload:
        return False
    to_save = payloads if batch_submitted else [selected_payload]
    try:
        with db_session() as conn:
            result = save_knockout_round_predictions(
                conn,
                player_id=user["id"],
                round_name=stage,
                projected_matches_payload=to_save,
            )
            synced_specials = (
                sync_derived_special_predictions(conn, user["id"])
                if stage == "final" and not result["errores"]
                else {"synced": False}
            )
        if result["errores"]:
            for error in result["errores"]:
                st.error(error)
            return False
        for payload in to_save:
            mark_prediction_saved(
                st.session_state,
                player_id=user["id"],
                match_number=payload["match_number"],
                payload=payload,
            )
        saved_now = result["guardadas"] + result["actualizadas"]
        if batch_submitted:
            message = (
                f"✅ {KNOCKOUT_STAGE_LABELS[stage]} guardados correctamente: "
                f"{saved_now} apuestas."
            )
            st.session_state["last_saved_knockout_stage"] = stage
        else:
            message = f"✅ Apuesta del partido {selected_payload['match_number']} guardada correctamente."
            remember_save(message, match_number=selected_payload["match_number"])
        st.session_state["last_saved_knockout_stage"] = stage
        updated_saved = min(saved_matches + result["guardadas"], stage_total)
        progress_metric.metric("Guardadas", f"{updated_saved} / {stage_total}")
        progress_bar.progress((updated_saved / stage_total) if stage_total else 0.0)
        st.session_state["last_save_message"] = message
        st.session_state["active_knockout_round"] = stage
        st.success(message)
        if synced_specials["synced"]:
            st.success(
                "✅ Campeón, subcampeón y semifinalistas actualizados "
                "automáticamente desde tu cuadro."
            )
        return True
    except Exception as exc:
        st.error(f"No se pudo guardar la ronda. No se guardó ningún cambio. Detalle: {exc}")
        return False


def render_knockout_tab() -> None:
    st.divider()
    st.subheader("🏆 Cuadro Eliminatorio")
    st.caption(
        "Cada ronda se calcula con tus propias apuestas. No modifica los partidos "
        "reales globales."
    )

    progress = fetch_df(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE p.predicted_home_score IS NOT NULL
                  AND p.predicted_away_score IS NOT NULL
            ) AS saved,
            COUNT(*) AS total
        FROM matches m
        LEFT JOIN predictions p
            ON p.match_id = m.id
           AND p.player_id = :player_id
        WHERE m.stage = 'group'
        """,
        {"player_id": user["id"]},
    ).iloc[0]
    saved = int(progress["saved"])
    total = int(progress["total"])
    st.metric("Apuestas de fase de grupos guardadas", f"{saved} / {total}")
    st.progress((saved / total) if total else 0.0)
    if total != 72 or saved != 72:
        st.info(
            "Completa primero tus apuestas de fase de grupos para generar el cuadro "
            "eliminatorio."
        )
        return

    try:
        with get_engine().connect() as conn:
            bracket = get_projected_bracket_for_player(conn, user["id"])
    except MissingThirdPlaceAssignmentError as exc:
        st.warning(str(exc))
        return
    except BracketProjectionError as exc:
        st.info(str(exc))
        return
    except Exception as exc:
        st.error(f"No se pudo calcular la proyección: {exc}")
        return

    if bracket.alphabetical_tiebreak_used:
        st.warning(
            "Empate resuelto automáticamente por orden alfabético para esta proyección."
        )
    st.warning(
        "Si cambias tus apuestas de grupos, tus cruces proyectados pueden cambiar. "
        "Revisa tus apuestas de eliminatorias."
    )
    st.info(f"third_place_key: `{bracket.third_place_key}`")

    with st.expander("Ver clasificación proyectada de grupos"):
        group_columns = st.columns(3)
        for index, group_letter in enumerate(sorted(bracket.tables)):
            with group_columns[index % 3]:
                st.markdown(f"**Grupo {group_letter}**")
                st.dataframe(
                    projection_table(bracket.tables[group_letter]),
                    width="stretch",
                    hide_index=True,
                )

    with st.expander("Ver mejores terceros proyectados"):
        st.dataframe(
            projection_table(bracket.best_thirds),
            width="stretch",
            hide_index=True,
        )

    try:
        with get_engine().connect() as conn:
            knockout = build_full_projected_knockout_bracket(conn, user["id"])
    except Exception as exc:
        st.error(
            "No se pudo construir el cuadro completo. Ejecuta "
            "`python seed_knockout_placeholders.py` si faltan los partidos 89-104. "
            f"Detalle: {exc}"
        )
        return

    total_saved = 0
    total_matches = 0
    stage_progress = {}
    for stage, projected_matches in knockout.items():
        saved_matches = sum(bool(match.get("existing_prediction")) for match in projected_matches)
        stage_progress[stage] = (saved_matches, len(projected_matches))
        total_saved += saved_matches
        total_matches += len(projected_matches)
    metric_cols = st.columns(2)
    metric_cols[0].metric("Eliminatorias guardadas", f"{total_saved} / {total_matches}")
    metric_cols[1].metric(
        "Progreso",
        f"{(total_saved / total_matches) if total_matches else 0:.0%}",
    )
    st.progress((total_saved / total_matches) if total_matches else 0.0)
    st.warning(
        "Cambiar apuestas de rondas anteriores puede invalidar apuestas posteriores. "
        "Revisa el cuadro completo."
    )

    for stage in KNOCKOUT_STAGE_LABELS:
        projected_matches = knockout[stage]
        saved_matches = sum(bool(match.get("existing_prediction")) for match in projected_matches)
        stage_total = len(projected_matches)
        with st.expander(
            f"{KNOCKOUT_STAGE_LABELS[stage]} · {saved_matches}/{stage_total} guardados",
            expanded=stage == "round_of_32",
        ):
            round_saved = render_knockout_round(stage, projected_matches)
        if round_saved:
            with get_engine().connect() as conn:
                knockout = build_full_projected_knockout_bracket(conn, user["id"])


def render_group_matches_form(
    group_letter: str,
    group: pd.DataFrame,
    pred_by_match: dict,
    projected_table: list[dict] | None = None,
) -> None:
    group_rows = group.to_dict("records")
    saved_count = sum(row["id"] in pred_by_match for row in group_rows)
    st.markdown(f'<div id="group-{h(group_letter)}"></div>', unsafe_allow_html=True)
    st.markdown(f"### Grupo {group_letter}")
    progress_cols = st.columns([1, 3])
    saved_metric = progress_cols[0].empty()
    saved_metric.metric("Guardadas", f"{saved_count} / {len(group_rows)}")
    progress_bar = progress_cols[1].progress((saved_count / len(group_rows)) if group_rows else 0.0)

    if st.session_state.get("last_saved_group_letter") == group_letter:
        st.success(st.session_state.get("last_save_message", "Apuestas guardadas correctamente."))

    payloads = []
    individual_submits = {}
    with st.form(f"group_matches_{user['id']}_{group_letter}"):
        for match in group_rows:
            prediction = pred_by_match.get(match["id"], {})
            match_number = match.get("match_number") or match["id"]
            home_team = clean(match.get("home_team")) or "Local por definir"
            away_team = clean(match.get("away_team")) or "Visitante por definir"
            st.markdown(f'<div id="match-{h(match_number)}"></div>', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="match-card">
                    <div class="match-head">
                        <div>
                            <div class="match-title">
                                Match {h(match_number)} · {team_label_html(home_team)}
                                <span class="versus">vs</span>
                                {team_label_html(away_team)}
                            </div>
                            <div class="match-meta">
                                <span class="pill">{h(kickoff_text(match.get("kickoff_time")))}</span>
                                <span class="pill">{h(venue_text(match))}</span>
                            </div>
                        </div>
                        <div>{status_badge(match.get("status"))}</div>
                    </div>
                    <div class="current-bet">{h(current_prediction_text(prediction, {}))}</div>
                    {render_saved_badge(
                        bool(prediction),
                        prediction.get("updated_at"),
                        saved_label=saved_label_for_match(match_number),
                    )}
                </div>
                """,
                unsafe_allow_html=True,
            )
            cols = st.columns([1, 1, 2.5, 1.2])
            home_key = group_score_key("home", match_number)
            away_key = group_score_key("away", match_number)
            init_prediction_widget_value(
                st.session_state,
                home_key,
                clean(prediction.get("predicted_home_score")),
            )
            init_prediction_widget_value(
                st.session_state,
                away_key,
                clean(prediction.get("predicted_away_score")),
            )
            home_score = cols[0].number_input(
                "Goles local",
                min_value=0,
                max_value=30,
                key=home_key,
                disabled=not is_open,
            )
            away_score = cols[1].number_input(
                "Goles visitante",
                min_value=0,
                max_value=30,
                key=away_key,
                disabled=not is_open,
            )
            stored_home = clean(prediction.get("predicted_home_score"))
            stored_away = clean(prediction.get("predicted_away_score"))
            changed = bool(prediction) and (
                stored_home is None
                or stored_away is None
                or int(home_score) != int(stored_home)
                or int(away_score) != int(stored_away)
            )
            if changed:
                cols[2].warning("✏️ Cambios pendientes de guardar")
            else:
                cols[2].caption("El signo lo calcula la base de datos.")
            individual_submits[match["id"]] = cols[3].form_submit_button(
                "Guardar partido",
                disabled=not is_open,
                width="stretch",
                key=f"save_match_{user['id']}_{match_number}",
            )
            payloads.append(
                {
                    "match_id": match["id"],
                    "match_number": match_number,
                    "predicted_home_score": int(home_score),
                    "predicted_away_score": int(away_score),
                }
            )
        batch_submitted = st.form_submit_button(
            f"Guardar apuestas del Grupo {group_letter}",
            disabled=not is_open,
            width="stretch",
            key=f"save_group_{user['id']}_{group_letter}",
        )

    if projected_table:
        st.markdown("#### Clasificación proyectada")
        st.dataframe(
            projection_table(projected_table),
            width="stretch",
            hide_index=True,
        )

    selected_payload = next(
        (payload for payload in payloads if individual_submits[payload["match_id"]]),
        None,
    )
    if not batch_submitted and not selected_payload:
        return

    to_save = payloads if batch_submitted else [selected_payload]
    if batch_submitted and len(payloads) != 6:
        st.error(f"El Grupo {group_letter} debe tener exactamente 6 partidos antes de guardarlo.")
        return
    try:
        with db_session() as conn:
            saved = save_group_match_predictions(
                conn,
                player_id=user["id"],
                group_letter=group_letter,
                predictions_payload=to_save,
            )
            sync_derived_group_predictions(conn, user["id"], group_letter)
        if batch_submitted:
            message = f"Grupo {group_letter} guardado correctamente: {saved} apuestas actualizadas."
            remember_save(message, group_letter=group_letter)
        else:
            message = f"Partido {selected_payload['match_number']} guardado correctamente."
            remember_save(
                message,
                match_number=selected_payload["match_number"],
                group_letter=group_letter,
            )
        for payload in to_save:
            mark_prediction_saved(
                st.session_state,
                player_id=user["id"],
                match_id=payload["match_id"],
                match_number=payload["match_number"],
                payload=payload,
            )
        saved_ids = {row["id"] for row in group_rows if row["id"] in pred_by_match}
        saved_ids.update(payload["match_id"] for payload in to_save)
        updated_count = len(saved_ids)
        saved_metric.metric("Guardadas", f"{updated_count} / {len(group_rows)}")
        progress_bar.progress((updated_count / len(group_rows)) if group_rows else 0.0)
        st.success(message)
        if st.session_state.get("show_only_pending"):
            st.info(
                "✅ Guardado. Este partido seguirá visible hasta que pulses "
                "`Actualizar lista de pendientes`."
            )
    except IntegrityError:
        st.error("No se pudieron guardar las apuestas. No se guardó ningún cambio.")
    except Exception as exc:
        st.error(f"No se pudieron guardar las apuestas. No se guardó ningún cambio. Detalle: {exc}")


def render_matches_tab() -> None:
    st.subheader("1️⃣ Grupos")
    stage_col = "phase" if "phase" in table_columns("matches") else "stage"
    matches = fetch_df(
        f"""
        SELECT m.*, m.{stage_col} AS display_stage, ht.name AS home_team, at.name AS away_team
        FROM matches m
        LEFT JOIN teams ht ON ht.id = m.home_team_id
        LEFT JOIN teams at ON at.id = m.away_team_id
        ORDER BY COALESCE(m.kickoff_time, '2099-01-01'::timestamp), display_stage, m.group_letter, m.id
        """
    )

    if matches.empty:
        st.info("No hay partidos cargados todavia.")
        return
    st.info(
        "La clasificación de grupos se calcula automáticamente a partir de tus "
        "marcadores."
    )

    refresh_predictions = st.button(
        "Actualizar progreso y lista de pendientes",
        key=f"refresh_predictions_{user['id']}",
        width="content",
    )
    pred_by_match = load_user_predictions_cached_or_state(
        st.session_state,
        player_id=user["id"],
        force_refresh=refresh_predictions,
        loader=lambda: fetch_df(
            """
            SELECT p.*, m.match_number, m.stage AS match_stage
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE p.player_id = :player_id
            """,
            {"player_id": user["id"]},
        ).to_dict("records"),
    )
    teams = team_options()
    with get_engine().connect() as conn:
        projected_tables = get_derived_group_order_for_player(conn, user["id"])

    matches["calendar_date"] = matches["kickoff_time"].apply(
        lambda value: madrid_datetime(value).strftime("%d/%m/%Y") if madrid_datetime(value) is not None else "Por confirmar"
    )
    regular_matches = matches[matches["display_stage"] == "group"].copy()
    progress = get_progress_counts(
        st.session_state,
        player_id=user["id"],
        group_match_ids=set(regular_matches["id"]),
        knockout_match_numbers=set(range(73, 105)),
    )
    total_matches = progress["group_total"]
    predicted_matches = progress["group_saved"]
    pending_matches = max(total_matches - predicted_matches, 0)
    completion = (predicted_matches / total_matches) if total_matches else 0.0
    with st.expander("Resumen de progreso", expanded=False):
        metric_cols = st.columns(4)
        metric_cols[0].metric("Total partidos", total_matches)
        metric_cols[1].metric("Apuestas guardadas", f"{predicted_matches} / {total_matches}")
        metric_cols[2].metric("Apuestas pendientes", pending_matches)
        metric_cols[3].metric("Completado", f"{completion:.0%}")
        st.progress(completion)
        st.metric(
            "Eliminatorias guardadas",
            f"{progress['knockout_saved']} / {progress['knockout_total']}",
        )

    filter_cols = st.columns(4)
    selected_date = filter_cols[0].selectbox(
        "Fecha",
        ["Todas"] + sorted(regular_matches["calendar_date"].dropna().unique().tolist()),
        key="selected_date",
    )
    selected_group = filter_cols[1].selectbox(
        "Grupo",
        ["Todos"] + sorted([str(value) for value in regular_matches["group_letter"].dropna().unique()]),
        key="selected_group",
    )
    stage_options = sorted([str(value) for value in regular_matches["display_stage"].dropna().unique()])
    selected_stage = filter_cols[2].selectbox("Fase", ["Todas"] + stage_options, key="selected_phase")
    team_names = sorted(teams.keys())
    selected_team = filter_cols[3].selectbox("Equipo", ["Todos"] + team_names, key="selected_team")
    only_pending = st.checkbox("Mostrar solo partidos sin apuesta", key="show_only_pending")
    refresh_pending = st.button(
        "Actualizar lista de pendientes",
        key=f"refresh_pending_{user['id']}",
        width="content",
    )
    if refresh_pending:
        reset_pending_match_ids(st.session_state, user["id"])

    filtered = regular_matches.copy()
    if selected_date != "Todas":
        filtered = filtered[filtered["calendar_date"] == selected_date]
    if selected_group != "Todos":
        filtered = filtered[filtered["group_letter"].astype(str) == selected_group]
    if selected_stage != "Todas":
        filtered = filtered[filtered["display_stage"].astype(str) == selected_stage]
    if selected_team != "Todos":
        filtered = filtered[
            (filtered["home_team"] == selected_team) | (filtered["away_team"] == selected_team)
        ]
    if only_pending:
        visible_pending_ids = get_or_init_pending_match_ids(
            st.session_state,
            player_id=user["id"],
            all_group_match_ids=set(regular_matches["id"]),
        )
        filtered = filtered[filtered["id"].isin(visible_pending_ids)]

    if filtered.empty:
        st.info("No hay partidos con esos filtros.")
        return

    visible_groups = filtered[["display_stage", "group_letter"]].drop_duplicates()
    for _, visible_group in visible_groups.iterrows():
        stage = visible_group["display_stage"]
        group_letter = visible_group["group_letter"]
        group = regular_matches[
            (regular_matches["display_stage"] == stage)
            & (regular_matches["group_letter"] == group_letter)
        ].copy()
        label = stage_label(stage)
        if pd.notna(group_letter):
            label = f"Grupo {group_letter} · {label}"
        expanded = is_group_stage(stage)
        with st.expander(label, expanded=expanded):
            render_group_matches_form(
                str(group_letter),
                group,
                pred_by_match,
                projected_tables.get(str(group_letter)),
            )


def render_summary_tab() -> None:
    st.subheader("Resumen de mi porra")
    st.caption("Vista de solo lectura calculada desde tus marcadores y tu cuadro.")
    try:
        with get_engine().connect() as conn:
            tables = get_derived_group_order_for_player(conn, user["id"])
            try:
                bracket = get_projected_bracket_for_player(conn, user["id"])
                knockout = build_full_projected_knockout_bracket(conn, user["id"])
                derived = get_derived_specials_from_bracket(conn, user["id"])
            except BracketProjectionError:
                bracket = None
                knockout = None
                derived = {}
    except Exception as exc:
        st.error(f"No se pudo preparar el resumen: {exc}")
        return

    with st.expander("Clasificación proyectada de grupos", expanded=False):
        columns = st.columns(3)
        for index, group_letter in enumerate(sorted(tables)):
            with columns[index % 3]:
                st.markdown(f"**Grupo {group_letter}**")
                st.dataframe(projection_table(tables[group_letter]), width="stretch", hide_index=True)

    if not bracket or not knockout:
        st.info("Completa los 72 marcadores de grupos para generar tus dieciseisavos proyectados.")
        return

    st.markdown("### Mejores terceros")
    st.dataframe(projection_table(bracket.best_thirds), width="stretch", hide_index=True)
    st.markdown("### 🏆 Mi cuadro proyectado")
    st.caption(
        "El árbol avanza con los ganadores que has elegido. En móvil puedes "
        "abrir cada ronda por separado."
    )
    render_projected_bracket_summary(knockout)

    st.markdown("### Resumen final")
    summary_cols = st.columns(3)
    semifinalists = derived.get("semifinalists") or []
    finalists = derived.get("finalists") or []
    summary_cols[0].markdown("**Semifinalistas**")
    summary_cols[0].markdown(
        "<br>".join(team_label_html(team["name"]) for team in semifinalists)
        if semifinalists
        else "⚠️ Completa los cuartos.",
        unsafe_allow_html=True,
    )
    summary_cols[1].markdown("**Finalistas**")
    summary_cols[1].markdown(
        "<br>".join(team_label_html(team["name"]) for team in finalists)
        if finalists
        else "⚠️ Completa las semifinales.",
        unsafe_allow_html=True,
    )
    summary_cols[2].markdown("**Campeón proyectado**")
    summary_cols[2].markdown(
        team_label_html(derived["champion_team_name"])
        if derived.get("champion_team_name")
        else "⚠️ Completa la final.",
        unsafe_allow_html=True,
    )
    details_cols = st.columns(2)
    details_cols[0].markdown("**Subcampeón proyectado**")
    details_cols[0].markdown(
        team_label_html(derived["runner_up_team_name"])
        if derived.get("runner_up_team_name")
        else "⚠️ Completa la final.",
        unsafe_allow_html=True,
    )
    details_cols[1].markdown("**Tercer puesto proyectado**")
    details_cols[1].markdown(
        team_label_html(derived["third_place_team_name"])
        if derived.get("third_place_team_name")
        else "⚠️ Completa el partido por el tercer puesto.",
        unsafe_allow_html=True,
    )


def render_specials_tab() -> None:
    st.subheader("Premios individuales")
    st.caption("Estas son las únicas apuestas manuales que no se pueden deducir del cuadro.")
    st.info(
        "Las apuestas de campeón, subcampeón y semifinalistas ahora se derivan "
        "automáticamente del cuadro eliminatorio."
    )

    special = fetch_one("SELECT * FROM special_predictions WHERE player_id = :player_id", {"player_id": user["id"]}) or {}
    completed = sum(
        bool(str(special.get(key) or "").strip())
        for key in ("top_scorer_name", "mvp_name")
    )
    progress_cols = st.columns(2)
    progress_cols[0].metric("Premios guardados", f"{completed} / 2")
    progress_cols[1].progress(completed / 2)
    st.markdown(
        render_saved_badge(
            completed == 2,
            special.get("updated_at"),
            saved_label="✅ Premios individuales completos",
            pending_label="⚠️ Premios individuales pendientes",
        ),
        unsafe_allow_html=True,
    )

    with st.form(f"individual_awards_{user['id']}"):
        player_cols = st.columns(2)
        top_scorer = player_cols[0].text_input(
            "Máximo goleador",
            value=special.get("top_scorer_name") or special.get("top_scorer") or "",
            disabled=not is_open,
        )
        mvp = player_cols[1].text_input(
            "MVP",
            value=special.get("mvp_name") or special.get("mvp") or "",
            disabled=not is_open,
        )
        submitted = st.form_submit_button("Guardar premios individuales", disabled=not is_open, width="stretch")

    if submitted:
        if not predictions_are_open():
            st.error("Las apuestas estan cerradas.")
        else:
            payload = {
                "player_id": user["id"],
                "top_scorer_name": top_scorer.strip(),
                "mvp_name": mvp.strip(),
            }
            try:
                with db_session() as conn:
                    existing = conn.execute(
                        text("SELECT id FROM special_predictions WHERE player_id = :player_id"),
                        {"player_id": user["id"]},
                    ).mappings().first()
                    if existing:
                        update_dynamic(conn, "special_predictions", payload, "id = :id", {"id": existing["id"]})
                    else:
                        insert_dynamic(conn, "special_predictions", payload)
                message = "Premios individuales guardados correctamente."
                remember_save(message)
                st.success(message)
            except Exception:
                st.error("No se pudieron guardar los premios individuales. Inténtalo de nuevo.")


st.title("Apuestas")
render_lock_banner()
st.info(
    "Tu porra se construye de forma progresiva: primero grupos, luego cuadro, "
    "después revisas tu resumen y completas los premios individuales."
)
try:
    render_user_export()
except Exception as exc:
    st.info(f"No se pudo preparar la exportación de apuestas: {exc}")

BETTING_SECTIONS = [
    "1️⃣ Grupos",
    "2️⃣ Cuadro eliminatorio",
    "3️⃣ Resumen de mi porra",
    "4️⃣ Premios individuales",
]
legacy_section = {
    "Partidos": "1️⃣ Grupos",
    "🏆 Cuadro Eliminatorio": "2️⃣ Cuadro eliminatorio",
    "Especiales": "4️⃣ Premios individuales",
}.get(st.session_state.get("selected_tab_apuestas"))
if legacy_section:
    st.session_state["selected_tab_apuestas"] = legacy_section
elif st.session_state.get("selected_tab_apuestas") not in BETTING_SECTIONS:
    st.session_state["selected_tab_apuestas"] = "1️⃣ Grupos"

selected_tab = st.segmented_control(
    "Sección de apuestas",
    BETTING_SECTIONS,
    key="selected_tab_apuestas",
    width="stretch",
)

if selected_tab == "1️⃣ Grupos":
    try:
        render_matches_tab()
    except Exception as exc:
        st.error(f"No se pudieron cargar las apuestas por partido: {exc}")

elif selected_tab == "2️⃣ Cuadro eliminatorio":
    try:
        render_knockout_tab()
    except Exception as exc:
        st.error(f"No se pudo cargar el cuadro eliminatorio: {exc}")

elif selected_tab == "3️⃣ Resumen de mi porra":
    try:
        render_summary_tab()
    except Exception as exc:
        st.error(f"No se pudo cargar el resumen de tu porra: {exc}")

elif selected_tab == "4️⃣ Premios individuales":
    try:
        render_specials_tab()
    except Exception as exc:
        st.error(f"No se pudieron cargar las apuestas especiales: {exc}")

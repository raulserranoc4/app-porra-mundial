from __future__ import annotations

import html

import streamlit as st

from bracket import get_projected_winner_from_prediction
from utils.flags import team_label_html


BRACKET_STAGES = (
    ("round_of_32", "Dieciseisavos"),
    ("round_of_16", "Octavos"),
    ("quarter_final", "Cuartos"),
    ("semi_final", "Semifinales"),
    ("final", "Final"),
)


def _h(value) -> str:
    return html.escape(str(value or ""))


def _prediction_text(prediction: dict | None) -> str:
    if not prediction:
        return "Pendiente"
    home_score = prediction.get("predicted_home_score")
    away_score = prediction.get("predicted_away_score")
    if home_score is None or away_score is None:
        return "Pendiente"
    return f"{int(home_score)} - {int(away_score)}"


def _team_row(team_name, is_winner: bool) -> str:
    row_class = " bracket-winner" if is_winner else ""
    winner_badge = '<span class="bracket-advance">avanza</span>' if is_winner else ""
    return (
        f'<div class="bracket-team{row_class}">'
        f"{team_label_html(team_name)}"
        f"{winner_badge}"
        "</div>"
    )


def bracket_match_card_html(projected_match: dict) -> str:
    match_number = projected_match.get("match_number", "-")
    prediction = projected_match.get("existing_prediction")
    is_available = bool(projected_match.get("is_available"))
    winner, winner_warning = get_projected_winner_from_prediction(prediction, projected_match)
    warning = projected_match.get("warning") or winner_warning
    if not is_available:
        reason = projected_match.get("missing_reason") or "Por definir"
        return (
            '<div class="bracket-card bracket-card-locked">'
            f'<div class="bracket-match-meta">Match {_h(match_number)}</div>'
            '<div class="bracket-pending">Por definir</div>'
            f'<div class="bracket-source">{_h(reason)}</div>'
            "</div>"
        )

    winner_id = winner.get("team_id") if winner else None
    warning_html = (
        f'<div class="bracket-warning">{_h(warning)}</div>'
        if warning
        else ""
    )
    return (
        '<div class="bracket-card">'
        f'<div class="bracket-match-meta">Match {_h(match_number)}'
        f'<span class="bracket-score">{_h(_prediction_text(prediction))}</span></div>'
        f'{_team_row(projected_match.get("home_team_name"), winner_id == projected_match.get("home_team_id"))}'
        f'{_team_row(projected_match.get("away_team_name"), winner_id == projected_match.get("away_team_id"))}'
        f"{warning_html}"
        "</div>"
    )


def champion_card_html(final_match: dict | None) -> str:
    final_match = final_match or {}
    champion, warning = get_projected_winner_from_prediction(
        final_match.get("existing_prediction"),
        final_match,
    )
    if not champion:
        detail = warning or "Completa la final para conocer tu campeón."
        return (
            '<div class="bracket-champion bracket-card-locked">'
            '<div class="bracket-trophy">🏆</div>'
            '<div class="bracket-champion-title">Campeón proyectado</div>'
            '<div class="bracket-pending">Pendiente</div>'
            f'<div class="bracket-source">{_h(detail)}</div>'
            "</div>"
        )
    return (
        '<div class="bracket-champion">'
        '<div class="bracket-trophy">🏆</div>'
        '<div class="bracket-champion-title">Campeón proyectado</div>'
        f'<div class="bracket-champion-team">{team_label_html(champion["name"])}</div>'
        "</div>"
    )


def projected_bracket_summary_html(bracket_data: dict[str, list[dict]]) -> str:
    columns_html = []
    mobile_rounds_html = []
    for stage, title in BRACKET_STAGES:
        cards = "".join(
            bracket_match_card_html(match)
            for match in bracket_data.get(stage, [])
        )
        columns_html.append(
            '<section class="bracket-round">'
            f'<div class="bracket-round-title">{_h(title)}</div>'
            f'<div class="bracket-round-cards">{cards}</div>'
            "</section>"
        )
        mobile_rounds_html.append(
            '<details class="mobile-round">'
            f'<summary>{_h(title)}</summary>'
            f"{cards}"
            "</details>"
        )
    final_match = next(iter(bracket_data.get("final", [])), None)
    champion_html = champion_card_html(final_match)
    columns_html.append(
        '<section class="bracket-round bracket-round-champion">'
        '<div class="bracket-round-title">Campeón</div>'
        f"{champion_html}"
        "</section>"
    )
    return (
        '<div class="desktop-only bracket-scroll"><div class="bracket-grid">'
        + "".join(columns_html)
        + "</div></div>"
        + '<div class="mobile-only">'
        + "".join(mobile_rounds_html)
        + '<details class="mobile-round" open>'
        + "<summary>Campeón</summary>"
        + champion_html
        + "</details></div>"
    )


def render_projected_bracket_summary(bracket_data: dict[str, list[dict]]) -> None:
    st.markdown(
        projected_bracket_summary_html(bracket_data),
        unsafe_allow_html=True,
    )

    third_place = next(iter(bracket_data.get("third_place", [])), None)
    if third_place:
        st.markdown("#### 🥉 Tercer puesto proyectado")
        st.markdown(bracket_match_card_html(third_place), unsafe_allow_html=True)

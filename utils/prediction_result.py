def derive_prediction_result(home_score, away_score) -> str:
    if int(home_score) > int(away_score):
        return "home"
    if int(away_score) > int(home_score):
        return "away"
    return "draw"


def derive_result_from_score(home_score, away_score) -> str:
    return derive_prediction_result(home_score, away_score)


def prediction_result_db_value(home_score, away_score) -> str:
    return derive_prediction_result(home_score, away_score)


def prediction_result_label(value, home_team: str, away_team: str) -> str:
    if value == "home":
        return f"Gana {home_team}"
    if value == "away":
        return f"Gana {away_team}"
    if value == "draw":
        return "Empate"
    return "-"


def result_label_from_score(home_score, away_score, home_team_name: str, away_team_name: str) -> str:
    result = derive_prediction_result(home_score, away_score)
    if result == "home":
        return f"Resultado calculado: gana {home_team_name}"
    if result == "away":
        return f"Resultado calculado: gana {away_team_name}"
    return "Resultado calculado: empate"


def allowed_advancing_options_from_score(home_score, away_score, home_team, away_team) -> list:
    result = derive_prediction_result(home_score, away_score)
    if result == "home":
        return [home_team]
    if result == "away":
        return [away_team]
    return [home_team, away_team]

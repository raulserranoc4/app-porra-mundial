import base64
import html
from functools import lru_cache
from pathlib import Path


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets" / "flags"

TEAM_FLAGS = {
    "México": {"code": "mx", "emoji": "🇲🇽"},
    "Corea del Sur": {"code": "kr", "emoji": "🇰🇷"},
    "Sudáfrica": {"code": "za", "emoji": "🇿🇦"},
    "Chequia": {"code": "cz", "emoji": "🇨🇿"},
    "Canadá": {"code": "ca", "emoji": "🇨🇦"},
    "Suiza": {"code": "ch", "emoji": "🇨🇭"},
    "Catar": {"code": "qa", "emoji": "🇶🇦"},
    "Bosnia y Herzegovina": {"code": "ba", "emoji": "🇧🇦"},
    "Brasil": {"code": "br", "emoji": "🇧🇷"},
    "Marruecos": {"code": "ma", "emoji": "🇲🇦"},
    "Escocia": {"code": "gb-sct", "emoji": "🏴"},
    "Haití": {"code": "ht", "emoji": "🇭🇹"},
    "Estados Unidos": {"code": "us", "emoji": "🇺🇸"},
    "Australia": {"code": "au", "emoji": "🇦🇺"},
    "Paraguay": {"code": "py", "emoji": "🇵🇾"},
    "Turquía": {"code": "tr", "emoji": "🇹🇷"},
    "Alemania": {"code": "de", "emoji": "🇩🇪"},
    "Ecuador": {"code": "ec", "emoji": "🇪🇨"},
    "Costa de Marfil": {"code": "ci", "emoji": "🇨🇮"},
    "Curazao": {"code": "cw", "emoji": "🇨🇼"},
    "Países Bajos": {"code": "nl", "emoji": "🇳🇱"},
    "Japón": {"code": "jp", "emoji": "🇯🇵"},
    "Túnez": {"code": "tn", "emoji": "🇹🇳"},
    "Suecia": {"code": "se", "emoji": "🇸🇪"},
    "Bélgica": {"code": "be", "emoji": "🇧🇪"},
    "Irán": {"code": "ir", "emoji": "🇮🇷"},
    "Egipto": {"code": "eg", "emoji": "🇪🇬"},
    "Nueva Zelanda": {"code": "nz", "emoji": "🇳🇿"},
    "España": {"code": "es", "emoji": "🇪🇸"},
    "Uruguay": {"code": "uy", "emoji": "🇺🇾"},
    "Arabia Saudí": {"code": "sa", "emoji": "🇸🇦"},
    "Cabo Verde": {"code": "cv", "emoji": "🇨🇻"},
    "Francia": {"code": "fr", "emoji": "🇫🇷"},
    "Senegal": {"code": "sn", "emoji": "🇸🇳"},
    "Noruega": {"code": "no", "emoji": "🇳🇴"},
    "Irak": {"code": "iq", "emoji": "🇮🇶"},
    "Argentina": {"code": "ar", "emoji": "🇦🇷"},
    "Austria": {"code": "at", "emoji": "🇦🇹"},
    "Argelia": {"code": "dz", "emoji": "🇩🇿"},
    "Jordania": {"code": "jo", "emoji": "🇯🇴"},
    "Portugal": {"code": "pt", "emoji": "🇵🇹"},
    "Colombia": {"code": "co", "emoji": "🇨🇴"},
    "Uzbekistán": {"code": "uz", "emoji": "🇺🇿"},
    "RD Congo": {"code": "cd", "emoji": "🇨🇩"},
    "Inglaterra": {"code": "gb-eng", "emoji": "🏴"},
    "Croacia": {"code": "hr", "emoji": "🇭🇷"},
    "Panamá": {"code": "pa", "emoji": "🇵🇦"},
    "Ghana": {"code": "gh", "emoji": "🇬🇭"},
}


def normalize_team_name(team_name: object | None) -> str | None:
    if not isinstance(team_name, str):
        return None
    team_name = team_name.strip()
    return team_name or None


def get_team_flag_emoji(team_name: object | None) -> str:
    team_name = normalize_team_name(team_name)
    if not team_name:
        return ""
    return TEAM_FLAGS.get(team_name, {}).get("emoji", "")


def team_label(team_name: object | None) -> str:
    team_name = normalize_team_name(team_name)
    if not team_name:
        return "Por definir"
    emoji = get_team_flag_emoji(team_name)
    return f"{emoji} {team_name}" if emoji else team_name


def _flag_path(team_name: object | None) -> Path | None:
    team_name = normalize_team_name(team_name)
    metadata = TEAM_FLAGS.get(team_name or "")
    if not metadata:
        return None
    for extension in ("svg", "png"):
        path = ASSETS_DIR / f"{metadata['code']}.{extension}"
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=64)
def _image_data_uri(path: str) -> str:
    flag_path = Path(path)
    mime = "image/svg+xml" if flag_path.suffix.lower() == ".svg" else "image/png"
    encoded = base64.b64encode(flag_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def flag_img_html(team_name: object | None) -> str:
    path = _flag_path(team_name)
    if path:
        return (
            f'<img class="flag-img" src="{_image_data_uri(str(path))}" '
            'alt="" aria-hidden="true">'
        )
    emoji = get_team_flag_emoji(team_name)
    return f'<span class="flag">{html.escape(emoji)}</span>' if emoji else ""


def team_label_html(team_name: object | None) -> str:
    team_name = normalize_team_name(team_name)
    if not team_name:
        return '<span class="team-label"><span>Por definir</span></span>'
    return (
        '<span class="team-label">'
        f"{flag_img_html(team_name)}"
        f"<span>{html.escape(team_name)}</span>"
        "</span>"
    )

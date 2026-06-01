SHOW_PAID_BADGE = True


def is_paid(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "si", "sí"}
    if value is None:
        return False
    try:
        if value != value:
            return False
    except TypeError:
        return False
    return bool(value)


def paid_status_label(paid) -> str:
    return "✅ Pagado" if is_paid(paid) else "❌ Pendiente"


def player_display_name(name=None, email=None, paid=False, show_badge=SHOW_PAID_BADGE) -> str:
    label = str(name or email or "Participante")
    return f"{label} 💰" if show_badge and is_paid(paid) else label

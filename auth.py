import os
from datetime import datetime

import streamlit as st
from passlib.context import CryptContext
from sqlalchemy import text

from db import db_session, fetch_one, insert_dynamic, require_invite_code, table_columns, update_dynamic


pwd_context = CryptContext(schemes=[os.getenv("PASSWORD_HASH_SCHEME", "bcrypt")], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def get_player_by_email(email: str) -> dict | None:
    return fetch_one("SELECT * FROM players WHERE lower(email) = lower(:email)", {"email": email.strip()})


def get_player(player_id: int) -> dict | None:
    return fetch_one("SELECT * FROM players WHERE id = :id", {"id": player_id})


def current_user() -> dict | None:
    player_id = st.session_state.get("player_id")
    if not player_id:
        return None
    user = get_player(player_id)
    if not user:
        st.session_state.pop("player_id", None)
    return user


def login(email: str, password: str) -> tuple[bool, str]:
    player = get_player_by_email(email)
    if not player or not player.get("password_hash"):
        return False, "Email o contraseña incorrectos."
    if not verify_password(password, player["password_hash"]):
        return False, "Email o contraseña incorrectos."
    st.session_state["player_id"] = player["id"]
    return True, "Sesión iniciada."


def logout() -> None:
    st.session_state.pop("player_id", None)


def _invite_code_is_valid(conn, code: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM invite_codes WHERE upper(code) = upper(:code)"),
        {"code": code.strip()},
    ).mappings().first()
    if row:
        data = dict(row)
        if "is_active" in data and data["is_active"] is False:
            return None
        used_value = data.get("times_used", data.get("used_count", 0))
        if "max_uses" in data and data["max_uses"] is not None:
            if int(used_value or 0) >= int(data["max_uses"]):
                return None
        return data

    default_code = os.getenv("DEFAULT_INVITE_CODE", "MUNDIAL2026").strip()
    if code.strip().upper() == default_code.upper():
        return {"id": None, "code": default_code}
    return None


def register(name: str, email: str, password: str, invite_code: str | None = None) -> tuple[bool, str]:
    name = name.strip()
    email = email.strip().lower()
    if not name or not email or not password:
        return False, "Nombre, email y contraseña son obligatorios."
    if len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."
    if get_player_by_email(email):
        return False, "Ya existe un usuario con ese email."

    with db_session() as conn:
        code_data = None
        if require_invite_code():
            if not invite_code:
                return False, "El código de invitación es obligatorio."
            code_data = _invite_code_is_valid(conn, invite_code)
            if not code_data:
                return False, "Código de invitación no válido."

        admin_emails = {item.strip().lower() for item in os.getenv("ADMIN_EMAILS", "").split(",") if item.strip()}
        values = {
            "name": name,
            "email": email,
            "password_hash": hash_password(password),
            "is_admin": email in admin_emails,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        insert_dynamic(conn, "players", values)
        player = conn.execute(text("SELECT * FROM players WHERE lower(email) = lower(:email)"), {"email": email}).mappings().one()

        if code_data and code_data.get("id") and "invite_code_id" in table_columns("invite_code_usages"):
            insert_dynamic(
                conn,
                "invite_code_usages",
                {
                    "invite_code_id": code_data["id"],
                    "player_id": player["id"],
                    "used_at": datetime.utcnow(),
                },
            )
        if code_data and code_data.get("id"):
            if "times_used" in table_columns("invite_codes"):
                conn.execute(text("UPDATE invite_codes SET times_used = COALESCE(times_used, 0) + 1 WHERE id = :id"), {"id": code_data["id"]})
            elif "used_count" in table_columns("invite_codes"):
                conn.execute(text("UPDATE invite_codes SET used_count = COALESCE(used_count, 0) + 1 WHERE id = :id"), {"id": code_data["id"]})

    return True, "Registro completado. Ya puedes iniciar sesión."


def upsert_admin(name: str, email: str, password: str) -> None:
    email = email.strip().lower()
    with db_session() as conn:
        existing = conn.execute(text("SELECT id FROM players WHERE lower(email) = lower(:email)"), {"email": email}).mappings().first()
        values = {
            "name": name.strip(),
            "email": email,
            "password_hash": hash_password(password),
            "is_admin": True,
            "updated_at": datetime.utcnow(),
            "created_at": datetime.utcnow(),
        }
        if existing:
            values.pop("created_at", None)
            update_dynamic(conn, "players", values, "id = :id", {"id": existing["id"]})
        else:
            insert_dynamic(conn, "players", values)

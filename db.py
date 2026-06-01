from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


load_dotenv()


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL no está configurada. Crea un .env a partir de .env.example.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True, future=True)


@contextmanager
def db_session():
    engine = get_engine()
    with engine.begin() as conn:
        yield conn


def fetch_df(sql: str, params: dict | None = None):
    import pandas as pd

    try:
        with get_engine().connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params or {})
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Error leyendo PostgreSQL: {exc}") from exc


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None


def execute(sql: str, params: dict | None = None) -> None:
    with db_session() as conn:
        conn.execute(text(sql), params or {})


@lru_cache(maxsize=128)
def table_columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(get_engine()).get_columns(table_name)}


def insert_dynamic(conn, table_name: str, values: dict) -> None:
    cols = table_columns(table_name)
    filtered = {key: value for key, value in values.items() if key in cols}
    if not filtered:
        return
    names = ", ".join(filtered.keys())
    binds = ", ".join(f":{key}" for key in filtered.keys())
    conn.execute(text(f"INSERT INTO {table_name} ({names}) VALUES ({binds})"), filtered)


def update_dynamic(conn, table_name: str, values: dict, where_sql: str, where_params: dict) -> None:
    cols = table_columns(table_name)
    filtered = {key: value for key, value in values.items() if key in cols}
    if not filtered:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in filtered.keys())
    conn.execute(text(f"UPDATE {table_name} SET {assignments} WHERE {where_sql}"), filtered | where_params)


def app_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("APP_TIMEZONE", "Europe/Madrid"))


def parse_dt(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def get_app_setting(key: str, default: str | None = None) -> str | None:
    row = fetch_one("SELECT value FROM app_settings WHERE key = :key", {"key": key})
    if not row:
        return default
    return str(row["value"])


def get_global_lock_at() -> datetime:
    value = get_app_setting("global_predictions_lock_at", os.getenv("GLOBAL_PREDICTIONS_LOCK_AT"))
    if not value:
        value = "2026-06-11T00:00:00+02:00"
    dt = parse_dt(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=app_timezone())
    return dt


def predictions_are_open() -> bool:
    return datetime.now(app_timezone()) < get_global_lock_at().astimezone(app_timezone())


def normalize_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "si", "sí"}


def require_invite_code() -> bool:
    return normalize_bool(os.getenv("REQUIRE_INVITE_CODE"), True)

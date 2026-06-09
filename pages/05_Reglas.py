from datetime import datetime

import pandas as pd
import streamlit as st

from db import app_timezone, get_global_lock_at
from utils.ui import inject_app_css


st.set_page_config(page_title="Reglas de la porra", page_icon="📘", layout="wide")

FALLBACK_LOCK_AT = datetime.fromisoformat("2026-06-11T00:00:00+02:00")


def safe_lock_at() -> tuple[datetime, bool]:
    try:
        return get_global_lock_at().astimezone(app_timezone()), True
    except Exception:
        return FALLBACK_LOCK_AT, False


def points_table(rows: list[tuple[str, str]]) -> None:
    st.table(pd.DataFrame(rows, columns=["Acierto", "Puntos"]))


lock_at, lock_loaded = safe_lock_at()
inject_app_css()

st.title("📘 Reglas de la porra")
st.write("Aquí tienes una referencia rápida para saber qué apostar y cómo se calcula la clasificación.")

st.header("🕒 Fecha límite de apuestas")
st.info(f"Todas las apuestas se pueden crear y editar hasta el **{lock_at:%d/%m/%Y a las %H:%M}**, hora de Madrid.")
st.write("A partir de esa fecha no se podrán crear ni modificar apuestas por partido, de grupos ni especiales.")
if not lock_loaded:
    st.warning("No se ha podido leer la configuración de la base de datos. Se muestra la fecha límite prevista por defecto.")

st.header("🏆 Premios")
st.write("La aportación para participar en la porra es de **10€ por persona**.")
st.caption("Se aplicará una comisión de gestión de **1€ por participante**.")
st.write("Al finalizar el Mundial, el bote total se repartirá entre tres participantes:")

prize_cols = st.columns(3)
with prize_cols[0]:
    with st.container(border=True):
        st.subheader("🥇 1º Clasificado")
        st.metric("Premio principal", "70%")
        st.write("El jugador con más puntos al finalizar el torneo recibirá el premio principal.")
with prize_cols[1]:
    with st.container(border=True):
        st.subheader("🥈 2º Clasificado")
        st.metric("Premio secundario", "20%")
        st.write("El segundo clasificado recibirá un premio secundario.")
with prize_cols[2]:
    with st.container(border=True):
        st.subheader("🥉 Último Clasificado")
        st.metric("Premio consolación", "10%")
        st.write("El último clasificado también recibirá un premio especial de consolación.")

st.info(
    "El reparto se calculará automáticamente en función del número total de participantes. "
    "Solo se tendrán en cuenta los jugadores que hayan abonado su inscripción. "
    "La clasificación final será la mostrada en la aplicación al finalizar el torneo "
    "y tras el recálculo definitivo de puntos."
)

st.header("⚽ Apuestas por partido")
st.write(
    "Cada jugador predice el marcador de cada partido. El sistema comprueba automáticamente "
    "el marcador exacto, el signo, la diferencia de goles y los goles de cada equipo."
)
points_table(
    [
        ("Marcador exacto", "7 puntos"),
        ("Signo correcto, si no hay marcador exacto", "3 puntos"),
        ("Diferencia de goles correcta, si no hay marcador exacto", "+2 puntos"),
        ("Goles del equipo local correctos, si no hay marcador exacto", "+1 punto"),
        ("Goles del equipo visitante correctos, si no hay marcador exacto", "+1 punto"),
    ]
)
st.warning("Si aciertas el marcador exacto, recibes 7 puntos. No se suman extras por signo, diferencia o goles.")

st.header("🏆 Eliminatorias")
st.write("El marcador apostado siempre cuenta a **90 minutos**, sin incluir prórroga ni penales.")
points_table(
    [
        ("Equipo que avanza correcto", "+3 puntos"),
        ("Apostar penales cuando efectivamente los hay", "+2 puntos"),
    ]
)
st.write(
    "En eliminatorias debes elegir qué equipo avanza. Si el partido se decide por penales, "
    "los lanzamientos se registran aparte del marcador a 90 minutos."
)
st.warning(
    "En eliminatorias, el marcador y los penales solo puntúan si los dos equipos "
    "del cruce apostado coinciden con los del cruce real. Si juegan los mismos equipos "
    "con local y visitante invertidos, la app adapta el marcador. El equipo que avanza "
    "se puntúa por separado: suma +3 si pasa esa ronda, aunque jugara contra otro rival."
)

st.header("📋 Apuestas de grupos")
st.write(
    "La clasificación proyectada de cada grupo se calcula automáticamente a "
    "partir de los marcadores que apuestas. No necesitas ordenar los equipos "
    "manualmente."
)
points_table(
    [
        ("Equipo clasificado correctamente", "3 puntos"),
        ("Posición exacta", "+2 puntos"),
    ]
)
st.write("La posición exacta añade 2 puntos a los 3 del acierto de clasificación cuando corresponde.")

st.header("⭐ Apuestas especiales")
st.write(
    "Campeón, subcampeón y semifinalistas se derivan automáticamente de tu "
    "cuadro eliminatorio. Solo eliges manualmente goleador y MVP."
)
points_table(
    [
        ("Campeón", "20 puntos"),
        ("Subcampeón", "12 puntos"),
        ("Semifinalista", "8 puntos por equipo"),
        ("Goleador", "15 puntos"),
        ("MVP", "10 puntos"),
    ]
)

st.header("Resumen de puntuaciones")
summary = pd.DataFrame(
    [
        ("Partidos", "Marcador exacto", "7"),
        ("Partidos", "Signo correcto", "3"),
        ("Partidos", "Diferencia correcta", "+2"),
        ("Partidos", "Goles local correctos", "+1"),
        ("Partidos", "Goles visitante correctos", "+1"),
        ("Eliminatorias", "Equipo que avanza", "+3"),
        ("Eliminatorias", "Penales acertados", "+2"),
        ("Grupos", "Equipo clasificado", "3"),
        ("Grupos", "Posición exacta", "+2"),
        ("Especiales", "Campeón", "20"),
        ("Especiales", "Subcampeón", "12"),
        ("Especiales", "Semifinalista", "8 por equipo"),
        ("Especiales", "Goleador", "15"),
        ("Especiales", "MVP", "10"),
    ],
    columns=["Categoría", "Acierto", "Puntos"],
)
st.dataframe(summary, width="stretch", hide_index=True)

st.header("💡 Ejemplos prácticos")

with st.container(border=True):
    st.subheader("Ejemplo 1: marcador exacto")
    st.write("**Pronóstico:** 🇪🇸 España 2-1 🇺🇾 Uruguay")
    st.write("**Resultado:** 🇪🇸 España 2-1 🇺🇾 Uruguay")
    st.info("Puntos: 7 por marcador exacto.")

with st.container(border=True):
    st.subheader("Ejemplo 2: signo y diferencia")
    st.write("**Pronóstico:** 🇪🇸 España 2-1 🇺🇾 Uruguay")
    st.write("**Resultado:** 🇪🇸 España 3-2 🇺🇾 Uruguay")
    st.info("Puntos: 3 por signo correcto + 2 por diferencia correcta = 5 puntos.")

with st.container(border=True):
    st.subheader("Ejemplo 3: eliminatoria con penales")
    st.write("**Pronóstico:** 🇪🇸 España 1-1 🇺🇾 Uruguay, avanza España")
    st.write("**Resultado a 90 minutos:** 🇪🇸 España 1-1 🇺🇾 Uruguay, avanza España en penales")
    st.info("Puntos: 7 por marcador exacto + 3 por equipo que avanza. Si además apostaste penales, +2.")

st.header("📈 Clasificación")
st.write(
    "La clasificación se calcula automáticamente a partir de `score_events`. "
    "Si un resultado se corrige, el administrador puede recalcular los puntos y la clasificación se actualiza."
)

st.header("Desempates")
st.write("Si dos jugadores terminan con los mismos puntos, se aplica este orden:")
st.markdown(
    """
1. Más marcadores exactos.
2. Más signos correctos.
3. Más aciertos de equipo que avanza.
4. Más puntos por partidos.
5. Más puntos por grupos.
6. Más puntos especiales.
"""
)

st.header("❓ Preguntas frecuentes")

with st.expander("¿Puedo cambiar mis apuestas?"):
    st.write("Sí, hasta la fecha límite.")

with st.expander("¿Qué pasa si no apuesto un partido?"):
    st.write("Obtienes 0 puntos en ese partido.")

with st.expander("¿El marcador de eliminatorias incluye prórroga?"):
    st.write("No. El marcador apostado siempre corresponde a los primeros 90 minutos.")

with st.expander("¿Qué pasa si hay penales?"):
    st.write("Los penales solo cuentan para el equipo que avanza y para la apuesta específica de penales.")

with st.expander("¿Quién actualiza los resultados?"):
    st.write("El administrador o la integración con un proveedor externo.")

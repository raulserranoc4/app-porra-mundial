import streamlit as st

from auth import current_user, login, logout, register
from db import get_global_lock_at, predictions_are_open, require_invite_code
from utils.ui import inject_app_css


st.set_page_config(page_title="Porra Mundial 2026", page_icon="⚽", layout="wide")

inject_app_css()
st.markdown(
    "<style>.status-open { color: #146c43; font-weight: 700; } .status-closed { color: #9f1239; font-weight: 700; }</style>",
    unsafe_allow_html=True,
)


def lock_banner() -> None:
    lock_at = get_global_lock_at()
    if predictions_are_open():
        st.markdown(f"<span class='status-open'>Apuestas abiertas</span> hasta {lock_at:%d/%m/%Y %H:%M %Z}.", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='status-closed'>Apuestas cerradas</span> desde {lock_at:%d/%m/%Y %H:%M %Z}.", unsafe_allow_html=True)


def auth_view() -> None:
    st.title("Porra Mundial 2026")
    lock_banner()
    login_tab, register_tab = st.tabs(["Entrar", "Registro"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Iniciar sesión", width="stretch")
        if submitted:
            ok, message = login(email, password)
            if ok:
                st.success(message)
                st.rerun()
            st.error(message)

    with register_tab:
        with st.form("register_form"):
            name = st.text_input("Nombre")
            email = st.text_input("Email", key="register_email")
            password = st.text_input("Contraseña", type="password", key="register_password")
            invite_code = st.text_input("Código de invitación") if require_invite_code() else None
            submitted = st.form_submit_button("Crear cuenta", width="stretch")
        if submitted:
            ok, message = register(name, email, password, invite_code)
            if ok:
                st.success(message)
            else:
                st.error(message)


def home_view() -> None:
    user = current_user()
    if not user:
        auth_view()
        return

    st.title("Porra Mundial 2026")
    lock_banner()

    col1, col2, col3 = st.columns(3)
    col1.metric("Apuestas", "Globales")
    col2.metric("Cierre", get_global_lock_at().strftime("%d/%m/%Y"))
    col3.metric("Modo", "PostgreSQL")

    st.write(
        "Usa las páginas del menú lateral para registrar apuestas, consultar la "
        "clasificación, revisar resultados o administrar la porra."
    )


navigation = st.navigation(
    [
        st.Page(home_view, title="Inicio", default=True),
        st.Page("pages/05_Reglas.py", title="Reglas"),
        st.Page("pages/01_Apuestas.py", title="Mis Apuestas"),
        st.Page("pages/02_Clasificacion.py", title="Clasificación"),
        st.Page("pages/03_Resultados.py", title="Resultados"),
        st.Page("pages/04_Admin.py", title="Admin"),
    ]
)

user = current_user()
if user:
    with st.sidebar:
        st.write(f"**{user.get('name') or user.get('email')}**")
        st.caption("Admin" if user.get("is_admin") else "Participante")
        if st.button("Cerrar sesión", width="stretch"):
            logout()
            st.rerun()

navigation.run()

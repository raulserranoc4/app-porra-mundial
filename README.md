# Porra Mundial 2026

Aplicación web responsive construida con Streamlit para gestionar una porra
privada del Mundial 2026. Incluye registro por invitación, apuestas progresivas,
cuadro eliminatorio proyectado por jugador, clasificación automática, resultados,
administración y control de pagos.

La aplicación trabaja exclusivamente sobre una base PostgreSQL existente. No
crea el schema, no elimina tablas y no ejecuta migraciones destructivas. Puede
conectarse tanto a PostgreSQL local como a Supabase PostgreSQL mediante
`DATABASE_URL`.

## Funcionalidades

- Login y registro seguro con hash `bcrypt`.
- Registro opcionalmente protegido por código de invitación.
- Bloqueo global de edición de apuestas configurable.
- Calendario oficial con fecha, hora de Madrid, sede, ciudad y país.
- Banderas locales o emojis, sin dependencia obligatoria de internet.
- Apuestas de fase de grupos con guardado individual o masivo por grupo.
- Clasificación proyectada de grupos calculada desde los marcadores apostados.
- Asignación oficial de los ocho mejores terceros.
- Cuadro eliminatorio personal desde dieciseisavos hasta campeón.
- Guardado individual o masivo de cada ronda eliminatoria.
- Premios individuales: máximo goleador y MVP.
- Clasificación general desde la view `leaderboard`.
- Resultados, standings de grupos y exportaciones CSV.
- Panel de administración para resultados, puntuaciones, providers y pagos.
- Interfaz responsive para escritorio y móvil.

## Flujo de la porra

La experiencia de apuestas evita formularios redundantes:

1. Cada jugador completa los 72 marcadores de fase de grupos.
2. La app calcula su clasificación proyectada de los grupos A-L.
3. Los ocho mejores terceros se asignan según el Anexo C oficial.
4. La app genera los 16 cruces personales de dieciseisavos.
5. El jugador completa octavos, cuartos, semifinales, tercer puesto y final.
6. Campeón, subcampeón y semifinalistas se derivan automáticamente del cuadro.
7. El jugador completa manualmente únicamente máximo goleador y MVP.

Cada usuario puede tener un cuadro distinto. Las proyecciones personales se
guardan en `predictions`, pero nunca modifican los equipos reales globales de
`matches`.

El usuario solo introduce marcadores. El resultado del partido se calcula
automaticamente desde los goles. En eliminatorias, si el marcador no es empate,
avanza automaticamente el ganador del marcador; con empate, el usuario elige
que equipo avanza.

## Navegación

El menú lateral está organizado así:

1. `Inicio`
2. `Reglas`
3. `Mis Apuestas`
4. `Clasificación`
5. `Resultados`
6. `Admin`

`Reglas` es pública. Las páginas privadas requieren login y `Admin` solo permite
el acceso a jugadores con `players.is_admin = TRUE`.

## Requisitos

- Python 3.11 o superior.
- PostgreSQL con el schema existente de la porra.
- Acceso de escritura a la base para registro, apuestas y administración.

Dependencias principales:

- Streamlit
- SQLAlchemy
- psycopg2-binary
- pandas
- python-dotenv
- passlib con bcrypt
- requests

## Base de datos existente

La aplicación espera las tablas:

```text
players
invite_codes
invite_code_usages
password_reset_tokens
teams
matches
predictions
group_predictions
special_predictions
group_standings
tournament_results
score_events
manual_adjustments
provider_config
provider_sync_logs
app_settings
app_event_logs
```

Y las views:

```text
leaderboard
matches_summary
match_predictions_summary
group_predictions_summary
group_standings_summary
```

La columna `players.paid` permite controlar si un participante ha pagado la
porra.

## Instalación

En Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

En macOS o Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuración

Edita `.env` antes de iniciar la aplicación:

```env
DATABASE_URL=
APP_ENV=development
APP_TIMEZONE=Europe/Madrid
GLOBAL_PREDICTIONS_LOCK_AT=2026-06-11T00:00:00+02:00
FOOTBALL_PROVIDER=manual
API_FOOTBALL_KEY=
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
ADMIN_EMAILS=
PASSWORD_HASH_SCHEME=bcrypt
REQUIRE_INVITE_CODE=true
DEFAULT_INVITE_CODE=MUNDIAL2026
```

Variables importantes:

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | Cadena de conexión PostgreSQL local o Supabase. |
| `APP_TIMEZONE` | Zona horaria mostrada en la interfaz. |
| `GLOBAL_PREDICTIONS_LOCK_AT` | Fallback del cierre global de apuestas. |
| `REQUIRE_INVITE_CODE` | Activa o desactiva el código de invitación al registrar usuarios. |
| `DEFAULT_INVITE_CODE` | Código de invitación por defecto. |
| `FOOTBALL_PROVIDER` | Provider activo: `manual`, `mock` o `api-football`. |
| `API_FOOTBALL_KEY` | API key opcional para API-FOOTBALL. |
| `ALLOW_LEGACY_KNOCKOUT_SCORING` | Permite puntuar apuestas eliminatorias antiguas sin snapshot; por defecto `false`. |

Si existe `app_settings.key = 'global_predictions_lock_at'`, ese valor prevalece
sobre `GLOBAL_PREDICTIONS_LOCK_AT`.

No guardes `.env` ni secretos en el repositorio.

## Preparación inicial

### 1. Partidos de fase de grupos

Si `teams` ya contiene los 48 equipos con su `group_letter`, genera los seis
cruces de cada grupo sin duplicados:

```bash
python seed_matches.py
```

### 2. Calendario oficial

Importa el CSV oficial de forma transaccional:

```bash
python import_fixtures.py data/worldcup_2026_fixtures.csv
```

Columnas requeridas:

```text
match_number
stage
group_letter
home_team
away_team
kickoff_time
venue
city
country
```

El importador valida el archivo completo y los nombres de `teams` antes de
escribir. Si detecta un error, no inserta ni actualiza ningún partido.

### 3. Placeholders de eliminatorias

Crea los partidos 89-104 necesarios para octavos, cuartos, semifinales, tercer
puesto y final:

```bash
python seed_knockout_placeholders.py
```

El script es idempotente y no modifica partidos existentes.

### 4. Usuario administrador

Crea o actualiza un administrador:

```bash
python create_admin.py --name "Gustavo" --email "gsg090971@gmail.com" --password "cambia-esta-password"
```

La contraseña se almacena siempre como hash `bcrypt`, nunca en texto plano.

## Ejecutar la aplicación

```bash
streamlit run app.py
```

Streamlit mostrará la URL local, normalmente:

```text
http://localhost:8501
```

## Reglas de puntuación

### Partidos

| Acierto | Puntos |
| --- | ---: |
| Marcador exacto | 7 |
| Signo correcto, si no hay marcador exacto | 3 |
| Diferencia de goles correcta | +2 |
| Goles del equipo local correctos | +1 |
| Goles del equipo visitante correctos | +1 |

Si hay marcador exacto, se asignan 7 puntos y no se suman extras.

### Eliminatorias

El marcador apostado corresponde siempre a los 90 minutos:

| Acierto | Puntos |
| --- | ---: |
| Equipo que avanza en dieciseisavos | +3 |
| Equipo que avanza en octavos | +5 |
| Equipo que avanza en cuartos | +7 |
| Equipo que avanza en semifinales | +11 |
| Tercer puesto correcto | +15 |
| Campeón correcto en la final | +20 |
| Partido decidido por penales | +2 |

Si el marcador no es empate, solo puede avanzar el ganador del marcador. Los
penales únicamente se pueden seleccionar cuando hay empate a los 90 minutos.

En eliminatorias, los puntos de marcador, signo, diferencia, goles y penales
solo se conceden si los dos equipos del cruce apostado coinciden con los del
cruce real. Si los mismos equipos juegan con local y visitante invertidos, el
marcador apostado se adapta antes de calcular los puntos.

El equipo que avanza se puntua por separado: suma los puntos de esa ronda si
ese equipo pasa la misma ronda real, aunque finalmente jugara contra otro rival
o en otro `match_number`. Un mismo equipo solo puede conceder puntos de avance
una vez por jugador y ronda.

Las apuestas eliminatorias nuevas guardan un snapshot de ambos equipos. Las
apuestas antiguas sin snapshot no puntuan por marcador ni penales por defecto,
pero sí pueden sumar los puntos de avance de la ronda por acertar el equipo que
pasa. El modo legacy para puntuar su marcador solo puede activarse explicitamente con
`ALLOW_LEGACY_KNOCKOUT_SCORING=true`.

Tras aplicar las columnas de snapshot, puedes rellenar de forma segura las
predicciones de fase de grupos:

```bash
python backfill_prediction_team_snapshots.py
```

La migracion idempotente esta disponible en
`scripts/add_prediction_team_snapshots.sql`.

El script no intenta adivinar ni modificar cruces eliminatorios antiguos.

### Grupos

| Acierto | Puntos |
| --- | ---: |
| Clasificación proyectada | 0 |

Las clasificaciones de grupos no puntuan directamente. Se derivan de los
marcadores apostados y sirven para construir el cuadro de eliminatorias de cada
jugador.

### Especiales

Campeon, subcampeon y semifinalistas se derivan automaticamente del cuadro
eliminatorio apostado por cada jugador. Las apuestas manuales especiales que
quedan son maximo goleador y MVP.

| Acierto | Puntos |
| --- | ---: |
| Campeón | 20 |
| Subcampeón | 12 |
| Semifinalista | 8 por equipo |
| Máximo goleador | 15 |
| MVP | 10 |

## Puntuación y clasificación

La clasificación no depende de totales fijos guardados manualmente. Los puntos
se regeneran en `score_events` y la view `leaderboard` construye el ranking.

Recalcular toda la porra:

```bash
python recalculate_scores.py
```

Recalcular únicamente un partido:

```bash
python recalculate_scores.py --match-id 123
```

Recalcular grupos o especiales:

```bash
python recalculate_scores.py --groups
python recalculate_scores.py --specials
```

Estas operaciones eliminan únicamente eventos recalculables de `score_events`.
No borran tablas ni apuestas.

## Mi Resumen

La página `Mi Resumen` permite a cada usuario consultar únicamente su propia
puntuación por partido una vez que el resultado está finalizado y cargado.
Incluye el resultado real, la apuesta realizada, los puntos obtenidos, el
motivo del cálculo, filtros por fase, grupo y equipo, además de descarga CSV.

## Administración

La página `Admin` permite:

- Filtrar y actualizar resultados de partidos.
- Registrar marcador, penales, ganador y equipo que avanza.
- Recalcular un partido o toda la puntuación.
- Editar standings de grupos y resultados del torneo.
- Exportar leaderboard, apuestas y eventos de puntuación a CSV.
- Ejecutar providers `manual`, `mock` o `api-football`.
- Consultar métricas de jugadores, partidos, apuestas y eventos.
- Gestionar el estado de pago de los participantes.

### Flujo cuando empiezan los resultados reales

1. El admin introduce el resultado del partido desde `Admin > Partidos`.
2. La app deriva `winner_team_id` automaticamente. En fase de grupos un empate
   deja el ganador a `NULL`.
3. Si el partido es de grupo, el admin ejecuta `Recalcular clasificaciones de
   grupos`. La app recalcula `group_standings` desde los partidos finalizados.
4. Al terminar los 72 partidos de grupo, el admin ejecuta `Actualizar
   dieciseisavos reales desde clasificaciones`. La app usa
   `data/third_place_assignment_2026.json` para asignar los mejores terceros.
5. Durante eliminatorias, el admin introduce resultados y ejecuta `Actualizar
   siguientes rondas reales` para rellenar octavos, cuartos, semifinales, tercer
   puesto y final.
6. Cuando la final esta terminada, el admin ejecuta `Actualizar resultados
   finales del torneo`. Esto actualiza campeon, subcampeon y semifinalistas sin
   tocar goleador ni MVP.
7. El admin ejecuta `Recalcular todos los puntos` o `Recalcular standings +
   cuadro real + puntos` para refrescar `score_events` y el `leaderboard`.

Los desempates de grupos se calculan por puntos, diferencia de goles, goles a
favor y nombre del equipo como fallback determinista. No se implementan todavia
criterios FIFA adicionales como fair play o ranking FIFA.

### Control de pagos

La pestaña `Jugadores y pagos` incluye métricas, filtros y guardado masivo:

- `players.paid = TRUE`: jugador pagado.
- `players.paid = FALSE`: pendiente de pago.

La clasificación muestra `💰` junto a los jugadores pagados. Puedes ocultarlo
cambiando `SHOW_PAID_BADGE` en `utils/payments.py`.

## Providers

La app funciona completamente sin API key:

| Provider | Comportamiento |
| --- | --- |
| `manual` | Operación normal mediante la página Admin. |
| `mock` | Respuesta de prueba para comprobar la integración. |
| `api-football` | Conexión opcional preparada para API-FOOTBALL. |

`api-football` requiere `API_FOOTBALL_KEY`. No hay secretos hardcodeados.

## Responsive y móvil

La interfaz está optimizada para escritorio y teléfono:

- Formularios y botones apilados con áreas táctiles amplias.
- Guardado masivo de grupos y rondas disponible desde móvil.
- Clasificación y Resultados con tarjetas compactas.
- Tablas detalladas disponibles dentro de expanders.
- Cuadro eliminatorio horizontal en escritorio y por rondas desplegables en móvil.
- Edición de pagos accesible desde móvil.

Para administración avanzada se recomienda una pantalla grande.

## Exportaciones CSV

Los usuarios pueden descargar:

- Sus apuestas de partidos.
- Sus proyecciones de grupos.
- Sus apuestas especiales.

Los administradores también pueden descargar:

- Leaderboard.
- Todas las apuestas.
- Eventos de puntuación.
- Resumen de partidos.

Las exportaciones no incluyen `password_hash` ni secretos.

## Despliegue con Supabase

1. Confirma que las tablas, views y columnas requeridas existen en Supabase.
2. Configura la cadena PostgreSQL del proyecto en `DATABASE_URL`.
3. Define las variables de `.env.example` como secretos del entorno.
4. Ejecuta una vez los scripts de preparación necesarios.
5. Inicia la aplicación con:

```bash
streamlit run app.py
```

La misma base de código funciona en desarrollo local y producción.

## Despliegue en Streamlit Community Cloud

El repositorio incluye `app.py` como entrypoint y `requirements.txt` con las
dependencias fijadas para que el despliegue sea reproducible.

1. Sube el repositorio a GitHub.
2. En Streamlit Community Cloud crea una app con la rama deseada y el entrypoint
   `app.py`.
3. En `Advanced settings`, selecciona Python `3.12`.
4. En Supabase, abre `Connect` y copia la cadena de `Session pooler`. Esta ruta
   admite IPv4 e IPv6 y es la opción recomendada para una app persistente.
5. Pega los secretos en formato TOML. Como mínimo, configura `DATABASE_URL`:

```toml
DATABASE_URL = "postgresql://postgres.PROJECT_REF:password@aws-0-REGION.pooler.supabase.com:5432/postgres"
APP_ENV = "production"
APP_TIMEZONE = "Europe/Madrid"
GLOBAL_PREDICTIONS_LOCK_AT = "2026-06-11T00:00:00+02:00"
FOOTBALL_PROVIDER = "manual"
API_FOOTBALL_KEY = ""
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
ADMIN_EMAILS = "admin@example.com"
PASSWORD_HASH_SCHEME = "bcrypt"
REQUIRE_INVITE_CODE = "true"
DEFAULT_INVITE_CODE = "cambia-este-codigo"
```

No subas `.env` ni `.streamlit/secrets.toml` a Git. Community Cloud expone los
secretos de nivel raíz como variables de entorno, que es el formato consumido
por la aplicación. Si la contraseña contiene caracteres reservados de una URL,
como `@`, `:`, `/`, `?` o `#`, codifícalos antes de incluirla en
`DATABASE_URL`.

## Tests

Ejecuta la suite:

```bash
python -m unittest discover -s tests -v
```

Los tests cubren el bracket proyectado, asignaciones de terceros, validaciones de
eliminatorias, sincronización de predicciones derivadas, estado local de
formularios, presentación responsive del cuadro y helpers de pagos.

## Seguridad operativa

- La aplicación no ejecuta `DROP TABLE`.
- No recrea el schema.
- No genera una base nueva.
- No almacena contraseñas en texto plano.
- No expone `password_hash` en la interfaz ni en exportaciones.
- Las importaciones de calendario y los guardados masivos son transaccionales.
- Los cruces proyectados de cada usuario no modifican los resultados reales.

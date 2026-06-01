# Archivos para implementar dieciseisavos proyectados correctos

## 1. Generar el JSON oficial de asignación de terceros

Ejecuta desde la raíz de tu proyecto:

```bash
python scripts/generate_third_place_assignment_2026.py
```

Esto crea:

```text
data/third_place_assignment_2026.json
```

Ese archivo debe contener 495 combinaciones.

## 2. Verificar que se generó correctamente

```bash
python - <<'PY'
import json
data = json.load(open('data/third_place_assignment_2026.json', encoding='utf-8'))
assignments = data.get('assignments', data)
print(len(assignments))
print(assignments.get('ABCDEFGH'))
PY
```

Debe imprimir:

```text
495
{...}
```

## 3. Ejecutar Codex

Después de generar el JSON, copia y ejecuta el comando de:

```text
codex_prompt_round_of_32_projected.txt
```

## 4. Qué hará Codex

Codex debe crear `bracket.py`, integrar la sección de dieciseisavos proyectados en `pages/01_Apuestas.py`, y permitir apostar los partidos 73-88 usando los equipos proyectados de cada usuario.

## 5. Importante

No se debe modificar `matches.home_team_id` ni `matches.away_team_id` para los partidos 73-88, porque cada usuario puede tener cruces proyectados diferentes.

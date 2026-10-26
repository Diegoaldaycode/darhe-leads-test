# DARHE · Limpieza y calificación de leads

Toma el CSV de leads, lo **limpia**, **une duplicados**, **califica** (A / B / C / Descartado) con una razón de una línea,
marca qué necesita **revisión humana** y genera el **resumen de una página para Christian**.
Python 3.10+ y **solo librería estándar** (no hay nada que instalar, no hay llaves ni APIs de pago).

## Cómo correrlo

```bash
python -m leadflow data/leads_test_darhe.csv --json     # genera los archivos de abajo en la carpeta actual
python -m unittest discover -s tests -v                 # 26 pruebas
```

| Archivo | Qué es |
|---|---|
| `leads_calificados.csv` (y `.json`) | Salida principal: un renglón por lead original |
| `RESUMEN_CHRISTIAN.md` | Resumen de una página, lenguaje no técnico (se genera solo desde los datos) |
| `leads_con_error.csv` | Solo aparece si algún renglón no se pudo procesar |

Columnas de la salida: `id, fecha, nombre, empresa, email, email_alterno, telefono, segmento, num_empleados, empleados_fuente, ciudad, fuente, mensaje, duplicado_de, ids_fusionados, calificacion, razon, siguiente_accion, requiere_revision, motivo_revision, prioridad, notas_limpieza`.

- El lead **principal** de un grupo de duplicados trae el *mejor dato de cada campo* y `ids_fusionados` (p. ej. `1,3`). Los otros renglones del grupo traen `duplicado_de = <id del principal>` y la acción "no contactar por separado", para no perder trazabilidad.
- `prioridad` ordena la cola de llamadas (1 = primero). Los descartados y duplicados no tienen prioridad.
- `notas_limpieza` es la bitácora de cada cambio (qué dato se descartó o corrigió y por qué).

### Opcionales incluidos
- **Webhook**: `WEBHOOK_TOKEN=algo python -m leadflow.webhook --puerto 8080` y `POST /leads` con JSON. Calcula duplicados contra los leads recibidos antes.
- **Supabase**: `sql/schema.sql` (tabla, checks, índices, vista `cola_para_christian`, RLS activado). **No** está conectado: el webhook guarda en un archivo local.
- **LLM para el mensaje**: no lo usé (ver "dos semanas más"). El mensaje se lee con palabras clave documentadas en `leadflow/config.py`.

## Estructura

```
leadflow/normalize.py   limpieza de teléfono, correo, nombre, empresa, segmento, empleados
leadflow/dedupe.py      detección (union-find) y fusión de duplicados
leadflow/scoring.py     reglas A/B/C/Descartado, razón, acción, motivos de revisión, puntaje de prioridad
leadflow/summary.py     resumen para Christian
leadflow/pipeline.py    CLI y flujo completo
leadflow/config.py      TODAS las reglas ajustables (segmentos, 20 empleados, spam, competidores)
```

## Supuestos y decisiones (donde las reglas no alcanzan)

**Limpieza**
- Teléfono: se quitan símbolos, lada `52`/`521`/`044`/`045` y extensiones; debe quedar de 10 dígitos que no empiecen con 0 o 1 y que no sean todos iguales (`0000000000` es inválido). Salida `+52XXXXXXXXXX`. Solo México; un `+1…` se marca inválido. No valido que la lada exista.
- Correo: minúsculas y formato válido. `ana.torres@pilar` (sin dominio completo) es inválido y **no lo "arreglo"** adivinando `.com`. No consulto DNS, así que `.example` pasa.
- Segmento: sinónimos sin acentos (`restaurant`→`restaurantero`, `construcción`→`construccion`). Un segmento no reconocido (p. ej. hotelería) se conserva tal cual y cuenta como fuera de segmento. Si viene vacío se intenta inferir por el nombre de la empresa y **siempre** se marca para revisión.
- Empleados: si el campo es inválido (`abc`) y el mensaje dice una cifra clara ("somos como 60"), uso esa cifra, la etiqueto `empleados_fuente = mensaje` y la mando a revisión.

**Duplicados**: mismo teléfono válido, mismo correo válido, o mismo nombre + empresa compatible. Un nombre solo no basta. Si se fusionan por teléfono/correo con nombres distintos, se marca revisión (podría ser una línea compartida). Si dos correos válidos difieren, el segundo va a `email_alterno`. Si las cifras de empleados difieren, gana la más reciente y se avisa.

**Calificación** (la primera regla que aplica gana): spam → Descartado; competidor → Descartado *con revisión*; sin contacto válido → Descartado; fuera de segmento → C; < 20 empleados → C; sin dato de empleados → B; ≥ 20 empleados → A si hay necesidad concreta (cotización, demo o problema descrito), si no B. "Contacto válido" = al menos un teléfono **o** un correo válido.

Casos que las reglas no cubren y cómo los resolví (todos con `requiere_revision = sí`):

| Lead | Decisión | Por qué |
|---|---|---|
| 6 Grupo Salas (250 empl., referido, sin necesidad explícita) | **B** | Por regla, sin necesidad concreta no es A; pero es el lead más grande y llegó recomendado. Queda alto en la cola y se pregunta si se trata como A. |
| 9 Constructora Lara (18 fijos, 60 eventuales, "Urge") | **B** | Con 18 sería C; la contradicción con el mensaje justifica una llamada. No decido yo si los eventuales cuentan. |
| 12 Logística Ríos (`abc`, "como 60", problema claro) | **A** | La cifra del mensaje es aproximada; se valida en la llamada. |
| 13 Tacos Paredes ("¿Cuánto cuesta?") | **B** | Preguntar precio no es describir una necesidad. Si Christian lo cuenta como cotización, sube a A. |
| 15 Hotel Campos (hotelería, 70 empl., problema concreto) | **C** | Fuera de segmento por regla; se avisa por si quieren una excepción. |
| 7 Despacho Vega (8 empl., "para mis clientes") | **C** | Cumple C; pero podría ser un canal/revendedor. |
| 11 "Competencia Monederos SA" | **Descartado** | El nombre y el pedido de comisiones lo delatan, pero declara 500 empleados: Christian confirma antes de descartar. |
| 2, 8, 10 | sin revisión | Caen limpiamente en las reglas. |

**Revisión humana**: marco solo lo ambiguo, no todo. Christian valida *todo* antes de contactar, y si cada renglón dice "revisar" la marca deja de servir.

**Prioridad**: puntaje = base por calificación + tamaño + necesidad concreta + urgencia ("urge", "esta semana") + referido + escribió más de una vez − un descuento si el dato de empleados es estimado. Las fórmulas están en `scoring._puntaje`.

**Fechas**: los leads son del 1 al 8 de octubre y hoy es 26. El resumen lo advierte: los que pedían respuesta rápida ya esperaron semanas.

## ¿Qué pasa si llega un lead roto?

Un renglón malo **nunca tumba el lote**:
- Renglón vacío, o que lanza una excepción → va a `leads_con_error.csv` con el número de renglón y el error; los demás se procesan.
- Columnas faltantes, valores `None` o encabezados con otros nombres (`correo`, `celular`, `giro`…) → se leen con alias; lo que falta queda vacío.
- Sin teléfono ni correo válido → **Descartado** ("sin forma de contactarlo"), con revisión si tenía interés o segmento válido (se podría rescatar).
- `id` vacío o repetido → se asigna/renombra y se avisa.
- Campos de más de 2,000 caracteres se recortan. Se acepta UTF-8 (con o sin BOM) y Windows-1252, y separador `,` `;` tab o `|`.
- Celdas que empiezan con `=`, `@`, `+`, `-` se escriben con `'` para evitar inyección de fórmulas al abrir el CSV en Excel.
- Archivo vacío o inexistente → mensaje claro y código de salida 2.
- Webhook: token opcional, límite de 20 KB, responde 400/401/413 y no cae por una línea corrupta del almacén.

## Cómo comprobé que funciona

1. **Resultado esperado definido antes de correr el código**: revisé los 15 leads uno por uno y fijé la calificación esperada de cada uno y los dos pares de duplicados (1–3 y 4–14); esas expectativas son las pruebas de `TestMuestra`.
2. **26 pruebas automáticas** (`tests/`): normalización por casos, calificaciones esperadas de los 15 leads, que la fusión conserve el mejor dato (nombre con acento, correo válido, 45 empleados), que el resumen quepa en una página, idempotencia (correr dos veces da lo mismo) y casos rotos (renglón vacío, excepción forzada con `mock`, texto de 100 mil caracteres, inyección de fórmulas, archivo vacío, Windows-1252 con `;`, mismo nombre en empresas distintas que **no** debe fusionarse).
3. **Corrida real del CLI y del webhook** (con `curl`, incluyendo token inválido y JSON malformado).
4. Un hallazgo: en la prueba del webhook mi regla de teléfonos rechazaba `55 4444 5555` por tener solo dos dígitos distintos; la relajé a "todos iguales" y dejé una prueba que lo cubre (detalle en `BITACORA_IA.md`).

Límites honestos: las reglas de mensaje son palabras clave; "¿Funciona para hoteles?" o ironía se les escapan. Los 15 leads son pocos para medir precisión de verdad.

## Con dos semanas más

1. **LLM para el mensaje**, con salida JSON validada (necesidad, urgencia, número de personas, idioma) y *fallback* a las palabras clave si falla; sin mandar datos personales innecesarios.
2. **Supabase real**: webhook → tabla, dedupe contra la base, y una vista/tablero donde Christian valide con un clic (`validado`, `contactado`, `descartado`) y quede registro de quién y cuándo.
3. **Aprender de Christian**: guardar cada decisión que contradiga la calificación y usarla para recalibrar umbrales (¿20 empleados incluye eventuales? ¿"¿cuánto cuesta?" cuenta como cotización?).
4. **Duplicados difusos** (distancia de edición en nombres/empresas) y validación de ladas con `libphonenumber`; verificación MX del dominio del correo.
5. **Antigüedad del lead** dentro del puntaje y alertas por leads A sin atender.
6. Entradas reales: WhatsApp Business API, Meta Lead Ads y formularios web hacia el mismo webhook; cola de reintentos.
7. **Privacidad**: aviso de privacidad (LFPDPPP), retención y borrado; el CSV con datos personales no debería vivir en un repo.
8. CI con más casos (generados al azar) y medir precisión con un set etiquetado por Christian.

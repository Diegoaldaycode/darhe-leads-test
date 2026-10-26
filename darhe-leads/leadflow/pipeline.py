"""Flujo completo: leer CSV -> normalizar -> deduplicar -> calificar -> escribir salidas.

    python -m leadflow data/leads_test_darhe.csv --json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .dedupe import find_groups, merge_group
from .models import Lead
from .normalize import clean_text, normalize_row
from .scoring import Evaluacion, evaluate

COLUMNAS_SALIDA = [
    "id", "fecha", "nombre", "empresa", "email", "email_alterno", "telefono", "segmento",
    "num_empleados", "empleados_fuente", "ciudad", "fuente", "mensaje",
    "duplicado_de", "ids_fusionados", "calificacion", "razon", "siguiente_accion",
    "requiere_revision", "motivo_revision", "prioridad", "notas_limpieza",
]
MAX_CAMPO = 2000          # un campo más largo se recorta (protección ante basura)
COLUMNAS_SIN_SANEAR = {"telefono"}


@dataclass
class Resultado:
    filas: list[dict] = field(default_factory=list)          # una por lead original, en orden
    principales: list[tuple[Lead, Evaluacion, int | None]] = field(default_factory=list)  # lead fusionado, evaluación, prioridad
    errores: list[dict] = field(default_factory=list)        # renglones que no se pudieron procesar


# ---------------------------------------------------------------- lectura
def leer_filas(ruta: str | Path) -> list[dict]:
    datos = Path(ruta).read_bytes()
    if not datos.strip():
        raise ValueError("el archivo está vacío")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            texto = datos.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    primera = texto.splitlines()[0] if texto.strip() else ""
    delim = max(",;\t|", key=primera.count) if primera else ","
    filas = list(csv.DictReader(io.StringIO(texto), delimiter=delim))
    if not filas:
        raise ValueError("el archivo no tiene renglones de datos")
    return filas


# ---------------------------------------------------------------- proceso
def _a_texto_seguro(raw: dict) -> dict:
    """Los valores None (renglón corto) o listas (renglón largo) se vuelven texto y se recortan."""
    out = {}
    for k, v in raw.items():
        if k is None:
            continue
        if isinstance(v, list):
            v = " ".join(v)
        out[k] = clean_text(v)[:MAX_CAMPO]
    return out


def procesar(filas_crudas: list[dict]) -> Resultado:
    res = Resultado()
    leads: list[Lead] = []
    vistos: set[str] = set()
    for n, raw in enumerate(filas_crudas, start=2):          # renglón 2 = primer dato (el 1 es el encabezado)
        try:
            raw = _a_texto_seguro(raw)
            if not any(raw.values()):
                res.errores.append({"renglon": n, "error": "renglón vacío", **raw})
                continue
            lead = normalize_row(raw, fallback_id=f"fila{n}")
            if lead.id in vistos:
                nuevo = f"{lead.id}-dup{n}"
                lead.notas_limpieza.append(f"id repetido en el archivo ('{lead.id}'); se renombró a '{nuevo}'")
                lead.avisos_revision.append("el id venía repetido en el archivo de origen")
                lead.id = nuevo
            vistos.add(lead.id)
            leads.append(lead)
        except Exception as exc:                              # un lead roto nunca tumba el lote
            res.errores.append({"renglon": n, "error": f"{type(exc).__name__}: {exc}", **{str(k): str(v) for k, v in raw.items()}})

    fusionados: dict[str, tuple[Lead, Evaluacion]] = {}
    pertenece: dict[str, str] = {}
    for grupo in find_groups(leads):
        try:
            m = merge_group(grupo)
            ev = evaluate(m)
        except Exception as exc:
            for l in grupo:
                res.errores.append({"renglon": l.id, "error": f"{type(exc).__name__}: {exc}", **{str(k): str(v) for k, v in l.raw.items()}})
            continue
        fusionados[m.id] = (m, ev)
        for l in grupo:
            pertenece[l.id] = m.id

    # prioridad: A/B/C ordenados por puntaje; los descartados no entran en la cola
    cola = sorted((x for x in fusionados.values() if x[1].calificacion != "Descartado"),
                  key=lambda x: (-x[1].puntaje, x[0].id))
    prioridad = {m.id: i for i, (m, _) in enumerate(cola, start=1)}
    for m, ev in fusionados.values():
        res.principales.append((m, ev, prioridad.get(m.id)))
    res.principales.sort(key=lambda t: (t[2] is None, t[2] or 0, t[0].id))

    for l in leads:
        if l.id not in pertenece:
            continue
        pid = pertenece[l.id]
        m, ev = fusionados[pid]
        if l.id == pid:
            res.filas.append(_fila(m, ev, prioridad.get(pid), duplicado_de=""))
        else:
            res.filas.append(_fila(l, Evaluacion(
                ev.calificacion, f"Duplicado de #{pid}: se atiende allá.", f"No contactar por separado; ver lead #{pid}.", [], 0),
                None, duplicado_de=pid))
    return res


def _fila(l: Lead, ev: Evaluacion, prioridad: int | None, duplicado_de: str) -> dict:
    return {
        "id": l.id, "fecha": l.fecha, "nombre": l.nombre, "empresa": l.empresa, "email": l.email,
        "email_alterno": l.email_alterno, "telefono": l.telefono, "segmento": l.segmento,
        "num_empleados": "" if l.num_empleados is None else l.num_empleados,
        "empleados_fuente": l.empleados_fuente, "ciudad": l.ciudad, "fuente": l.fuente, "mensaje": l.mensaje,
        "duplicado_de": duplicado_de, "ids_fusionados": ",".join(l.ids_fusionados) if len(l.ids_fusionados) > 1 else "",
        "calificacion": ev.calificacion, "razon": ev.razon, "siguiente_accion": ev.siguiente_accion,
        "requiere_revision": "sí" if ev.revision else "no",
        "motivo_revision": " | ".join(dict.fromkeys(ev.revision)),
        "prioridad": "" if prioridad is None else prioridad,
        "notas_limpieza": " | ".join(l.notas_limpieza),
    }


# ---------------------------------------------------------------- escritura
def _sanear(columna: str, valor):
    """Evita inyección de fórmulas al abrir el CSV en Excel/Sheets."""
    if isinstance(valor, str) and columna not in COLUMNAS_SIN_SANEAR and valor[:1] in ("=", "@", "+", "-", "\t", "\r"):
        return "'" + valor
    return valor


def escribir_csv(filas: list[dict], ruta: Path, columnas: list[str]) -> None:
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: Excel muestra bien los acentos
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({c: _sanear(c, fila.get(c, "")) for c in columnas})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="leadflow", description="Limpia, deduplica y califica leads.")
    ap.add_argument("entrada", help="CSV de leads")
    ap.add_argument("--salida", default=".", help="carpeta de salida (default: carpeta actual)")
    ap.add_argument("--json", action="store_true", help="además de CSV, escribe leads_calificados.json")
    args = ap.parse_args(argv)

    try:
        filas = leer_filas(args.entrada)
    except (OSError, ValueError) as exc:
        print(f"ERROR: no se pudo leer '{args.entrada}': {exc}", file=sys.stderr)
        return 2

    res = procesar(filas)
    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)
    escribir_csv(res.filas, out / "leads_calificados.csv", COLUMNAS_SALIDA)
    if args.json:
        (out / "leads_calificados.json").write_text(json.dumps(res.filas, ensure_ascii=False, indent=2), encoding="utf-8")
    if res.errores:
        cols = sorted({k for e in res.errores for k in e}, key=lambda k: (k not in ("renglon", "error"), k))
        escribir_csv(res.errores, out / "leads_con_error.csv", cols)

    from .summary import generar_resumen
    (out / "RESUMEN_CHRISTIAN.md").write_text(generar_resumen(res, total_origen=len(filas)), encoding="utf-8")

    conteo: dict[str, int] = {}
    for m, ev, _ in res.principales:
        conteo[ev.calificacion] = conteo.get(ev.calificacion, 0) + 1
    print(f"{len(filas)} renglones leídos -> {len(res.principales)} leads únicos | " +
          " ".join(f"{k}:{v}" for k, v in sorted(conteo.items())) +
          f" | para revisión: {sum(1 for _, ev, _ in res.principales if ev.revision)} | con error: {len(res.errores)}")
    print(f"Archivos en {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

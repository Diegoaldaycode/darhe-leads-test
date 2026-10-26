"""Resumen de una página para el área comercial (lenguaje no técnico)."""
from __future__ import annotations

from .models import Lead
from .scoring import Evaluacion

MAX_LLAMAR_PRIMERO = 4


def _telefono_legible(tel: str) -> str:
    return f"{tel[:3]} {tel[3:5]} {tel[5:9]} {tel[9:]}" if len(tel) == 13 else tel


def _contacto(l: Lead) -> str:
    partes = [p for p in (_telefono_legible(l.telefono) if l.telefono else "", l.email) if p]
    return " · ".join(partes)


def _una_linea(texto: str, limite: int = 150) -> str:
    texto = texto.replace("\n", " ")
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def generar_resumen(res, total_origen: int) -> str:
    P = res.principales
    por = lambda cal: [(l, e, p) for l, e, p in P if e.calificacion == cal]
    A, B, C, D = por("A"), por("B"), por("C"), por("Descartado")
    n_dup = total_origen - len(P) - len(res.errores)
    L: list[str] = []
    L.append("# Resumen de leads para Christian\n")
    L.append(f"Llegaron **{total_origen} leads**; {n_dup} eran repetidos y quedaron unidos, así que hay **{len(P)} personas/empresas distintas**: "
             f"**{len(A)} A**, **{len(B)} B**, **{len(C)} C** y **{len(D)} descartados**. "
             "Nadie ha sido contactado: todo espera tu visto bueno.\n")

    L.append("## 1. Llama primero (A)\n")
    for i, (l, e, _) in enumerate(A[:MAX_LLAMAR_PRIMERO], start=1):
        aviso = " ⚠️ *revisar antes*" if e.revision else ""
        L.append(f"{i}. **{l.nombre}, {l.empresa}** ({l.ciudad}). {_contacto(l)}{aviso}  \n   {_una_linea(e.razon)}")
    L.append("")

    L.append("## 2. Después (B): una llamada para completar datos\n")
    for l, e, _ in B:
        extra = "referido, " if "referido" in l.fuente else ""
        L.append(f"- **{l.nombre}, {l.empresa}**: {extra}{l.num_empleados} empleados" + (" ⚠️" if e.revision else ""))
    L.append("")

    para_revisar = [(l, e) for l, e, _ in P if e.revision]
    L.append("## 3. Necesito tu decisión antes de avanzar\n")
    L.append("Las reglas actuales no alcanzan para estos casos; dejé mi supuesto y tú decides:\n")
    for l, e in para_revisar:
        L.append(f"- **{l.empresa}** ({e.calificacion}): {e.revision[0]}")
    L.append("")

    L.append("## 4. No llamar\n")
    if C:
        L.append("- **C (poco prioritarios, solo correo informativo):** " + "; ".join(f"{l.empresa}" for l, _, _ in C) + ".")
    if D:
        etiqueta = lambda e: "spam" if e.razon.startswith("Spam") else ("posible competidor" if "competidor" in e.razon else "sin contacto")
        L.append("- **Descartados:** " + "; ".join(f"{l.empresa or l.nombre} ({etiqueta(e)})" for l, e, _ in D) + ".")
    if res.errores:
        L.append(f"- **{len(res.errores)} renglón(es) no se pudieron leer**: están en `leads_con_error.csv`.")
    L.append("")
    fechas = sorted(l.fecha for l, _, _ in P if l.fecha)
    if fechas:
        L.append(f"*Los leads son del {fechas[0]} al {fechas[-1]}: los que pedían respuesta rápida ya llevan días esperando.*")
    return "\n".join(L) + "\n"

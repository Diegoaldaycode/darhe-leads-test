"""Limpieza y normalización de los campos de un lead. Todo es tolerante a datos rotos:
ninguna función lanza excepción por un valor raro; devuelve vacío/inválido y una nota."""
from __future__ import annotations

import re
import unicodedata

from . import config
from .models import Lead

_PARTICULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "da", "di", "van", "von"}
_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")

# Nombres de columna aceptados (por si llega un archivo con encabezados distintos)
_ALIAS_COLUMNAS = {
    "id": ["id", "folio"],
    "fecha": ["fecha", "date", "fecha_alta"],
    "nombre": ["nombre", "name", "contacto"],
    "empresa": ["empresa", "company", "razon_social"],
    "email": ["email", "correo", "e-mail", "mail"],
    "telefono": ["telefono", "tel", "celular", "whatsapp", "phone"],
    "segmento": ["segmento", "giro", "industria", "segment"],
    "num_empleados": ["num_empleados", "empleados", "no_empleados", "employees"],
    "ciudad": ["ciudad", "city"],
    "fuente": ["fuente", "origen", "source", "canal"],
    "mensaje": ["mensaje", "message", "comentarios", "notas"],
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def fold(s: str | None) -> str:
    """Minúsculas, sin acentos, espacios colapsados. Para COMPARAR, nunca para mostrar."""
    return re.sub(r"\s+", " ", strip_accents(s or "").lower()).strip()


def clean_text(s) -> str:
    if s is None:
        return ""
    s = str(s).replace("\u00a0", " ").replace("\ufeff", "")
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def get_field(raw: dict, campo: str) -> str:
    """Busca el valor de una columna por nombre canónico o alias, sin importar mayúsculas/acentos/BOM."""
    claves = {fold(clean_text(k)): k for k in raw if k is not None}
    for alias in _ALIAS_COLUMNAS[campo]:
        if alias in claves:
            return clean_text(raw[claves[alias]])
    return ""


# ---------- Nombres y empresas ----------
def title_name(s: str) -> str:
    """Capitaliza nombres escritos en MAYÚSCULAS o minúsculas. Si ya vienen mezclados, se respetan."""
    s = clean_text(s)
    if not s or not (s.isupper() or s.islower()):
        return s
    palabras = []
    for i, p in enumerate(s.lower().split(" ")):
        palabras.append(p if (i > 0 and p in _PARTICULAS) else p[:1].upper() + p[1:])
    return " ".join(palabras)


def normalize_company(s: str) -> str:
    s = title_name(s)
    return re.sub(r"\bS\.?\s?A\.?\s?de\s?C\.?\s?V\.?(?!\w)", "SA de CV", s, flags=re.I)


def company_key(s: str) -> str:
    """Clave para comparar empresas: sin acentos, sin puntuación ni sufijos legales."""
    k = re.sub(r"[^a-z0-9 ]", " ", fold(s))
    k = re.sub(r"\b(s a de c v|sa de cv|s de r l de c v|s de rl de cv|s de rl|sapi de cv|sapi|s a)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def companies_compatible(a: str, b: str) -> bool:
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    ta, tb = set(ka.split()), set(kb.split())
    return min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta)


def text_quality(s: str) -> float:
    """Para elegir la mejor versión de un texto: prefiere mayúsc/minúsc mezcladas, acentos y más completo."""
    s = clean_text(s)
    if not s:
        return -1
    q = 0.0
    if not (s.isupper() or s.islower()):
        q += 2
    if any(ord(c) > 127 for c in s):
        q += 1
    return q + min(len(s), 100) / 100


# ---------- Teléfono ----------
def normalize_phone(raw: str) -> tuple[str, str]:
    """Devuelve (+52XXXXXXXXXX, 'ok') o ('', 'vacio'|'invalido')."""
    raw = clean_text(raw)
    if not raw:
        return "", "vacio"
    raw = re.split(r"\b(?:ext|extension|x)\b\.?|#", raw, flags=re.I)[0]   # quita extensiones
    d = re.sub(r"\D", "", raw)
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 12 and d.startswith("52"):
        d = d[2:]
    elif len(d) == 13 and d.startswith("521"):
        d = d[3:]
    elif len(d) == 13 and d[:3] in ("044", "045"):
        d = d[3:]
    if len(d) != 10 or d[0] in "01" or len(set(d)) == 1:
        return "", "invalido"
    return "+52" + d, "ok"


# ---------- Correo ----------
def normalize_email(raw: str) -> tuple[str, str]:
    e = clean_text(raw).lower().removeprefix("mailto:").strip(" <>;,")
    if not e:
        return "", "vacio"
    if ".." in e or not _EMAIL_RE.match(e):
        return "", "invalido"
    return e, "ok"


# ---------- Segmento ----------
def normalize_segment(raw: str) -> str:
    f = fold(raw)
    if not f:
        return ""
    for canonico, alias in config.SEGMENTOS_ALIAS.items():
        if any(a in f for a in alias):
            return canonico
    return f   # no reconocido (p. ej. hoteleria): se conserva para que se vea


def infer_segment(empresa: str) -> str:
    f = fold(empresa)
    for seg, pistas in config.SEGMENTO_PISTAS_EMPRESA.items():
        if any(p in f for p in pistas):
            return seg
    return ""


# ---------- Empleados ----------
def parse_employees(raw: str) -> int | None:
    s = clean_text(raw).replace(",", "")
    m = re.fullmatch(r"(\d{1,7})(?:\s*(?:-|a)\s*\d{1,7})?(?:\s*(?:empleados|personas))?", fold(s))
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n < 1_000_000 else None


def employees_from_message(msg: str) -> int | None:
    f = fold(msg)
    for pat in config.PAT_EMPLEADOS_MSG:
        m = re.search(pat, f)
        if m:
            return int(m.group(1))
    return None


# ---------- Un renglón completo ----------
def normalize_row(raw: dict, fallback_id: str) -> Lead:
    notas: list[str] = []
    id_ = get_field(raw, "id") or fallback_id
    nombre = title_name(get_field(raw, "nombre"))
    empresa = normalize_company(get_field(raw, "empresa"))

    email_raw = get_field(raw, "email")
    email, email_status = normalize_email(email_raw)
    if email_status == "invalido":
        notas.append(f"correo inválido descartado: '{email_raw}'")

    tel_raw = get_field(raw, "telefono")
    tel, tel_status = normalize_phone(tel_raw)
    if tel_status == "invalido":
        notas.append(f"teléfono inválido descartado: '{tel_raw}'")
    elif tel and re.sub(r"\D", "", tel_raw) != tel[1:]:
        notas.append(f"teléfono normalizado desde '{tel_raw}'")

    seg_raw = get_field(raw, "segmento")
    segmento, inferido = normalize_segment(seg_raw), False
    if not segmento:
        segmento = infer_segment(empresa)
        inferido = bool(segmento)
        if inferido:
            notas.append(f"segmento vacío; inferido por el nombre de la empresa: {segmento}")
    elif segmento != fold(seg_raw):
        notas.append(f"segmento normalizado: '{seg_raw}' → {segmento}")

    emp_raw = get_field(raw, "num_empleados")
    emp = parse_employees(emp_raw)
    emp_msg = employees_from_message(get_field(raw, "mensaje"))
    fuente_emp = "declarado" if emp is not None else ""
    if emp is None:
        if emp_raw:
            notas.append(f"número de empleados no válido: '{emp_raw}'")
        if emp_msg is not None:
            emp, fuente_emp = emp_msg, "mensaje"
            notas.append(f"empleados estimados desde el mensaje: {emp_msg}")

    return Lead(
        id=str(id_), fecha=get_field(raw, "fecha"), nombre=nombre, empresa=empresa,
        email=email, email_status=email_status, telefono=tel, telefono_status=tel_status,
        segmento=segmento, segmento_inferido=inferido, num_empleados=emp,
        empleados_fuente=fuente_emp, empleados_mensaje=emp_msg,
        ciudad=title_name(get_field(raw, "ciudad")), fuente=get_field(raw, "fuente").lower(),
        mensaje=get_field(raw, "mensaje"), notas_limpieza=notas, raw=dict(raw),
    )

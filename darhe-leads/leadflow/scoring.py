"""Calificación A / B / C / Descartado con razón de una línea y marcas de revisión humana.

Orden de decisión (la primera que aplica gana):
  1. Spam                -> Descartado
  2. Competidor          -> Descartado (siempre con revisión: es un juicio)
  3. Sin contacto válido -> Descartado
  4. Fuera de segmento   -> C
  5. < 20 empleados      -> C   (salvo contradicción con el mensaje -> B + revisión)
  6. Empleados desconocidos -> B
  7. >= 20 empleados     -> A si hay necesidad concreta, si no B
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config
from .models import Lead
from .normalize import fold

ETIQUETA_SEGMENTO = {"construccion": "construcción", "hoteleria": "hotelería"}


@dataclass
class Evaluacion:
    calificacion: str
    razon: str
    siguiente_accion: str
    revision: list[str] = field(default_factory=list)
    puntaje: float = 0.0


@dataclass
class Senales:
    cotiza: bool
    demo: bool
    problema: bool
    precio: bool
    urgente: bool
    canal: bool
    ingles: bool
    spam_puntos: int
    spam_motivos: list[str]

    @property
    def necesidad_concreta(self) -> bool:
        return self.cotiza or self.demo or self.problema

    @property
    def necesidad_texto(self) -> str:
        partes = []
        if self.cotiza:
            partes.append("pide cotización")
        if self.demo:
            partes.append("pide demo")
        if self.problema:
            partes.append("describe un problema")
        return ", ".join(partes[:-1]) + (" y " if len(partes) > 1 else "") + partes[-1] if partes else ""


def detectar_senales(lead: Lead) -> Senales:
    msg = fold(lead.mensaje)
    email_crudo = fold(str(lead.raw.get("email", "")))
    pesos = {"mensaje con texto de spam": 2, "correo de dominio spam": 2, "enlace en el mensaje": 1}
    spam_motivos = []
    if any(re.search(p, msg) for p in config.SPAM_PALABRAS):
        spam_motivos.append("mensaje con texto de spam")
    if any(d in f"{lead.email} {email_crudo}" for d in config.SPAM_DOMINIOS):
        spam_motivos.append("correo de dominio spam")
    if re.search(config.PAT_URL, msg):
        spam_motivos.append("enlace en el mensaje")
    puntos = sum(pesos[m] for m in spam_motivos)
    return Senales(
        cotiza=bool(re.search(config.PAT_COTIZACION, msg)), demo=bool(re.search(config.PAT_DEMO, msg)),
        problema=bool(re.search(config.PAT_PROBLEMA, msg)), precio=bool(re.search(config.PAT_PRECIO, msg)),
        urgente=bool(re.search(config.PAT_URGENCIA, msg)), canal=bool(re.search(config.PAT_CANAL, msg)),
        ingles=len(re.findall(config.PAT_INGLES, msg)) >= 2,
        spam_puntos=puntos, spam_motivos=spam_motivos,
    )


def es_competidor(lead: Lead) -> bool:
    texto = fold(f"{lead.empresa} {lead.nombre} {lead.email} {lead.raw.get('email', '')}")
    return any(c in texto for c in config.COMPETIDORES)


def _canal_preferido(lead: Lead) -> str:
    if lead.telefono_status == "ok" and "whatsapp" in lead.fuente:
        return f"llamar o escribir por WhatsApp al {lead.telefono}"
    if lead.telefono_status == "ok":
        return f"llamar al {lead.telefono}"
    return f"escribir a {lead.email}"


def _puntaje(lead: Lead, base: float, s: Senales) -> float:
    p = base
    if lead.num_empleados:
        p += min(lead.num_empleados, 500) / 500 * 30
    p += 25 if s.necesidad_concreta else (8 if (s.precio or "llam" in fold(lead.mensaje)) else 0)
    p += 15 if s.urgente else 0
    p += 10 if "referido" in lead.fuente else 0
    p += 10 if lead.n_contactos > 1 else 0
    p -= 10 if lead.empleados_fuente == "mensaje" else 0
    return round(p, 1)


def evaluate(lead: Lead) -> Evaluacion:
    s = detectar_senales(lead)
    rev: list[str] = list(lead.avisos_revision)
    seg = lead.segmento
    seg_txt = ETIQUETA_SEGMENTO.get(seg, seg or "sin segmento")
    emp = lead.num_empleados
    objetivo = seg in config.SEGMENTOS_OBJETIVO

    # 1. Spam
    if s.spam_puntos >= config.SPAM_UMBRAL:
        return Evaluacion("Descartado", "Spam: " + "; ".join(s.spam_motivos) + ".", "No contactar.", [], 0)
    if s.spam_puntos == 1:
        rev.append("señal débil de spam (" + "; ".join(s.spam_motivos) + ")")

    # 2. Competidor
    if es_competidor(lead):
        return Evaluacion(
            "Descartado", "Parece competidor (el nombre de la empresa/correo lo indica) y pide precios y comisiones.",
            "No contactar hasta que Christian confirme que no es un prospecto real.",
            rev + [f"¿es de verdad competidor? declara {emp} empleados; si fuera prospecto real sería un lead grande"
                   if (emp or 0) >= config.MIN_EMPLEADOS else "confirmar que es competidor antes de descartar"], 0)

    # 3. Sin forma de contacto
    if not lead.tiene_contacto:
        if objetivo or s.necesidad_concreta:
            rev.append("tiene interés/segmento válido pero ningún dato de contacto utilizable: intentar rescatarlo por otro canal")
        return Evaluacion("Descartado", "Sin forma de contactarlo: correo y teléfono vacíos o inválidos.",
                          "No contactar; intentar recuperar el dato solo si Christian lo decide.", rev, 0)

    if lead.segmento_inferido:
        rev.append(f"segmento vacío; se infirió '{seg_txt}' por el nombre de la empresa")
    ctx_ingles = " Responder en inglés." if s.ingles else ""
    contacto = _canal_preferido(lead)
    empleados_txt = (f"~{emp} empleados (estimado del mensaje)" if lead.empleados_fuente == "mensaje"
                     else f"{emp} empleados") if emp is not None else "empleados sin dato"

    # 4. Fuera de segmento
    if not objetivo:
        if (emp or 0) >= config.MIN_EMPLEADOS and s.necesidad_concreta:
            rev.append(f"{seg_txt} no es segmento objetivo, pero tiene {emp} empleados y un problema concreto: ¿se hace excepción?")
        return Evaluacion("C", f"Fuera de segmento ({seg_txt}); {empleados_txt}.",
                          "Enviar información por correo; no priorizar llamada." + ctx_ingles,
                          rev, _puntaje(lead, 100, s))

    # 5. Menos de 20 empleados
    if emp is not None and emp < config.MIN_EMPLEADOS:
        if lead.empleados_mensaje is not None and lead.empleados_mensaje >= config.MIN_EMPLEADOS:
            rev.append(f"declara {emp} empleados pero el mensaje habla de {lead.empleados_mensaje} trabajadores (¿eventuales?); "
                       "por reglas sería C, se dejó en B")
            return Evaluacion(
                "B", f"{seg_txt.capitalize()} con {emp} empleados fijos pero {lead.empleados_mensaje} eventuales/trabajadores según el mensaje"
                     + (" y urgencia" if s.urgente else "") + "; dato contradictorio.",
                f"Christian valida y {contacto} para confirmar cuántas personas pagaría con el servicio.", rev, _puntaje(lead, 200, s))
        if s.canal:
            rev.append("busca opciones «para mis clientes»: posible revendedor o canal, no cliente final")
        return Evaluacion("C", f"Solo {emp} empleados (mínimo {config.MIN_EMPLEADOS}); {seg_txt}.",
                          "Enviar información por correo; no priorizar llamada." + ctx_ingles, rev, _puntaje(lead, 100, s))

    # 6. Empleados desconocidos
    if emp is None:
        rev.append("falta el número de empleados y no se pudo estimar")
        return Evaluacion("B", f"{seg_txt.capitalize()} con contacto válido pero sin dato de empleados.",
                          f"Christian valida y {contacto} para preguntar el tamaño.", rev, _puntaje(lead, 200, s))

    # 7. >= 20 empleados
    if lead.empleados_fuente == "mensaje":
        rev.append(f"el campo de empleados venía inválido; se usó ~{emp} que menciona el mensaje")
    if s.necesidad_concreta:
        razon = f"{seg_txt.capitalize()}, {empleados_txt}; {s.necesidad_texto}; contacto válido."
        if lead.n_contactos > 1:
            razon += f" Escribió {lead.n_contactos} veces ({lead.fuente})."
        return Evaluacion("A", razon, f"Christian valida y {contacto} primero." + ctx_ingles,
                          rev, _puntaje(lead, 300, s))

    # B: segmento y tamaño bien, necesidad vaga
    if s.precio:
        rev.append("solo pregunta el precio, sin describir necesidad; si se cuenta como cotización sería A")
    if emp >= config.EMPLEADOS_ALTO_POTENCIAL or "referido" in lead.fuente:
        rev.append(f"{emp} empleados"
                   + (" y llegó por referido" if "referido" in lead.fuente else "")
                   + " pero sin necesidad explícita (las reglas no lo cubren): ¿se trata como A?")
    vago = "necesidad vaga" if (lead.mensaje and not s.necesidad_concreta) else "sin mensaje"
    return Evaluacion("B", f"{seg_txt.capitalize()}, {empleados_txt}, contacto válido, pero {vago}.",
                      f"Christian valida y {contacto} para descubrir la necesidad." + ctx_ingles,
                      rev, _puntaje(lead, 200, s))

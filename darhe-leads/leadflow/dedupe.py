"""Detección y fusión de duplicados.

Dos leads son el mismo si comparten: (a) teléfono válido, (b) correo válido, o
(c) mismo nombre (sin acentos/mayúsculas) y empresa compatible. Un nombre solo NO basta
(hay muchos 'Juan Pérez'). Coincidir solo por teléfono/correo con nombre distinto sí fusiona,
pero se marca para revisión humana (podría ser una línea compartida)."""
from __future__ import annotations

from dataclasses import replace

from .models import Lead
from .normalize import companies_compatible, fold, text_quality


class _UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)   # la raíz es siempre el índice menor


def find_groups(leads: list[Lead]) -> list[list[Lead]]:
    """Agrupa leads duplicados. Mantiene el orden original; cada grupo conserva ese orden."""
    uf = _UnionFind(len(leads))
    por_clave: dict[tuple, list[int]] = {}
    motivos: list[tuple[int, int, str]] = []
    avisos: dict[int, list[str]] = {}

    def registrar(clave: tuple, i: int, motivo: str) -> None:
        for j in por_clave.get(clave, []):
            uf.union(i, j)
            motivos.append((j, i, motivo))
        por_clave.setdefault(clave, []).append(i)

    for i, l in enumerate(leads):
        if l.telefono_status == "ok":
            registrar(("tel", l.telefono), i, "teléfono")
        if l.email_status == "ok":
            registrar(("mail", l.email), i, "correo")
        if fold(l.nombre):
            # el bloqueo es por nombre; la empresa se verifica contra cada candidato
            for j in por_clave.get(("nom", fold(l.nombre)), []):
                if companies_compatible(l.empresa, leads[j].empresa):
                    uf.union(i, j)
                    motivos.append((j, i, "nombre+empresa"))
            por_clave.setdefault(("nom", fold(l.nombre)), []).append(i)

    for j, i, motivo in motivos:
        if motivo in ("teléfono", "correo") and fold(leads[i].nombre) != fold(leads[j].nombre):
            avisos.setdefault(uf.find(i), []).append(
                f"se fusionó por {motivo} compartido pero los nombres difieren "
                f"('{leads[j].nombre}' vs '{leads[i].nombre}'): confirmar que es la misma persona")

    grupos: dict[int, list[Lead]] = {}
    for i, l in enumerate(leads):
        grupos.setdefault(uf.find(i), []).append(l)
    resultado = []
    for raiz, g in grupos.items():
        g[0].avisos_revision.extend(a for a in dict.fromkeys(avisos.get(raiz, [])))  # sin repetir
        resultado.append(g)
    return resultado


def _primero(valores):
    return next((v for v in valores if v), "")


def merge_group(group: list[Lead]) -> Lead:
    """Une un grupo en un solo lead quedándose con el mejor dato de cada campo."""
    if len(group) == 1:
        g = group[0]
        g.ids_fusionados = [g.id]
        return g
    g = sorted(group, key=lambda l: (l.fecha or "9999", ))   # estable: respeta el orden original en empates
    p = g[0]
    m = replace(p)   # copia del principal
    m.ids_fusionados = [l.id for l in g]
    m.n_contactos = len(g)
    m.nombre = max((l.nombre for l in g), key=text_quality)
    m.empresa = max((l.empresa for l in g), key=text_quality)
    m.ciudad = max((l.ciudad for l in g), key=text_quality)

    correos = list(dict.fromkeys(l.email for l in g if l.email_status == "ok"))
    m.email, m.email_status = (correos[0], "ok") if correos else ("", "vacio" if all(l.email_status == "vacio" for l in g) else "invalido")
    m.email_alterno = "; ".join(correos[1:])
    telefonos = list(dict.fromkeys(l.telefono for l in g if l.telefono_status == "ok"))
    m.telefono, m.telefono_status = (telefonos[0], "ok") if telefonos else ("", "vacio" if all(l.telefono_status == "vacio" for l in g) else "invalido")

    # segmento: preferir uno reconocido y NO inferido
    segs = sorted((l for l in g if l.segmento), key=lambda l: (l.segmento_inferido,))
    m.segmento = segs[0].segmento if segs else ""
    m.segmento_inferido = segs[0].segmento_inferido if segs else False

    # empleados: preferir cifras declaradas; si difieren, la más reciente + aviso
    declarados = [l for l in g if l.empleados_fuente == "declarado"]
    avisos = []
    if declarados:
        valores = {l.num_empleados for l in declarados}
        elegido = declarados[-1]
        m.num_empleados, m.empleados_fuente = elegido.num_empleados, "declarado"
        if len(valores) > 1:
            avisos.append(f"cifras de empleados distintas entre contactos {sorted(valores)}; se usó la más reciente ({elegido.num_empleados})")
    else:
        est = next((l for l in g if l.num_empleados is not None), None)
        m.num_empleados = est.num_empleados if est else None
        m.empleados_fuente = est.empleados_fuente if est else ""
    m.empleados_mensaje = next((l.empleados_mensaje for l in g if l.empleados_mensaje is not None), None)

    m.fuente = " + ".join(dict.fromkeys(l.fuente for l in g if l.fuente))
    mensajes = list(dict.fromkeys((l.id, l.mensaje) for l in g if l.mensaje))
    m.mensaje = " | ".join(f"[#{i}] {t}" for i, t in mensajes)
    m.fecha = p.fecha
    m.notas_limpieza = [f"[#{l.id}] {n}" for l in g for n in l.notas_limpieza]
    m.notas_limpieza.append(f"fusión de leads {', '.join(m.ids_fusionados)} (mismo contacto)")
    m.avisos_revision = list(dict.fromkeys(a for l in g for a in l.avisos_revision)) + avisos
    return m

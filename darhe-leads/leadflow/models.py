from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Lead:
    id: str
    fecha: str = ""
    nombre: str = ""
    empresa: str = ""
    email: str = ""
    email_status: str = "vacio"        # ok | vacio | invalido
    email_alterno: str = ""
    telefono: str = ""
    telefono_status: str = "vacio"     # ok | vacio | invalido
    segmento: str = ""                 # canónico, o el texto original (sin acentos) si no se reconoce
    segmento_inferido: bool = False
    num_empleados: int | None = None
    empleados_fuente: str = ""         # declarado | mensaje | ""
    empleados_mensaje: int | None = None   # cifra leída del mensaje (se use o no)
    ciudad: str = ""
    fuente: str = ""
    mensaje: str = ""
    n_contactos: int = 1
    ids_fusionados: list[str] = field(default_factory=list)
    notas_limpieza: list[str] = field(default_factory=list)
    avisos_revision: list[str] = field(default_factory=list)   # avisos que vienen de limpieza/dedup
    raw: dict = field(default_factory=dict)

    @property
    def tiene_contacto(self) -> bool:
        return self.email_status == "ok" or self.telefono_status == "ok"

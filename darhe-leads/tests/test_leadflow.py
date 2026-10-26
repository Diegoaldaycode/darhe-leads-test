import csv
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from leadflow import normalize as N                      # noqa: E402
from leadflow.pipeline import procesar, leer_filas, escribir_csv, COLUMNAS_SALIDA, main  # noqa: E402

DATOS = RAIZ / "data" / "leads_test_darhe.csv"


def por_id(res):
    return {f["id"]: f for f in res.filas}


class TestNormalizacion(unittest.TestCase):
    def test_telefonos(self):
        casos = {
            "55 1234 5678": "+525512345678", "(55)23456789": "+525523456789",
            "+52 55 1234 5678": "+525512345678", "+52 1 55 1234 5678": "+525512345678",
            "044 55 1234 5678": "+525512345678", "55 1234 5678 ext 12": "+525512345678",
        }
        for crudo, esperado in casos.items():
            self.assertEqual(N.normalize_phone(crudo), (esperado, "ok"), crudo)
        for malo in ["0000000000", "123", "+1 305 555 1234", "abc", "1234567890"]:
            self.assertEqual(N.normalize_phone(malo)[1], "invalido", malo)
        self.assertEqual(N.normalize_phone("")[1], "vacio")
        # solo dos dígitos distintos NO basta para rechazar: es un número válido poco común
        self.assertEqual(N.normalize_phone("55 4444 5555"), ("+525544445555", "ok"))

    def test_correos(self):
        self.assertEqual(N.normalize_email(" ANA@Pilar.COM "), ("ana@pilar.com", "ok"))
        for malo in ["ana.torres@pilar", "sin_arroba", "a..b@x.com", "a@b"]:
            self.assertEqual(N.normalize_email(malo)[1], "invalido", malo)

    def test_segmentos(self):
        for crudo, esperado in [("Restaurant", "restaurantero"), ("construcción", "construccion"),
                                ("TRANSPORTISTA", "transportista"), ("empresario", "empresario"),
                                ("hotelería", "hoteleria"), ("", "")]:
            self.assertEqual(N.normalize_segment(crudo), esperado)

    def test_nombres_y_empresas(self):
        self.assertEqual(N.title_name("LAURA MENDEZ"), "Laura Mendez")
        self.assertEqual(N.title_name("juan de la cruz"), "Juan de la Cruz")
        self.assertEqual(N.title_name("McDonald Pérez"), "McDonald Pérez")      # ya mezclado: se respeta
        self.assertEqual(N.normalize_company("LOGÍSTICA RÍOS S.A. DE C.V."), "Logística Ríos SA de CV")

    def test_empleados(self):
        self.assertEqual(N.parse_employees("1,200"), 1200)
        self.assertIsNone(N.parse_employees("abc"))
        self.assertIsNone(N.parse_employees("0"))
        self.assertEqual(N.employees_from_message("Somos como 60, necesitamos"), 60)
        self.assertIsNone(N.employees_from_message("Tenemos 6 sucursales"))


class TestMuestra(unittest.TestCase):
    """Resultados esperados sobre los 15 leads del test (decisiones documentadas en el README)."""

    @classmethod
    def setUpClass(cls):
        cls.res = procesar(leer_filas(DATOS))
        cls.f = por_id(cls.res)

    def test_calificaciones(self):
        esperado = {"1": "A", "2": "C", "3": "A", "4": "A", "5": "Descartado", "6": "B", "7": "C", "8": "B",
                    "9": "B", "10": "B", "11": "Descartado", "12": "A", "13": "B", "14": "A", "15": "C"}
        self.assertEqual({i: f["calificacion"] for i, f in self.f.items()}, esperado)

    def test_duplicados(self):
        self.assertEqual(self.f["3"]["duplicado_de"], "1")
        self.assertEqual(self.f["14"]["duplicado_de"], "4")
        self.assertEqual(sum(1 for f in self.f.values() if f["duplicado_de"]), 2)
        self.assertEqual(len(self.res.principales), 13)

    def test_fusion_conserva_mejor_dato(self):
        l1, l4 = self.f["1"], self.f["4"]
        self.assertEqual(l1["nombre"], "Laura Méndez")                       # con acento, no la versión en MAYÚSCULAS
        self.assertEqual(l1["empresa"], "Transportes del Bajío SA de CV")    # versión más completa
        self.assertEqual(l1["email_alterno"], "lmendez@transbajio.example")
        self.assertEqual(l4["email"], "ana.torres@pilar.example")            # el válido, no "ana.torres@pilar"
        self.assertEqual(l4["num_empleados"], 45)                            # el lead 4 no traía el dato
        self.assertEqual(l4["ids_fusionados"], "4,14")

    def test_datos_limpios(self):
        for f in self.f.values():
            if f["telefono"]:
                self.assertRegex(f["telefono"], r"^\+52\d{10}$")
            if f["email"]:
                self.assertIn("@", f["email"])
        self.assertEqual(self.f["5"]["telefono"], "")        # 0000000000 no es teléfono
        self.assertEqual(self.f["10"]["segmento"], "restaurantero")

    def test_revision_humana(self):
        con_revision = {i for i, f in self.f.items() if f["requiere_revision"] == "sí"}
        self.assertEqual(con_revision, {"6", "7", "9", "11", "12", "13", "15"})
        for i in con_revision:
            self.assertTrue(self.f[i]["motivo_revision"], f"lead {i} marcado sin motivo")

    def test_todo_tiene_razon_y_accion(self):
        for f in self.f.values():
            self.assertTrue(f["razon"] and f["siguiente_accion"])

    def test_prioridad_a_primero(self):
        prios = {i: f["prioridad"] for i, f in self.f.items() if f["prioridad"] != ""}
        self.assertEqual([i for i, _ in sorted(prios.items(), key=lambda x: x[1])][:3], ["1", "4", "12"])
        self.assertNotIn("5", prios)   # descartados fuera de la cola

    def test_resumen_cabe_en_una_pagina(self):
        from leadflow.summary import generar_resumen
        texto = generar_resumen(self.res, 15)
        self.assertLess(len(texto.split()), 450)
        self.assertLess(len(texto.splitlines()), 50)

    def test_idempotente(self):
        otra = procesar(leer_filas(DATOS))
        self.assertEqual(self.res.filas, otra.filas)


def fila(**kw):
    base = {"id": "1", "fecha": "2026-10-01", "nombre": "Test Uno", "empresa": "Acme", "email": "t@acme.example",
            "telefono": "55 1234 5678", "segmento": "transportista", "num_empleados": "50",
            "ciudad": "CDMX", "fuente": "web", "mensaje": "Quiero una cotización"}
    base.update(kw)
    return base


class TestLeadsRotos(unittest.TestCase):
    def test_renglon_vacio_no_tumba_el_lote(self):
        res = procesar([fila(), {k: "" for k in fila()}, fila(id="2", nombre="Otro", email="o@x.example", telefono="55 9999 1111")])
        self.assertEqual(len(res.filas), 2)
        self.assertEqual(len(res.errores), 1)

    def test_columnas_faltantes_y_valores_none(self):
        res = procesar([{"id": "7", "nombre": "Solo Nombre"}, {"id": "8", "nombre": None, "telefono": None}])
        self.assertEqual({f["calificacion"] for f in res.filas}, {"Descartado"})   # sin contacto

    def test_sin_forma_de_contacto_es_descartado(self):
        res = procesar([fila(email="malo@", telefono="000")])
        self.assertEqual(res.filas[0]["calificacion"], "Descartado")
        self.assertIn("contactar", res.filas[0]["razon"])

    def test_ids_repetidos_o_vacios(self):
        res = procesar([fila(id="1"), fila(id="1", nombre="Distinto", email="d@x.example", telefono="55 2222 3333"), fila(id="")])
        self.assertEqual(len({f["id"] for f in res.filas}), len(res.filas))

    def test_excepcion_en_un_renglon_se_aisla(self):
        original = N.normalize_row

        def falla(raw, fallback_id):
            if raw.get("id") == "2":
                raise RuntimeError("boom")
            return original(raw, fallback_id)

        with mock.patch("leadflow.pipeline.normalize_row", falla):
            res = procesar([fila(), fila(id="2", telefono="55 3333 4444", email="z@x.example", nombre="Zeta")])
        self.assertEqual(len(res.filas), 1)
        self.assertEqual(len(res.errores), 1)
        self.assertIn("boom", res.errores[0]["error"])

    def test_texto_enorme_se_recorta(self):
        res = procesar([fila(mensaje="x" * 100_000)])
        self.assertLessEqual(len(res.filas[0]["mensaje"]), 2000)

    def test_inyeccion_de_formulas_en_csv(self):
        res = procesar([fila(nombre="=HYPERLINK(\"http://malo\")")])
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "o.csv"
            escribir_csv(res.filas, ruta, COLUMNAS_SALIDA)
            with open(ruta, encoding="utf-8-sig") as fh:
                leido = list(csv.DictReader(fh))
        self.assertTrue(leido[0]["nombre"].startswith("'="))

    def test_mismo_telefono_distinto_nombre_se_fusiona_pero_se_revisa(self):
        res = procesar([fila(), fila(id="2", nombre="Persona Distinta", email="otra@acme.example")])
        self.assertEqual(len(res.principales), 1)
        self.assertEqual(res.filas[0]["requiere_revision"], "sí")

    def test_mismo_nombre_distinta_empresa_no_se_fusiona(self):
        res = procesar([fila(), fila(id="2", empresa="Otra Compañía Distinta", email="o@otra.example", telefono="55 8888 7777")])
        self.assertEqual(len(res.principales), 2)


class TestArchivos(unittest.TestCase):
    def escribir(self, d, contenido: bytes, nombre="in.csv"):
        ruta = Path(d) / nombre
        ruta.write_bytes(contenido)
        return ruta

    def test_archivo_vacio_y_inexistente_salen_con_error_limpio(self):
        with tempfile.TemporaryDirectory() as d:
            vacio = self.escribir(d, b"")
            self.assertEqual(main([str(vacio), "--salida", d]), 2)
            self.assertEqual(main([str(Path(d) / "no_existe.csv"), "--salida", d]), 2)

    def test_latin1_y_punto_y_coma(self):
        texto = "id;nombre;telefono;email;segmento;num_empleados\n1;José Pérez;55 1234 5678;j@x.example;transportista;30\n"
        with tempfile.TemporaryDirectory() as d:
            ruta = self.escribir(d, texto.encode("cp1252"))
            filas = leer_filas(ruta)
        self.assertEqual(filas[0]["nombre"], "José Pérez")
        self.assertEqual(procesar(filas).filas[0]["telefono"], "+525512345678")

    def test_cli_de_punta_a_punta(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-m", "leadflow", str(DATOS), "--salida", d, "--json"],
                               cwd=RAIZ, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            for nombre in ("leads_calificados.csv", "leads_calificados.json", "RESUMEN_CHRISTIAN.md"):
                self.assertTrue((Path(d) / nombre).exists(), nombre)


if __name__ == "__main__":
    unittest.main()

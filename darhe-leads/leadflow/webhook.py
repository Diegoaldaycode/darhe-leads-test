"""Receptor de leads por webhook (opcional). Solo librería estándar.

    WEBHOOK_TOKEN=secreto python -m leadflow.webhook --puerto 8080
    curl -X POST localhost:8080/leads -H "Authorization: Bearer secreto" \
         -H "Content-Type: application/json" -d '{"nombre":"Ana","telefono":"55 1111 2222", ...}'

Cada lead nuevo se agrega a un almacén local (data/webhook_store.jsonl) y se vuelve a correr el flujo
completo sobre todo el almacén, así la detección de duplicados considera los leads anteriores.
En producción ese almacén sería la tabla de Supabase (ver sql/schema.sql)."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import procesar

MAX_BYTES = 20_000
_lock = threading.Lock()


def _cargar(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    out = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(linea))
        except json.JSONDecodeError:
            continue          # una línea corrupta del almacén no debe tumbar el servicio
    return out


def recibir_lead(payload: dict, almacen: Path) -> dict:
    with _lock:
        previos = _cargar(almacen)
        payload = {str(k): v for k, v in payload.items()}
        payload["id"] = str(payload.get("id") or f"w{len(previos) + 1}")
        todos = previos + [payload]
        res = procesar(todos)
        fila = next((f for f in res.filas if f["id"] == payload["id"]), None)
        if fila is None:
            return {"estado": "rechazado", "errores": [e["error"] for e in res.errores][-1:]}
        almacen.parent.mkdir(parents=True, exist_ok=True)
        with open(almacen, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return {"estado": "recibido", "lead": fila}


def crear_handler(almacen: Path, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _responder(self, codigo: int, cuerpo: dict):
            datos = json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_POST(self):
            if self.path != "/leads":
                return self._responder(404, {"error": "usa POST /leads"})
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                return self._responder(401, {"error": "token inválido"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_BYTES:
                return self._responder(413, {"error": f"cuerpo vacío o mayor a {MAX_BYTES} bytes"})
            try:
                payload = json.loads(self.rfile.read(n))
                if not isinstance(payload, dict):
                    raise ValueError
            except ValueError:
                return self._responder(400, {"error": "se esperaba un objeto JSON"})
            self._responder(200, recibir_lead(payload, almacen))

        def log_message(self, *a):   # sin ruido en consola
            pass

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--almacen", default="data/webhook_store.jsonl")
    args = ap.parse_args()
    token = os.environ.get("WEBHOOK_TOKEN", "")
    if not token:
        print("AVISO: WEBHOOK_TOKEN vacío; el endpoint queda abierto (solo para pruebas locales).")
    print(f"Escuchando en http://127.0.0.1:{args.puerto}/leads")
    ThreadingHTTPServer(("127.0.0.1", args.puerto), crear_handler(Path(args.almacen), token)).serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3  
# -*- coding: utf-8 -*-  
"""  
Mini-CMS con Flask  
– content_id es la ruta + extensión del fichero (relativa a esta carpeta)  
– El nombre “sugerido” para el JSON local es: <id>_<basename(content_id)>.json  
–  NUEVO: recarga automática del JSONL si éste ha cambiado.  
"""  
  
import json  
import pathlib  
import threading  
from typing import Dict, List, Optional  
  
from flask import Flask, jsonify, abort, send_file, Response  
  
# ------------------------------------------------------------------- #  
# Configuración  
# ------------------------------------------------------------------- #  
BASE_DIR   = pathlib.Path(__file__).resolve().parent  
JSONL_FILE = BASE_DIR / "cms_content/documents.jsonl"  
  
# ------------------------------------------------------------------- #  
#  Soporte “cache con autorefresco”  
# ------------------------------------------------------------------- #  
_docs_lock      = threading.Lock()  
_docs_cache:    List[Dict] = []  
_docs_mtime:    float      = 0.0  
  
  
def _load_metadata_from_disk() -> List[Dict]:
    print(f"\t >>> Cargando metadatos desde {JSONL_FILE}")
    with JSONL_FILE.open(encoding="utf-8") as fh:  
        return [json.loads(line) for line in fh if line.strip()]  
  
  
def _ensure_fresh_cache() -> List[Dict]:  
    """Recarga el JSONL si su mtime ha cambiado."""  
    global _docs_cache, _docs_mtime  
    with _docs_lock:  
        current_mtime = JSONL_FILE.stat().st_mtime  
        if current_mtime != _docs_mtime:  
            _docs_cache = _load_metadata_from_disk()  
            _docs_mtime = current_mtime  
    return _docs_cache  
  
  
# ------------------------------------------------------------------- #  
# Utilidades varias  
# ------------------------------------------------------------------- #  
def _metadata_filename(doc: Dict) -> str:  
    base = pathlib.Path(doc["content_id"]).name.lstrip("./")  
    return f"{doc['id']}_{base}.json"  
  
  
def _decorate(doc: Dict) -> Dict:  
    """Añade el campo metadata_file a la respuesta."""  
    d = dict(doc)  
    d["metadata_file"] = _metadata_filename(doc)  
    return d  
  
  
def _find_doc(doc_id: int) -> Optional[Dict]:  
    return next((d for d in _ensure_fresh_cache() if d["id"] == doc_id), None)  
  
  
# ------------------------------------------------------------------- #  
# Flask  
# ------------------------------------------------------------------- #  
app = Flask(__name__)  
  
  
@app.route("/api/documents", methods=["GET"])  
def list_documents() -> Response:  
    return jsonify([_decorate(d) for d in _ensure_fresh_cache()])  
  
  
@app.route("/api/documents/<int:doc_id>", methods=["GET"])  
def get_document_metadata(doc_id: int) -> Response:  
    doc = _find_doc(doc_id)  
    if not doc:  
        abort(404, description="Documento no encontrado")  
    return jsonify(_decorate(doc))  
  
  
@app.route("/api/documents/<int:doc_id>/download", methods=["GET"])  
def download_document(doc_id: int):  
    doc = _find_doc(doc_id)  
    if not doc:  
        abort(404, description="Documento no encontrado")  
  
    rel_path = pathlib.Path(doc["content_id"])  
    if rel_path.is_absolute():  
        abort(400, description="content_id debe ser ruta relativa")  
  
    abs_path = (BASE_DIR / rel_path).resolve()  
    try:  
        abs_path.relative_to(BASE_DIR)          # evita path-traversal  
    except ValueError:  
        abort(403, description="Ruta fuera del directorio permitido")  
  
    if not abs_path.is_file():  
        abort(404, description="Archivo asociado no encontrado")  
  
    return send_file(abs_path, as_attachment=True)  
  
  
if __name__ == "__main__":  
    app.run(host="0.0.0.0", port=8000, debug=True)  
# sync_cms.py  
"""  
Sincronización incremental de documentos/archivos desde la API Flask.  
Guarda:  - metadatos   →  metadata/<id>_<basename(content_id)>.json  
         - documentos  →  files/<nombre_original.ext>  
"""  
from __future__ import annotations  
  
import json  
import re  
from datetime import datetime  
from pathlib import Path  
from typing import Dict, List, Optional  
  
import requests  
from common_sync import *
  
# ------------------------------------------------------------------- #  
# Local Metadata
# ------------------------------------------------------------------- #  
# Get the metadata filename based on document ID and content ID
def meta_fname(doc_id: int, content_id: str) -> str:  
    return f"{doc_id}_{Path(content_id).name.lstrip('./')}.json"  
  
# Get the path for the metadata file based on document ID and content ID
def meta_path(doc_id: int, content_id: str) -> Path:  
    return META_DIR / meta_fname(doc_id, content_id)  
  
# Load local metadata from a JSON file based on document ID and content ID
def load_local_meta(doc_id: int, content_id: str) -> Optional[Dict]:  
    p = meta_path(doc_id, content_id)  
    if p.exists():  
        with p.open(encoding="utf-8") as fh:  
            return json.load(fh)  
    return None  
  
# Save metadata to a JSON file based on document ID and content ID  
def save_meta(meta: Dict) -> Path:  
    META_DIR.mkdir(parents=True, exist_ok=True)  
    p = meta_path(meta["id"], meta["content_id"])  
    with p.open("w", encoding="utf-8") as fh:  
        json.dump(meta, fh, ensure_ascii=False, indent=2)  
    return p  
  
# --------------------------------------------------------------------------- #  
# Incremental Syncronization
# --------------------------------------------------------------------------- #  
def incremental_sync() -> None:  
    server_docs = list_documents()  
    print(f"Documents in CMS server: {len(server_docs)}")  
  
    to_update: List[Dict] = []  
  
    for doc in server_docs:  
        local = load_local_meta(doc["id"], doc["content_id"])  
        if local is None:  
            to_update.append(doc)  
            continue  
  
        if iso_to_dt(doc["update_date"]) > iso_to_dt(local["update_date"]):  
            to_update.append(doc)  
  
    print(f"Documents to update: {len(to_update)}\n")  
  
    for doc in to_update:  
        doc_id = doc["id"]  
        print(f"→ id={doc_id} ({doc['description']})")  
  
        meta = get_document_metadata(doc_id)  
        m_path = save_meta(meta)  
        print(f"   · Metadatos → {m_path}")  
  
        f_path = download_document(doc_id, FILE_DIR)  
        print(f"   · Archivo   → {f_path}")  
  
    print("\nSincronización completa.")  

# --------------------------------------------------------------------------- #  
# Main  
# --------------------------------------------------------------------------- #  
if __name__ == "__main__":  
    incremental_sync()  
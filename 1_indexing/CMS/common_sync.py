import requests
import re
import json
from datetime import datetime  
from pathlib import Path  
from typing import Dict, List, Optional  

# --------------------------------------------------------------------------- #  
# Configuración  
# --------------------------------------------------------------------------- #  
BASE_URL = "http://localhost:8000"         #  URL donde corre tu API Flask  
META_DIR = Path("metadata")                #  Carpeta para los .json  
FILE_DIR = Path("files")                   #  Carpeta para los documentos  
TIMEOUT = 15                               #  segundos para peticiones HTTP  
DATE_FMTS = (  
    "%Y-%m-%d",  
    "%Y-%m-%dT%H:%M:%S",  
    "%Y-%m-%dT%H:%M:%S.%f",  
) #  Formatos de fecha ISO esperados 

# --------------------------------------------------------------------------- #  
# API REST  (requests)  
# --------------------------------------------------------------------------- #  
def list_documents() -> List[Dict]:  
    r = requests.get(f"{BASE_URL}/api/documents", timeout=TIMEOUT)  
    r.raise_for_status()  
    return r.json()  
  
  
def get_document_metadata(doc_id: int) -> Dict:  
    r = requests.get(f"{BASE_URL}/api/documents/{doc_id}", timeout=TIMEOUT)  
    r.raise_for_status()  
    return r.json()  
  
  
def download_document(doc_id: int, dest: Path | str) -> Path:  
    dest = Path(dest)  
    dest.mkdir(parents=True, exist_ok=True)  
  
    r = requests.get(f"{BASE_URL}/api/documents/{doc_id}/download",  
                     stream=True, timeout=TIMEOUT)  
    r.raise_for_status()  
  
    # nombre de fichero  
    cd = r.headers.get("content-disposition", "")  
    m = re.search(r'filename="?([^"]+)"?', cd)  
    if m:  
        fname = m.group(1)  
    else:  
        fname = Path(get_document_metadata(doc_id)["content_id"]).name  
  
    out = dest / fname  
    with out.open("wb") as fh:  
        for chunk in r.iter_content(chunk_size=8192):  
            fh.write(chunk)  
    return out 

# --------------------------------------------------------------------------- #  
# Utilidades  
# --------------------------------------------------------------------------- #  
def iso_to_dt(text: str) -> datetime:  
    for fmt in DATE_FMTS:  
        try:  
            return datetime.strptime(text, fmt)  
        except ValueError:  
            pass  
    try:  
        # python 3.11+ gestiona Z, ±hh:mm, etc.  
        return datetime.fromisoformat(text.replace("Z", "+00:00"))  
    except Exception:  
        return datetime.min 

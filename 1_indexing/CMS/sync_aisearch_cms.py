# sync_cms.py  
"""  
Sincronización incremental de documentos/archivos desde la API Flask.  
Guarda:  - metadatos   →  metadata/<id>_<basename(content_id)>.json  
         - documentos  →  files/<nombre_original.ext>  
"""  
from __future__ import annotations  
  
import json
import os
import sys
from datetime import datetime  
from pathlib import Path  
from typing import Dict, List, Optional
import time

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from langchain.text_splitter import TokenTextSplitter

sys.path.append(os.path.abspath('../..'))
from common_utils import *
from common_sync import *

# Load Azure OpenAI and AI Search variables and create clients
openai_config, ai_search_config = load_config()
index_name = "cms_index"

 # Create an Azure AI Search client
aisearch_credential = AzureKeyCredential(ai_search_config["ai_search_apikey"])
ai_search_client = SearchClient(endpoint=ai_search_config["ai_search_endpoint"],
                                index_name=index_name,
                                credential=aisearch_credential)

# Load Document Intelligence configuration
doc_intel_endpoint = os.getenv("DOC_INTEL_ENDPOINT")
doc_intel_key = os.getenv("DOC_INTEL_KEY")
doc_intel_client = DocumentIntelligenceClient(endpoint=doc_intel_endpoint, credential=AzureKeyCredential(doc_intel_key))
print(f'doc_intel_endpoint: {doc_intel_endpoint}')

MAX_TOKENS = 512
OVERLAP_TOKENS = 128 # 25% of 512 tokens is 128 tokens

def search_by_doc_id(ai_search_client, openai_client, aoai_embedding_model, query, max_docs):
    SELECT_FIELDS=["doc_id", "title", "update_date"]

    results = ai_search_client.search(
        filter=query,
        select=SELECT_FIELDS,
        query_type=QueryType.SIMPLE,
        include_total_count=True,
        top=max_docs,
    )

    return list(results), results.get_count()

# Load metadata from AI Search by document ID  
def load_aisearch_meta(doc_id: int) -> Optional[Dict]:  

    query = f"doc_id eq '{doc_id}'"
    results, num_results = search_by_doc_id(ai_search_client,
                                            openai_config["openai_client"],
                                            openai_config["aoai_embedding_model"],
                                            query=query,
                                            max_docs=1)
    print(f"Resultados de búsqueda en AI Search: {num_results} documento(s) encontrado(s)")
    print(f"Resultados de búsqueda: {results}")
    if num_results == 0:
        return None
    else:
        return results  

# Convert one document to MARKDOWN
def convert_file_to_markdown(file_path):
    print(f'Converting {file_path} to markdown format...')
    try:
        # Read the file
        with open(file_path, "rb") as pdf_file:
            pdf_content = pdf_file.read()
        # Convert to markdown with Document Intelligence
        poller = doc_intel_client.begin_analyze_document("prebuilt-layout",
                                                        body=pdf_content,
                                                        output_content_format=DocumentContentFormat.MARKDOWN,
                                                        content_type="application/octet-stream")
        result = poller.result()
        markdown = result['content']

    except Exception as ex:
        markdown = None
        print(ex)

    return markdown

# Index the batch in Azure AI Search index
def index_lote(batch_client, lote, i):
    try:
        print(f'Indexing until document {i+1}...')
        batch_client.merge_or_upload_documents(documents=lote)
        print('Waiting 15 seconds...')
        time.sleep(15)
    except Exception as ex:
        print(ex)

# Index the contents or chunks
def index_documents(ai_search_endpoint, ai_search_credential, index_name, embedding_client, embedding_model_name, chunks):
    print(f'Indexing {len(chunks)} documents in {index_name} index...')
    # Create an index batch client
    batch_client = SearchIndexingBufferedSender(
                endpoint=ai_search_endpoint,
                index_name=index_name,
                credential=ai_search_credential
            )

    lote = []
    for i, chunk in enumerate(chunks):  # Index the chunks using the file name as title
        print('=================================================================')
        doc_id = chunk['doc_id']
        chunk_id = f"{chunk['doc_id']}_{i}"  # Create a unique chunk ID
        title = chunk['title']
        content = chunk['content']
        print(f"[{i + 1}] doc_id: {doc_id}, chunk_id: {chunk_id}: title: {title}")
        #print(f"\t[{content}]")
        document = {
            "doc_id": str(i),
            "chunk_id": str(i),
            "title": title,
            "content": content,
            "description": chunk['description'],
            "author": chunk['author'],
            "content_id": chunk['content_id'],
            "creation_date": chunk['creation_date'],
            "update_date": chunk['update_date'],
            # Create embeddings with ADA-2
            "embeddingTitle": embedding_client.embeddings.create(input=cut_max_tokens(title), model=embedding_model_name).data[0].embedding,
            "embeddingContent": embedding_client.embeddings.create(input=cut_max_tokens(content), model=embedding_model_name).data[0].embedding,
        }
        # Add the document to the batch
        lote.append(document)
        # Index every 10 documents in the batch
        if (i + 1) % 10 == 0:
            # Upload documents
            print(f'INDEXING BATCH {i + 1}')
            index_lote(batch_client, lote, i)
            lote = []

    # Index the rest of documents after the last batch
    if len(lote) > 0:
        index_lote(batch_client, lote, i)

def index_aisearch_doc(meta: Dict, f_path: Path | str) -> None:  
    """  
    Indexa un documento con sus metatados en Azure AI Search.  
    """  
    # Convert the document to markdown format
    markdown_content = convert_file_to_markdown(f_path)
    if markdown_content is None:
        print(f"Error converting {f_path} to markdown format. Skipping indexing.")
        return
    # Dividir el contenido en fragmentos de texto  
    text_splitter = TokenTextSplitter(chunk_size=MAX_TOKENS, chunk_overlap=OVERLAP_TOKENS)  
    texts = text_splitter.split_text(markdown_content)
  
    # Indexar en AI Search cada fragmento de texto de un fichero como documentos
    docs = []
    for i, text in enumerate(texts):
        row = {"doc_id": meta['id'],
               "chunk_id": f"{meta['id']}_{i}",  # Crear un ID único para cada fragmento                  
               "title": meta['content_id'],
               "content": text,
               "description": meta['description'],
               "author": meta['author'],
               "content_id": meta['content_id'],
               "creation_date": meta['creation_date'],
               "update_date": meta['update_date'],
        }
        docs.append(row)
  
    index_documents(ai_search_config["ai_search_endpoint"],
                    aisearch_credential,
                    index_name,
                    openai_config["openai_client"], 
                    openai_config["aoai_embedding_model"],
                    docs)

    print(f"Documento {meta['id']} indexado en AI Search con {len(texts)} fragmentos.")

# --------------------------------------------------------------------------- #  
# Sincronización incremental  
# --------------------------------------------------------------------------- #  
def incremental_sync() -> None:  
    server_docs = list_documents()
    print(f"Documentos en servidor: {len(server_docs)}")
    #print(f"{json.dumps(server_docs, indent=2)}")
  
    to_update: List[Dict] = []  
  
    for doc in server_docs:  
        print("--------------------------------------------------------")
        aisearch_doc = load_aisearch_meta(doc["id"])
        if aisearch_doc is None:  
            to_update.append(doc)  
            continue  
  
        print(f"AISearch update_date: {aisearch_doc[0]['update_date']}, CMS update_date: {doc['update_date']}")
        if iso_to_dt(doc["update_date"]) > iso_to_dt(aisearch_doc[0]["update_date"]):  
            to_update.append(doc)
        else:
            print(f"Documento {doc['id']} ya está actualizado en AI Search.")
  
    print(f"A crear/actualizar: {len(to_update)} documento(s)")  
  
    for doc in to_update:  
        doc_id = doc["id"]  
        print(f"→ id={doc_id} ({doc['description']})")  
  
        meta = get_document_metadata(doc_id)   
        print(f"   · Metadatos → {meta}")
  
        f_path = download_document(doc_id, FILE_DIR)  
        print(f"   · Archivo   → {f_path}")

        index_aisearch_doc(meta, f_path)  # Indexar el documento en AI Search
  
    print("\nSincronización completa.")  

# --------------------------------------------------------------------------- #  
# Main  
# --------------------------------------------------------------------------- #  
if __name__ == "__main__":  
    incremental_sync()  
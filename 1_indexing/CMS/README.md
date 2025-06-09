# RAG Workshop: Simulated CMS synchronization

The purpose of the CMS folder is to provide a sample of Azure AI Search index synchronization with the content stored in a Content Management System (CMS)

The metadata of the documents are stored in the file `documents.jsonl`. The cms application check changes and refresh its cache.

To run the simulated CMS run: `python cms.py` that uses Flask to expose it in the endpoint `http://localhost:8000`
The endpoint has the following methods:
- `api/documents`: list the documents stored in the CMS
- `api/documents/<doc_id>`: retrieve the metadata of a document by its id
- `api/documents/<doc_id>/download`: download the file associated to the metadata of the document

### Applications:
- create_cms_index.ipynb: to create the Azure AI Search index. The index name by default is `cms_index`
- sync_local_cms.py: synchronize locally the content in the CMS, downloading the metadata and associated file of every document, checking the `update_date` field.
- sync_aisearch_cms.py: synchronize the Azure AI Search index with the content in the CMS, downloading the metadata and associated file of every document, checking the `update_date` field.

## Prerequisites
+ An Azure subscription, with [access to Azure OpenAI](https://aka.ms/oai/access).
+ An Azure OpenAI service with the service name and an API key.
+ An instance of ada-02 model on the Azure OpenAI Service. Used to vectorize the content before indexing it in AI Search.
+ An instance of Azure AI Search.
+ An instance Document Intelligence service. Used to convert the files to markdown.


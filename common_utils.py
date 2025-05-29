import concurrent.futures
import json
import re
import os
from dotenv import load_dotenv, find_dotenv
import tiktoken
encoding = tiktoken.get_encoding("cl100k_base")
from openai import AzureOpenAI

from azure.search.documents.models import VectorizedQuery, QueryType, QueryCaptionType, QueryAnswerType
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient, SearchIndexingBufferedSender
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SimpleField, SearchFieldDataType, SearchableField, SearchField, VectorSearch, HnswAlgorithmConfiguration,
    VectorSearchProfile, SemanticConfiguration, SemanticPrioritizedFields, SemanticField, SemanticSearch,
    SearchIndex, VectorSearchAlgorithmKind, HnswParameters, VectorSearchAlgorithmMetric
)
from prompts import *

# CONSTANTS
EMBEDDINGS_DIMENSIONS = 1536
THRESHOLD_CONFIDENCE = 90
MAX_RETRIEVE = 70
MAX_GENERATE = 10
MAX_TOKENS = 512
TOKENS_OVERLAP = 128 # 25% of 512 tokens is 128 tokens

def load_config():
    # Load configuration variables from .env file
    load_dotenv(find_dotenv(), override=True)
    # Azure OpenAI configuration
    aoai_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
    aoai_key = os.getenv('AZURE_OPENAI_API_KEY')
    api_version = os.getenv('AZURE_OPENAI_API_VERSION')
    openai_config = {
        "aoai_endpoint": aoai_endpoint,
        "aoai_key": aoai_key,
        "aoai_deployment_name": os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME'),
        "aoai_embedding_model": os.getenv('AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME'),
        "aoai_rerank_model": os.getenv('AZURE_OPENAI_RERANK_DEPLOYMENT_NAME'),
        "api_version": api_version,
        # Initialize Azure OpenAI client
        "openai_client": AzureOpenAI(azure_endpoint=aoai_endpoint,
                                     api_key=aoai_key,
                                     api_version=api_version),
    }

    print(f'aoai_endpoint: {openai_config["aoai_endpoint"]}')
    print(f'aoai_deployment_name: {openai_config["aoai_deployment_name"]}')
    print(f'oai_embedding_model: {openai_config["aoai_embedding_model"]}')
    print(f'aoai_rerank_model: {openai_config["aoai_rerank_model"]}')

    # Azure AI Search configuration
    ai_search_endpoint = os.environ["SEARCH_SERVICE_ENDPOINT"]
    ai_search_apikey = os.environ["SEARCH_SERVICE_QUERY_KEY"]
    ai_search_index_name_regs = os.environ["SEARCH_INDEX_NAME_REGS"]
    ai_search_index_name_docs = os.environ["SEARCH_INDEX_NAME_DOCS"]
    ai_search_credential = AzureKeyCredential(ai_search_apikey)
    ai_search_config = {
        "ai_search_endpoint": ai_search_endpoint,
        "ai_search_apikey": ai_search_apikey,
        "ai_search_index_name_regs": ai_search_index_name_regs,
        "ai_search_index_name_docs": ai_search_index_name_docs,
        "ai_search_credential": ai_search_credential,
        # Initialize AI Search clients
        "ai_search_client_regs": SearchClient(endpoint=ai_search_endpoint,
                                              index_name=ai_search_index_name_regs,
                                              credential=ai_search_credential),
        "ai_search_client_docs": SearchClient(endpoint=ai_search_endpoint,
                                              index_name=ai_search_index_name_docs,
                                              credential=ai_search_credential),
    }

    print(f'ai_search_index_name_regs: {ai_search_config["ai_search_index_name_regs"]}')
    print(f'ai_search_index_name_docs: {ai_search_config["ai_search_index_name_docs"]}')

    return openai_config, ai_search_config

# Load in an array the content of every file in a directory
def load_files(input_dir, ext):
    print(f'Loading files in {input_dir}...')
    files_content = []
    for filename in os.listdir(input_dir):
        if filename.lower().endswith(ext):
            file_path = os.path.join(input_dir, filename)
            with open(file_path, 'r', encoding="utf-8") as f:
                row = {"title": filename.replace('_', ' ').replace('.txt', ''), "content": f.read()}
                files_content.append(row)
    return files_content

# Semantic Hybrid Search in AI Search
def semantic_hybrid_search(ai_search_client, openai_client, aoai_embedding_model, query, max_docs):
    EMBEDDING_FIELDS = "embeddingTitle, embeddingContent"
    SELECT_FIELDS=["id", "title", "content"]

    # Semantic Hybrid Search
    embedding = create_embedding(openai_client, aoai_embedding_model, query)
    vector_query = VectorizedQuery(vector=embedding, k_nearest_neighbors=max_docs, fields=EMBEDDING_FIELDS)

    results = ai_search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        select=SELECT_FIELDS,
        query_type=QueryType.SEMANTIC,
        semantic_configuration_name='semantic-config',
        query_caption=QueryCaptionType.EXTRACTIVE,
        query_answer=QueryAnswerType.EXTRACTIVE,
        include_total_count=True,
        top=max_docs,
        # highlight_fields=["table_description", "column_description"]
    )

    return list(results), results.get_count()

# Print the AI Search search results
def show_results(results, query):
    json_search_results = []
    for result in results:
        # Prepare json
        json_search_results.append({
            "id": result["id"],
            "title": result["title"],
            "content": result["content"],
            "score": result["@search.score"]
            }
        )
    print("Hybrid Search Results:", json.dumps(json_search_results, indent=2))

# Send a call to the model deployed on Azure OpenAI
def call_aoai(aoai_client, aoai_model_name, system_prompt, user_prompt, temperature, max_tokens):
    messages = [{'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}]
    #print('---------------------------------------------')
    #print(f'SYSTEM_PROMPT: {system_prompt}')
    #print(f'USER_PROMPT: {user_prompt}')
    #print('---------------------------------------------')
    try:
        response = aoai_client.chat.completions.create(
            model=aoai_model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        json_response = json.loads(response.model_dump_json())
        response = json_response['choices'][0]['message']['content']
    except Exception as ex:
        print(f'ERROR call_aoai: {ex}')
        response = None
    
    #print(f'RESPONSE: {response}')
    return response

# Extract data between two delimiters
def extract_text(texto, start_delimiter, end_delimiter=''):
    # This regular expression searches for any text between the delimiters.
    patron = re.escape(start_delimiter) + '(.*?)' + re.escape(end_delimiter)
    resultado = re.search(patron, texto, re.DOTALL)
    if resultado:
        return resultado.group(1)
    else:
        return None
        
# Calculate the confidence and generate the 'answer' from the content
def calculate_rank(aoai_client, aoai_model_name, id, title, content, question):
    # Include every relevant detail from the text to ensure all pertinent information is retained.
    system_prompt = SYSTEM_PROMPT_TO_CALCULATE_RANK
    
    user_prompt = """Search Query: """ + question + """
    Text:  """ + content + """
    """
    #print(f'USER PROMPT CALCULATE RANK: {user_prompt}')
    response = call_aoai(aoai_client, aoai_model_name, system_prompt, user_prompt, 0.0, 800)

    if response is not None:
        confidence = extract_text(response, 'confidence": ', ',')
        answer = extract_text(response, 'answer": ', '\n}')
        if answer is None or answer == '':
            answer = ''
        if confidence is None or confidence == '':
            confidence = 0
    else:
        confidence = 0
        answer = ''

    #print(f'\t- Response calculate rank: id: {id}, title: {title}, confidence: {confidence}')
    return id, title, content, confidence, answer

# Re-ranker: calculate in parallel the percentage of confidence and the answer comparing with the query
def get_filtered_chunks(aoai_client, aoai_model_name, results, query):
    i = 1
    chunks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_RETRIEVE) as executor:
        futures = []
        for result in results:
            futures.append(executor.submit(calculate_rank, aoai_client, aoai_model_name, result['id'], result['title'], result['content'], query))

        for future in concurrent.futures.as_completed(futures):
            id, title, content, confidence, answer = future.result()
            #print(f'\t  title: {title}, confidence: {confidence}, answer: {answer}')
            if int(confidence) >= THRESHOLD_CONFIDENCE:
                chunks.append({
                    "id": int(id),
                    "title": title,
                    "content": content,
                    "confidence": int(confidence),
                    "answer": answer
                    }
                )
                i += 1
    
    # Sort them by confidence and leave only the max number of docs to generate
    if chunks is not []:
        sorted_data = sorted(chunks, key=lambda x: x.get('confidence', float('-inf')), reverse=True)
        chunks = sorted_data[:MAX_GENERATE]

    # Valid chunks for the user question
    valid_chunks=""
    for chunk in chunks:
        valid_chunks = valid_chunks + f"'Title: {chunk['title']}. Content: {chunk['content']}\n"

    return valid_chunks, len(chunks)

# Create embedding from a chunk
def create_embedding(openai_client, aoai_embedding_model, text):
    response = openai_client.embeddings.create(
        model=aoai_embedding_model,
        input=text
    )
    return response.data[0].embedding

# GENERATE THE ANSWER
def generate_answer(aoai_client, aoai_deployment_name, valid_chunks, question):
    #print(f'\nCalling Azure OpenAI model {aoai_deployment_name}...')
    user_prompt = f"**Knowledge base:**\nSections: {valid_chunks}\n**Question:** {question}\nFinal Response:"

    answer = call_aoai(aoai_client, aoai_deployment_name, SYSTEM_PROMPT_GENERATE_ANSWER, user_prompt, 0.0, 1200)
    #print(f'\tRESPONSE: [{answer}]')
    if answer == None: answer = 'ERROR'
    return answer


def generate_answer_with_history(aoai_client, aoai_deployment_name, valid_chunks, question, history):
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT_GENERATE_ANSWER}]
    for q_a in history:
        messages.append({"role": "user", "content": q_a["question"]})
        messages.append({"role": "assistant", "content": q_a["answer"]})
    
    messages.append({"role": "user", "content": f"**Knowledge base:**\nSections: {valid_chunks}\n**Question:** {question}\nFinal Response:"})

    print(f"\nmessages: {json.dumps(messages, indent=2)}\n")
    try:
        response = aoai_client.chat.completions.create(
            model=aoai_deployment_name,
            messages=messages,
            temperature=0.0,
            max_tokens=1200
        )
        json_response = json.loads(response.model_dump_json())
        response = json_response['choices'][0]['message']['content']
    except Exception as ex:
        print(f'ERROR generate_query: {ex}')
        response = None
    return response

# Cut a text to a maximum number of tokens
def cut_max_tokens(text):
    tokens = encoding.encode(text)
    max_tokens = 8191
    if len(tokens) > max_tokens:
        print(f'\t*** CUT TOKENS, tokens: {len(tokens)}')
        return encoding.decode(tokens[:max_tokens])
    else:
        return text

# Evaluate Groundedness and Similarity with SDK of AI Foundry
def evaluate_answer(qa_eval, query, context, response, expected_answer):
    qa_score = qa_eval(
        query = query,
        response=response,
        context = context, 
        ground_truth= expected_answer,
    ) 

    return json.dumps(qa_score, indent=2)

# Generate the search query for the user question based on the conversation history
conversation_messages = [{"role": "system", "content": SYSTEM_PROMPT_REWRITE_QUERY},
                         {"role": "user", "content": "How did crypto do last year?"},
                         {"role": "assistant", "content": "Summarize Cryptocurrency Market Dynamics from last year"},
                         {"role": "user", "content": "What are my health plans?"},
                         {"role": "assistant", "content": "Show available health plans"},]

def generate_search_query(aoai_client, aoai_deployment_name, query, history):
    curr_messages = conversation_messages.copy()
    for q_a in history:
        curr_messages.append({"role": "user", "content": q_a["question"]})
        curr_messages.append({"role": "assistant", "content": q_a["answer"]})
    curr_messages.append({"role": "user", "content": f"Generate search query for: {query}"})
    print(f"\ncurr_messages: {json.dumps(curr_messages, indent=2)}\n")
    try:
        response = aoai_client.chat.completions.create(
            model=aoai_deployment_name,
            messages=curr_messages,
            temperature=0.0,
            max_tokens=1200
        )
        json_response = json.loads(response.model_dump_json())
        response = json_response['choices'][0]['message']['content']
    except Exception as ex:
        print(f'ERROR generate_query: {ex}')
        response = None
    return response
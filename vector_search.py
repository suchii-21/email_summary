import os, logging
from azure.identity import ClientSecretCredential, DefaultAzureCredential,get_bearer_token_provider
from azure.keyvault.secrets import SecretClient
from azure.search.documents.models import (
    VectorizableTextQuery,
    QueryType,
    QueryAnswerType,
    QueryCaptionType
)
from azure.search.documents import (SearchClient,SearchItemPaged)
from azure.search.documents.indexes import SearchIndexClient 
from azure.appconfiguration.provider import (
    load,
    SettingSelector
)
# from azure.search.documents.models import RawvectorQuery
from dotenv import load_dotenv
load_dotenv() 
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

class get_top_chunk:
    def __init__(self) :
       
        self.kv_uri = os.getenv('keyvault_url')
        self.credential = DefaultAzureCredential()
        self.kv_client = SecretClient(vault_url=self.kv_uri, credential=self.credential) # type: ignore
        self.app_config_endpoint = self.get_kv_secrets('app-config-endpoint')
        self.config = load(endpoint = self.app_config_endpoint,  # type: ignore
                           credential = self.credential)
        self.index_name =  self.config['legacyindex']
        self.search_endpoint = self.config['search-endpoint']
        self.search_client=SearchClient(endpoint=self.search_endpoint,credential=self.credential,index_name=self.index_name) # type: ignore


        self.azure_openai_endpoint = self.config['azure-endpoint']
        self.azure_openai_version = self.config['pii:openai_api_version']
        self.embedding_model = self.config['embedding-name']
        self.token_provider = get_bearer_token_provider(
                        self.credential,
                        "https://cognitiveservices.azure.com/.default"
                        )
        self.embedding_client = AzureOpenAI(
             azure_endpoint=self.azure_openai_endpoint,
             api_version=self.azure_openai_version,
             azure_ad_token_provider= self.token_provider

        )


    def get_kv_secrets(self, secret_name):
        """
        get keyvault secrets 
        """

        try:
            return self.kv_client.get_secret(secret_name).value
        except Exception as e:
            print(f"Error fetching secret {secret_name}: {str(e)}")
            return None
        
    def retriveal_of_top_chunk(self, query):
        """
        get top chunks based on the incoming query
        """

        embedding = self.embedding_client.embeddings.create(
            model=self.embedding_model,
            input=query
        )
        

        query_embedding =embedding.data[0].embedding

        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=50,
            fields="text_vector"
        )

        logging.warning('Query has been embedded')



        try:
                results = self.search_client.search(
                    search_text=query,
                    select=['natureofincidents', 'chunk' , 'caseid'],
                    vector_queries=[vector_query],
                    query_type="semantic",
                    semantic_configuration_name='default',
                    query_caption="extractive",
                    query_answer="extractive",
                    query_answer_threshold=0.95,
                    top=50
                )
                logging.warning('Got results')

                reranker_threshold = 2.0

                final_response = []

                for result in results:
                    reranker_score = result.get('@search.reranker_score') or 0

                    if reranker_score < reranker_threshold:
                        # logging.warning(f"Skipping chunk with low reranker score: {reranker_score:.2f}")
                        continue

                    response = {
                        "context": result.get('chunk', ''),
                        "natureofincidents": result.get("natureofincidents"),
                        "reranker_score": reranker_score
                    }
                    final_response.append(response)

                semantic_answers = results.get_answers()
                if semantic_answers:
                    for ans in semantic_answers:
                        
                            if ans.score >= 0.95:
                                final_response.append({
                                    "context": ans.text,
                                    "natureofincidents": None,
                                })

                logging.warning(f'final response is :{final_response}')
                return final_response

        except Exception as e:
                logging.error(f'Failure to get the top chunks due to: {e}')
                return [{"context": "", "citations": "", "confidentialflag": "", "caseid": ""}]
    









# import os, logging
# from azure.identity import ClientSecretCredential, DefaultAzureCredential
# from azure.keyvault.secrets import SecretClient
# from azure.search.documents.models import (
#     VectorizableTextQuery,
#     QueryType,
#     QueryAnswerType,
#     QueryCaptionType
# )
# from azure.search.documents import (SearchClient,SearchItemPaged)
# from azure.search.documents.indexes import SearchIndexClient 
# from dotenv import load_dotenv
# load_dotenv() 

# class get_top_chunk:
#     def __init__(self) :
       
#         self.kv_uri = os.getenv('keyvault_url')
#         # self.kv_uri = f"https://{self.keyvault_name}.vault.azure.net"
#         # self.credential = ClientSecretCredential(
#         #     tenant_id= os.getenv('AZURE_TENANT_ID'), # type: ignore
#         #     client_id= os.getenv('AZURE_CLIENT_ID'), # type: ignore
#         #     client_secret=os.getenv('AZURE_CLIENT_SECRET') # type: ignore
#         # )
#         self.credential = DefaultAzureCredential()
#         self.kv_client = SecretClient(vault_url=self.kv_uri, credential=self.credential) # type: ignore
#         self.index_name =  self.get_kv_secrets('get-index-name')
#         self.search_endpoint = self.get_kv_secrets('get-search-endpoint')
#         self.search_client=SearchClient(endpoint=self.search_endpoint,credential=self.credential,index_name=self.index_name) # type: ignore


#     def get_kv_secrets(self, secret_name):
#         """
#         get keyvault secrets 
#         """

#         try:
#             return self.kv_client.get_secret(secret_name).value
#         except Exception as e:
#             print(f"Error fetching secret {secret_name}: {str(e)}")
#             return None
        
#     def retriveal_of_top_chunk(self, query):
#         try:
#             vector_query=VectorizableTextQuery(
#             text=query,
#             k=5,
#             fields='text_vector',
#             exhaustive=True
#         ) 
#             results=self.search_client.search(
#             search_text=query,
#             vector_queries=[vector_query],
#             select=['title','chunk','parent_id','confidential'],
#             query_type=QueryType.SEMANTIC,
#             semantic_configuration_name='legacy-semantic-config', 
#             query_caption=QueryCaptionType.EXTRACTIVE,
#             query_answer=QueryAnswerType.EXTRACTIVE,
#             top=3
#         ) 
#             print(results)
#             # return results.get_answers()
#             context_chunks = []
#             for result in results:
#                 chunk = result.get('chunk')
#                 if chunk:
#                     context_chunks.append(chunk)

#             semantic_answers = results.get_answers()
#             if semantic_answers:
#                 for ans in semantic_answers:
#                     if ans.text not in context_chunks:
#                         context_chunks.append(ans.text)
#             return "\n\n".join(context_chunks)
#         except Exception as e:
#             logging.error(f'Failed to return the top chunks due to : {e}')
#             return ''
    



import os, json, logging
from azure.search.documents.models import VectorizableTextQuery, QueryType, QueryCaptionType, QueryAnswerType
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticField,
    SemanticSearch, 
    SemanticPrioritizedFields,
    ExhaustiveKnnAlgorithmConfiguration,
    AzureOpenAIVectorizer,
    
)


class IndexLogic:
    """"
    Class to perform index operations 
    """

    def __init__(self):
        self.search_key = os.getenv('search_key')
        self.search_endpoint = os.getenv('search_endpoint')
        self.index_name = os.getenv('index_name')

        if not all([self.search_endpoint, self.search_key]):
            logging.error('Missing Credentials related to AI Search Service')
            raise ValueError
        

        try :
            self.index_client = SearchIndexClient(
                endpoint=self.search_endpoint,
                credential=AzureKeyCredential(self.search_key) # type: ignore
            )

        except Exception as e:
            logging.error(f'Error Occured while trying to initialize search client due to : {e}')




    def index_exists(self, index_name):
        """
        Function to check if the Index exist or not
        
        :param self: Description
        :param index_name: Name of the Index 
        """
        try:
            self.index_client.get_index(index_name)
            return True
        except Exception:
            return False


        
    def storing_content_in_index(self):
        """
        Function to create Index 

        """
        # Check if the Index with the same name exists already
        if self.index_exists(self.index_name):
            logging.info(f"Index '{self.index_name}' already exists, skipping creation.")
            return True
        
        else :
            index_fields = [
                    SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                    SearchField(name="Parentid", type=SearchFieldDataType.String, searchable=False),
                    SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
                    SearchField(name="title", type=SearchFieldDataType.String, searchable=False),
                    SearchField(
                        name="contentVector",
                        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                        searchable=True,
                        vector_search_dimensions=1536,
                        vector_search_profile_name="vector-profile"
                    )]
            

            vector_search = VectorSearch(
                    algorithms=[
                        HnswAlgorithmConfiguration(name="my-hnsw-vector-config-1", kind="hnsw"),
                        ExhaustiveKnnAlgorithmConfiguration(name="my-eknn-vector-config", kind="exhaustiveKnn")
                    ],
                    # vectorizers=[
                    #     AzureOpenAIVectorizer(

                    #         vectorizer_name= "text-embedding-ada-002",
                    #         kind = 'azureOpenAI',
                    #         azure_open_ai_parameters=AzureOpenAIParameters(
                    #                 resource_uri="https://analysisnextopenai.openai.azure.com/",    
                    #                 deployment_id="text-embedding-ada-002"   
                    #         )

                    #     )
                    # ],
                    profiles=[
                        VectorSearchProfile(name="vector-profile", algorithm_configuration_name="my-hnsw-vector-config-1")
                    ]
                )
            semantic_config = SemanticConfiguration(
                    name="semantic-config",
                    prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"), 
                    content_fields=[SemanticField(field_name="content")], 
                    )
                )
                    
                
            semantic_search = SemanticSearch(configurations=[semantic_config])

            semantic_settings = SemanticSearch(configurations=[semantic_config])
            scoring_profiles = []
            try :
                index = SearchIndex(name=self.index_name, fields=index_fields, vector_search=vector_search, semantic_search=semantic_search)
                result = self.index_client.create_or_update_index(index)
                logging.info(f' {result.name} created')
                return True
            except Exception as e:
                logging.error(f'Error occured while creating or updating the Index : {e}')
                return False
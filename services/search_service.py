from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

class SearchService:
    def __init__(self, config, embedding_service):
        self.client = SearchClient(
            endpoint=config.search_endpoint,
            index_name=config.index_name,
            credential=config.credential
        )
        self.embedding_service = embedding_service

    def search(self, query, nature):
        vector = self.embedding_service.get_embedding(query)

        results = self.client.search(
            search_text=query,
            vector_queries=[
                VectorizedQuery(
                    vector=vector,
                    k_nearest_neighbors=5,
                    fields="text_vector"
                )
            ],
            filter=f"natureofincidents eq '{nature}'",
            query_type="semantic",
            semantic_configuration_name="default",
            top=5
        )

        return [r for r in results]

from openai import AzureOpenAI
from azure.identity import get_bearer_token_provider

class EmbeddingService:
    def __init__(self, config):
        self.client = AzureOpenAI(
            azure_endpoint=config.openai_endpoint,
            api_version=config.api_version,
            azure_ad_token_provider=get_bearer_token_provider(
                config.credential,
                "https://cognitiveservices.azure.com/.default"
            )
        )
        self.model = config.embedding_model

    def get_embedding(self, text):
        response = self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding

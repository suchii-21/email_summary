import os
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

class Config:
    def __init__(self):
        self.credential = DefaultAzureCredential()
        kv_url = os.getenv("KEYVAULT_URL")

        self.secret_client = SecretClient(vault_url=kv_url, credential=self.credential)

        self.search_endpoint = self.get_secret("get-search-endpoint")
        self.index_name = self.get_secret("legacy-index-name")

        self.openai_endpoint = self.get_secret("azure-endpoint")
        self.chat_model = self.get_secret("deploymentname")
        self.embedding_model = self.get_secret("embedding-model")
        self.api_version = self.get_secret("api-version")

        self.language_endpoint = self.get_secret("language-endpoint")

    def get_secret(self, name):
        return self.secret_client.get_secret(name).value

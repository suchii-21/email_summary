from openai import AzureOpenAI
from azure.identity import get_bearer_token_provider

class LLMService:
    def __init__(self, config):
        self.client = AzureOpenAI(
            azure_endpoint=config.openai_endpoint,
            api_version=config.api_version,
            azure_ad_token_provider=get_bearer_token_provider(
                config.credential,
                "https://cognitiveservices.azure.com/.default"
            )
        )
        self.model = config.chat_model

    def generate(self, prompt):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a fraud analytics expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format = {'type' : 'json_object'},
            max_completion_tokens= 800
        )
        return response.choices[0].message.content

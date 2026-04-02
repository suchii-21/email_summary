import os, json, logging
from azure.identity import DefaultAzureCredential

class summarized_email:

    def __init__(self):
        self.BLOB_CONN_STR = os.getenv('BLOB_CONN_STR')
        self.BLOB_CONTAINER_NAME = os.getenv('BLOB_CONTAINER_NAME')
        self.DOC_INT_KEY = os.getenv('DOC_INT_KEY')
        self.DOC_INT_ENDPOINT = os.getenv('DOC_INT_ENDPOINT')
        self.deployment_name = os.getenv('deployment_name')
        self.api_version = os.getenv('api_version')
        self.azure_endpoint = os.getenv('azure_endpoint')
        self.blob_container_name = os.getenv('blob_container_name')
        self.account_url = os.getenv('account_url')
        self.credential = DefaultAzureCredential()

        if not all([self.BLOB_CONN_STR,
                    self.BLOB_CONTAINER_NAME,
                    self.DOC_INT_KEY,
                    self.DOC_INT_ENDPOINT,
                    self.deployment_name,
                    self.api_version,
                    self.azure_endpoint,
                    self.blob_container_name,
                    self.account_url
                ]):
            logging.error("Missing one or more environment variables")


    def get_email_summary(self, email_session_id, email_subject, email_body, attachments_raw = []):
        pass



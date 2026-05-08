import logging
from azure.ai.contentsafety import ContentSafetyClient


class ContentSafetyService:

    def __init__(self, config):
        self.client = ContentSafetyClient(
            endpoint=config.content_safety_endpoint,
            credential=config.credential
        )

    def analyze(self, text: str) -> dict:
        """
        Returns structured decision:
        {
            "allowed": bool,
            "reason": str,
            "categories": []
        }
        """

        try:
            response = self.client.analyze_text({"text": text})

            flagged_categories = []

            for category in response.categories_analysis:
                if category.severity >= 3:
                    flagged_categories.append(category.category)

            if flagged_categories:
                logging.warning(f"Unsafe content detected: {flagged_categories}")

                return {
                    "allowed": False,
                    "reason": "Input contains inappropriate or unsafe content.",
                    "categories": flagged_categories
                }

            return {
                "allowed": True,
                "reason": "",
                "categories": []
            }

        except Exception as e:
            logging.warning(f"Content safety check failed: {e}")

            # Fail-open (important for production reliability)
            return {
                "allowed": True,
                "reason": "",
                "categories": []
            }
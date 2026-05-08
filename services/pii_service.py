import logging
import re
from collections import defaultdict

from azure.ai.textanalytics import TextAnalyticsClient
from azure.identity import DefaultAzureCredential

# import your custom detector
from services.custom_entity_detector import detect_and_mask_custom


# -----------------------------
# Category mapping (simplified)
# -----------------------------
CATEGORY_TOKEN_MAP = {
    "Person": "person",
    "PhoneNumber": "phone",
    "Email": "email",
    "Address": "address",
    "CreditCardNumber": "credit_card",
    "BankAccountNumber": "bank_account",
    "DateTime": "datetime",
    "Organization": "organization",
    "Location": "location",
}


class PIIService:

    def __init__(self, config):
        self.client = TextAnalyticsClient(
            endpoint=config.language_endpoint,
            credential=config.credential
        )

    # -----------------------------
    # Build counters from registry
    # -----------------------------
    def _build_counters(self, registry):
        counters = defaultdict(int)

        for token in registry:
            match = re.match(r'\[([a-z_]+)_(\d+)\]', token)
            if match:
                base, num = match.group(1), int(match.group(2))
                counters[base] = max(counters[base], num)

        return counters

    # -----------------------------
    # Stage 1: Azure PII
    # -----------------------------
    def _azure_detect(self, text, registry):

        try:
            response = self.client.recognize_pii_entities([text])
            result = response[0]

            if result.is_error or not result.entities:
                return text, registry

        except Exception as e:
            logging.warning(f"Azure PII failed: {e}")
            return text, registry

        counters = self._build_counters(registry)
        value_to_token = {v: k for k, v in registry.items()}

        masked_text = text

        for entity in sorted(result.entities, key=lambda x: x.offset, reverse=True):

            if entity.confidence_score < 0.5:
                continue

            original = entity.text

            # reuse token if already seen
            if original in value_to_token:
                token = value_to_token[original]
            else:
                base = CATEGORY_TOKEN_MAP.get(
                    entity.category,
                    entity.category.lower()
                )

                counters[base] += 1
                token = f"[{base}_{counters[base]}]"

                registry[token] = original
                value_to_token[original] = token

            start = entity.offset
            end = start + entity.length

            masked_text = masked_text[:start] + token + masked_text[end:]

        return masked_text, registry

    # -----------------------------
    # PUBLIC: Mask chunks
    # -----------------------------
    def mask_chunks(self, chunks):

        registry = {}
        masked_chunks = []

        for text in chunks:

            if not text:
                masked_chunks.append(text)
                continue

            # Stage 1: Azure Language
            text, registry = self._azure_detect(text, registry)

            # Stage 2: Custom regex (your enterprise logic)
            text, registry = detect_and_mask_custom(text, registry)

            masked_chunks.append(text)

        logging.info(f"PII entities detected: {len(registry)}")

        return masked_chunks, registry

    # -----------------------------
    # Restore
    # -----------------------------
    def restore_pii(self, text, registry):

        if not registry:
            return text

        for token, value in registry.items():
            text = text.replace(token, value)

        return text

    # -----------------------------
    # Optional: Entity summary
    # -----------------------------
    def build_entity_summary(self, registry):

        return [
            {
                "token": token,
                "type": token.strip("[]").rsplit("_", 1)[0],
                "masked": True
            }
            for token in registry
        ]
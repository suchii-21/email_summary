"""
app/shared/custom_entity_detector.py
======================================
Custom regex-based detector for ADIB FID domain-specific sensitive identifiers
that Azure Language Services does not cover.

These are not standard PII but are equally sensitive in a banking/fraud context:
  - Account numbers, staff IDs, case IDs, card serial numbers, etc.

All patterns are loaded from App Configuration so they can be updated
without redeployment. New entity types can be added purely via App Config.

Pattern format in App Config (key: custom_entities/patterns):
  JSON array of objects:
  [
    {"name": "account_number", "pattern": "\\b(ACC|ACCT|Account)?[-\\s]?\\d{8,16}\\b", "flags": "IGNORECASE"},
    {"name": "case_id",        "pattern": "\\bCASE[-/]?\\d{4,12}\\b",                  "flags": "IGNORECASE"},
    ...
  ]

Runs BEFORE Azure Language Services so combined registry is complete.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

# from app.shared.config import cfg

logger = logging.getLogger("adib_rag.custom_entity")

# ─────────────────────────────────────────────────────────────────────
# Default built-in patterns — used if App Config key is not set
# All patterns are case-insensitive by default
# ─────────────────────────────────────────────────────────────────────

_DEFAULT_PATTERNS: list[dict] = [
    # ── Account identifiers ──────────────────────────────────────────
    {
        "name":    "account_number",
        "pattern": r"\b(?:ACC(?:T|OUNT)?(?:[-\s#:.]?\s*(?:NO|NUMBER|NUM|#)?)?[-\s#:.]*|Account\s*(?:No|Number|Num|#)?[-\s#:.]*)\d{6,18}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "iban",
        "pattern": r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b",
        "flags":   "",
    },

    # ── Staff / Employee identifiers ─────────────────────────────────
    {
        "name":    "staff_id",
        "pattern": r"\b(?:STAFF[-\s#:.]?(?:ID|NO|NUMBER|#)?|EMP(?:LOYEE)?[-\s#:.]?(?:ID|NO|NUMBER|#)?|EMPLOYEE\s*ID)[-\s#:.]*[A-Z0-9]{4,12}\b",
        "flags":   "IGNORECASE",
    },

    # ── Case / Complaint / Reference identifiers ──────────────────────
    {
        "name":    "case_id",
        "pattern": r"\b(?:CASE[-\s#/]?(?:ID|NO|NUMBER|REF|REFERENCE)?|CASE\s*(?:ID|NO|NUMBER|REFERENCE))[-\s#/:.]*[A-Z0-9\-]{4,20}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "case_ref_id",
        "pattern": r"\b(?:CASE[-\s]?REF(?:ERENCE)?[-\s#/:.]*|REF[-\s#/:.]*(?:NO|NUMBER|ID)?[-\s#/:.]*)[A-Z0-9\-]{4,20}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "complaint_number",
        "pattern": r"\b(?:COMPLAINT[-\s#/:.]*(?:NO|NUMBER|ID|REF)?|COMPLAINT\s*(?:CALL\s*)?(?:NO|NUMBER|ID))[-\s#/:.]*[A-Z0-9\-]{4,20}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "call_reference",
        "pattern": r"\b(?:CALL[-\s#/:.]*(?:REF|REFERENCE|NO|NUMBER|ID)?|CALL\s*(?:REF|REFERENCE))[-\s#/:.]*[A-Z0-9\-]{4,20}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "ticket_number",
        "pattern": r"\b(?:TICKET[-\s#/:.]*(?:NO|NUMBER|ID)?|TKT[-\s#/:.]*[A-Z0-9\-]{4,20})\b",
        "flags":   "IGNORECASE",
    },

    # ── Card identifiers ──────────────────────────────────────────────
    {
        "name":    "card_serial_number",
        "pattern": r"\b(?:CARD[-\s]?(?:SERIAL[-\s]?(?:NO|NUMBER|#)?|SN|S/N)[-\s#:.]*)[A-Z0-9\-]{8,20}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "card_number",
        "pattern": r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "flags":   "",
    },
    {
        "name":    "card_last_four",
        "pattern": r"\b(?:CARD|CC)[-\s]*(?:ENDING|ENDS?|LAST\s*4|LAST\s*FOUR)[-\s]*(?:IN|WITH)?[-\s]*(\d{4})\b",
        "flags":   "IGNORECASE",
    },

    # ── Cheque / Check identifiers ────────────────────────────────────
    {
        "name":    "cheque_number",
        "pattern": r"\b(?:CH(?:E(?:QUE?|CK))[-\s#/:.]*(?:NO|NUMBER|NUM|#)?[-\s#/.]*)\d{4,12}\b",
        "flags":   "IGNORECASE",
    },

    # ── Transaction identifiers ───────────────────────────────────────
    {
        "name":    "transaction_id",
        "pattern": r"\b(?:TXN|TRX|TRANSACTION|TRANS)[-\s#/:.]*(?:ID|NO|NUMBER|REF)?[-\s#/:.]*[A-Z0-9\-]{6,24}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "reference_number",
        "pattern": r"\b(?:REF(?:ERENCE)?[-\s#/:.]*(?:NO|NUMBER|NUM|#)?[-\s#/:.]*)[A-Z0-9\-]{6,24}\b",
        "flags":   "IGNORECASE",
    },

    # ── Fraud investigation specific ──────────────────────────────────
    {
        "name":    "investigation_id",
        "pattern": r"\b(?:INV(?:ESTIGATION)?[-\s#/:.]*(?:ID|NO|NUMBER|REF)?[-\s#/:.]*)[A-Z0-9\-]{4,20}\b",
        "flags":   "IGNORECASE",
    },
    {
        "name":    "sar_number",
        "pattern": r"\b(?:SAR|STR|CTR)[-\s#/:.]*(?:NO|NUMBER|ID|REF)?[-\s#/:.]*[A-Z0-9\-]{4,20}\b",
        "flags":   "IGNORECASE",
    },

    # ── Bare numeric patterns (last resort — high specificity required) ─
    {
        "name":    "account_number_bare",
        "pattern": r"\b(?<![/\-\d])(?:0\d{8,11}|\d{10,16})(?![/\-\d])\b",
        "flags":   "",
        "min_confidence": 0.6,   # only apply if not caught by named patterns above
    },
]


# ─────────────────────────────────────────────────────────────────────
# Load compiled patterns — from App Config if available, else defaults
# ─────────────────────────────────────────────────────────────────────

_compiled_patterns: list[tuple[str, re.Pattern]] | None = None


def _get_patterns() -> list[tuple[str, re.Pattern]]:
    global _compiled_patterns
    if _compiled_patterns is not None:
        return _compiled_patterns

    
        # raw = cfg("custom_entities/patterns")
        # pattern_defs = json.loads(raw)
        
        # logger.info("Custom entity patterns loaded from App Configuration (%d patterns)", len(pattern_defs))

    pattern_defs = _DEFAULT_PATTERNS
    logger.info("Using default custom entity patterns (%d patterns)", len(pattern_defs))

    compiled = []
    for p in pattern_defs:
        try:
            flags_str = p.get("flags", "IGNORECASE")
            flags     = 0
            if "IGNORECASE" in flags_str:
                flags |= re.IGNORECASE
            if "MULTILINE" in flags_str:
                flags |= re.MULTILINE
            compiled.append((p["name"], re.compile(p["pattern"], flags)))
        except Exception as exc:
            logger.warning("Failed to compile pattern '%s': %s", p.get("name", "?"), exc)

    _compiled_patterns = compiled
    return _compiled_patterns


def invalidate_pattern_cache() -> None:
    """Call after updating custom_entities/patterns in App Config."""
    global _compiled_patterns
    _compiled_patterns = None


# ─────────────────────────────────────────────────────────────────────
# Main: detect and mask custom domain entities
# ─────────────────────────────────────────────────────────────────────

def detect_and_mask_custom(
    text: str,
    existing_registry: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """
    Detect ADIB FID domain-specific entities and mask them.

    Runs on top of (or instead of) Azure Language PII detection.
    Existing registry is used to reuse tokens for already-seen values.

    Returns:
        masked_text:  text with custom entities replaced by tokens
        registry:     dict mapping [token] → original_value (merged with existing)
    """
    if not text or not text.strip():
        return text, existing_registry or {}

    registry       = dict(existing_registry or {})
    value_to_token = {v: k for k, v in registry.items()}

    # Track highest counter per type
    type_counters: dict[str, int] = defaultdict(int)
    for token in registry:
        m = re.match(r'\[([a-z_]+)_(\d+)\]', token)
        if m:
            base, num = m.group(1), int(m.group(2))
            type_counters[base] = max(type_counters[base], num)

    patterns = _get_patterns()

    # Collect all matches across all patterns first
    # Format: (start, end, token_name, matched_text)
    all_matches: list[tuple[int, int, str, str]] = []

    for token_name, pattern in patterns:
        for match in pattern.finditer(text):
            start         = match.start()
            end           = match.end()
            matched_value = match.group(0).strip()

            # Skip if too short (avoid false positives)
            if len(matched_value.replace(" ", "").replace("-", "")) < 4:
                continue

            all_matches.append((start, end, token_name, matched_value))

    # Remove overlapping matches — keep longest match at each position
    all_matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    filtered: list[tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, name, value in all_matches:
        if start >= last_end:
            filtered.append((start, end, name, value))
            last_end = end

    if not filtered:
        return text, registry

    # Replace from end to preserve offsets
    masked_text = text
    for start, end, token_name, original_value in sorted(filtered, key=lambda x: x[0], reverse=True):
        if original_value in value_to_token:
            token = value_to_token[original_value]
        else:
            type_counters[token_name] += 1
            token = f"[{token_name}_{type_counters[token_name]}]"
            value_to_token[original_value] = token
            registry[token] = original_value

        masked_text = masked_text[:start] + token + masked_text[end:]

    if registry:
        new_tokens = [k for k in registry if k not in (existing_registry or {})]
        if new_tokens:
            logger.info(
                "Custom entities masked: %d new tokens → %s",
                len(new_tokens),
                new_tokens,
            )

    return masked_text, registry
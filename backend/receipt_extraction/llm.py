from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


PROMPT_TEMPLATE = """
You are a financial data extraction AI.

Extract structured data from this receipt text.

Return ONLY valid JSON with this schema:
{{
  "merchant": "",
  "date": "",
  "total": "",
  "tax": "",
  "currency": "",
  "items": [
    {{
      "name": "",
      "price": ""
    }}
  ]
}}

Rules:
- If a field is missing, return null
- Do not hallucinate values
- Detect currency automatically
- Normalize date format to YYYY-MM-DD
- Total must be the final payable amount
- Extract multiple items if present

Receipt Text:
{ocr_text}
"""


class LLMConfigurationError(RuntimeError):
    """Raised when no usable LLM endpoint is configured."""


class LLMResponseError(RuntimeError):
    """Raised when the LLM response is unavailable or invalid."""


@dataclass(frozen=True)
class LLMConfig:
    endpoint: str
    api_key: str
    model: str
    mode: str = "openai"
    account_id: Optional[str] = None
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "LLMConfig":
        endpoint = os.getenv("RECEIPT_LLM_ENDPOINT", "").strip()
        api_key = os.getenv("RECEIPT_LLM_API_KEY", "").strip()
        model = os.getenv("RECEIPT_LLM_MODEL", "").strip()
        mode = os.getenv("RECEIPT_LLM_MODE", "openai").strip().lower()
        account_id = os.getenv("RECEIPT_LLM_ACCOUNT_ID", "").strip() or None

        if not endpoint and os.getenv("GROQ_API_KEY"):
            endpoint = os.getenv("GROQ_LLM_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions").strip()
            api_key = os.getenv("GROQ_API_KEY", "").strip()
            model = model or os.getenv("GROQ_MODEL_NAME", "llama-3.3-70b-versatile").strip()
            mode = "openai"

        if not endpoint and os.getenv("OPENAI_API_KEY"):
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            endpoint = f"{base_url}/chat/completions"
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
            mode = "openai"

        if not endpoint and os.getenv("CLOUDFLARE_LLM_ENDPOINT"):
            endpoint = os.getenv("CLOUDFLARE_LLM_ENDPOINT", "").strip()
            api_key = os.getenv("CLOUDFLARE_LLM_API_KEY", "").strip()
            model = model or os.getenv("CLOUDFLARE_MODEL_NAME", "").strip()
            account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip() or None
            mode = "custom"

        if not endpoint or not api_key:
            raise LLMConfigurationError(
                "Configure RECEIPT_LLM_ENDPOINT/RECEIPT_LLM_API_KEY, GROQ_API_KEY, or OPENAI_API_KEY before calling receipt extraction."
            )
        return cls(endpoint=endpoint, api_key=api_key, model=model, mode=mode, account_id=account_id)


class ReceiptLLMClient:
    """OpenAI-compatible or custom JSON extraction client."""

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig.from_env()

    def extract(self, ocr_text: str) -> dict[str, Any]:
        if not ocr_text.strip():
            raise LLMResponseError("OCR text is empty; receipt extraction cannot continue.")
        prompt = PROMPT_TEMPLATE.format(ocr_text=ocr_text.strip())
        response = self._post_json(self._payload(prompt))
        raw_text = self._extract_text(response)
        payload = self._parse_json(raw_text)
        return validate_receipt_json(payload)

    async def aextract(self, ocr_text: str) -> dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(self.extract, ocr_text)

    def _payload(self, prompt: str) -> dict[str, Any]:
        messages = [{"role": "user", "content": prompt}]
        if self.config.mode == "custom":
            payload: dict[str, Any] = {"messages": messages}
            if self.config.model:
                payload["model"] = self.config.model
            if self.config.account_id:
                payload["account_id"] = self.config.account_id
            return payload
        return {
            "model": self.config.model or "gpt-4.1-mini",
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                decoded = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise LLMResponseError(f"Receipt LLM request failed: {exc}") from exc

        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("Receipt LLM returned non-JSON transport response.") from exc
        if not isinstance(parsed, dict):
            raise LLMResponseError("Receipt LLM transport response must be a JSON object.")
        return parsed

    def _extract_text(self, response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]

        for key in ("response", "result", "text", "output", "answer"):
            value = response.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = self._extract_text(value)
                if nested:
                    return nested
        return json.dumps(response)

    def _parse_json(self, raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if not match:
                raise LLMResponseError("Receipt LLM did not return a JSON object.")
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise LLMResponseError("Receipt LLM returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise LLMResponseError("Receipt LLM JSON response must be an object.")
        return payload


def validate_receipt_json(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise LLMResponseError("Receipt JSON field 'items' must be a list.")

    return {
        "merchant": _nullable_string(payload.get("merchant")),
        "date": _normalize_date(payload.get("date")),
        "total": _nullable_money(payload.get("total")),
        "tax": _nullable_money(payload.get("tax")),
        "currency": _normalize_currency(payload.get("currency")),
        "items": [_validate_item(item) for item in items if isinstance(item, dict)],
    }


def _validate_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _nullable_string(item.get("name")),
        "price": _nullable_money(item.get("price")),
    }


def _nullable_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"null", "none", "n/a", "na"}:
        return None
    return cleaned


def _nullable_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "na"}:
        return None
    text = re.sub(r"[^0-9,.\-]", "", text)
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value_decimal = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise LLMResponseError(f"Invalid money value in receipt JSON: {value}") from exc
    return float(value_decimal.quantize(Decimal("0.01")))


def _normalize_date(value: Any) -> Optional[str]:
    cleaned = _nullable_string(value)
    if not cleaned:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return cleaned


def _normalize_currency(value: Any) -> Optional[str]:
    cleaned = _nullable_string(value)
    if not cleaned:
        return None
    currency_map = {
        "$": "USD",
        "US$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "A$": "AUD",
        "C$": "CAD",
    }
    upper = cleaned.upper()
    return currency_map.get(cleaned, currency_map.get(upper, upper[:3] if re.fullmatch(r"[A-Z]{3}", upper[:3]) else cleaned))

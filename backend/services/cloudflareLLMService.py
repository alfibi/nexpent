import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_LLM_API_KEY,
    CLOUDFLARE_LLM_ENDPOINT,
    CLOUDFLARE_MODEL_NAME,
    GROQ_API_KEY,
    GROQ_LLM_ENDPOINT,
    GROQ_MODEL_NAME,
)

logger = logging.getLogger(__name__)


class CloudflareLLMService:
    def __init__(self) -> None:
        self.provider = "groq" if GROQ_API_KEY else "cloudflare"
        self.endpoint = GROQ_LLM_ENDPOINT if GROQ_API_KEY else CLOUDFLARE_LLM_ENDPOINT
        self.api_key = GROQ_API_KEY or CLOUDFLARE_LLM_API_KEY
        self.account_id = None if GROQ_API_KEY else CLOUDFLARE_ACCOUNT_ID
        self.model_name = GROQ_MODEL_NAME if GROQ_API_KEY else CLOUDFLARE_MODEL_NAME

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key)

    def _categorize_receipt_text(self, text: str) -> str:
        normalized = text.lower()
        category_keywords = (
            ("Food & Drinks", ("restaurant", "cafe", "coffee", "pizza", "burger", "bakery", "bar", "diner", "food")),
            ("Groceries", ("grocery", "supermarket", "market", "walmart", "costco", "aldi", "kroger", "milk", "bread")),
            ("Transport", ("fuel", "gas", "uber", "lyft", "metro", "parking", "taxi")),
            ("Shopping", ("store", "mall", "target", "amazon", "clothing", "apparel")),
            ("Health", ("pharmacy", "chemist", "clinic", "medical", "drug")),
        )
        for category, keywords in category_keywords:
            if any(keyword in normalized for keyword in keywords):
                return category
        return "Uncategorized"

    def _money_matches(self, line: str) -> list[tuple[float, tuple[int, int]]]:
        matches: list[tuple[float, tuple[int, int]]] = []
        for match in re.finditer(r"(?<![\w])(?:[$€£₹]\s*)?(\d{1,6}(?:,\d{3})*\.\d{2})(?![\w])", line):
            try:
                matches.append((float(match.group(1).replace(",", "")), match.span()))
            except ValueError:
                continue
        for match in re.finditer(r"[$€£₹]\s*(\d{1,6}(?:,\d{3})*)(?![\w.])", line):
            try:
                matches.append((float(match.group(1).replace(",", "")), match.span()))
            except ValueError:
                continue
        return sorted(matches, key=lambda item: item[1][0])

    def _extract_items_fallback(self, lines: list[str]) -> list[dict[str, Any]]:
        excluded_labels = (
            "total",
            "subtotal",
            "tax",
            "amount",
            "balance",
            "cash",
            "change",
            "visa",
            "mastercard",
            "debit",
            "credit",
        )
        items: list[dict[str, Any]] = []
        in_item_section = False
        for line in lines:
            normalized = line.lower()
            if re.search(r"\bname\b", normalized) and re.search(r"\b(qty|quantity)\b", normalized):
                in_item_section = True
                continue
            if in_item_section and any(label in normalized for label in ("total", "price", "cash", "change", "thank")):
                break
            if not in_item_section or any(label in normalized for label in excluded_labels):
                continue
            matches = self._money_matches(line)
            if not matches:
                continue
            total_price, span = matches[-1]
            name = re.sub(r"\s+\d+(?:\.\d+)?\s*$", "", line[: span[0]]).strip()
            name = re.sub(r"[-–—:\s]+$", "", name).strip()
            if len(name) < 2:
                continue
            items.append({"name": name[:160], "quantity": 1, "totalPrice": total_price})
        return items[:50]

    def _extract_receipt_fallback(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("cleaned_text") or "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        total_labels = (
            "grand total",
            "amount paid",
            "amount due",
            "balance due",
            "total paid",
            "total",
            "price",
        )
        excluded_total_labels = ("cash", "change", "tender", "paid by")

        amount = 0.0
        amount_source = None
        for line in reversed(lines):
            normalized = line.lower()
            if any(label in normalized for label in excluded_total_labels):
                continue
            if not any(label in normalized for label in total_labels):
                continue
            matches = self._money_matches(line)
            if matches:
                amount = matches[-1][0]
                amount_source = "labeled_total"
                break

        if amount == 0:
            candidates: list[float] = []
            for line in lines:
                normalized = line.lower()
                if any(label in normalized for label in excluded_total_labels):
                    continue
                candidates.extend(value for value, _span in self._money_matches(line))
            amount = max(candidates) if candidates else 0.0
            amount_source = "largest_currency_value" if amount else None

        date_match = (
            re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
            or re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", text)
        )
        parsed_date = None
        if date_match:
            groups = date_match.groups()
            if len(groups[0]) == 4:
                parsed_date = f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
            else:
                parsed_date = f"{groups[2]}-{int(groups[0]):02d}-{int(groups[1]):02d}"

        merchant = next(
            (
                line
                for line in lines
                if not self._money_matches(line)
                and not re.search(r"\b(20\d{2}|\d{1,2}[-/]\d{1,2})\b", line)
                and len(line) > 2
            ),
            "Receipt",
        )
        category = self._categorize_receipt_text(" ".join([merchant, *lines]))
        return {
            "merchant": merchant[:160],
            "amount": amount,
            "currency": payload.get("currency") or "USD",
            "date": parsed_date,
            "items": self._extract_items_fallback(lines),
            "category": category,
            "confidence": 0.35 if amount else 0.1,
            "amountSource": amount_source,
        }

    def _fallback(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task == "extract_receipt":
            return self._extract_receipt_fallback(payload)
        if task == "categorize_transaction":
            description = f"{payload.get('merchant', '')} {payload.get('description', '')}".lower()
            if any(word in description for word in ["coffee", "restaurant", "food", "grocery"]):
                category = "Food & Drinks"
            elif any(word in description for word in ["salary", "payroll"]):
                category = "Income"
            elif any(word in description for word in ["uber", "fuel", "metro", "train"]):
                category = "Transport"
            else:
                category = "Uncategorized"
            return {"category": category, "subcategory": None, "confidence": 0.3}
        if task == "generate_insights":
            return {
                "title": "Financial snapshot",
                "summary": "Your financial summary is ready. Add more transaction history for sharper personalized advice.",
                "recommendations": ["Review top categories weekly.", "Keep emergency savings separate from spending cash."],
            }
        if task == "chat":
            return {
                "message": "I can help analyze spending, budgets, and savings goals once your account data is synced."
            }
        return {"summary": "AI response unavailable. Exact financial calculations were completed by the backend."}

    def _parse_json(self, raw: str) -> Optional[dict[str, Any]]:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _extract_text(self, response: dict[str, Any]) -> str:
        for key in ("response", "result", "text", "output", "answer"):
            value = response.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = self._extract_text(value)
                if nested:
                    return nested
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
        return json.dumps(response)

    def generate_json(self, task: str, payload: dict[str, Any], schema_hint: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return self._fallback(task, payload)

        prompt = {
            "task": task,
            "instructions": [
                "Return valid JSON only.",
                "Do not invent transactions or exact calculations.",
                "Use only the provided financial data.",
            ],
            "schema": schema_hint,
            "data": payload,
        }
        request_payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are a personal finance advisor. JSON only for structured tasks."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
            "temperature": 0,
        }
        if self.provider == "groq":
            request_payload["response_format"] = {"type": "json_object"}
        if self.provider == "cloudflare" and self.account_id:
            request_payload["account_id"] = self.account_id

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                decoded = response.read().decode()
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("%s LLM request failed for %s: %s", self.provider.title(), task, exc)
            return self._fallback(task, payload)

        parsed_response = self._parse_json(decoded)
        if not parsed_response:
            return self._fallback(task, payload)

        raw_text = self._extract_text(parsed_response)
        parsed_json = self._parse_json(raw_text)
        return parsed_json or self._fallback(task, payload)


llm_service = CloudflareLLMService()

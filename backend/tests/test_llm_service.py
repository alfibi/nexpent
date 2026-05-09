import json

from services import cloudflareLLMService as llm_module
from services.cloudflareLLMService import CloudflareLLMService


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_groq_config_takes_priority_over_cloudflare(monkeypatch):
    monkeypatch.setattr(llm_module, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(llm_module, "GROQ_LLM_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
    monkeypatch.setattr(llm_module, "GROQ_MODEL_NAME", "llama-3.3-70b-versatile")
    monkeypatch.setattr(llm_module, "CLOUDFLARE_LLM_ENDPOINT", "https://cloudflare.example")
    monkeypatch.setattr(llm_module, "CLOUDFLARE_LLM_API_KEY", "cloudflare-key")
    monkeypatch.setattr(llm_module, "CLOUDFLARE_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(llm_module, "CLOUDFLARE_MODEL_NAME", "@cf/model")

    service = CloudflareLLMService()

    assert service.provider == "groq"
    assert service.endpoint == "https://api.groq.com/openai/v1/chat/completions"
    assert service.api_key == "groq-key"
    assert service.account_id is None
    assert service.model_name == "llama-3.3-70b-versatile"


def test_groq_request_uses_openai_compatible_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm_module, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(llm_module, "GROQ_LLM_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
    monkeypatch.setattr(llm_module, "GROQ_MODEL_NAME", "llama-3.3-70b-versatile")

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode())
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "message": "Trim dining spend by 10% this month.",
                                    "suggestedActions": ["Set a weekly food budget."],
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fake_urlopen)

    result = CloudflareLLMService().generate_json(
        "chat",
        {"question": "What should I do?", "financial_context": {"expenses": 500}},
        {"message": "string", "suggestedActions": ["string"]},
    )

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["timeout"] == 20
    assert captured["headers"]["Authorization"] == "Bearer groq-key"
    assert captured["body"]["model"] == "llama-3.3-70b-versatile"
    assert "account_id" not in captured["body"]
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert result == {
        "message": "Trim dining spend by 10% this month.",
        "suggestedActions": ["Set a weekly food budget."],
    }


def test_receipt_fallback_ignores_ids_dates_and_cash_change():
    text = """Coffee-Shop
Lorem ipsum 258
City Index - 02025
Tel.: +456-468-987-02
Store: 25896 02-05-2023 11:20 AM
Server: NY 58/8
Survey code: 0000-2555-2588-4545-69
Name Qty Price
Lorem ipsum 1 $21.00
Lorem ipsum dolor sit 1 $19.00
Lorem ipsum 1 $15.00
Price $55.00
CASH $100.00
CHANGE $45.00
THANK YOU
modif.ai"""

    result = CloudflareLLMService()._extract_receipt_fallback({"cleaned_text": text, "currency": "USD"})

    assert result["merchant"] == "Coffee-Shop"
    assert result["amount"] == 55.0
    assert result["category"] == "Food & Drinks"
    assert result["items"] == [
        {"name": "Lorem ipsum", "quantity": 1, "totalPrice": 21.0},
        {"name": "Lorem ipsum dolor sit", "quantity": 1, "totalPrice": 19.0},
        {"name": "Lorem ipsum", "quantity": 1, "totalPrice": 15.0},
    ]

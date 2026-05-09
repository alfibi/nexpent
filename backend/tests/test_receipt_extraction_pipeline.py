import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./backend/tests/test_moneyhub_receipt_pipeline.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-receipt-pipeline")

import pytest
from fastapi import HTTPException

from receipt_extraction.llm import LLMConfig, PROMPT_TEMPLATE, validate_receipt_json
from receipt_extraction.ocr import OCRDependencyError, OCRDocument, OCRTextBlock
from receipt_extraction.parser import ReceiptOCRParser
from routers import receipts


def test_receipt_parser_preserves_line_structure():
    document = OCRDocument(
        image_path="receipt.jpg",
        raw_result={},
        blocks=[
            OCRTextBlock("Walmart", [[0, 0], [120, 0], [120, 12], [0, 12]], 0.98),
            OCRTextBlock("Milk", [[0, 30], [50, 30], [50, 42], [0, 42]], 0.96),
            OCRTextBlock("$5.00", [[150, 30], [190, 30], [190, 42], [150, 42]], 0.95),
            OCRTextBlock("Total $5.00", [[0, 80], [190, 80], [190, 92], [0, 92]], 0.97),
        ],
    )

    parsed = ReceiptOCRParser().parse(document)

    assert parsed.text.splitlines() == ["Walmart", "Milk $5.00", "Total $5.00"]


def test_llm_receipt_json_validation_normalizes_values():
    payload = validate_receipt_json(
        {
            "merchant": "Walmart",
            "date": "04/21/2026",
            "total": "$45.67",
            "tax": "3.20",
            "currency": "usd",
            "items": [{"name": "Milk", "price": "5.00"}],
        }
    )

    assert payload == {
        "merchant": "Walmart",
        "date": "2026-04-21",
        "total": 45.67,
        "tax": 3.2,
        "currency": "USD",
        "items": [{"name": "Milk", "price": 5.0}],
    }


def test_prompt_contains_required_receipt_text_slot():
    prompt = PROMPT_TEMPLATE.format(ocr_text="Store\nTotal $12.34")

    assert "You are a financial data extraction AI." in prompt
    assert "Return ONLY valid JSON" in prompt
    assert "Receipt Text:\nStore\nTotal $12.34" in prompt


def test_receipt_llm_config_prefers_groq(monkeypatch):
    monkeypatch.delenv("RECEIPT_LLM_ENDPOINT", raising=False)
    monkeypatch.delenv("RECEIPT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_LLM_ENDPOINT", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GROQ_MODEL_NAME", "llama-3.3-70b-versatile")

    config = LLMConfig.from_env()

    assert config.endpoint == "https://api.groq.com/openai/v1/chat/completions"
    assert config.api_key == "groq-key"
    assert config.model == "llama-3.3-70b-versatile"
    assert config.mode == "openai"


def test_upload_ocr_helper_uses_paddle_parser_for_images(monkeypatch, tmp_path):
    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"fake image")

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def extract(self, image_path, preprocess=False):
            assert str(image_path).endswith("receipt.png")
            assert preprocess is False
            return OCRDocument(
                image_path=str(image_path),
                raw_result={},
                blocks=[
                    OCRTextBlock("Corner Store", [[0, 0], [120, 0], [120, 12], [0, 12]], 0.98),
                    OCRTextBlock("Total", [[0, 30], [50, 30], [50, 42], [0, 42]], 0.96),
                    OCRTextBlock("$12.34", [[120, 30], [170, 30], [170, 42], [120, 42]], 0.95),
                ],
            )

    monkeypatch.setattr(receipts, "PaddleReceiptOCR", FakePaddleOCR)

    raw_text, cleaned_text = receipts._extract_ocr_text(image_path)

    assert raw_text == "Corner Store\nTotal\n$12.34"
    assert cleaned_text == "Corner Store\nTotal $12.34"


def test_upload_ocr_helper_uses_local_fallback_when_paddle_missing(monkeypatch, tmp_path):
    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"fake image")

    class MissingPaddleOCR:
        def __init__(self, **kwargs):
            pass

        def extract(self, image_path, preprocess=False):
            raise OCRDependencyError("PaddleOCR is not installed.")

    class LocalFallbackOCR:
        def extract_text(self, image_path):
            return "Corner Store\nTotal $12.34"

    monkeypatch.setattr(receipts, "PaddleReceiptOCR", MissingPaddleOCR)
    monkeypatch.setattr(receipts, "get_ocr_provider", lambda: LocalFallbackOCR())

    raw_text, cleaned_text = receipts._extract_ocr_text(image_path)

    assert raw_text == "Corner Store\nTotal $12.34"
    assert cleaned_text == "Corner Store\nTotal $12.34"


def test_upload_ocr_helper_errors_when_no_ocr_engine_reads_text(monkeypatch, tmp_path):
    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"fake image")

    class MissingPaddleOCR:
        def __init__(self, **kwargs):
            pass

        def extract(self, image_path, preprocess=False):
            raise OCRDependencyError("PaddleOCR is not installed.")

    class EmptyFallbackOCR:
        def extract_text(self, image_path):
            return ""

    monkeypatch.setattr(receipts, "PaddleReceiptOCR", MissingPaddleOCR)
    monkeypatch.setattr(receipts, "get_ocr_provider", lambda: EmptyFallbackOCR())

    with pytest.raises(HTTPException) as exc:
        receipts._extract_ocr_text(image_path)

    assert exc.value.status_code == 503
    assert "paddleocr and paddlepaddle" in exc.value.detail


def test_receipt_extraction_normalizes_total_and_item_price():
    normalized = receipts._normalize_extracted_receipt(
        {
            "merchant": "Corner Store",
            "total": "12.34",
            "currency": None,
            "items": [{"name": "Milk", "price": "4.99"}],
        },
        "USD",
    )

    assert normalized["amount"] == "12.34"
    assert normalized["currency"] == "USD"
    assert normalized["items"] == [
        {
            "name": "Milk",
            "quantity": 1,
            "unitPrice": None,
            "totalPrice": "4.99",
            "category": None,
        }
    ]


def test_receipt_extraction_prefers_ocr_labeled_total_over_bad_ai_amount():
    merged = receipts._merge_ai_and_ocr_extraction(
        {
            "merchant": "Coffee-Shop",
            "amount": 25896,
            "currency": "USD",
            "items": [{"name": "City Index", "totalPrice": 2025}],
            "category": "Food & Drinks",
        },
        {
            "merchant": "Coffee-Shop",
            "amount": 55,
            "currency": "USD",
            "date": "2023-02-05",
            "items": [{"name": "Lorem ipsum", "totalPrice": 21}],
            "category": "Food & Drinks",
            "amountSource": "labeled_total",
        },
        "USD",
    )

    assert merged["amount"] == 55
    assert merged["merchant"] == "Coffee-Shop"

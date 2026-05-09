import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from config import RECEIPT_UPLOAD_DIR
from models import User
from oauth2 import get_current_user
from receipt_extraction.llm import LLMConfigurationError, LLMResponseError
from receipt_extraction.main import ReceiptExtractionError, ReceiptExtractionPipeline, ReceiptPipelineResult
from receipt_extraction.ocr import OCRDependencyError
from services.cloudflareLLMService import llm_service

router = APIRouter(tags=["receipt-extraction"])

_pipeline: ReceiptExtractionPipeline | None = None


def _get_pipeline() -> ReceiptExtractionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ReceiptExtractionPipeline()
    return _pipeline


@router.post("/extract-receipt")
async def extract_receipt_endpoint(
    file: UploadFile = File(...),
    preprocess: bool = Form(False),
    include_ocr: bool = Form(False),
    current_user: User = Depends(get_current_user),
):
    """Upload a receipt image and return validated structured expense JSON."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="Upload a receipt image file.")

    RECEIPT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    image_path = RECEIPT_UPLOAD_DIR / f"extract_{uuid.uuid4().hex}{extension}"
    with image_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = await _get_pipeline().aextract(image_path, preprocess=preprocess, return_ocr=include_ocr)
    except OCRDependencyError as exc:
        try:
            from routers.receipts import _extract_ocr_text, _extract_structured_receipt

            raw_text, cleaned_text = _extract_ocr_text(image_path)
            receipt = _extract_structured_receipt(cleaned_text, "US", "USD")
        except HTTPException:
            raise
        except Exception as fallback_exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from fallback_exc
        if include_ocr:
            return {"receipt": receipt, "ocr": {"image_path": str(image_path), "text": raw_text, "cleaned_text": cleaned_text}}
        return receipt
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (ReceiptExtractionError, LLMResponseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if isinstance(result, ReceiptPipelineResult):
        return {
            "receipt": result.receipt,
            "ocr": result.ocr,
        }
    return result

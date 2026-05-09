from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from receipt_extraction.llm import ReceiptLLMClient
from receipt_extraction.ocr import OCRDocument, PaddleReceiptOCR
from receipt_extraction.parser import ParsedReceiptText, ReceiptOCRParser


class ReceiptExtractionError(RuntimeError):
    """Raised when the receipt extraction pipeline cannot produce structured data."""


@dataclass(frozen=True)
class ReceiptPipelineResult:
    receipt: dict[str, Any]
    ocr: dict[str, Any]


class ReceiptExtractionPipeline:
    """Image -> PaddleOCR -> cleaned receipt text -> LLM -> validated JSON."""

    def __init__(
        self,
        *,
        ocr: Optional[PaddleReceiptOCR] = None,
        parser: Optional[ReceiptOCRParser] = None,
        llm: Optional[ReceiptLLMClient] = None,
    ) -> None:
        self.ocr = ocr or PaddleReceiptOCR(lang="en")
        self.parser = parser or ReceiptOCRParser()
        self.llm = llm or ReceiptLLMClient()

    def extract(
        self,
        image_path: str | Path,
        *,
        preprocess: bool = False,
        return_ocr: bool = False,
    ) -> dict[str, Any] | ReceiptPipelineResult:
        document = self.ocr.extract(image_path, preprocess=preprocess)
        parsed = self.parser.parse(document)
        if not parsed.text.strip():
            raise ReceiptExtractionError("OCR returned no text for this receipt image.")
        receipt = self.llm.extract(parsed.text)
        if return_ocr:
            return ReceiptPipelineResult(receipt=receipt, ocr=self._ocr_payload(document, parsed))
        return receipt

    async def aextract(
        self,
        image_path: str | Path,
        *,
        preprocess: bool = False,
        return_ocr: bool = False,
    ) -> dict[str, Any] | ReceiptPipelineResult:
        document = await asyncio.to_thread(self.ocr.extract, image_path, preprocess=preprocess)
        parsed = self.parser.parse(document)
        if not parsed.text.strip():
            raise ReceiptExtractionError("OCR returned no text for this receipt image.")
        receipt = await self.llm.aextract(parsed.text)
        if return_ocr:
            return ReceiptPipelineResult(receipt=receipt, ocr=self._ocr_payload(document, parsed))
        return receipt

    def extract_batch(
        self,
        image_paths: Iterable[str | Path],
        *,
        preprocess: bool = False,
        continue_on_error: bool = False,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for image_path in image_paths:
            try:
                results.append(self.extract(image_path, preprocess=preprocess))  # type: ignore[arg-type]
            except Exception as exc:
                if not continue_on_error:
                    raise
                results.append({"error": str(exc), "image_path": str(image_path)})
        return results

    async def aextract_batch(
        self,
        image_paths: Iterable[str | Path],
        *,
        preprocess: bool = False,
        continue_on_error: bool = False,
    ) -> list[dict[str, Any]]:
        tasks = [self.aextract(path, preprocess=preprocess) for path in image_paths]
        gathered = await asyncio.gather(*tasks, return_exceptions=continue_on_error)
        results: list[dict[str, Any]] = []
        for path, result in zip(image_paths, gathered):
            if isinstance(result, Exception):
                results.append({"error": str(result), "image_path": str(path)})
            else:
                results.append(result)  # type: ignore[arg-type]
        return results

    def _ocr_payload(self, document: OCRDocument, parsed: ParsedReceiptText) -> dict[str, Any]:
        return {
            "raw": document.to_dict(),
            "parsed": parsed.to_dict(),
        }


def extract_receipt(image_path: str | Path, *, preprocess: bool = False) -> dict[str, Any]:
    return ReceiptExtractionPipeline().extract(image_path, preprocess=preprocess)  # type: ignore[return-value]


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Extract structured receipt data from an image.")
    parser.add_argument("image_path", help="Path to a receipt image")
    parser.add_argument("--preprocess", action="store_true", help="Apply grayscale and threshold preprocessing before OCR")
    args = parser.parse_args()

    result = extract_receipt(args.image_path, preprocess=args.preprocess)
    print(json.dumps(result, indent=2, ensure_ascii=False))

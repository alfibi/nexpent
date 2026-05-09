from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


class OCRDependencyError(RuntimeError):
    """Raised when PaddleOCR or optional image preprocessing dependencies are missing."""


@dataclass(frozen=True)
class OCRTextBlock:
    text: str
    bbox: list[list[float]]
    confidence: float

    @property
    def x_min(self) -> float:
        return min(point[0] for point in self.bbox) if self.bbox else 0.0

    @property
    def y_center(self) -> float:
        if not self.bbox:
            return 0.0
        return sum(point[1] for point in self.bbox) / len(self.bbox)


@dataclass(frozen=True)
class OCRDocument:
    image_path: str
    blocks: list[OCRTextBlock]
    raw_result: Any

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "text": self.text,
            "blocks": [
                {
                    "text": block.text,
                    "bbox": block.bbox,
                    "confidence": block.confidence,
                }
                for block in self.blocks
            ],
        }


class PaddleReceiptOCR:
    """PaddleOCR wrapper for receipt images.

    The current PaddleOCR 3.x API uses ``PaddleOCR(lang="en").predict(path)`` and
    exposes JSON-ready fields such as ``rec_texts``, ``rec_scores`` and
    ``rec_polys``. This class also supports the older 2.x ``ocr`` return shape
    so upgrades do not break the receipt pipeline abruptly.
    """

    def __init__(
        self,
        *,
        lang: str = "en",
        device: Optional[str] = None,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_textline_orientation: bool = False,
        extra_options: Optional[dict[str, Any]] = None,
    ) -> None:
        self.lang = lang
        self.device = device
        self.options = {
            "lang": lang,
            "use_doc_orientation_classify": use_doc_orientation_classify,
            "use_doc_unwarping": use_doc_unwarping,
            "use_textline_orientation": use_textline_orientation,
            **(extra_options or {}),
        }
        if device:
            self.options["device"] = device
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def _build_engine(self):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCRDependencyError(
                "PaddleOCR is not installed. Install backend requirements, including paddleocr and paddlepaddle."
            ) from exc

        try:
            return PaddleOCR(**self.options)
        except TypeError:
            legacy_options = {"lang": self.lang, "use_angle_cls": True}
            if self.device:
                legacy_options["device"] = self.device
            return PaddleOCR(**legacy_options)

    def extract(
        self,
        image_path: str | Path,
        *,
        preprocess: bool = False,
        grayscale: bool = True,
        threshold: bool = True,
    ) -> OCRDocument:
        source_path = Path(image_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Receipt image not found: {source_path}")

        work_path = source_path
        temp_path: Optional[Path] = None
        if preprocess:
            temp_path = self._preprocess_image(source_path, grayscale=grayscale, threshold=threshold)
            work_path = temp_path

        try:
            raw_result = self._predict(work_path)
            blocks = self._normalize_result(raw_result)
            return OCRDocument(image_path=str(source_path), blocks=blocks, raw_result=raw_result)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def extract_batch(
        self,
        image_paths: Iterable[str | Path],
        *,
        preprocess: bool = False,
        continue_on_error: bool = False,
    ) -> list[OCRDocument]:
        documents: list[OCRDocument] = []
        for image_path in image_paths:
            try:
                documents.append(self.extract(image_path, preprocess=preprocess))
            except Exception:
                if not continue_on_error:
                    raise
        return documents

    def _preprocess_image(self, image_path: Path, *, grayscale: bool, threshold: bool) -> Path:
        try:
            import cv2
        except ImportError as exc:
            raise OCRDependencyError(
                "Image preprocessing requires opencv-python-headless. Install backend requirements first."
            ) from exc

        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Could not read receipt image: {image_path}")
        if grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if threshold:
            image = cv2.adaptiveThreshold(
                image,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9,
            )

        suffix = image_path.suffix if image_path.suffix.lower() in {".png", ".jpg", ".jpeg"} else ".png"
        with tempfile.NamedTemporaryFile(prefix="receipt_ocr_", suffix=suffix, delete=False) as tmp:
            temp_path = Path(tmp.name)
        cv2.imwrite(str(temp_path), image)
        return temp_path

    def _predict(self, image_path: Path):
        engine = self.engine
        if hasattr(engine, "predict"):
            return engine.predict(str(image_path))
        try:
            return engine.ocr(str(image_path), cls=True)
        except TypeError:
            return engine.ocr(str(image_path))

    def _normalize_result(self, raw_result: Any) -> list[OCRTextBlock]:
        blocks: list[OCRTextBlock] = []
        pages = raw_result if isinstance(raw_result, list) else [raw_result]
        for page in pages:
            blocks.extend(self._normalize_page(page))
        return sorted(blocks, key=lambda block: (round(block.y_center / 10), block.x_min))

    def _normalize_page(self, page: Any) -> list[OCRTextBlock]:
        payload = self._page_to_payload(page)
        if payload:
            return self._normalize_payload(payload)
        return self._normalize_legacy(page)

    def _page_to_payload(self, page: Any) -> Optional[dict[str, Any]]:
        json_payload = getattr(page, "json", None)
        if callable(json_payload):
            json_payload = json_payload()
        if isinstance(json_payload, dict):
            payload = json_payload.get("res", json_payload)
            return payload.get("prunedResult", payload) if isinstance(payload, dict) else None
        if isinstance(page, dict):
            payload = page.get("res", page)
            return payload.get("prunedResult", payload) if isinstance(payload, dict) else None
        return None

    def _normalize_payload(self, payload: dict[str, Any]) -> list[OCRTextBlock]:
        texts = payload.get("rec_texts") or payload.get("texts") or []
        scores = payload.get("rec_scores") or payload.get("scores") or []
        boxes = payload.get("rec_polys") or payload.get("rec_boxes") or payload.get("dt_polys") or []

        blocks: list[OCRTextBlock] = []
        for index, text in enumerate(texts):
            cleaned = str(text or "").strip()
            if not cleaned:
                continue
            box = self._coerce_bbox(boxes[index] if index < len(boxes) else [])
            score = self._coerce_score(scores[index] if index < len(scores) else None)
            blocks.append(OCRTextBlock(text=cleaned, bbox=box, confidence=score))
        return blocks

    def _normalize_legacy(self, page: Any) -> list[OCRTextBlock]:
        rows = page
        if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list):
            rows = rows[0]
        blocks: list[OCRTextBlock] = []
        if not isinstance(rows, list):
            return blocks
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            bbox = self._coerce_bbox(row[0])
            text_value = row[1]
            if isinstance(text_value, (list, tuple)) and text_value:
                text = str(text_value[0] or "").strip()
                score = self._coerce_score(text_value[1] if len(text_value) > 1 else None)
            else:
                text = str(text_value or "").strip()
                score = 0.0
            if text:
                blocks.append(OCRTextBlock(text=text, bbox=bbox, confidence=score))
        return blocks

    def _coerce_bbox(self, value: Any) -> list[list[float]]:
        try:
            if hasattr(value, "tolist"):
                value = value.tolist()
            if len(value) == 4 and all(isinstance(point, (int, float)) for point in value):
                x_min, y_min, x_max, y_max = value
                return [
                    [float(x_min), float(y_min)],
                    [float(x_max), float(y_min)],
                    [float(x_max), float(y_max)],
                    [float(x_min), float(y_max)],
                ]
            return [[float(point[0]), float(point[1])] for point in value]
        except (TypeError, ValueError, IndexError):
            return []

    def _coerce_score(self, value: Any) -> float:
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return 0.0

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from receipt_extraction.ocr import OCRDocument, OCRTextBlock


@dataclass(frozen=True)
class OCRLine:
    text: str
    bbox: list[list[float]]
    confidence: float


@dataclass(frozen=True)
class ParsedReceiptText:
    text: str
    markdown: str
    lines: list[OCRLine]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "markdown": self.markdown,
            "lines": [
                {
                    "text": line.text,
                    "bbox": line.bbox,
                    "confidence": line.confidence,
                }
                for line in self.lines
            ],
        }


class ReceiptOCRParser:
    """Clean PaddleOCR blocks into LLM-ready receipt text while preserving layout."""

    # Keep characters that matter for international receipts: currency, dates,
    # decimal separators, tax IDs, percentages and item names.
    _noise_pattern = re.compile(r"[^A-Za-z0-9\s.,:;#/@&%+\-_*()$€£¥₹₩₽₺₪฿₫₱]")
    _space_pattern = re.compile(r"[ \t]+")

    def parse(self, document: OCRDocument) -> ParsedReceiptText:
        lines = self._blocks_to_lines(document.blocks)
        text = "\n".join(line.text for line in lines if line.text)
        markdown = self.to_markdown(lines)
        return ParsedReceiptText(text=text, markdown=markdown, lines=lines)

    def to_text(self, document: OCRDocument) -> str:
        return self.parse(document).text

    def to_markdown(self, lines: list[OCRLine]) -> str:
        if not lines:
            return ""
        body = "\n".join(f"- {line.text}" for line in lines if line.text)
        return f"## Receipt OCR\n{body}"

    def _blocks_to_lines(self, blocks: list[OCRTextBlock]) -> list[OCRLine]:
        if not blocks:
            return []

        sorted_blocks = sorted(blocks, key=lambda block: (block.y_center, block.x_min))
        heights = [self._height(block.bbox) for block in sorted_blocks if self._height(block.bbox) > 0]
        y_tolerance = max(8.0, (sum(heights) / len(heights) if heights else 14.0) * 0.65)

        grouped: list[list[OCRTextBlock]] = []
        for block in sorted_blocks:
            if not grouped:
                grouped.append([block])
                continue
            current_line = grouped[-1]
            current_y = sum(item.y_center for item in current_line) / len(current_line)
            if abs(block.y_center - current_y) <= y_tolerance:
                current_line.append(block)
            else:
                grouped.append([block])

        lines: list[OCRLine] = []
        for group in grouped:
            group = sorted(group, key=lambda block: block.x_min)
            text = self._clean_text(" ".join(block.text for block in group))
            if not text:
                continue
            lines.append(
                OCRLine(
                    text=text,
                    bbox=self._union_bbox([block.bbox for block in group]),
                    confidence=round(sum(block.confidence for block in group) / len(group), 4),
                )
            )
        return self._merge_broken_lines(lines)

    def _clean_text(self, value: str) -> str:
        cleaned = self._noise_pattern.sub(" ", value)
        cleaned = self._space_pattern.sub(" ", cleaned)
        cleaned = re.sub(r"\s+([,.:;%])", r"\1", cleaned)
        cleaned = re.sub(r"([$€£¥₹₩₽₺₪฿₫₱])\s+", r"\1", cleaned)
        return cleaned.strip(" -_")

    def _merge_broken_lines(self, lines: list[OCRLine]) -> list[OCRLine]:
        merged: list[OCRLine] = []
        amount_pattern = re.compile(r"([$€£¥₹₩₽₺₪฿₫₱]?\s*\d+[,.]\d{2})$")
        amount_only_pattern = re.compile(r"^[$€£¥₹₩₽₺₪฿₫₱]?\s*\d+[,.]\d{2}$")
        label_pattern = re.compile(r"^(subtotal|tax|total|amount|balance|change|cash|card)\b", re.IGNORECASE)

        for line in lines:
            if (
                merged
                and amount_pattern.search(line.text)
                and amount_only_pattern.fullmatch(line.text)
                and not label_pattern.search(line.text)
                and not amount_pattern.search(merged[-1].text)
            ):
                previous = merged.pop()
                merged.append(
                    OCRLine(
                        text=self._clean_text(f"{previous.text} {line.text}"),
                        bbox=self._union_bbox([previous.bbox, line.bbox]),
                        confidence=round((previous.confidence + line.confidence) / 2, 4),
                    )
                )
            else:
                merged.append(line)
        return merged

    def _height(self, bbox: list[list[float]]) -> float:
        if not bbox:
            return 0.0
        ys = [point[1] for point in bbox]
        return max(ys) - min(ys)

    def _union_bbox(self, boxes: list[list[list[float]]]) -> list[list[float]]:
        points = [point for box in boxes for point in box]
        if not points:
            return []
        x_min = min(point[0] for point in points)
        y_min = min(point[1] for point in points)
        x_max = max(point[0] for point in points)
        y_max = max(point[1] for point in points)
        return [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]]

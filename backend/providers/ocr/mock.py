from pathlib import Path
import shutil
import subprocess

from providers.ocr.base import OCRProvider


class MockOCRProvider(OCRProvider):
    provider_name = "mock"

    def extract_text(self, image_path: str) -> str:
        path = Path(image_path)
        if path.suffix.lower() in {".txt", ".csv"}:
            return path.read_text(errors="ignore")[:8000]
        if path.suffix.lower() == ".pdf" and shutil.which("pdftotext"):
            try:
                result = subprocess.run(
                    ["pdftotext", "-layout", str(path), "-"],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=15,
                )
                return result.stdout[:8000]
            except (OSError, subprocess.SubprocessError):
                return ""
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and shutil.which("tesseract"):
            try:
                result = subprocess.run(
                    ["tesseract", str(path), "stdout"],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=20,
                )
                return result.stdout[:8000]
            except (OSError, subprocess.SubprocessError):
                return ""
        return ""


def get_ocr_provider() -> OCRProvider:
    return MockOCRProvider()

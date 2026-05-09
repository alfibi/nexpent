from typing import Protocol


class OCRProvider(Protocol):
    provider_name: str

    def extract_text(self, image_path: str) -> str:
        ...


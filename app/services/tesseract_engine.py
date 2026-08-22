# filepath: app/services/tesseract_engine.py
"""
In-memory Tesseract OCR engine wrapper.

No bytes are ever written to disk. The flow is:
    upload bytes -> PIL.Image.open(BytesIO(bytes)) -> pytesseract.image_to_data / image_to_string

This keeps us disk-free, which is a hard requirement.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
import pytesseract

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class OcrOutcome:
    """Outcome of a single OCR run."""

    text: str
    confidence: float  # normalized to [0.0, 1.0]


class TesseractEngineError(Exception):
    """Raised when OCR cannot be performed on the supplied bytes."""


class TesseractEngine:
    """Thin wrapper around pytesseract with sane defaults and config injection."""

    def __init__(
        self,
        *,
        lang: str = "eng",
        oem: str | None = None,
        psm: str | None = None,
        cmd: str | None = None,
    ) -> None:
        self.lang = lang
        self.oem = oem
        self.psm = psm
        if cmd:
            # Allow operator to point at a non-standard binary.
            pytesseract.pytesseract.tesseract_cmd = cmd

    def _build_config(self) -> str:
        """Compose Tesseract's --oem/--psm config string."""
        parts: list[str] = []
        if self.oem:
            parts.append(f"--oem {self.oem}")
        if self.psm:
            parts.append(f"--psm {self.psm}")
        return " ".join(parts)

    @staticmethod
    def _normalize_confidence(mean_conf: float | None) -> float:
        """Tesseract returns 0..100 (with -1 for n/a). Clamp + normalize to 0..1."""
        if mean_conf is None or mean_conf < 0:
            return 0.0
        return round(mean_conf / 100.0, 4)

    def extract(self, image_bytes: bytes) -> OcrOutcome:
        """Run OCR on the given bytes. Raises TesseractEngineError on failure."""
        try:
            image = Image.open(io.BytesIO(image_bytes))
        except UnidentifiedImageError as exc:
            raise TesseractEngineError(
                "Cannot decode image: unsupported format or corrupt bytes."
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise TesseractEngineError(f"Failed to decode image: {exc}") from exc

        # Some PIL modes confuse Tesseract; convert to RGB to be safe.
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        config = self._build_config()

        try:
            text = pytesseract.image_to_string(image, lang=self.lang, config=config).strip()
            data = pytesseract.image_to_data(
                image, lang=self.lang, config=config, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise TesseractEngineError(
                "Tesseract binary not found on PATH. Install `tesseract-ocr`."
            ) from exc
        except Exception as exc:
            raise TesseractEngineError(f"Tesseract failed: {exc}") from exc

        # Average confidence over words that actually have one.
        confs = [c for c in data.get("conf", []) if isinstance(c, (int, float)) and c >= 0]
        mean_conf = sum(confs) / len(confs) if confs else None
        confidence = self._normalize_confidence(mean_conf)

        logger.info(
            "tesseract ok lang=%s words=%d conf=%.2f", self.lang, len(confs), confidence
        )
        return OcrOutcome(text=text, confidence=confidence)

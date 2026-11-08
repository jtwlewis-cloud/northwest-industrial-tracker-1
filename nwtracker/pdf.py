"""Download and extract text from PDF marketing brochures (cached on disk)."""
from __future__ import annotations

import hashlib
import io
import logging
import time

from . import config
from .http import Fetcher

log = logging.getLogger(__name__)
CACHE_TTL_DAYS = 7


def _cache_path(url: str):
    return config.CACHE_DIR / "pdf" / (hashlib.sha1(url.encode()).hexdigest() + ".txt")


def pdf_bytes_to_text(data: bytes, max_pages: int = 12) -> str:
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(doc[i].get_text() for i in range(min(len(doc), max_pages)))
    except Exception as e:
        log.debug("PyMuPDF failed (%s), trying pdfplumber", e)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
    except Exception as e:
        log.debug("pdfplumber failed: %s", e)
    return ""


def brochure_text(fetcher: Fetcher, url: str) -> str:
    cp = _cache_path(url)
    if cp.exists() and (time.time() - cp.stat().st_mtime) < CACHE_TTL_DAYS * 86400:
        return cp.read_text(encoding="utf-8")
    r = fetcher.get(url, stream=True)
    data = b""
    for chunk in r.iter_content(65536):
        data += chunk
        if len(data) > config.MAX_PDF_BYTES:
            raise ValueError(f"brochure larger than {config.MAX_PDF_BYTES // 1_000_000} MB: {url}")
    if not data.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {url}")
    text = pdf_bytes_to_text(data)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(text, encoding="utf-8")
    return text

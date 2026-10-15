"""Defensive PDF inspection. We never render or execute the file; we only parse its structure with pypdf and refuse
anything that is not a plain, unencrypted, script-free document."""
import io
import re
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PyPdfError


class InvalidPdf(ValueError):
    pass


@dataclass(frozen=True)
class PdfInfo:
    pages: int


_ACTIVE = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|OpenAction|AA|RichMedia|XFA|SubmitForm)(?![A-Za-z0-9])")


def sniff_pdf(data: bytes, *, max_pages: int) -> PdfInfo:
    if not data.startswith(b"%PDF-"):
        raise InvalidPdf("File is not a PDF")
    if b"%%EOF" not in data[-2048:]:
        raise InvalidPdf("PDF appears truncated or malformed")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise InvalidPdf("Encrypted or password-protected PDFs are not allowed")
        pages = len(reader.pages)
        root: Any = reader.trailer["/Root"]
        names: Any = root.get("/Names") or {}
        if any(k in root for k in ("/OpenAction", "/AA", "/AcroForm")) or "/JavaScript" in names or "/EmbeddedFiles" in names:
            raise InvalidPdf("PDFs with scripts, forms or embedded files are not allowed")
    except InvalidPdf:
        raise
    except (PyPdfError, KeyError, ValueError, TypeError, RecursionError, OSError) as exc:
        raise InvalidPdf("PDF could not be read") from exc
    if pages < 1:
        raise InvalidPdf("PDF has no pages")
    if pages > max_pages:
        raise InvalidPdf(f"PDF has too many pages (max {max_pages})")
    # belt and braces: raw token scan catches active content hidden in object streams the catalog check cannot see
    if _ACTIVE.search(data):
        raise InvalidPdf("PDFs with scripts, forms or embedded files are not allowed")
    return PdfInfo(pages=pages)

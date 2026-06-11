from typing import Literal
from uuid import UUID

from pydantic import BaseModel

LangCode = Literal[
    "ces",
    "dan",
    "deu",
    "ell",
    "eng",
    "fas",
    "fin",
    "fra",
    "guj",
    "heb",
    "hin",
    "ita",
    "jpn",
    "kor",
    "lit",
    "nld",
    "nor",
    "pol",
    "por",
    "ron",
    "san",
    "spa",
    "kaz",
    "rus",
]

OCREngine = Literal["tesseract", "qwen-vl", "auto"]


class OCRTaskIn(BaseModel):
    document_id: UUID  # document model ID
    lang: LangCode
    engine: OCREngine | None = None  # None or "auto" = auto-select based on config

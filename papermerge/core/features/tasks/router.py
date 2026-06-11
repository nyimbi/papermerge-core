from typing import Annotated

from fastapi import APIRouter, Security

from papermerge.core import constants, schema, utils
from papermerge.core.features.auth import get_current_user, scopes
from papermerge.core import tasks

from .schema import OCRTaskIn

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
)


@router.post("/ocr")
@utils.docstring_parameter(scope=scopes.TASK_OCR)
def start_ocr(
    ocr_task: OCRTaskIn,
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.TASK_OCR])],
):
    """Triggers OCR for specific document

    Required scope: `{scope}`

    Engine options:
    - `tesseract`: Traditional Tesseract OCR via ocrmypdf
    - `qwen-vl`: Vision-language model OCR via Ollama (requires Ollama with qwen model)
    - `auto` or omitted: Auto-select based on server configuration
    """
    kwargs = {
        "document_id": str(ocr_task.document_id),
        "lang": ocr_task.lang,
    }
    # Pass engine if explicitly specified (not "auto" or None)
    if ocr_task.engine and ocr_task.engine != "auto":
        kwargs["engine"] = ocr_task.engine

    tasks.send_task(
        constants.WORKER_OCR_DOCUMENT,
        kwargs=kwargs,
        route_name="ocr",
    )

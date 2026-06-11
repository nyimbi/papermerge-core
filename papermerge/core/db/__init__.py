import importlib
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import get_db

DBRouterAsyncSession = Annotated[AsyncSession, Depends(get_db)]

__all__ = [
    "DBRouterAsyncSession",
    "AsyncSession",
    "search_documents",
    "update_document_custom_field_values",
    "has_node_perm",
    "get_doc_ver_lang",
    "set_doc_ver_lang",
    "get_last_doc_ver",
    "get_db",
]

# All feature-module imports are deferred to break circular dependencies:
# ownership.db.orm → papermerge.core.db → {common,search,document,...} → ownership.db.orm
_LAZY = {
    "has_node_perm": ("papermerge.core.db.common", "has_node_perm"),
    "search_documents": ("papermerge.core.features.search.db.api", "search_documents"),
    "update_document_custom_field_values": (
        "papermerge.core.features.custom_fields.db.api",
        "update_document_custom_field_values",
    ),
    "get_doc_ver_lang": ("papermerge.core.features.document.db.api", "get_doc_ver_lang"),
    "set_doc_ver_lang": ("papermerge.core.features.document.db.api", "set_doc_ver_lang"),
    "get_last_doc_ver": ("papermerge.core.features.document.db.api", "get_last_doc_ver"),
}


def __getattr__(name: str):
    if name in _LAZY:
        mod_path, attr = _LAZY[name]
        mod = importlib.import_module(mod_path)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

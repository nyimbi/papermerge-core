# (c) Copyright Datacraft, 2026
"""Tests for NLP-driven tagging task."""
import pytest
import uuid
from unittest.mock import AsyncMock, patch

from papermerge.core.features.workflows.tasks.tagging import tag_task

@pytest.mark.asyncio
async def test_tag_task_success():
    """Test that tag_task correctly extracts and applies tags."""
    document_id = str(uuid.uuid4())
    initiated_by = str(uuid.uuid4())
    
    ctx = {
        "document_id": document_id,
        "initiated_by": initiated_by,
        "previous_results": {
            "classify": {
                "data": {"classification": {"assigned_type": "invoice"}}
            },
            "nlp": {
                "data": {
                    "entities": [
                        {"label": "ORG", "text": "Datacraft"},
                        {"label": "DATE", "text": "2026-01-20"}
                    ]
                }
            },
            "validate": {
                "data": {"fields": {"amount": "100.00", "items": ["item1", "item2"]}}
            }
        }
    }
    
    config = {
        "include_type": True,
        "include_vendor": True,
        "include_date": True,
        "tag_prefix": "ai:"
    }
    
    with patch("papermerge.core.db.engine.get_session") as mock_get_session, \
         patch("papermerge.core.features.nodes.db.api.assign_node_tags", new_callable=AsyncMock) as mock_assign_tags:
        
        mock_get_session.return_value.__aenter__.return_value = AsyncMock()
        
        result = await tag_task(ctx, config)
        
        assert result["success"] is True
        applied_tags = result["data"]["tagging"]["applied_tags"]
        
        # Check that all expected tags are present
        assert "ai:invoice" in applied_tags
        assert "ai:Datacraft" in applied_tags
        assert "ai:2026-01-20" in applied_tags
        assert "ai:100.00" in applied_tags
        assert "ai:item1" in applied_tags
        assert "ai:item2" in applied_tags
        
        mock_assign_tags.assert_called_once()
        # Verify tags passed to API
        call_args = mock_assign_tags.call_args
        assert set(call_args.kwargs["tags"]) == set(applied_tags)

@pytest.mark.asyncio
async def test_tag_task_prefix_and_custom_tags():
    """Test tag_task with custom tags and different prefix."""
    document_id = str(uuid.uuid4())
    
    ctx = {
        "document_id": document_id,
        "previous_results": {
            "classify": {"data": {"classification": {"assigned_type": "contract"}}}
        }
    }
    
    config = {
        "include_type": True,
        "include_vendor": False,
        "include_date": False,
        "custom_tags": ["urgent", "legal"],
        "tag_prefix": "auto_"
    }
    
    with patch("papermerge.core.db.engine.get_session"), \
         patch("papermerge.core.features.nodes.db.api.assign_node_tags", new_callable=AsyncMock):
        
        result = await tag_task(ctx, config)
        
        applied_tags = result["data"]["tagging"]["applied_tags"]
        assert "auto_contract" in applied_tags
        assert "urgent" in applied_tags
        assert "legal" in applied_tags
        assert len(applied_tags) == 3

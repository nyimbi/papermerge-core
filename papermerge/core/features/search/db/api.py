"""
Unified search function that combines search_documents and search_documents_by_type.

This module provides a single search function that:
1. Filters by custom fields when they are present in the payload
2. Determines which custom fields to include in the response based on:
   - Document types specified in category filters
   - Custom fields specified in custom field filters
3. Returns documents with custom field values (DocumentCFV) when custom fields are relevant
"""

import logging
import math
from uuid import UUID
from typing import Sequence

from datetime import datetime, timezone as dt_timezone
from sqlalchemy import select, func, and_, or_, text, String
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.document.db import orm as doc_orm
from papermerge.core.features.search.schema import TagOperator, \
    CategoryOperator, \
    OwnerOperator
from papermerge.core import orm, schema
from papermerge.core.features.search import schema as search_schema
from papermerge.core.features.search.db.orm import DocumentSearchIndex
from papermerge.core.features.custom_fields.db.orm import CustomField, \
    CustomFieldValue
from papermerge.core.features.document_types.db.orm import DocumentType
from papermerge.core.features.groups.db.orm import UserGroup
from papermerge.core.types import OwnerType, ResourceType
from papermerge.core.features.custom_fields.cf_types.registry import \
    TypeRegistry
from papermerge.core.features.document.db.orm import DocumentVersion
from papermerge.core.features.quality.db.orm import QualityAssessment
from papermerge.core.features.annotations.db.orm import DocumentAnnotation
from papermerge.core.features.exceptions.db.orm import ExceptionEvent
from papermerge.core.features.batches.db.orm import ScanBatch
from papermerge.core.features.scanning_projects.models import ScanningProjectModel

logger = logging.getLogger(__name__)


async def search_documents(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    params: search_schema.SearchQueryParams,
) -> search_schema.SearchDocumentsResponse:
    """
    Unified search function for documents.

    This function combines the functionality of the previous search_documents
    and search_documents_by_type functions into a single unified search.

    Behavior:
    - If custom_fields filters are present → filter by those custom fields
    - If category filters are present → collect custom fields from those document types
    - Response includes custom_fields metadata that is the union of:
      * All custom fields from document types in category filters
      * All custom fields referenced in custom_field filters
    - Documents are returned with their custom field values for the relevant fields

    Args:
        db_session: AsyncSession for database operations
        user_id: UUID of the current user (for access control)
        params: SearchQueryParams with filters, pagination, and sorting

    Returns:
        SearchDocumentsResponse with DocumentCFV items and custom_fields metadata
    """
    # =========================================================================
    # Collect custom fields of interest
    # =========================================================================
    custom_fields_map: dict[UUID, CustomField] = {}  # id -> CustomField (for deduplication)
    document_type_ids: list[UUID] = []

    # 1a. Get custom fields from category filters (document types)
    if params.filters and params.filters.categories:
        for cat_filter in params.filters.categories:
            for category_name in cat_filter.values:
                # Look up document type by name
                stmt = select(DocumentType).where(
                    and_(
                        DocumentType.name == category_name,
                        DocumentType.deleted_at.is_(None)
                    )
                )
                result = await db_session.execute(stmt)
                doc_type = result.scalar_one_or_none()

                if doc_type:
                    document_type_ids.append(doc_type.id)
                    # Get custom fields for this document type
                    stmt_cf = (
                        select(CustomField)
                        .join(DocumentType.custom_fields)
                        .where(DocumentType.id == doc_type.id)
                    )
                    result_cf = await db_session.execute(stmt_cf)
                    for cf in result_cf.scalars().all():
                        custom_fields_map[cf.id] = cf

    # 1b. Get custom fields from custom_field filters
    if params.filters and params.filters.custom_fields:
        for cf_filter in params.filters.custom_fields:
            # Look up custom field by name
            stmt = select(CustomField).where(
                and_(
                    CustomField.name == cf_filter.field_name,
                    CustomField.deleted_at.is_(None)
                )
            )
            result = await db_session.execute(stmt)
            cf = result.scalar_one_or_none()

            if cf and cf.id not in custom_fields_map:
                custom_fields_map[cf.id] = cf

    # Convert to list for ordered iteration
    custom_fields: list[CustomField] = list(custom_fields_map.values())

    # Determine if we should include custom fields in response
    include_custom_fields = len(custom_fields) > 0

    # Build custom fields info for response
    custom_fields_info = [
        search_schema.CustomFieldInfo(
            id=cf.id,
            name=cf.name,
            type_handler=cf.type_handler,
            config=cf.config or {}
        )
        for cf in custom_fields
    ]

    # =========================================================================
    # Build base query
    # =========================================================================
    base_query = (
        select(DocumentSearchIndex)
        .join(
            orm.Node,
            DocumentSearchIndex.document_id == orm.Node.id
        )
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id
            )
        )
    )

    # Build count query with same base structure
    count_query = (
        select(func.count(DocumentSearchIndex.document_id.distinct()))
        .select_from(DocumentSearchIndex)
        .join(
            orm.Node,
            DocumentSearchIndex.document_id == orm.Node.id
        )
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id
            )
        )
    )

    # =========================================================================
    # Apply access control
    # =========================================================================
    user_groups_subquery = select(UserGroup.group_id).where(
        UserGroup.user_id == user_id
    )

    access_filter = or_(
        and_(
            DocumentSearchIndex.owner_type == OwnerType.USER.value,
            DocumentSearchIndex.owner_id == user_id
        ),
        and_(
            DocumentSearchIndex.owner_type == OwnerType.GROUP.value,
            DocumentSearchIndex.owner_id.in_(user_groups_subquery)
        )
    )

    base_query = base_query.where(access_filter)
    count_query = count_query.where(access_filter)

    # =========================================================================
    # Apply FTS filter
    # =========================================================================
    if params.filters and params.filters.fts:
        fts_query = _build_fts_query(params.filters.fts, params.lang or 'eng')
        base_query = base_query.where(fts_query)
        count_query = count_query.where(fts_query)

    # =========================================================================
    # Step 5: Apply category filter
    # =========================================================================
    if params.filters and params.filters.categories:
        category_filter = _build_category_filter(params.filters.categories)
        base_query = base_query.where(category_filter)
        count_query = count_query.where(category_filter)

    # =========================================================================
    # Apply tag filters
    # =========================================================================
    if params.filters and params.filters.tags:
        tag_filters = _build_tag_filters(params.filters.tags)
        if tag_filters is not None:
            base_query = base_query.where(tag_filters)
            count_query = count_query.where(tag_filters)

    # =========================================================================
    # Apply custom field filters (NEW: now works regardless of document_type_id)
    # =========================================================================
    if params.filters and params.filters.custom_fields:
        for filter_spec in params.filters.custom_fields:
            # Find custom field by name in our collected custom fields
            cf = next(
                (f for f in custom_fields if f.name == filter_spec.field_name),
                None
            )

            if not cf:
                # If not found in collected fields, try to look it up
                stmt = select(CustomField).where(
                    and_(
                        CustomField.name == filter_spec.field_name,
                        CustomField.deleted_at.is_(None)
                    )
                )
                result = await db_session.execute(stmt)
                cf = result.scalar_one_or_none()

            if not cf:
                logger.warning(
                    f"Custom field '{filter_spec.field_name}' not found, skipping filter"
                )
                continue

            # Get handler and build filter
            handler = TypeRegistry.get_handler(cf.type_handler)
            cfv_alias = aliased(CustomFieldValue)
            sort_column = getattr(cfv_alias, handler.get_sort_column())
            config = handler.parse_config(cf.config or {})
            if filter_spec.value is not None:
                value = filter_spec.value
            else:
                value = filter_spec.values

            if filter_spec.operator == "is_null":
                has_value_subquery = (
                    select(CustomFieldValue.document_id)
                    .where(
                        and_(
                            CustomFieldValue.field_id == cf.id,
                            CustomFieldValue.value["raw"].astext.isnot(None)
                        )
                    )
                )
                base_query = base_query.where(
                    ~DocumentSearchIndex.document_id.in_(has_value_subquery)
                )
                count_query = count_query.where(
                    ~DocumentSearchIndex.document_id.in_(has_value_subquery)
                )
                continue

            if filter_spec.operator == "is_not_checked":
                # For is_not_checked, we want documents where:
                # 1. The boolean field is False
                # 2. The boolean field is not set (no entry in custom_field_values)
                # This is equivalent to: NOT (value is True)
                is_checked_subquery = (
                    select(CustomFieldValue.document_id)
                    .where(
                        and_(
                            CustomFieldValue.field_id == cf.id,
                            CustomFieldValue.value_boolean == True
                        )
                    )
                )
                base_query = base_query.where(
                    ~DocumentSearchIndex.document_id.in_(is_checked_subquery)
                )
                count_query = count_query.where(
                    ~DocumentSearchIndex.document_id.in_(is_checked_subquery)
                )
                continue

            filter_expr = handler.get_filter_expression(
                sort_column,
                filter_spec.operator,
                config=config,
                value=value,
            )

            # Join with custom field values
            base_query = base_query.join(
                cfv_alias,
                and_(
                    cfv_alias.document_id == DocumentSearchIndex.document_id,
                    cfv_alias.field_id == cf.id,
                    filter_expr
                )
            )
            count_query = count_query.join(
                cfv_alias,
                and_(
                    cfv_alias.document_id == DocumentSearchIndex.document_id,
                    cfv_alias.field_id == cf.id,
                    filter_expr
                )
            )

    # =========================================================================
    # Apply created_at filters
    # =========================================================================
    if params.filters and params.filters.created_at:
        created_at_filter = _build_datetime_filter(
            params.filters.created_at,
            orm.Node.created_at
        )
        if created_at_filter is not None:
            base_query = base_query.where(created_at_filter)
            count_query = count_query.where(created_at_filter)

    # =========================================================================
    # Apply updated_at filters
    # =========================================================================
    if params.filters and params.filters.updated_at:
        # updated_at comes from the latest DocumentVersion.updated_at
        updated_at_filter = _build_updated_at_filter(
            params.filters.updated_at,
            DocumentSearchIndex.document_id
        )
        if updated_at_filter is not None:
            base_query = base_query.where(updated_at_filter)
            count_query = count_query.where(updated_at_filter)

    # =========================================================================
    # Apply created_by filters
    # =========================================================================
    if params.filters and params.filters.created_by:
        created_by_filters = []

        for f in params.filters.created_by:
            created_by_filters.append(orm.Node.created_by == f.value)
        if created_by_filters:
            base_query = base_query.where(and_(*created_by_filters))
            count_query = count_query.where(and_(*created_by_filters))

    # =========================================================================
    # Apply updated_by filters
    # =========================================================================
    if params.filters and params.filters.updated_by:
        updated_by_filters = []
        # Get the updated_by from the version with the highest version number
        latest_version_updated_by = (
            select(DocumentVersion.updated_by)
            .where(DocumentVersion.document_id == DocumentSearchIndex.document_id)
            .order_by(DocumentVersion.number.desc())
            .limit(1)
            .scalar_subquery()
        )
        for f in params.filters.updated_by:
            updated_by_filters.append(latest_version_updated_by == f.value)

        if updated_by_filters:
            base_query = base_query.where(and_(*updated_by_filters))
            count_query = count_query.where(and_(*updated_by_filters))

    # =========================================================================
    # Apply owner filter
    # =========================================================================
    if params.filters and params.filters.owner:
        owner_conditions = []

        for f in params.filters.owner:
            if f.operator == OwnerOperator.EQ:
                owner_conditions.append(
                    DocumentSearchIndex.owner_id == f.value.id
                )
            else:
                owner_conditions.append(
                    DocumentSearchIndex.owner_id != f.value.id
                )

        if owner_conditions:
            base_query = base_query.where(and_(*owner_conditions))
            count_query = count_query.where(and_(*owner_conditions))

    # =========================================================================
    # Apply date_from / date_to filters (created_at shorthand)
    # =========================================================================
    if params.filters and params.filters.date_from:
        dt_from = datetime.combine(params.filters.date_from, datetime.min.time()).replace(tzinfo=dt_timezone.utc)
        base_query = base_query.where(orm.Node.created_at >= dt_from)
        count_query = count_query.where(orm.Node.created_at >= dt_from)

    if params.filters and params.filters.date_to:
        dt_to = datetime.combine(params.filters.date_to, datetime.max.time()).replace(tzinfo=dt_timezone.utc)
        base_query = base_query.where(orm.Node.created_at <= dt_to)
        count_query = count_query.where(orm.Node.created_at <= dt_to)

    # =========================================================================
    # Apply quality_score_min filter (join QualityAssessment)
    # =========================================================================
    if params.filters and params.filters.quality_score_min is not None:
        quality_subq = (
            select(QualityAssessment.document_id)
            .where(QualityAssessment.quality_score >= params.filters.quality_score_min)
        )
        base_query = base_query.where(DocumentSearchIndex.document_id.in_(quality_subq))
        count_query = count_query.where(DocumentSearchIndex.document_id.in_(quality_subq))

    # =========================================================================
    # Apply scanned_by_id filter (document created_by)
    # =========================================================================
    if params.filters and params.filters.scanned_by_id is not None:
        base_query = base_query.where(orm.Node.created_by == params.filters.scanned_by_id)
        count_query = count_query.where(orm.Node.created_by == params.filters.scanned_by_id)

    # =========================================================================
    # Apply project_id filter (via ScanBatch -> document relationship)
    # =========================================================================
    if params.filters and params.filters.project_id is not None:
        # ScanBatch links operator/project to batches; documents are linked via
        # node.created_by matching operator_id. We use a subquery on ScanBatch.
        try:
            project_uuid = UUID(params.filters.project_id)
        except (ValueError, AttributeError):
            project_uuid = None
        if project_uuid is not None:
            batch_operator_subq = (
                select(ScanBatch.operator_id)
                .where(ScanBatch.project_id == str(project_uuid))
                .where(ScanBatch.operator_id.isnot(None))
            )
            base_query = base_query.where(orm.Node.created_by.in_(batch_operator_subq))
            count_query = count_query.where(orm.Node.created_by.in_(batch_operator_subq))

    # =========================================================================
    # Apply has_annotations filter
    # =========================================================================
    if params.filters and params.filters.has_annotations is not None:
        annotation_subq = (
            select(DocumentAnnotation.document_id).distinct()
        )
        if params.filters.has_annotations:
            base_query = base_query.where(DocumentSearchIndex.document_id.in_(annotation_subq))
            count_query = count_query.where(DocumentSearchIndex.document_id.in_(annotation_subq))
        else:
            base_query = base_query.where(~DocumentSearchIndex.document_id.in_(annotation_subq))
            count_query = count_query.where(~DocumentSearchIndex.document_id.in_(annotation_subq))

    # =========================================================================
    # Apply has_exceptions filter
    # =========================================================================
    if params.filters and params.filters.has_exceptions is not None:
        # ExceptionEvent.document_id is a String column containing UUID values
        exception_doc_ids_subq = (
            select(func.cast(ExceptionEvent.document_id, doc_orm.Document.id.type))
            .where(ExceptionEvent.document_id.isnot(None))
            .distinct()
        )
        if params.filters.has_exceptions:
            base_query = base_query.where(DocumentSearchIndex.document_id.in_(exception_doc_ids_subq))
            count_query = count_query.where(DocumentSearchIndex.document_id.in_(exception_doc_ids_subq))
        else:
            base_query = base_query.where(~DocumentSearchIndex.document_id.in_(exception_doc_ids_subq))
            count_query = count_query.where(~DocumentSearchIndex.document_id.in_(exception_doc_ids_subq))

    # Note: We'll apply sorting later, after getting distinct document IDs

    # =========================================================================
    #  Get total count
    # =========================================================================
    count_result = await db_session.execute(count_query)
    total_count = count_result.scalar() or 0

    # =========================================================================
    # Get distinct document IDs (without ordering yet)
    # =========================================================================
    offset = (params.page_number - 1) * params.page_size

    # First get distinct document IDs without ordering
    # (to avoid PostgreSQL "SELECT DISTINCT, ORDER BY" conflict)
    distinct_ids_query = (
        base_query
        .with_only_columns(DocumentSearchIndex.document_id)
        .distinct()
    )

    distinct_ids_result = await db_session.execute(distinct_ids_query)
    all_distinct_ids = [row[0] for row in distinct_ids_result.all()]

    if not all_distinct_ids:
        num_pages = math.ceil(total_count / params.page_size) if total_count > 0 else 0
        return search_schema.SearchDocumentsResponse(
            items=[],
            page_number=params.page_number,
            page_size=params.page_size,
            num_pages=num_pages,
            total_items=total_count,
            custom_fields=custom_fields_info if include_custom_fields else [],
            document_type_id=document_type_ids[0] if len(document_type_ids) == 1 else None
        )

    # =========================================================================
    # Apply sorting and pagination to the distinct IDs
    # =========================================================================
    # Build a new query with just the search index for these document IDs
    sorted_query = (
        select(DocumentSearchIndex.document_id)
        .where(DocumentSearchIndex.document_id.in_(all_distinct_ids))
    )

    # Apply sorting
    if include_custom_fields:
        sorted_query = _apply_sorting_with_custom_fields(
            sorted_query,
            params,
            custom_fields
        )
    else:
        sorted_query = _apply_sorting_simple(sorted_query, params)

    # Apply pagination
    sorted_query = sorted_query.limit(params.page_size).offset(offset)

    sorted_result = await db_session.execute(sorted_query)
    paginated_doc_ids = [row[0] for row in sorted_result.all()]

    if not paginated_doc_ids:
        num_pages = math.ceil(total_count / params.page_size) if total_count > 0 else 0
        return search_schema.SearchDocumentsResponse(
            items=[],
            page_number=params.page_number,
            page_size=params.page_size,
            num_pages=num_pages,
            total_items=total_count,
            custom_fields=custom_fields_info if include_custom_fields else [],
            document_type_id=document_type_ids[0] if len(document_type_ids) == 1 else None
        )

    # =========================================================================
    # Load full document data
    # =========================================================================
    created_user = aliased(orm.User, name='created_user')
    updated_user = aliased(orm.User, name='updated_user')
    owner_user = aliased(orm.User, name='owner_user')
    owner_group = aliased(orm.Group, name='owner_group')
    category = aliased(DocumentType, name='category')

    full_data_query = (
        select(
            DocumentSearchIndex,
            orm.Ownership.owner_type.label('owner_type'),
            orm.Ownership.owner_id.label('owner_id'),
            owner_user.id.label('owner_user_id'),
            owner_user.username.label('owner_username'),
            owner_group.id.label('owner_group_id'),
            owner_group.name.label('owner_group_name'),
            category.id.label('category_id'),
            category.name.label('category_name'),
            orm.Node.created_at.label('created_at'),
            orm.Node.updated_at.label('updated_at'),
            created_user.id.label('created_by_id'),
            created_user.username.label('created_by_username'),
            updated_user.id.label('updated_by_id'),
            updated_user.username.label('updated_by_username'),
            orm.Tag.id.label('tag_id'),
            orm.Tag.name.label('tag_name'),
            orm.Tag.bg_color.label('tag_bg_color'),
            orm.Tag.fg_color.label('tag_fg_color'),
        )
        .join(
            orm.Node,
            DocumentSearchIndex.document_id == orm.Node.id
        )
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id
            )
        )
        .outerjoin(
            owner_user,
            and_(
                orm.Ownership.owner_type == OwnerType.USER.value,
                orm.Ownership.owner_id == owner_user.id
            )
        )
        .outerjoin(
            owner_group,
            and_(
                orm.Ownership.owner_type == OwnerType.GROUP.value,
                orm.Ownership.owner_id == owner_group.id
            )
        )
        .outerjoin(
            category,
            DocumentSearchIndex.document_type_id == category.id
        )
        .outerjoin(
            created_user,
            orm.Node.created_by == created_user.id
        )
        .outerjoin(
            updated_user,
            orm.Node.updated_by == updated_user.id
        )
        .outerjoin(
            orm.NodeTagsAssociation,
            orm.NodeTagsAssociation.node_id == DocumentSearchIndex.document_id
        )
        .outerjoin(
            orm.Tag,
            orm.Tag.id == orm.NodeTagsAssociation.tag_id
        )
        .where(DocumentSearchIndex.document_id.in_(paginated_doc_ids))
    )

    full_data_result = await db_session.execute(full_data_query)
    rows = full_data_result.all()

    # Group by document_id (to handle multiple tags per document)
    docs_dict: dict = {}
    for row in rows:
        doc_id = row[0].document_id

        if doc_id not in docs_dict:
            docs_dict[doc_id] = {
                'row': row,
                'tags': []
            }

        # Add tag if present
        if row.tag_id is not None:
            tag = search_schema.Tag(
                id=row.tag_id,
                name=row.tag_name,
                bg_color=row.tag_bg_color,
                fg_color=row.tag_fg_color
            )
            # Avoid duplicates
            if tag not in docs_dict[doc_id]['tags']:
                docs_dict[doc_id]['tags'].append(tag)

    # =========================================================================
    # Load custom field values (if custom fields are relevant)
    # =========================================================================
    cfvs_by_doc: dict = {}

    if include_custom_fields:
        doc_ids = list(docs_dict.keys())

        # Get custom field values for all documents
        stmt_cfv = (
            select(CustomFieldValue)
            .where(CustomFieldValue.document_id.in_(doc_ids))
        )
        result_cfv = await db_session.execute(stmt_cfv)
        all_cfvs = result_cfv.scalars().all()

        # Group CFVs by document_id
        for cfv in all_cfvs:
            if cfv.document_id not in cfvs_by_doc:
                cfvs_by_doc[cfv.document_id] = []
            cfvs_by_doc[cfv.document_id].append(cfv)

    # =========================================================================
    # Step 15: Build response items
    # =========================================================================
    items = []
    for doc_id, doc_data in docs_dict.items():
        row = doc_data['row']
        search_index = row[0]

        # Build owner info
        if row.owner_type == OwnerType.USER.value:
            owned_by = schema.OwnedBy(
                id=row.owner_user_id,
                name=row.owner_username,
                type=OwnerType.USER
            )
        else:
            owned_by = schema.OwnedBy(
                id=row.owner_group_id,
                name=row.owner_group_name,
                type=OwnerType.GROUP
            )

        # Build category
        doc_category = None
        if row.category_id:
            doc_category = search_schema.Category(
                id=row.category_id,
                name=row.category_name,
            )

        # Build created_by and updated_by
        created_by = schema.ByUser(
            id=row.created_by_id,
            username=row.created_by_username
        ) if row.created_by_id else None

        updated_by = schema.ByUser(
            id=row.updated_by_id,
            username=row.updated_by_username
        ) if row.updated_by_id else None

        # Build custom field rows (only for relevant custom fields)
        cf_rows = []
        if include_custom_fields:
            cfv_list = cfvs_by_doc.get(doc_id, [])

            for cf in custom_fields:
                cfv = next((v for v in cfv_list if v.field_id == cf.id), None)

                cf_rows.append(
                    schema.CustomFieldRow(
                        custom_field=schema.CustomFieldShort(
                            id=cf.id,
                            name=cf.name,
                            type_handler=cf.type_handler,
                            config=cf.config or {}
                        ),
                        custom_field_value=search_schema.CustomFieldValueShort(
                            value=cfv.value if cfv else None,
                            value_text=cfv.value_text if cfv else None,
                            value_numeric=cfv.value_numeric if cfv else None,
                            value_date=cfv.value_date if cfv else None,
                            value_datetime=cfv.value_datetime if cfv else None,
                            value_boolean=cfv.value_boolean if cfv else None
                        ) if cfv else None
                    )
                )

        items.append(
            search_schema.DocumentCFV(
                id=doc_id,
                title=search_index.title,
                category=doc_category,
                tags=doc_data['tags'],
                custom_fields=cf_rows,
                lang=search_index.lang,
                owned_by=owned_by,
                created_at=row.created_at,
                updated_at=row.updated_at,
                created_by=created_by,
                updated_by=updated_by
            )
        )

    # Preserve the original sort order from paginated_doc_ids
    items_dict = {item.id: item for item in items}
    items = [items_dict[doc_id] for doc_id in paginated_doc_ids if doc_id in items_dict]

    num_pages = math.ceil(total_count / params.page_size) if total_count > 0 else 0

    return search_schema.SearchDocumentsResponse(
        items=items,
        page_number=params.page_number,
        page_size=params.page_size,
        num_pages=num_pages,
        total_items=total_count,
        custom_fields=custom_fields_info if include_custom_fields else [],
        document_type_id=document_type_ids[0] if len(document_type_ids) == 1 else None
    )


# ============================================================================
# Helper functions
# ============================================================================

def _build_fts_query(fts_filter: search_schema.FullTextSearchFilter, lang: str):
    """Build full-text search query with support for AND/OR logic."""
    lang_config_map = {
        'deu': 'german',
        'eng': 'english',
        'fra': 'french',
        'spa': 'spanish',
        'ita': 'italian',
        'por': 'portuguese',
        'rus': 'russian',
        'nld': 'dutch',
    }

    lang_config = lang_config_map.get(lang, 'simple')
    query_str = ' & '.join(fts_filter.terms)

    # Use plainto_tsquery or to_tsquery depending on complexity
    if '|' in query_str or '(' in query_str:
        ts_query = func.to_tsquery(lang_config, query_str)
    else:
        ts_query = func.plainto_tsquery(lang_config, query_str)

    # Use @@ operator directly instead of .match() to avoid double wrapping
    return DocumentSearchIndex.search_vector.op('@@')(ts_query)


def _build_category_filter(category_filters: list[search_schema.CategoryFilter]):
    """Build category filter"""
    conditions = []

    for cat_filter in category_filters:
        if cat_filter.operator in CategoryOperator.ANY:
            cat_conditions = [
                DocumentSearchIndex.document_type_name == value
                for value in cat_filter.values
            ]
            conditions.append(or_(*cat_conditions))  # OR_(...)
        elif cat_filter.operator in CategoryOperator.NOT:
            cat_condition = ~DocumentSearchIndex.document_type_name.in_(cat_filter.values)
            conditions.append(cat_condition)

    # AND logic: match all the specified categories
    return and_(*conditions)


def _build_tag_filters(tag_filters: list[search_schema.TagFilter]):
    """Build tag filters with positive and negative matching."""
    conditions = []
    for tag_filter in tag_filters:
        if tag_filter.operator == TagOperator.ANY:
            tag_conditions = [
                DocumentSearchIndex.tags.contains([value])
                for value in tag_filter.values
            ]
            conditions.append(or_(*tag_conditions))  # OR_(...)
        elif tag_filter.operator == TagOperator.ALL:
            tag_conditions = [
                DocumentSearchIndex.tags.contains([value])
                for value in tag_filter.values
            ]
            conditions.append(and_(*tag_conditions))  # AND_(...)
        elif tag_filter.operator == TagOperator.NOT:
            tag_conditions = []
            for value in tag_filter.values:
                tag_conditions.append(
                    ~DocumentSearchIndex.tags.contains([value])  # ~...
                )
            conditions.append(and_(*tag_conditions))

    # final AND_(all tag filters)
    return and_(*conditions) if conditions else None


def _build_datetime_filter(filters, column):
    """Build datetime filter for created_at field.

    Args:
        filters: List of CreatedAtFilter
        column: SQLAlchemy column (orm.Node.created_at)

    Returns:
        SQLAlchemy filter expression combining all filters with AND logic
    """
    conditions = []

    for filter_spec in filters:
        operator = filter_spec.operator
        value = filter_spec.value

        if operator == search_schema.NumericOperator.EQ:
            conditions.append(column == value)
        elif operator == search_schema.NumericOperator.NE:
            conditions.append(column != value)
        elif operator == search_schema.NumericOperator.GT:
            conditions.append(column > value)
        elif operator == search_schema.NumericOperator.GTE:
            conditions.append(column >= value)
        elif operator == search_schema.NumericOperator.LT:
            conditions.append(column < value)
        elif operator == search_schema.NumericOperator.LTE:
            conditions.append(column <= value)

    return and_(*conditions) if conditions else None


def _build_updated_at_filter(filters, document_id_column):
    """Build datetime filter for updated_at field using latest DocumentVersion.updated_at.

    Args:
        filters: List of UpdatedAtFilter
        document_id_column: SQLAlchemy column referencing document_id

    Returns:
        SQLAlchemy filter expression combining all filters with AND logic
    """
    conditions = []
    latest_version_updated_at = (
        select(func.max(DocumentVersion.updated_at))
        .where(DocumentVersion.document_id == document_id_column)
        .scalar_subquery()
    )

    for filter_spec in filters:
        operator = filter_spec.operator
        value = filter_spec.value

        if operator == search_schema.NumericOperator.EQ:
            conditions.append(latest_version_updated_at == value)
        elif operator == search_schema.NumericOperator.NE:
            conditions.append(latest_version_updated_at != value)
        elif operator == search_schema.NumericOperator.GT:
            conditions.append(latest_version_updated_at > value)
        elif operator == search_schema.NumericOperator.GTE:
            conditions.append(latest_version_updated_at >= value)
        elif operator == search_schema.NumericOperator.LT:
            conditions.append(latest_version_updated_at < value)
        elif operator == search_schema.NumericOperator.LTE:
            conditions.append(latest_version_updated_at <= value)

    return and_(*conditions) if conditions else None


def _apply_sorting_simple(query, params: search_schema.SearchQueryParams):
    """Apply sorting without custom fields (for general search)."""
    sort_column_map = {
        search_schema.SortBy.ID: DocumentSearchIndex.document_id,
        search_schema.SortBy.TITLE: DocumentSearchIndex.title,
        search_schema.SortBy.CATEGORY: DocumentSearchIndex.document_type_name,
        search_schema.SortBy.UPDATED_AT: DocumentSearchIndex.last_updated,
    }

    sort_column = sort_column_map.get(params.sort_by, DocumentSearchIndex.last_updated)

    if params.sort_direction == search_schema.SortDirection.DESC:
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    return query


def _apply_sorting_with_custom_fields(
    query,
    params: search_schema.SearchQueryParams,
    custom_fields: Sequence[CustomField]
):
    """Apply sorting with custom field support (for document type search)."""

    # Check if sorting by custom field
    if params.sort_by and isinstance(params.sort_by, str):
        # Try to find custom field with this name
        cf = next((f for f in custom_fields if f.name == params.sort_by), None)
        if cf:
            # Sort by custom field
            handler = TypeRegistry.get_handler(cf.type_handler)
            cfv_alias = aliased(CustomFieldValue)
            sort_column = getattr(cfv_alias, handler.get_sort_column())

            # Join with custom field values for sorting
            query = query.outerjoin(
                cfv_alias,
                and_(
                    cfv_alias.document_id == DocumentSearchIndex.document_id,
                    cfv_alias.field_id == cf.id
                )
            )

            if params.sort_direction == search_schema.SortDirection.DESC:
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())

            return query

    # Default sorting (same as simple)
    return _apply_sorting_simple(query, params)



async def rebuild_document_search_index(
    db_session: AsyncSession,
) -> int:
    """
    Rebuild the entire DocumentSearchIndex by calling the PostgreSQL
    upsert_document_search_index function for all documents.
    This function:
    1. Clears the existing search index
    2. Gets all document IDs from the database
    3. Calls the PostgreSQL upsert function for each document
    The PostgreSQL function handles:
    - Computing tsvector from title, tags, document type, and custom fields
    - Applying proper language configuration
    - Managing ownership/access control data
    Args:
        db_session: AsyncSession for database operations
    Returns:
        int: Number of documents indexed
    Example:
        ```python
        from papermerge.core.db.engine import AsyncSessionLocal
        from papermerge.core import dbapi
        async with AsyncSessionLocal() as db_session:
            count = await dbapi.rebuild_document_search_index(db_session)
            print(f"Indexed {count} documents")
        ```
    """
    logger.info("Starting full rebuild of document search index")

    # Step 1: Clear existing index
    await db_session.execute(
        text("DELETE FROM document_search_index")
    )
    await db_session.commit()
    logger.info("Cleared existing search index")

    # Step 2: Get all document IDs
    stmt = select(doc_orm.Document.id)
    result = await db_session.execute(stmt)
    document_ids = result.scalars().all()

    total_docs = len(document_ids)
    logger.info(f"Found {total_docs} documents to index")

    # Step 3: Call upsert function for each document
    indexed_count = 0
    failed_count = 0

    for doc_id in document_ids:
        try:
            # Call PostgreSQL function to upsert this document
            await db_session.execute(
                text("SELECT upsert_document_search_index(:doc_id)"),
                {"doc_id": doc_id}
            )
            indexed_count += 1

            # Commit every 100 documents to avoid long transactions
            if indexed_count % 100 == 0:
                await db_session.commit()
                logger.info(f"Indexed {indexed_count}/{total_docs} documents")

        except Exception as e:
            logger.error(
                f"Error indexing document {doc_id}: {e}",
                exc_info=True
            )
            failed_count += 1
            # Continue with next document
            continue

    # Final commit
    await db_session.commit()

    logger.info(
        f"Completed index rebuild: {indexed_count} succeeded, "
        f"{failed_count} failed out of {total_docs} total"
    )

    return indexed_count


async def index_specific_documents(
    db_session: AsyncSession,
    document_ids: list[UUID],
) -> int:
    """
    Rebuild search index for specific documents by their IDs.
    This is useful when you want to reindex only certain documents
    instead of the entire database. The PostgreSQL upsert function
    will be called for each document.
    Args:
        db_session: AsyncSession for database operations
        document_ids: List of document UUIDs to index
    Returns:
        int: Number of documents successfully indexed
    Example:
        ```python
        from uuid import UUID
        from papermerge.core.db.engine import AsyncSessionLocal
        from papermerge.core import dbapi
        doc_ids = [
            UUID('123e4567-e89b-12d3-a456-426614174000'),
            UUID('223e4567-e89b-12d3-a456-426614174001'),
        ]
        async with AsyncSessionLocal() as db_session:
            count = await dbapi.index_specific_documents(db_session, doc_ids)
            print(f"Indexed {count} documents")
        ```
    """
    if not document_ids:
        logger.warning("No document IDs provided for indexing")
        return 0

    logger.info(f"Indexing {len(document_ids)} specific documents")

    indexed_count = 0
    failed_count = 0

    for doc_id in document_ids:
        try:
            # Call PostgreSQL function to upsert this document
            await db_session.execute(
                text("SELECT upsert_document_search_index(:doc_id)"),
                {"doc_id": doc_id}
            )
            indexed_count += 1

        except Exception as e:
            logger.error(
                f"Error indexing document {doc_id}: {e}",
                exc_info=True
            )
            failed_count += 1
            # Continue with next document
            continue

    # Commit all changes
    await db_session.commit()

    logger.info(
        f"Indexed {indexed_count} succeeded, {failed_count} failed "
        f"out of {len(document_ids)} requested"
    )

    return indexed_count


async def get_document_search_index_stats(
    db_session: AsyncSession,
) -> dict:
    """
    Get statistics about the document search index.
    Returns information about:
    - Total documents in the system
    - Total documents in the search index
    - Documents missing from the index
    - Index size information
    Args:
        db_session: AsyncSession for database operations
    Returns:
        dict: Statistics about the search index
    Example:
        ```python
        async with AsyncSessionLocal() as db_session:
            stats = await dbapi.get_document_search_index_stats(db_session)
            print(f"Total documents: {stats['total_documents']}")
            print(f"Indexed documents: {stats['indexed_documents']}")
            print(f"Missing from index: {stats['missing_from_index']}")
        ```
    """
    # Get total document count
    stmt = select(text("COUNT(*)")).select_from(doc_orm.Document)
    result = await db_session.execute(stmt)
    total_documents = result.scalar()

    # Get indexed document count
    stmt_indexed = text("SELECT COUNT(*) FROM document_search_index")
    result_indexed = await db_session.execute(stmt_indexed)
    indexed_documents = result_indexed.scalar()

    # Calculate missing documents
    missing_from_index = total_documents - indexed_documents

    # Get index size (PostgreSQL specific)
    try:
        size_query = text("""
            SELECT pg_size_pretty(pg_total_relation_size('document_search_index'))
        """)
        result_size = await db_session.execute(size_query)
        index_size = result_size.scalar()
    except Exception as e:
        logger.warning(f"Could not get index size: {e}")
        index_size = "unknown"

    return {
        "total_documents": total_documents,
        "indexed_documents": indexed_documents,
        "missing_from_index": missing_from_index,
        "index_size": index_size,
    }


async def find_unindexed_documents(
    db_session: AsyncSession,
) -> list[UUID]:
    """
    Find documents that exist in the database but are missing from the search index.
    This can happen if:
    - The index was manually cleared
    - Database triggers were disabled
    - There were errors during indexing
    Args:
        db_session: AsyncSession for database operations
    Returns:
        list[UUID]: List of document IDs that are not in the search index
    Example:
        ```python
        async with AsyncSessionLocal() as db_session:
            missing_ids = await dbapi.find_unindexed_documents(db_session)
            if missing_ids:
                print(f"Found {len(missing_ids)} unindexed documents")
                # Reindex them
                await dbapi.index_specific_documents(db_session, missing_ids)
        ```
    """
    query = text("""
        SELECT d.node_id
        FROM documents d
        LEFT JOIN document_search_index dsi ON dsi.document_id = d.node_id
        WHERE dsi.document_id IS NULL
    """)

    result = await db_session.execute(query)
    unindexed_ids = [row[0] for row in result]

    logger.info(f"Found {len(unindexed_ids)} documents missing from search index")


async def get_search_facets(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    q: str | None = None,
) -> search_schema.SearchFacetsResponse:
    """
    Compute facet counts for the search UI.

    Returns:
      - document_types: counts per document type
      - date_histogram: monthly document counts
      - quality_buckets: four 25-point quality bands
      - operators: counts per creating user
      - projects: counts per scanning project
    """
    # Access control: only docs owned by this user (or their groups)
    user_groups_subquery = select(UserGroup.group_id).where(UserGroup.user_id == user_id)

    access_filter = or_(
        and_(
            DocumentSearchIndex.owner_type == OwnerType.USER.value,
            DocumentSearchIndex.owner_id == user_id,
        ),
        and_(
            DocumentSearchIndex.owner_type == OwnerType.GROUP.value,
            DocumentSearchIndex.owner_id.in_(user_groups_subquery),
        ),
    )

    # Optionally narrow by FTS query
    fts_filter = None
    if q and q.strip():
        ts_query = func.plainto_tsquery('english', q.strip())
        fts_filter = DocumentSearchIndex.search_vector.op('@@')(ts_query)

    def _base(extra_join=None):
        q2 = (
            select(DocumentSearchIndex.document_id)
            .join(orm.Node, DocumentSearchIndex.document_id == orm.Node.id)
            .join(
                orm.Ownership,
                and_(
                    orm.Ownership.resource_type == ResourceType.NODE.value,
                    orm.Ownership.resource_id == orm.Node.id,
                ),
            )
            .where(access_filter)
        )
        if fts_filter is not None:
            q2 = q2.where(fts_filter)
        if extra_join is not None:
            q2 = extra_join(q2)
        return q2

    # ------------------------------------------------------------------
    # 1. Document types
    # ------------------------------------------------------------------
    dt_rows = (await db_session.execute(
        select(
            DocumentSearchIndex.document_type_name,
            func.count(DocumentSearchIndex.document_id.distinct()).label("cnt"),
        )
        .join(orm.Node, DocumentSearchIndex.document_id == orm.Node.id)
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id,
            ),
        )
        .where(access_filter)
        .where(DocumentSearchIndex.document_type_name.isnot(None))
        .group_by(DocumentSearchIndex.document_type_name)
        .order_by(func.count(DocumentSearchIndex.document_id.distinct()).desc())
        .limit(20)
    )).all()

    document_types = [
        search_schema.FacetItem(name=r[0], count=r[1])
        for r in dt_rows if r[0]
    ]

    # ------------------------------------------------------------------
    # 2. Monthly date histogram (created_at from nodes)
    # ------------------------------------------------------------------
    date_rows = (await db_session.execute(
        select(
            func.to_char(orm.Node.created_at, 'YYYY-MM').label("month"),
            func.count(orm.Node.id.distinct()).label("cnt"),
        )
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id,
            ),
        )
        .join(
            DocumentSearchIndex,
            DocumentSearchIndex.document_id == orm.Node.id,
        )
        .where(access_filter)
        .group_by(func.to_char(orm.Node.created_at, 'YYYY-MM'))
        .order_by(func.to_char(orm.Node.created_at, 'YYYY-MM').desc())
        .limit(24)
    )).all()

    date_histogram = [
        search_schema.DateHistogramBucket(date=r[0], count=r[1])
        for r in date_rows if r[0]
    ]

    # ------------------------------------------------------------------
    # 3. Quality buckets  (join QualityAssessment)
    # ------------------------------------------------------------------
    quality_bands = [
        ("0-25", 0.0, 25.0),
        ("25-50", 25.0, 50.0),
        ("50-75", 50.0, 75.0),
        ("75-100", 75.0, 100.0),
    ]
    quality_buckets = []
    for label, lo, hi in quality_bands:
        (cnt,) = (await db_session.execute(
            select(func.count(QualityAssessment.document_id.distinct()))
            .join(
                DocumentSearchIndex,
                DocumentSearchIndex.document_id == QualityAssessment.document_id,
            )
            .join(orm.Node, DocumentSearchIndex.document_id == orm.Node.id)
            .join(
                orm.Ownership,
                and_(
                    orm.Ownership.resource_type == ResourceType.NODE.value,
                    orm.Ownership.resource_id == orm.Node.id,
                ),
            )
            .where(access_filter)
            .where(QualityAssessment.quality_score >= lo)
            .where(QualityAssessment.quality_score < hi if hi < 100.0 else QualityAssessment.quality_score <= hi)
        )).one()
        quality_buckets.append(
            search_schema.QualityBucket(label=label, min=lo, max=hi, count=cnt or 0)
        )

    # ------------------------------------------------------------------
    # 4. Operators (users who created documents)
    # ------------------------------------------------------------------
    op_rows = (await db_session.execute(
        select(
            orm.User.username,
            func.count(orm.Node.id.distinct()).label("cnt"),
        )
        .join(orm.Node, orm.Node.created_by == orm.User.id)
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id,
            ),
        )
        .join(
            DocumentSearchIndex,
            DocumentSearchIndex.document_id == orm.Node.id,
        )
        .where(access_filter)
        .group_by(orm.User.username)
        .order_by(func.count(orm.Node.id.distinct()).desc())
        .limit(20)
    )).all()

    operators = [
        search_schema.FacetItem(name=r[0], count=r[1])
        for r in op_rows if r[0]
    ]

    # ------------------------------------------------------------------
    # 5. Projects (via ScanBatch operator_id -> Node.created_by)
    # ------------------------------------------------------------------
    proj_rows = (await db_session.execute(
        select(
            ScanningProjectModel.name,
            func.count(orm.Node.id.distinct()).label("cnt"),
        )
        .join(ScanBatch, ScanBatch.project_id == func.cast(ScanningProjectModel.id, type_=String))
        .join(orm.Node, orm.Node.created_by == ScanBatch.operator_id)
        .join(
            orm.Ownership,
            and_(
                orm.Ownership.resource_type == ResourceType.NODE.value,
                orm.Ownership.resource_id == orm.Node.id,
            ),
        )
        .join(
            DocumentSearchIndex,
            DocumentSearchIndex.document_id == orm.Node.id,
        )
        .where(access_filter)
        .where(ScanBatch.operator_id.isnot(None))
        .group_by(ScanningProjectModel.name)
        .order_by(func.count(orm.Node.id.distinct()).desc())
        .limit(20)
    )).all()

    projects = [
        search_schema.FacetItem(name=r[0], count=r[1])
        for r in proj_rows if r[0]
    ]

    return search_schema.SearchFacetsResponse(
        document_types=document_types,
        date_histogram=date_histogram,
        quality_buckets=quality_buckets,
        operators=operators,
        projects=projects,
    )

    return unindexed_ids


# ============================================================================
# Semantic & Hybrid Search DB helpers
# ============================================================================

async def semantic_search_db(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    query_vector: list[float],
    limit: int = 20,
    threshold: float = 0.0,
) -> list[dict]:
    """
    Vector similarity search using pgvector cosine distance (<=>).

    Returns dicts with keys: document_id, title, score, snippet.
    Access-controlled to documents owned by user_id.
    """
    from sqlalchemy import text as sa_text

    # We use raw SQL for the <=> operator; pgvector doesn't expose it through
    # the ORM column operator at query-build time without a registered type.
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    stmt = sa_text("""
        SELECT DISTINCT ON (de.document_id)
               de.document_id,
               dsi.title,
               de.chunk_text                          AS snippet,
               1 - (de.embedding <=> :vec ::vector)   AS score
        FROM   document_embeddings de
        JOIN   document_search_index dsi ON dsi.document_id = de.document_id
        JOIN   nodes n                   ON n.id = de.document_id
        JOIN   ownerships o              ON o.resource_id = n.id
                                        AND o.resource_type = 'node'
        WHERE  o.owner_id = :user_id
          AND  1 - (de.embedding <=> :vec ::vector) >= :threshold
        ORDER  BY de.document_id,
                  de.embedding <=> :vec ::vector
        LIMIT  :limit
    """)

    result = await db_session.execute(stmt, {
        "vec": vector_literal,
        "user_id": str(user_id),
        "threshold": threshold,
        "limit": limit,
    })
    rows = result.mappings().all()

    return [
        {
            "document_id": str(r["document_id"]),
            "title": r["title"] or "",
            "snippet": r["snippet"] or "",
            "score": float(r["score"]),
        }
        for r in rows
    ]


async def hybrid_search_db(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    query_text: str,
    query_vector: list[float],
    limit: int = 20,
    lang: str = "eng",
    rrf_k: int = 60,
) -> list[dict]:
    """
    Reciprocal Rank Fusion of BM25 (tsvector @@) + cosine similarity ranks.

    RRF score = 1/(k + rank_bm25) + 1/(k + rank_semantic)
    """
    from sqlalchemy import text as sa_text

    lang_map = {
        "eng": "english", "deu": "german", "fra": "french",
        "spa": "spanish", "ita": "italian", "por": "portuguese",
    }
    pg_lang = lang_map.get(lang, "simple")
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    stmt = sa_text(f"""
        WITH bm25 AS (
            SELECT dsi.document_id,
                   dsi.title,
                   ROW_NUMBER() OVER (
                       ORDER BY ts_rank_cd(dsi.search_vector,
                                          plainto_tsquery('{pg_lang}', :query)) DESC
                   ) AS rk
            FROM   document_search_index dsi
            JOIN   nodes n       ON n.id = dsi.document_id
            JOIN   ownerships o  ON o.resource_id = n.id
                                AND o.resource_type = 'node'
            WHERE  o.owner_id = :user_id
              AND  dsi.search_vector @@ plainto_tsquery('{pg_lang}', :query)
            LIMIT  100
        ),
        sem AS (
            SELECT DISTINCT ON (de.document_id)
                   de.document_id,
                   dsi2.title,
                   de.chunk_text AS snippet,
                   ROW_NUMBER() OVER (
                       ORDER BY de.embedding <=> :vec ::vector
                   ) AS rk
            FROM   document_embeddings de
            JOIN   document_search_index dsi2 ON dsi2.document_id = de.document_id
            JOIN   nodes n2      ON n2.id = de.document_id
            JOIN   ownerships o2 ON o2.resource_id = n2.id
                                 AND o2.resource_type = 'node'
            WHERE  o2.owner_id = :user_id
            ORDER  BY de.document_id, de.embedding <=> :vec ::vector
            LIMIT  100
        ),
        fused AS (
            SELECT COALESCE(b.document_id, s.document_id) AS document_id,
                   COALESCE(b.title, s.title)             AS title,
                   s.snippet,
                   COALESCE(1.0 / (:rrf_k + b.rk), 0)
                   + COALESCE(1.0 / (:rrf_k + s.rk), 0)  AS rrf_score
            FROM   bm25 b
            FULL OUTER JOIN sem s ON s.document_id = b.document_id
        )
        SELECT document_id, title, snippet,
               rrf_score AS score
        FROM   fused
        ORDER  BY rrf_score DESC
        LIMIT  :limit
    """)

    result = await db_session.execute(stmt, {
        "query": query_text,
        "vec": vector_literal,
        "user_id": str(user_id),
        "rrf_k": rrf_k,
        "limit": limit,
    })
    rows = result.mappings().all()

    return [
        {
            "document_id": str(r["document_id"]),
            "title": r["title"] or "",
            "snippet": r["snippet"] or "",
            "score": float(r["score"]),
        }
        for r in rows
    ]


async def get_similar_documents_db(
    db_session: AsyncSession,
    *,
    document_id: UUID,
    user_id: UUID,
    limit: int = 5,
) -> list[dict]:
    """
    Return top-N documents most similar to document_id by cosine distance,
    averaged across all embedding chunks of the source document.
    """
    from sqlalchemy import text as sa_text

    stmt = sa_text("""
        WITH source_avg AS (
            SELECT AVG(embedding) AS avg_vec
            FROM   document_embeddings
            WHERE  document_id = :doc_id
        ),
        candidates AS (
            SELECT DISTINCT ON (de.document_id)
                   de.document_id,
                   dsi.title,
                   de.chunk_text AS snippet,
                   1 - (de.embedding <=> (SELECT avg_vec FROM source_avg)::vector) AS score
            FROM   document_embeddings de
            JOIN   document_search_index dsi ON dsi.document_id = de.document_id
            JOIN   nodes n       ON n.id = de.document_id
            JOIN   ownerships o  ON o.resource_id = n.id
                                AND o.resource_type = 'node'
            WHERE  de.document_id <> :doc_id
              AND  o.owner_id = :user_id
            ORDER  BY de.document_id,
                      de.embedding <=> (SELECT avg_vec FROM source_avg)::vector
        )
        SELECT document_id, title, snippet, score
        FROM   candidates
        ORDER  BY score DESC
        LIMIT  :limit
    """)

    result = await db_session.execute(stmt, {
        "doc_id": str(document_id),
        "user_id": str(user_id),
        "limit": limit,
    })
    rows = result.mappings().all()

    return [
        {
            "document_id": str(r["document_id"]),
            "title": r["title"] or "",
            "snippet": r["snippet"] or "",
            "score": float(r["score"]),
        }
        for r in rows
    ]

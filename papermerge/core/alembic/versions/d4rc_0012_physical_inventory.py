# (c) Copyright Datacraft, 2026
"""Physical inventory management tables.

Revision ID: d4rc_0012
Revises: d4rc_0011
Create Date: 2026-01-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd4rc_0012'
down_revision = 'd4rc_0011'
branch_labels = None
depends_on = None


def upgrade():
	# Create enum types
	container_type_enum = postgresql.ENUM(
		'box', 'folder', 'crate', 'shelf', 'cabinet', 'pallet', 'room', 'building',
		name='container_type_enum'
	)
	container_type_enum.create(op.get_bind(), checkfirst=True)

	inventory_status_enum = postgresql.ENUM(
		'in_storage', 'checked_out', 'in_transit', 'missing', 'destroyed', 'transferred', 'pending_review',
		name='inventory_status_enum'
	)
	inventory_status_enum.create(op.get_bind(), checkfirst=True)

	# Warehouse locations table
	op.create_table(
		'warehouse_locations',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('code', sa.String(50), unique=True, nullable=False, index=True),
		sa.Column('name', sa.String(200), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_locations.id', ondelete='SET NULL'), index=True),
		sa.Column('path', sa.String(1000), index=True),
		sa.Column('level', sa.Integer, default=0),
		sa.Column('capacity', sa.Integer),
		sa.Column('current_count', sa.Integer, default=0),
		sa.Column('climate_controlled', sa.Boolean, default=False),
		sa.Column('fire_suppression', sa.Boolean, default=False),
		sa.Column('access_restricted', sa.Boolean, default=False),
		sa.Column('aisle', sa.String(20)),
		sa.Column('bay', sa.String(20)),
		sa.Column('shelf_number', sa.String(20)),
		sa.Column('position', sa.String(20)),
		sa.Column('created_at', sa.DateTime, default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
	)

	# Physical containers table
	op.create_table(
		'physical_containers',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('barcode', sa.String(100), unique=True, nullable=False, index=True),
		sa.Column('container_type', container_type_enum, default='box'),
		sa.Column('label', sa.String(200)),
		sa.Column('description', sa.Text),
		sa.Column('location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_locations.id', ondelete='SET NULL'), index=True),
		sa.Column('parent_container_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('physical_containers.id', ondelete='SET NULL'), index=True),
		sa.Column('status', inventory_status_enum, default='in_storage'),
		sa.Column('item_count', sa.Integer, default=0),
		sa.Column('weight_kg', sa.Integer),
		sa.Column('dimensions', postgresql.JSON),
		sa.Column('retention_date', sa.DateTime),
		sa.Column('destruction_eligible', sa.Boolean, default=False),
		sa.Column('legal_hold', sa.Boolean, default=False),
		sa.Column('current_custodian_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('last_verified_at', sa.DateTime),
		sa.Column('last_verified_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('created_at', sa.DateTime, default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('scanning_project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='SET NULL'), index=True),
	)

	# Container documents junction table
	op.create_table(
		'container_documents',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('container_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('physical_containers.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('sequence_number', sa.Integer),
		sa.Column('page_count', sa.Integer),
		sa.Column('has_physical', sa.Boolean, default=True),
		sa.Column('verified', sa.Boolean, default=False),
		sa.Column('verified_at', sa.DateTime),
		sa.Column('created_at', sa.DateTime, default=sa.func.now()),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
	)

	# Custody events for chain of custody tracking
	op.create_table(
		'custody_events',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('container_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('physical_containers.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('event_type', sa.String(50), nullable=False),
		sa.Column('from_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('to_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('performed_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=False),
		sa.Column('from_location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_locations.id', ondelete='SET NULL')),
		sa.Column('to_location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_locations.id', ondelete='SET NULL')),
		sa.Column('reason', sa.Text),
		sa.Column('notes', sa.Text),
		sa.Column('signature_captured', sa.Boolean, default=False),
		sa.Column('witness_name', sa.String(200)),
		sa.Column('created_at', sa.DateTime, default=sa.func.now()),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
	)

	# Inventory scans audit table
	op.create_table(
		'inventory_scans',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('scanned_code', sa.String(500), nullable=False),
		sa.Column('code_type', sa.String(20)),
		sa.Column('success', sa.Boolean, default=True),
		sa.Column('resolved_container_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('physical_containers.id', ondelete='SET NULL')),
		sa.Column('resolved_document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='SET NULL')),
		sa.Column('resolved_location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_locations.id', ondelete='SET NULL')),
		sa.Column('error_message', sa.Text),
		sa.Column('scan_purpose', sa.String(50)),
		sa.Column('scanner_device_id', sa.String(100)),
		sa.Column('scanned_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=False),
		sa.Column('latitude', sa.Integer),
		sa.Column('longitude', sa.Integer),
		sa.Column('created_at', sa.DateTime, default=sa.func.now()),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
	)

	# Create indexes for common queries
	op.create_index('ix_physical_containers_status', 'physical_containers', ['status', 'tenant_id'])
	op.create_index('ix_custody_events_container_date', 'custody_events', ['container_id', 'created_at'])
	op.create_index('ix_inventory_scans_date', 'inventory_scans', ['created_at', 'tenant_id'])
	op.create_index('ix_container_documents_doc', 'container_documents', ['document_id', 'container_id'])


def downgrade():
	op.drop_index('ix_container_documents_doc')
	op.drop_index('ix_inventory_scans_date')
	op.drop_index('ix_custody_events_container_date')
	op.drop_index('ix_physical_containers_status')

	op.drop_table('inventory_scans')
	op.drop_table('custody_events')
	op.drop_table('container_documents')
	op.drop_table('physical_containers')
	op.drop_table('warehouse_locations')

	# Drop enum types
	postgresql.ENUM(name='inventory_status_enum').drop(op.get_bind(), checkfirst=True)
	postgresql.ENUM(name='container_type_enum').drop(op.get_bind(), checkfirst=True)

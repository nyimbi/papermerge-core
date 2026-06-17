"""add sftp ingestion connector tables

Revision ID: darchiva_sftp_001
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "darchiva_sftp_001"
down_revision: Union[str, None] = "fa71c2c795a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"sftp_connections",
		sa.Column("id", sa.String(), nullable=False),
		sa.Column("name", sa.String(), nullable=False),
		sa.Column("host", sa.String(), nullable=False),
		sa.Column("port", sa.Integer(), nullable=False, server_default="22"),
		sa.Column("username", sa.String(), nullable=False),
		sa.Column("password_encrypted", sa.Text(), nullable=True),
		sa.Column("ssh_key_encrypted", sa.Text(), nullable=True),
		sa.Column("remote_path", sa.String(), nullable=False, server_default="/"),
		sa.Column("file_pattern", sa.String(), nullable=False, server_default="*.pdf,*.tiff,*.jpg"),
		sa.Column("poll_interval_minutes", sa.Integer(), nullable=False, server_default="5"),
		sa.Column("destination_folder_id", sa.String(), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
		sa.Column(
			"last_polled_at",
			sa.TIMESTAMP(timezone=True),
			nullable=True,
		),
		sa.Column("last_error", sa.Text(), nullable=True),
		sa.Column("docs_ingested_total", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("tenant_id", sa.String(), nullable=False),
		sa.Column(
			"created_at",
			sa.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.func.now(),
		),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index("ix_sftp_connections_tenant_id", "sftp_connections", ["tenant_id"])

	op.create_table(
		"sftp_downloaded_files",
		sa.Column("id", sa.String(), nullable=False),
		sa.Column("connection_id", sa.String(), nullable=False),
		sa.Column("remote_path", sa.String(), nullable=False),
		sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"downloaded_at",
			sa.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.func.now(),
		),
		sa.ForeignKeyConstraint(
			["connection_id"],
			["sftp_connections.id"],
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index(
		"ix_sftp_downloaded_files_connection_id",
		"sftp_downloaded_files",
		["connection_id"],
	)
	op.create_index(
		"ix_sftp_downloaded_files_remote_path",
		"sftp_downloaded_files",
		["connection_id", "remote_path"],
		unique=True,
	)


def downgrade() -> None:
	op.drop_table("sftp_downloaded_files")
	op.drop_table("sftp_connections")

# Central import of all SQLAlchemy ORM models.
#
# SQLAlchemy resolves string-based relationship() references (e.g.,
# relationship("ScanBatch")) by looking up registered mappers at
# configure_mappers() time. If a referenced class hasn't been imported yet,
# SQLAlchemy raises InvalidRequestError.
#
# Importing this module guarantees all feature ORM classes are registered
# in the mapper registry before any mapper configuration occurs.

from papermerge.core.features.annotations.db.orm import *  # noqa: F401, F403
from papermerge.core.features.api_keys.db.orm import *  # noqa: F401, F403
from papermerge.core.features.api_tokens.db.orm import *  # noqa: F401, F403
from papermerge.core.features.audit.db.orm import *  # noqa: F401, F403
from papermerge.core.features.auto_routing.db.orm import *  # noqa: F401, F403
from papermerge.core.features.batches.db.orm import *  # noqa: F401, F403
from papermerge.core.features.billing.db.orm import *  # noqa: F401, F403
from papermerge.core.features.bundles.db.orm import *  # noqa: F401, F403
from papermerge.core.features.cases.db.orm import *  # noqa: F401, F403
from papermerge.core.features.custom_fields.db.orm import *  # noqa: F401, F403
from papermerge.core.features.departments.db.orm import *  # noqa: F401, F403
from papermerge.core.features.document_relationships.db.orm import *  # noqa: F401, F403
from papermerge.core.features.document_types.db.orm import *  # noqa: F401, F403
from papermerge.core.features.document.db.orm import *  # noqa: F401, F403
from papermerge.core.features.email_ingest.db.orm import *  # noqa: F401, F403
from papermerge.core.features.emails.models import *  # noqa: F401, F403
from papermerge.core.features.encryption.db.orm import *  # noqa: F401, F403
from papermerge.core.features.exceptions.db.orm import *  # noqa: F401, F403
from papermerge.core.features.expiry.db.orm import *  # noqa: F401, F403
from papermerge.core.features.form_recognition.db.orm import *  # noqa: F401, F403
from papermerge.core.features.groups.db.orm import *  # noqa: F401, F403
from papermerge.core.features.iam.db.orm import *  # noqa: F401, F403
from papermerge.core.features.ingestion.db.orm import *  # noqa: F401, F403
from papermerge.core.features.inventory.db.orm import *  # noqa: F401, F403
from papermerge.core.features.mfa.db.orm import *  # noqa: F401, F403
from papermerge.core.features.nodes.db.orm import *  # noqa: F401, F403
from papermerge.core.features.notifications.db.orm import *  # noqa: F401, F403
from papermerge.core.features.ownership.db.orm import *  # noqa: F401, F403
from papermerge.core.features.policies.db.orm import *  # noqa: F401, F403
from papermerge.core.features.portfolios.db.orm import *  # noqa: F401, F403
from papermerge.core.features.preferences.db.orm import *  # noqa: F401, F403
from papermerge.core.features.provenance.db.orm import *  # noqa: F401, F403
from papermerge.core.features.quality.db.orm import *  # noqa: F401, F403
from papermerge.core.features.roles.db.orm import *  # noqa: F401, F403
from papermerge.core.features.routing.db.orm import *  # noqa: F401, F403
from papermerge.core.features.search.db.orm import *  # noqa: F401, F403
from papermerge.core.features.scanners.models import *  # noqa: F401, F403
from papermerge.core.features.scanning_projects.db.orm_members import *  # noqa: F401, F403
from papermerge.core.features.scanning_projects.models import *  # noqa: F401, F403
from papermerge.core.features.scanning_projects.models_templates import *  # noqa: F401, F403
from papermerge.core.features.scanning_projects.operations_models import *  # noqa: F401, F403
from papermerge.core.features.sftp.db.orm import *  # noqa: F401, F403
from papermerge.core.features.segmentation.db.orm import *  # noqa: F401, F403
from papermerge.core.features.signatures.db.orm import *  # noqa: F401, F403
from papermerge.core.features.serial_numbers.models import *  # noqa: F401, F403
from papermerge.core.features.settings.db.orm import *  # noqa: F401, F403
from papermerge.core.features.shared_nodes.db.orm import *  # noqa: F401, F403
from papermerge.core.features.sharing.db.orm import *  # noqa: F401, F403
from papermerge.core.features.special_folders.db.orm import *  # noqa: F401, F403
from papermerge.core.features.tags.db.orm import *  # noqa: F401, F403
from papermerge.core.features.templates.db.orm import *  # noqa: F401, F403
from papermerge.core.features.tenants.db.orm import *  # noqa: F401, F403
from papermerge.core.features.users.db.orm import *  # noqa: F401, F403
from papermerge.core.features.webauthn.db.orm import *  # noqa: F401, F403
from papermerge.core.features.user_home.models import *  # noqa: F401, F403
from papermerge.core.features.retention.db.orm import *  # noqa: F401, F403
from papermerge.core.features.webhooks.db.orm import *  # noqa: F401, F403
from papermerge.core.features.workflows.db.orm import *  # noqa: F401, F403
from papermerge.core.features.approvals.db.orm import *  # noqa: F401, F403
from papermerge.core.features.classification_feedback.db.orm import *  # noqa: F401, F403
from papermerge.core.features.connectors.db.orm import *  # noqa: F401, F403
from papermerge.core.features.data_export.db.orm import *  # noqa: F401, F403
from papermerge.core.features.dedup.db.orm import *  # noqa: F401, F403
from papermerge.core.features.document_chat.db.orm import *  # noqa: F401, F403
from papermerge.core.features.legal_hold.db.orm import *  # noqa: F401, F403
from papermerge.core.features.acl.db.orm import *  # noqa: F401, F403
from papermerge.core.features.automation.db.orm import *  # noqa: F401, F403
from papermerge.core.features.scheduled_reports.db.orm import *  # noqa: F401, F403

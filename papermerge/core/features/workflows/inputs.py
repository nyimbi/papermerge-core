# (c) Copyright Datacraft, 2026
"""
Prefect RunInput models for human-in-the-loop workflow steps.

These models define the schema for user input when workflows pause
for human interaction (approvals, reviews, signatures, etc.).
"""
from datetime import datetime
from typing import Literal, Any
from uuid import UUID

from prefect.input import RunInput
from pydantic import BaseModel, Field, ConfigDict


class ApprovalInput(RunInput):
	"""
	Input model for standard approval decisions.

	Used when a workflow needs a simple approve/reject decision.
	"""
	decision: Literal["approved", "rejected", "returned"] = Field(
		...,
		description="The approval decision",
	)
	notes: str = Field(
		default="",
		description="Optional notes explaining the decision",
	)
	reviewer_id: str = Field(
		default="",
		description="ID of the user making the decision",
	)


class ReviewInput(RunInput):
	"""
	Input model for document review decisions.

	Extends approval with quality scoring and specific feedback.
	"""
	decision: Literal["approved", "rejected", "returned", "needs_revision"] = Field(
		...,
		description="The review decision",
	)
	quality_score: int | None = Field(
		default=None,
		ge=1,
		le=5,
		description="Quality rating from 1-5",
	)
	accuracy_score: int | None = Field(
		default=None,
		ge=1,
		le=5,
		description="Accuracy rating from 1-5",
	)
	completeness_score: int | None = Field(
		default=None,
		ge=1,
		le=5,
		description="Completeness rating from 1-5",
	)
	feedback: str = Field(
		default="",
		description="Detailed feedback for the submitter",
	)
	revision_items: list[str] = Field(
		default_factory=list,
		description="Specific items that need revision",
	)
	reviewer_id: str = Field(
		default="",
		description="ID of the user making the decision",
	)


class SignatureInput(RunInput):
	"""
	Input model for digital signature requests.

	Used when a workflow requires an electronic signature.
	"""
	signed: bool = Field(
		...,
		description="Whether the document was signed",
	)
	signature_data: str | None = Field(
		default=None,
		description="Base64-encoded signature image or signature hash",
	)
	signer_id: str = Field(
		default="",
		description="ID of the signer",
	)
	signer_name: str = Field(
		default="",
		description="Full name of the signer",
	)
	signer_title: str | None = Field(
		default=None,
		description="Title/role of the signer",
	)
	signature_timestamp: datetime | None = Field(
		default=None,
		description="Timestamp of the signature",
	)
	signature_ip: str | None = Field(
		default=None,
		description="IP address where signature was created",
	)
	decline_reason: str | None = Field(
		default=None,
		description="Reason for declining to sign",
	)


class DataEntryInput(RunInput):
	"""
	Input model for manual data entry tasks.

	Used when a workflow needs human-entered data.
	"""
	completed: bool = Field(
		...,
		description="Whether data entry was completed",
	)
	entered_data: dict[str, Any] = Field(
		default_factory=dict,
		description="The data entered by the user",
	)
	confidence: Literal["low", "medium", "high"] | None = Field(
		default=None,
		description="User's confidence in the entered data",
	)
	needs_verification: bool = Field(
		default=False,
		description="Whether the data should be verified by another user",
	)
	notes: str = Field(
		default="",
		description="Notes about the data entry",
	)
	operator_id: str = Field(
		default="",
		description="ID of the operator who entered the data",
	)


class QualityCheckInput(RunInput):
	"""
	Input model for quality control checks.

	Used in scanning/digitization workflows for QC samples.
	"""
	decision: Literal["passed", "failed", "needs_rescan"] = Field(
		...,
		description="Quality check decision",
	)
	image_quality: Literal["excellent", "good", "acceptable", "poor"] | None = Field(
		default=None,
		description="Image quality assessment",
	)
	ocr_quality: Literal["excellent", "good", "acceptable", "poor"] | None = Field(
		default=None,
		description="OCR quality assessment",
	)
	issues_found: list[str] = Field(
		default_factory=list,
		description="List of issues found during QC",
	)
	correction_notes: str = Field(
		default="",
		description="Instructions for correction if failed",
	)
	qc_inspector_id: str = Field(
		default="",
		description="ID of the QC inspector",
	)


class ClassificationVerificationInput(RunInput):
	"""
	Input model for verifying automatic classification.

	Used when AI classification confidence is below threshold.
	"""
	verified: bool = Field(
		...,
		description="Whether the classification was verified",
	)
	correct_classification: bool = Field(
		...,
		description="Whether the auto-classification was correct",
	)
	document_type: str | None = Field(
		default=None,
		description="Correct document type if different from auto-classified",
	)
	additional_tags: list[str] = Field(
		default_factory=list,
		description="Additional tags to apply",
	)
	verifier_id: str = Field(
		default="",
		description="ID of the user who verified",
	)


class RoutingDecisionInput(RunInput):
	"""
	Input model for manual routing decisions.

	Used when automatic routing cannot determine destination.
	"""
	route_to: str = Field(
		...,
		description="Selected route/destination",
	)
	priority: Literal["low", "normal", "high", "urgent"] = Field(
		default="normal",
		description="Priority for the routed item",
	)
	due_date: datetime | None = Field(
		default=None,
		description="Due date for the routed task",
	)
	assignee_id: str | None = Field(
		default=None,
		description="Specific user to assign to",
	)
	notes: str = Field(
		default="",
		description="Routing notes",
	)
	router_id: str = Field(
		default="",
		description="ID of the user who made the routing decision",
	)


class ExceptionHandlingInput(RunInput):
	"""
	Input model for handling workflow exceptions.

	Used when automatic processing fails and needs human intervention.
	"""
	action: Literal["retry", "skip", "abort", "manual_fix"] = Field(
		...,
		description="Action to take on the exception",
	)
	manual_fix_data: dict[str, Any] | None = Field(
		default=None,
		description="Data for manual fix (if action is manual_fix)",
	)
	root_cause: str | None = Field(
		default=None,
		description="Identified root cause of the exception",
	)
	preventive_action: str | None = Field(
		default=None,
		description="Suggested preventive action",
	)
	handler_id: str = Field(
		default="",
		description="ID of the user who handled the exception",
	)


# Mapping of approval types to their input models
INPUT_MODEL_REGISTRY: dict[str, type[RunInput]] = {
	"approval": ApprovalInput,
	"review": ReviewInput,
	"signature": SignatureInput,
	"data_entry": DataEntryInput,
	"quality_check": QualityCheckInput,
	"classification_verification": ClassificationVerificationInput,
	"routing_decision": RoutingDecisionInput,
	"exception_handling": ExceptionHandlingInput,
}


def get_input_model(approval_type: str) -> type[RunInput]:
	"""
	Get the appropriate input model for an approval type.

	Args:
		approval_type: The type of approval/input required

	Returns:
		The RunInput class to use for this approval type
	"""
	return INPUT_MODEL_REGISTRY.get(approval_type, ApprovalInput)

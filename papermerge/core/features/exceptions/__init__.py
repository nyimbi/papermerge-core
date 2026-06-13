# (c) Copyright Datacraft, 2026
"""
Exception Event management module.

Handles exceptions raised during scanning and document processing,
including quality rejections, missing signatures, incomplete sets,
barcode errors, and orientation errors.

Routing rules determine automated actions: rescan queue, supervisor review,
batch halt, operator notification, or auto-dismiss.
"""
from .db.orm import (
	ExceptionEvent,
	ExceptionRoutingRule,
	ExceptionType,
	ExceptionSeverity,
	ExceptionStatus,
	RoutingAction,
	RuleAction,
)

__all__ = [
	"ExceptionEvent",
	"ExceptionRoutingRule",
	"ExceptionType",
	"ExceptionSeverity",
	"ExceptionStatus",
	"RoutingAction",
	"RuleAction",
]

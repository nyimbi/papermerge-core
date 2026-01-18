# (c) Copyright Datacraft, 2026
"""
Document Quality Assurance module.

Provides automated quality assessment for scanned documents,
including resolution, skew, brightness, contrast, and OCR confidence analysis.
"""
from .assessment import (
	QualityAssessor,
	QualityMetrics,
	QualityIssue,
	assess_document_quality,
	assess_page_quality,
)
from .rules import (
	QualityRule,
	QualityRuleEngine,
	RuleSeverity,
	RuleAction,
)

__all__ = [
	'QualityAssessor',
	'QualityMetrics',
	'QualityIssue',
	'assess_document_quality',
	'assess_page_quality',
	'QualityRule',
	'QualityRuleEngine',
	'RuleSeverity',
	'RuleAction',
]

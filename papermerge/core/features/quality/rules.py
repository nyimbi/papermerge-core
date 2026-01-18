# (c) Copyright Datacraft, 2026
"""
Quality rules engine.

Evaluates quality metrics against configurable rules
to determine pass/fail status and required actions.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from uuid import UUID

from .assessment import QualityMetrics, QualityIssue

logger = logging.getLogger(__name__)


class RuleSeverity(str, Enum):
	"""Severity of rule violation."""
	INFO = "info"
	WARNING = "warning"
	ERROR = "error"
	CRITICAL = "critical"


class RuleAction(str, Enum):
	"""Action to take when rule is violated."""
	LOG = "log"
	FLAG = "flag"
	QUARANTINE = "quarantine"
	REJECT = "reject"
	NOTIFY = "notify"
	AUTO_FIX = "auto_fix"


class RuleOperator(str, Enum):
	"""Comparison operators for rules."""
	EQUALS = "eq"
	NOT_EQUALS = "neq"
	GREATER_THAN = "gt"
	GREATER_EQUAL = "gte"
	LESS_THAN = "lt"
	LESS_EQUAL = "lte"
	BETWEEN = "between"
	NOT_BETWEEN = "not_between"


@dataclass
class QualityRule:
	"""A quality rule definition."""
	id: UUID | str
	name: str
	metric: str  # Which metric to check
	operator: RuleOperator
	threshold: float
	threshold_upper: float | None = None  # For BETWEEN operator

	# Rule configuration
	severity: RuleSeverity = RuleSeverity.WARNING
	action: RuleAction = RuleAction.FLAG
	message_template: str = ""
	priority: int = 100  # Lower = higher priority

	# Scope
	document_type_id: UUID | None = None  # If set, only applies to this type
	applies_to_all: bool = True
	is_active: bool = True

	def evaluate(self, value: float | None) -> bool:
		"""
		Evaluate if the rule is violated.

		Returns True if the rule is violated (value fails the check).
		"""
		if value is None:
			return False

		if self.operator == RuleOperator.EQUALS:
			return value != self.threshold
		elif self.operator == RuleOperator.NOT_EQUALS:
			return value == self.threshold
		elif self.operator == RuleOperator.GREATER_THAN:
			return value <= self.threshold
		elif self.operator == RuleOperator.GREATER_EQUAL:
			return value < self.threshold
		elif self.operator == RuleOperator.LESS_THAN:
			return value >= self.threshold
		elif self.operator == RuleOperator.LESS_EQUAL:
			return value > self.threshold
		elif self.operator == RuleOperator.BETWEEN:
			if self.threshold_upper is None:
				return False
			return not (self.threshold <= value <= self.threshold_upper)
		elif self.operator == RuleOperator.NOT_BETWEEN:
			if self.threshold_upper is None:
				return False
			return self.threshold <= value <= self.threshold_upper

		return False

	def get_message(self, actual_value: float) -> str:
		"""Get the violation message."""
		if self.message_template:
			return self.message_template.format(
				metric=self.metric,
				actual=actual_value,
				threshold=self.threshold,
				threshold_upper=self.threshold_upper,
			)

		# Default messages
		op_text = {
			RuleOperator.EQUALS: f"must equal {self.threshold}",
			RuleOperator.NOT_EQUALS: f"must not equal {self.threshold}",
			RuleOperator.GREATER_THAN: f"must be greater than {self.threshold}",
			RuleOperator.GREATER_EQUAL: f"must be at least {self.threshold}",
			RuleOperator.LESS_THAN: f"must be less than {self.threshold}",
			RuleOperator.LESS_EQUAL: f"must be at most {self.threshold}",
			RuleOperator.BETWEEN: f"must be between {self.threshold} and {self.threshold_upper}",
			RuleOperator.NOT_BETWEEN: f"must not be between {self.threshold} and {self.threshold_upper}",
		}

		return f"{self.metric} {op_text.get(self.operator, '')} (actual: {actual_value})"


@dataclass
class RuleEvaluationResult:
	"""Result of evaluating a single rule."""
	rule: QualityRule
	violated: bool
	actual_value: float | None
	issue: QualityIssue | None = None


@dataclass
class RulesEvaluationResult:
	"""Result of evaluating all rules."""
	passed: bool
	results: list[RuleEvaluationResult] = field(default_factory=list)
	violations: list[RuleEvaluationResult] = field(default_factory=list)
	actions: list[RuleAction] = field(default_factory=list)

	@property
	def violation_count(self) -> int:
		return len(self.violations)

	@property
	def critical_count(self) -> int:
		return sum(1 for v in self.violations if v.rule.severity == RuleSeverity.CRITICAL)

	@property
	def should_reject(self) -> bool:
		return RuleAction.REJECT in self.actions


class QualityRuleEngine:
	"""
	Engine for evaluating quality rules against metrics.

	Applies rules in priority order and collects all violations.
	"""

	def __init__(
		self,
		rules: list[QualityRule] | None = None,
		reject_on_critical: bool = True,
		reject_threshold: int | None = None,  # Max violations before reject
	):
		self.rules = rules or []
		self.reject_on_critical = reject_on_critical
		self.reject_threshold = reject_threshold

		# Sort by priority
		self.rules.sort(key=lambda r: r.priority)

		# Custom metric extractors
		self._metric_extractors: dict[str, Callable[[QualityMetrics], float | None]] = {
			"resolution_dpi": lambda m: m.resolution_dpi,
			"skew_angle": lambda m: abs(m.skew_angle) if m.skew_angle else None,
			"brightness": lambda m: m.brightness,
			"contrast": lambda m: m.contrast,
			"sharpness": lambda m: m.sharpness,
			"noise_level": lambda m: m.noise_level,
			"blur_score": lambda m: m.blur_score,
			"ocr_confidence": lambda m: m.ocr_confidence,
			"quality_score": lambda m: m.quality_score,
			"file_size_kb": lambda m: m.file_size_bytes / 1024 if m.file_size_bytes else None,
		}

	def add_rule(self, rule: QualityRule) -> None:
		"""Add a rule to the engine."""
		self.rules.append(rule)
		self.rules.sort(key=lambda r: r.priority)

	def remove_rule(self, rule_id: UUID | str) -> bool:
		"""Remove a rule by ID."""
		for i, rule in enumerate(self.rules):
			if rule.id == rule_id:
				self.rules.pop(i)
				return True
		return False

	def get_metric_value(
		self, metrics: QualityMetrics, metric_name: str
	) -> float | None:
		"""Extract a metric value from QualityMetrics."""
		extractor = self._metric_extractors.get(metric_name)
		if extractor:
			return extractor(metrics)

		# Try attribute access
		if hasattr(metrics, metric_name):
			return getattr(metrics, metric_name)

		logger.warning(f"Unknown metric: {metric_name}")
		return None

	def evaluate(
		self,
		metrics: QualityMetrics,
		document_type_id: UUID | None = None,
	) -> RulesEvaluationResult:
		"""
		Evaluate all rules against the given metrics.

		Args:
			metrics: Quality metrics to evaluate
			document_type_id: Optional document type for rule filtering

		Returns:
			RulesEvaluationResult with all evaluation results
		"""
		result = RulesEvaluationResult(passed=True)

		for rule in self.rules:
			# Skip inactive rules
			if not rule.is_active:
				continue

			# Check document type scope
			if not rule.applies_to_all and rule.document_type_id != document_type_id:
				continue

			# Get metric value
			value = self.get_metric_value(metrics, rule.metric)

			# Evaluate rule
			violated = rule.evaluate(value)

			eval_result = RuleEvaluationResult(
				rule=rule,
				violated=violated,
				actual_value=value,
			)

			if violated and value is not None:
				issue = QualityIssue(
					metric=rule.metric,
					actual_value=value,
					expected_value=rule.threshold,
					severity=rule.severity.value,
					message=rule.get_message(value),
					auto_fixable=rule.action == RuleAction.AUTO_FIX,
				)
				eval_result.issue = issue
				result.violations.append(eval_result)

				# Add action if not already present
				if rule.action not in result.actions:
					result.actions.append(rule.action)

			result.results.append(eval_result)

		# Determine pass/fail
		result.passed = self._determine_pass(result)

		return result

	def _determine_pass(self, result: RulesEvaluationResult) -> bool:
		"""Determine if the overall evaluation passes."""
		# Reject if any rule says to reject
		if RuleAction.REJECT in result.actions:
			return False

		# Reject if any critical violation and we're configured to reject on critical
		if self.reject_on_critical and result.critical_count > 0:
			return False

		# Reject if too many violations
		if self.reject_threshold and result.violation_count > self.reject_threshold:
			return False

		# Reject if quarantine action (quarantine implies failure)
		if RuleAction.QUARANTINE in result.actions:
			return False

		return True


# Default rules for common quality checks
def get_default_rules() -> list[QualityRule]:
	"""Get a set of default quality rules."""
	return [
		QualityRule(
			id="default-resolution",
			name="Minimum Resolution",
			metric="resolution_dpi",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=200,
			severity=RuleSeverity.WARNING,
			action=RuleAction.FLAG,
			message_template="Resolution {actual} DPI is below minimum {threshold} DPI",
			priority=10,
		),
		QualityRule(
			id="default-resolution-critical",
			name="Critical Resolution",
			metric="resolution_dpi",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=100,
			severity=RuleSeverity.CRITICAL,
			action=RuleAction.REJECT,
			message_template="Resolution {actual} DPI is critically low (minimum 100 DPI)",
			priority=5,
		),
		QualityRule(
			id="default-skew",
			name="Maximum Skew",
			metric="skew_angle",
			operator=RuleOperator.LESS_EQUAL,
			threshold=2.0,
			severity=RuleSeverity.WARNING,
			action=RuleAction.AUTO_FIX,
			message_template="Skew angle {actual}° exceeds maximum {threshold}°",
			priority=20,
		),
		QualityRule(
			id="default-skew-critical",
			name="Critical Skew",
			metric="skew_angle",
			operator=RuleOperator.LESS_EQUAL,
			threshold=10.0,
			severity=RuleSeverity.ERROR,
			action=RuleAction.FLAG,
			message_template="Skew angle {actual}° is severely skewed",
			priority=15,
		),
		QualityRule(
			id="default-brightness-low",
			name="Minimum Brightness",
			metric="brightness",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=80,
			severity=RuleSeverity.WARNING,
			action=RuleAction.AUTO_FIX,
			message_template="Image is too dark (brightness: {actual})",
			priority=30,
		),
		QualityRule(
			id="default-brightness-high",
			name="Maximum Brightness",
			metric="brightness",
			operator=RuleOperator.LESS_EQUAL,
			threshold=220,
			severity=RuleSeverity.WARNING,
			action=RuleAction.AUTO_FIX,
			message_template="Image is too bright (brightness: {actual})",
			priority=30,
		),
		QualityRule(
			id="default-contrast",
			name="Minimum Contrast",
			metric="contrast",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=0.25,
			severity=RuleSeverity.WARNING,
			action=RuleAction.AUTO_FIX,
			message_template="Low contrast: {actual:.2f}",
			priority=40,
		),
		QualityRule(
			id="default-sharpness",
			name="Minimum Sharpness",
			metric="sharpness",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=0.2,
			severity=RuleSeverity.WARNING,
			action=RuleAction.FLAG,
			message_template="Image is blurry (sharpness: {actual:.2f})",
			priority=50,
		),
		QualityRule(
			id="default-noise",
			name="Maximum Noise",
			metric="noise_level",
			operator=RuleOperator.LESS_EQUAL,
			threshold=0.3,
			severity=RuleSeverity.INFO,
			action=RuleAction.LOG,
			message_template="High noise level: {actual:.2f}",
			priority=60,
		),
		QualityRule(
			id="default-ocr-confidence",
			name="Minimum OCR Confidence",
			metric="ocr_confidence",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=0.7,
			severity=RuleSeverity.WARNING,
			action=RuleAction.FLAG,
			message_template="Low OCR confidence: {actual:.0%}",
			priority=25,
		),
		QualityRule(
			id="default-ocr-critical",
			name="Critical OCR Confidence",
			metric="ocr_confidence",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=0.4,
			severity=RuleSeverity.ERROR,
			action=RuleAction.QUARANTINE,
			message_template="OCR confidence is critically low: {actual:.0%}",
			priority=20,
		),
		QualityRule(
			id="default-overall-score",
			name="Minimum Quality Score",
			metric="quality_score",
			operator=RuleOperator.GREATER_EQUAL,
			threshold=50.0,
			severity=RuleSeverity.ERROR,
			action=RuleAction.QUARANTINE,
			message_template="Overall quality score {actual:.0f} is below acceptable threshold",
			priority=1,
		),
	]


def create_rule_engine_from_db(
	rules_from_db: list[dict[str, Any]],
) -> QualityRuleEngine:
	"""
	Create a rule engine from database rule records.

	Args:
		rules_from_db: List of rule dictionaries from database

	Returns:
		Configured QualityRuleEngine
	"""
	rules = []
	for rule_data in rules_from_db:
		try:
			rule = QualityRule(
				id=rule_data["id"],
				name=rule_data["name"],
				metric=rule_data["metric"],
				operator=RuleOperator(rule_data["operator"]),
				threshold=rule_data["threshold"],
				threshold_upper=rule_data.get("threshold_upper"),
				severity=RuleSeverity(rule_data.get("severity", "warning")),
				action=RuleAction(rule_data.get("action", "flag")),
				message_template=rule_data.get("message_template", ""),
				priority=rule_data.get("priority", 100),
				document_type_id=rule_data.get("document_type_id"),
				applies_to_all=rule_data.get("applies_to_all", True),
				is_active=rule_data.get("is_active", True),
			)
			rules.append(rule)
		except (KeyError, ValueError) as e:
			logger.error(f"Failed to parse rule: {e}")

	return QualityRuleEngine(rules=rules)

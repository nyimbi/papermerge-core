# (c) Copyright Datacraft, 2026
"""
Policy DSL Parser for human-readable policy definitions.

Supports a natural language-like syntax:
    ALLOW view ON document
    WHERE subject.department = resource.department
    AND subject.role IN ["manager", "admin"]
    AND environment.time BETWEEN "09:00" AND "17:00"
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import (
	Policy, PolicyRule, PolicyCondition, PolicyEffect, PolicyStatus,
	ConditionOperator, AttributeCategory
)


class PolicySyntaxError(Exception):
	"""Raised when policy syntax is invalid."""
	def __init__(self, message: str, line: int = 0, column: int = 0):
		self.line = line
		self.column = column
		super().__init__(f"Line {line}, col {column}: {message}")


@dataclass
class Token:
	"""Lexer token."""
	type: str
	value: str
	line: int
	column: int


class PolicyLexer:
	"""Tokenizer for policy DSL."""

	KEYWORDS = {
		"ALLOW", "DENY", "ON", "WHERE", "AND", "OR", "NOT",
		"IN", "BETWEEN", "LIKE", "MATCHES", "EXISTS", "IS",
		"NULL", "TRUE", "FALSE", "MEMBER_OF", "HAS_ROLE",
		"IN_DEPARTMENT", "CONTAINS", "STARTS_WITH", "ENDS_WITH",
	}

	OPERATORS = {
		"=": "EQ",
		"!=": "NE",
		"<>": "NE",
		">": "GT",
		">=": "GTE",
		"<": "LT",
		"<=": "LTE",
	}

	def __init__(self, text: str):
		self.text = text
		self.pos = 0
		self.line = 1
		self.column = 1
		self.tokens: list[Token] = []

	def tokenize(self) -> list[Token]:
		while self.pos < len(self.text):
			self._skip_whitespace()
			if self.pos >= len(self.text):
				break

			char = self.text[self.pos]

			# Comments
			if char == "#" or (char == "-" and self._peek() == "-"):
				self._skip_comment()
				continue

			# String literals
			if char in ('"', "'"):
				self.tokens.append(self._read_string())
				continue

			# Numbers
			if char.isdigit():
				self.tokens.append(self._read_number())
				continue

			# Operators (multi-char first)
			two_char = self.text[self.pos:self.pos + 2]
			if two_char in self.OPERATORS:
				self.tokens.append(Token("OPERATOR", two_char, self.line, self.column))
				self._advance(2)
				continue
			if char in self.OPERATORS:
				self.tokens.append(Token("OPERATOR", char, self.line, self.column))
				self._advance()
				continue

			# Punctuation
			if char in "()[],.":
				self.tokens.append(Token("PUNCT", char, self.line, self.column))
				self._advance()
				continue

			# Identifiers and keywords
			if char.isalpha() or char == "_":
				self.tokens.append(self._read_identifier())
				continue

			raise PolicySyntaxError(f"Unexpected character: {char}", self.line, self.column)

		return self.tokens

	def _advance(self, count: int = 1):
		for _ in range(count):
			if self.pos < len(self.text):
				if self.text[self.pos] == "\n":
					self.line += 1
					self.column = 1
				else:
					self.column += 1
				self.pos += 1

	def _peek(self, offset: int = 1) -> str:
		pos = self.pos + offset
		return self.text[pos] if pos < len(self.text) else ""

	def _skip_whitespace(self):
		while self.pos < len(self.text) and self.text[self.pos] in " \t\n\r":
			self._advance()

	def _skip_comment(self):
		while self.pos < len(self.text) and self.text[self.pos] != "\n":
			self._advance()

	def _read_string(self) -> Token:
		quote = self.text[self.pos]
		start_line, start_col = self.line, self.column
		self._advance()  # Skip opening quote
		value = ""
		while self.pos < len(self.text) and self.text[self.pos] != quote:
			if self.text[self.pos] == "\\":
				self._advance()
				if self.pos < len(self.text):
					value += self.text[self.pos]
					self._advance()
			else:
				value += self.text[self.pos]
				self._advance()
		if self.pos >= len(self.text):
			raise PolicySyntaxError("Unterminated string", start_line, start_col)
		self._advance()  # Skip closing quote
		return Token("STRING", value, start_line, start_col)

	def _read_number(self) -> Token:
		start_line, start_col = self.line, self.column
		value = ""
		while self.pos < len(self.text) and (self.text[self.pos].isdigit() or self.text[self.pos] == "."):
			value += self.text[self.pos]
			self._advance()
		return Token("NUMBER", value, start_line, start_col)

	def _read_identifier(self) -> Token:
		start_line, start_col = self.line, self.column
		value = ""
		while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] in "_."):
			value += self.text[self.pos]
			self._advance()
		token_type = "KEYWORD" if value.upper() in self.KEYWORDS else "IDENTIFIER"
		return Token(token_type, value.upper() if token_type == "KEYWORD" else value, start_line, start_col)


class PolicyParser:
	"""
	Parser for policy DSL.

	Grammar:
		policy      := effect actions ON resources [WHERE conditions]
		effect      := ALLOW | DENY
		actions     := action (',' action)*
		action      := IDENTIFIER
		resources   := resource (',' resource)*
		resource    := IDENTIFIER
		conditions  := condition ((AND | OR) condition)*
		condition   := attribute operator value
		attribute   := category '.' IDENTIFIER
		category    := subject | resource | action | environment
		operator    := '=' | '!=' | '>' | '>=' | '<' | '<=' | IN | CONTAINS | ...
		value       := STRING | NUMBER | '[' value_list ']' | IDENTIFIER
	"""

	OPERATOR_MAP = {
		"EQ": ConditionOperator.EQUALS,
		"=": ConditionOperator.EQUALS,
		"NE": ConditionOperator.NOT_EQUALS,
		"!=": ConditionOperator.NOT_EQUALS,
		"<>": ConditionOperator.NOT_EQUALS,
		"GT": ConditionOperator.GREATER_THAN,
		">": ConditionOperator.GREATER_THAN,
		"GTE": ConditionOperator.GREATER_THAN_OR_EQUAL,
		">=": ConditionOperator.GREATER_THAN_OR_EQUAL,
		"LT": ConditionOperator.LESS_THAN,
		"<": ConditionOperator.LESS_THAN,
		"LTE": ConditionOperator.LESS_THAN_OR_EQUAL,
		"<=": ConditionOperator.LESS_THAN_OR_EQUAL,
		"IN": ConditionOperator.IN,
		"NOT_IN": ConditionOperator.NOT_IN,
		"CONTAINS": ConditionOperator.CONTAINS,
		"NOT_CONTAINS": ConditionOperator.NOT_CONTAINS,
		"STARTS_WITH": ConditionOperator.STARTS_WITH,
		"ENDS_WITH": ConditionOperator.ENDS_WITH,
		"MATCHES": ConditionOperator.MATCHES,
		"EXISTS": ConditionOperator.EXISTS,
		"MEMBER_OF": ConditionOperator.IS_MEMBER_OF,
		"HAS_ROLE": ConditionOperator.HAS_ROLE,
		"IN_DEPARTMENT": ConditionOperator.IN_DEPARTMENT,
	}

	CATEGORY_MAP = {
		"subject": AttributeCategory.SUBJECT,
		"resource": AttributeCategory.RESOURCE,
		"action": AttributeCategory.ACTION,
		"environment": AttributeCategory.ENVIRONMENT,
		"env": AttributeCategory.ENVIRONMENT,
		"user": AttributeCategory.SUBJECT,
		"doc": AttributeCategory.RESOURCE,
		"document": AttributeCategory.RESOURCE,
	}

	def __init__(self):
		self.tokens: list[Token] = []
		self.pos = 0

	def parse(self, text: str, policy_id: str = "", name: str = "") -> Policy:
		"""Parse policy text into Policy object."""
		lexer = PolicyLexer(text)
		self.tokens = lexer.tokenize()
		self.pos = 0

		if not self.tokens:
			raise PolicySyntaxError("Empty policy", 1, 1)

		# Parse effect
		effect = self._parse_effect()

		# Parse actions
		actions = self._parse_actions()

		# Expect ON
		self._expect_keyword("ON")

		# Parse resource types
		resource_types = self._parse_resources()

		# Parse optional WHERE clause
		rules = []
		if self._check_keyword("WHERE"):
			self._advance()
			rules = self._parse_conditions()

		return Policy(
			id=policy_id or f"policy_{datetime.utcnow().timestamp()}",
			name=name or f"Policy: {effect.value} {', '.join(actions)} on {', '.join(resource_types)}",
			description=text.strip(),
			effect=effect,
			priority=100,
			rules=rules,
			actions=actions,
			resource_types=resource_types,
			status=PolicyStatus.DRAFT,
		)

	def _current(self) -> Token | None:
		return self.tokens[self.pos] if self.pos < len(self.tokens) else None

	def _advance(self) -> Token | None:
		token = self._current()
		self.pos += 1
		return token

	def _check_keyword(self, keyword: str) -> bool:
		token = self._current()
		return token and token.type == "KEYWORD" and token.value == keyword

	def _expect_keyword(self, keyword: str):
		token = self._current()
		if not token or token.type != "KEYWORD" or token.value != keyword:
			line, col = (token.line, token.column) if token else (0, 0)
			raise PolicySyntaxError(f"Expected '{keyword}'", line, col)
		self._advance()

	def _parse_effect(self) -> PolicyEffect:
		token = self._current()
		if not token or token.type != "KEYWORD" or token.value not in ("ALLOW", "DENY"):
			line, col = (token.line, token.column) if token else (0, 0)
			raise PolicySyntaxError("Expected ALLOW or DENY", line, col)
		self._advance()
		return PolicyEffect.ALLOW if token.value == "ALLOW" else PolicyEffect.DENY

	def _parse_actions(self) -> list[str]:
		actions = []
		token = self._current()
		if not token or token.type != "IDENTIFIER":
			line, col = (token.line, token.column) if token else (0, 0)
			raise PolicySyntaxError("Expected action", line, col)

		actions.append(token.value)
		self._advance()

		while self._current() and self._current().type == "PUNCT" and self._current().value == ",":
			self._advance()  # Skip comma
			token = self._current()
			if not token or token.type != "IDENTIFIER":
				raise PolicySyntaxError("Expected action after comma", token.line if token else 0, token.column if token else 0)
			actions.append(token.value)
			self._advance()

		return actions

	def _parse_resources(self) -> list[str]:
		resources = []
		token = self._current()
		if not token or token.type != "IDENTIFIER":
			line, col = (token.line, token.column) if token else (0, 0)
			raise PolicySyntaxError("Expected resource type", line, col)

		resources.append(token.value)
		self._advance()

		while self._current() and self._current().type == "PUNCT" and self._current().value == ",":
			self._advance()
			token = self._current()
			if not token or token.type != "IDENTIFIER":
				raise PolicySyntaxError("Expected resource after comma", token.line if token else 0, token.column if token else 0)
			resources.append(token.value)
			self._advance()

		return resources

	def _parse_conditions(self) -> list[PolicyRule]:
		"""Parse WHERE clause conditions."""
		conditions = []
		current_logic = "AND"

		while self._current():
			# Check for AND/OR
			if self._check_keyword("AND"):
				current_logic = "AND"
				self._advance()
				continue
			if self._check_keyword("OR"):
				current_logic = "OR"
				self._advance()
				continue

			# Parse a condition
			condition = self._parse_single_condition()
			if condition:
				conditions.append(condition)
			else:
				break

		if not conditions:
			return []

		return [PolicyRule(conditions=conditions, logic=current_logic)]

	def _parse_single_condition(self) -> PolicyCondition | None:
		"""Parse a single condition: attribute operator value."""
		token = self._current()
		if not token or token.type not in ("IDENTIFIER", "KEYWORD"):
			return None

		# Parse attribute (category.attribute)
		attr_parts = token.value.split(".")
		if len(attr_parts) < 2:
			raise PolicySyntaxError(
				f"Invalid attribute format: {token.value}. Expected 'category.attribute'",
				token.line, token.column
			)

		category_str = attr_parts[0].lower()
		if category_str not in self.CATEGORY_MAP:
			raise PolicySyntaxError(f"Unknown category: {category_str}", token.line, token.column)
		category = self.CATEGORY_MAP[category_str]
		attribute = ".".join(attr_parts[1:])
		self._advance()

		# Parse operator
		op_token = self._current()
		if not op_token:
			raise PolicySyntaxError("Expected operator", token.line, token.column)

		if op_token.type == "OPERATOR":
			op_str = op_token.value
		elif op_token.type == "KEYWORD" and op_token.value in self.OPERATOR_MAP:
			op_str = op_token.value
		else:
			raise PolicySyntaxError(f"Unknown operator: {op_token.value}", op_token.line, op_token.column)

		operator = self.OPERATOR_MAP.get(op_str)
		if not operator:
			raise PolicySyntaxError(f"Unknown operator: {op_str}", op_token.line, op_token.column)
		self._advance()

		# Parse value
		value = self._parse_value()

		return PolicyCondition(
			category=category,
			attribute=attribute,
			operator=operator,
			value=value,
		)

	def _parse_value(self) -> Any:
		"""Parse a value (string, number, list, or identifier)."""
		token = self._current()
		if not token:
			raise PolicySyntaxError("Expected value", 0, 0)

		if token.type == "STRING":
			self._advance()
			return token.value

		if token.type == "NUMBER":
			self._advance()
			return float(token.value) if "." in token.value else int(token.value)

		if token.type == "KEYWORD":
			self._advance()
			if token.value == "TRUE":
				return True
			if token.value == "FALSE":
				return False
			if token.value == "NULL":
				return None
			return token.value

		if token.type == "PUNCT" and token.value == "[":
			return self._parse_list()

		if token.type == "IDENTIFIER":
			self._advance()
			return token.value

		raise PolicySyntaxError(f"Unexpected value: {token.value}", token.line, token.column)

	def _parse_list(self) -> list:
		"""Parse a list value: [item1, item2, ...]"""
		self._advance()  # Skip [
		items = []

		while self._current() and not (self._current().type == "PUNCT" and self._current().value == "]"):
			value = self._parse_value()
			items.append(value)

			if self._current() and self._current().type == "PUNCT" and self._current().value == ",":
				self._advance()

		if not self._current() or self._current().value != "]":
			raise PolicySyntaxError("Expected ']'", 0, 0)
		self._advance()  # Skip ]

		return items

	@staticmethod
	def to_dsl(policy: Policy) -> str:
		"""Convert a Policy object back to DSL text."""
		lines = []

		# Effect and actions
		effect = policy.effect.value.upper()
		actions = ", ".join(policy.actions)
		resources = ", ".join(policy.resource_types)
		lines.append(f"{effect} {actions} ON {resources}")

		# Conditions
		if policy.rules:
			conditions = []
			for rule in policy.rules:
				for cond in rule.conditions:
					cat = cond.category.value
					attr = cond.attribute
					op = cond.operator.value
					val = cond.value

					# Format value
					if isinstance(val, str):
						val_str = f'"{val}"'
					elif isinstance(val, list):
						val_str = "[" + ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in val) + "]"
					else:
						val_str = str(val)

					# Map operator to DSL
					op_map = {
						"eq": "=", "ne": "!=", "gt": ">", "gte": ">=",
						"lt": "<", "lte": "<=", "in": "IN", "not_in": "NOT_IN",
						"contains": "CONTAINS", "matches": "MATCHES",
						"is_member_of": "MEMBER_OF", "has_role": "HAS_ROLE",
						"in_department": "IN_DEPARTMENT",
					}
					op_str = op_map.get(op, op.upper())

					conditions.append(f"{cat}.{attr} {op_str} {val_str}")

			if conditions:
				logic = policy.rules[0].logic if policy.rules else "AND"
				lines.append("WHERE " + f" {logic} ".join(conditions))

		return "\n".join(lines)

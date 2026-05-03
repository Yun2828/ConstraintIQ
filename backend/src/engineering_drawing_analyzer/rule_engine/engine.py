"""Rule Engine framework for the Engineering Drawing Analyzer.

Defines the `VerificationRule` protocol and the `RuleEngine` class that
applies all registered rules against a `GeometricModel` and collects issues.
"""

import logging
import uuid
from typing import Protocol

from ..models import GeometricModel, Issue, LocationReference, Severity

logger = logging.getLogger(__name__)


class VerificationRule(Protocol):
    """Protocol that every verification rule must satisfy.

    Rules are stateless callables that inspect a `GeometricModel` and return
    zero or more `Issue` objects describing deficiencies found.
    """

    @property
    def rule_id(self) -> str:
        """Unique identifier for this rule, e.g. 'SIZE_DIMENSION_RULE'."""
        ...

    def check(self, model: GeometricModel) -> list[Issue]:
        """Inspect *model* and return any issues found.

        Returns an empty list when the model satisfies this rule.
        """
        ...


class RuleEngine:
    """Applies an ordered list of `VerificationRule` objects to a `GeometricModel`.

    Rules are executed in registration order.  If a rule raises an unexpected
    exception the engine catches it, logs the failure with the rule ID, appends
    an ``INFO``-severity issue noting the rule failure, and continues with the
    remaining rules so that a single broken rule never silences the rest.

    Args:
        rules: Ordered list of `VerificationRule` instances to apply.
    """

    def __init__(self, rules: list[VerificationRule]) -> None:
        self._rules = list(rules)

    def run(self, model: GeometricModel) -> list[Issue]:
        """Apply all registered rules to *model* and return the combined issue list.

        Per-rule exceptions are caught, logged, and converted to an ``INFO``
        issue so that the caller always receives a complete (possibly partial)
        list of issues rather than an unhandled exception.

        Args:
            model: The `GeometricModel` to verify.

        Returns:
            A flat list of all `Issue` objects produced by every rule.
        """
        issues: list[Issue] = []

        for rule in self._rules:
            try:
                rule_issues = rule.check(model)
                issues.extend(rule_issues)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Rule %s raised an unexpected exception: %s",
                    rule.rule_id,
                    exc,
                    exc_info=True,
                )
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=rule.rule_id,
                        issue_type="RULE_ENGINE_ERROR",
                        severity=Severity.INFO,
                        description=(
                            f"Rule '{rule.rule_id}' encountered an internal error "
                            f"and could not complete its check: {exc}"
                        ),
                        location=LocationReference(
                            view_name="UNKNOWN",
                            coordinates=None,
                            label=None,
                        ),
                        corrective_action=None,
                        standard_reference=None,
                    )
                )

        return issues

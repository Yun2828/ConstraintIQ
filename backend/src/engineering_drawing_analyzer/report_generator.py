"""Report Generator for the Engineering Drawing Analyzer.

Renders a VerificationReport from a GeometricModel and a list of Issues
into JSON, HTML, or PDF output bytes.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from .exceptions import UnsupportedReportFormatError
from .models import GeometricModel, Issue, ReportFormat, Severity, VerificationReport

# ---------------------------------------------------------------------------
# Template directory
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# ---------------------------------------------------------------------------
# Supported formats list (used in error messages)
# ---------------------------------------------------------------------------

_SUPPORTED_FORMATS = ["JSON", "HTML", "PDF"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_report(
    model: GeometricModel,
    issues: list[Issue],
) -> VerificationReport:
    """Assemble a VerificationReport from a model and its issues."""
    drawing_id = (
        model.title_block.part_number
        if model.title_block and model.title_block.part_number
        else "unknown"
    )
    analysis_timestamp = datetime.now(tz=timezone.utc).isoformat()
    overall_status = "Pass" if len(issues) == 0 else "Fail"

    # Count issues per severity
    issue_counts: dict[str, int] = {
        Severity.CRITICAL.value: 0,
        Severity.WARNING.value: 0,
        Severity.INFO.value: 0,
    }
    for issue in issues:
        key = issue.severity.value if isinstance(issue.severity, Severity) else str(issue.severity)
        if key in issue_counts:
            issue_counts[key] += 1

    # Detect systemic patterns: issue_type appearing more than 3 times
    type_counts: Counter[str] = Counter(issue.issue_type for issue in issues)
    systemic_patterns: list[str] = [
        f"Systemic pattern detected: '{issue_type}' appears {count} times across the drawing."
        for issue_type, count in type_counts.items()
        if count > 3
    ]

    return VerificationReport(
        drawing_id=drawing_id,
        analysis_timestamp=analysis_timestamp,
        overall_status=overall_status,
        issue_counts=issue_counts,
        issues=issues,
        systemic_patterns=systemic_patterns,
    )


def _report_to_dict(report: VerificationReport) -> dict:
    """Serialize a VerificationReport to a JSON-compatible dict."""
    issues_list = []
    for issue in report.issues:
        location = issue.location
        coordinates = None
        if location.coordinates is not None:
            coordinates = {"x": location.coordinates.x, "y": location.coordinates.y}

        issues_list.append(
            {
                "issue_id": issue.issue_id,
                "rule_id": issue.rule_id,
                "issue_type": issue.issue_type,
                "severity": issue.severity.value
                if isinstance(issue.severity, Severity)
                else str(issue.severity),
                "description": issue.description,
                "location": {
                    "view_name": location.view_name,
                    "coordinates": coordinates,
                    "label": location.label,
                },
                "corrective_action": issue.corrective_action,
                "standard_reference": issue.standard_reference,
            }
        )

    return {
        "drawing_id": report.drawing_id,
        "analysis_timestamp": report.analysis_timestamp,
        "overall_status": report.overall_status,
        "issue_counts": report.issue_counts,
        "issues": issues_list,
        "systemic_patterns": report.systemic_patterns,
    }


def _render_json(report: VerificationReport) -> bytes:
    """Serialize the report to JSON bytes."""
    data = _report_to_dict(report)
    return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")


def _render_html(report: VerificationReport) -> bytes:
    """Render the report to a self-contained HTML document using Jinja2."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:
        raise RuntimeError(
            "Jinja2 is required for HTML report generation. "
            "Install it with: pip install jinja2"
        ) from exc

    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("report.html.j2")
    html_str = template.render(report=report, Severity=Severity)
    return html_str.encode("utf-8")


def _render_pdf(report: VerificationReport) -> bytes:
    """Render the report to PDF bytes via WeasyPrint."""
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is required for PDF report generation. "
            "Install it with: pip install weasyprint"
        ) from exc

    html_bytes = _render_html(report)
    html_str = html_bytes.decode("utf-8")
    pdf_bytes: bytes = HTML(string=html_str).write_pdf()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class ReportGenerator:
    """Generates verification reports in JSON, HTML, or PDF format.

    The generator assembles a :class:`VerificationReport` internally from the
    provided ``model`` and ``issues``, then serializes it to the requested
    ``format``.
    """

    def generate(
        self,
        model: GeometricModel,
        issues: list[Issue],
        format: ReportFormat,  # noqa: A002  (shadows built-in, matches design spec)
    ) -> bytes:
        """Render the Verification Report.

        Args:
            model:  The :class:`GeometricModel` that was analyzed.
            issues: The list of :class:`Issue` objects produced by the rule engine.
            format: The desired output format (:class:`ReportFormat`).

        Returns:
            The report as raw bytes (UTF-8 encoded for JSON/HTML, binary for PDF).

        Raises:
            UnsupportedReportFormatError: If *format* is not one of
                ``ReportFormat.JSON``, ``ReportFormat.HTML``, or ``ReportFormat.PDF``.
        """
        if format not in (ReportFormat.JSON, ReportFormat.HTML, ReportFormat.PDF):
            raise UnsupportedReportFormatError(
                requested_format=str(format),
                supported_formats=_SUPPORTED_FORMATS,
            )

        report = _build_report(model, issues)

        if format == ReportFormat.JSON:
            return _render_json(report)
        elif format == ReportFormat.HTML:
            return _render_html(report)
        else:  # ReportFormat.PDF
            return _render_pdf(report)

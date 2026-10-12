"""Document generation validation for docgen.py output.

Validates that generated documents contain the required sections, have proper
encoding, and follow the structure rules defined in docgen-contract.json.

The contract at schemas/docgen-contract.json defines:
- Required sections per document type
- Validation rules (sections_exactly_once, encoding_utf8, etc.)
- Exit codes and refusal conditions

This module provides:
- validate(): returns a list of defect strings, empty means clean
- validate_json(): validates JSON document structure
"""

import json
import re
from pathlib import Path

__all__ = ["validate", "validate_json", "load_contract"]

_HERE = Path(__file__).resolve().parent
CONTRACT_PATH = _HERE.parent.parent / "schemas" / "docgen-contract.json"


def load_contract():
    """Load the docgen contract schema, letting the failure propagate.

    Swallowing it used to return an empty dict, and an empty contract means no
    required sections, no sections-exactly-once rule and none of the four
    validation flags -- so --validate answered PASS on a document that had been
    checked against nothing. report_qc refuses on the same condition, and for the
    same reason: a verdict with no rules behind it is the one false reassurance.
    """
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _get_required_sections(doc_type: str, contract: dict) -> list[str]:
    """Get required sections for a document type."""
    types = contract.get("document_types", {})
    doc_def = types.get(doc_type, {})
    sections = doc_def.get("required_sections", [])
    return [s.get("heading_anchor", "") for s in sections if s.get("heading_anchor")]


def validate(content: str, doc_type: str, contract: dict, format: str = "markdown") -> list[str]:
    """Validate a generated document. Returns defect strings, empty means clean.
    
    Args:
        content: The document content to validate
        doc_type: The type of document (class, table, onboarding)
        contract: The contract dictionary from docgen-contract.json
        format: The output format (markdown, json, html) - only markdown gets full validation
    """
    defects = []

    if not content:
        return ["document is empty"]

    # Check encoding. Read from the contract with a True default so the flag is a
    # real switch rather than decoration: the key was present in the schema and
    # the check ran regardless, so setting encoding_utf8 to false did nothing.
    val = contract.get("validation", {})
    if val.get("encoding_utf8", True) and "\ufffd" in content:
        defects.append("contains replacement character (U+FFFD)")

    # HTML format - only basic checks
    if format == "html":
        # Check for unclosed HTML tags (basic check)
        if content.count("<html") != content.count("</html>"):
            defects.append("unclosed html tag")
        if content.count("<body") != content.count("</body>"):
            defects.append("unclosed body tag")
        return defects

    # Markdown format - full validation
    # Check required sections. The schema declares required_sections under
    # validation and the list itself under document_types; before this check read
    # neither, so the key was decoration and a false value would have been ignored.
    if contract.get("validation", {}).get("required_sections", True):
        required = _get_required_sections(doc_type, contract)
        for section in required:
            if section and section not in content:
                defects.append(f"missing section: {section}")
    else:
        required = []

    # Check sections exactly once
    if contract.get("validation", {}).get("sections_exactly_once"):
        for section in required:
            if section and content.count(section) > 1:
                defects.append(f"section appears multiple times: {section}")

    # Check for unclosed code fences, gated by the flag that used to be read by
    # no caller at all.
    if contract.get("validation", {}).get("code_fences_closed", True):
        fence_count = content.count("```")
        if fence_count % 2 != 0:
            defects.append("unclosed code fence")

    # Check for line numbers in labels (should use anchors, not line numbers)
    if contract.get("validation", {}).get("no_line_numbers_in_labels"):
        line_num_pattern = re.compile(r"第\s*\d+\s*行|L\d{2,}")
        # Only check outside code fences
        in_fence = False
        for line in content.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and line_num_pattern.search(line):
                defects.append(f"line number reference in label: {line.strip()[:50]}")

    # Check mermaid safety
    if contract.get("validation", {}).get("mermaid_safe"):
        mermaid_fences = re.findall(r"```mermaid\n(.*?)```", content, re.DOTALL)
        for diagram in mermaid_fences:
            for char in ["<", ">", "#"]:
                if char in diagram:
                    defects.append(f"mermaid diagram contains unsafe character: {char}")

    # Check table well-formedness
    if contract.get("validation", {}).get("tables_well_formed"):
        lines = content.splitlines()
        in_table = False
        table_rows = 0
        for line in lines:
            if line.strip().startswith("|") and line.count("|") >= 2:
                if not in_table:
                    in_table = True
                    table_rows = 0
                table_rows += 1
                # Check separator row format
                if "---" in line and table_rows == 2:
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    if not all(re.match(r"-{3,}", c) for c in cells):
                        defects.append(f"malformed table separator: {line.strip()[:50]}")
            else:
                if in_table and table_rows >= 2:
                    in_table = False
                    table_rows = 0

    return defects


def validate_json(doc: dict, doc_type: str, contract: dict) -> list[str]:
    """Validate a JSON document. Returns defect strings, empty means clean."""
    defects = []

    if not doc:
        return ["document is empty"]

    # Check required top-level fields
    required_fields = ["document_type", "source_file", "total_lines", "generated_at"]
    for field in required_fields:
        if field not in doc:
            defects.append(f"missing required field: {field}")

    # Check document_type matches
    if doc.get("document_type") != doc_type:
        defects.append(f"document_type mismatch: expected '{doc_type}', got '{doc.get('document_type')}'")

    # Check type-specific required fields
    types = contract.get("document_types", {})
    if doc_type == "class":
        if "classes" not in doc:
            defects.append("missing 'classes' array")
    elif doc_type == "table":
        if "tables" not in doc:
            defects.append("missing 'tables' array")
    elif doc_type == "onboarding":
        for field in ["subprograms", "tables", "calls", "events"]:
            if field not in doc:
                defects.append(f"missing '{field}' array")

    return defects

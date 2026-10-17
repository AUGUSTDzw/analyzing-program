#!/usr/bin/env python3
"""
docgen.py - Document generator for ABAP programs.

Generates technical documentation from ABAP source code.

Document types:
  - class:     Class documentation (methods, interfaces, dependencies)
  - table:     Table structure documentation from SELECT statements
  - onboarding: Onboarding guide for new developers

Output formats:
  - markdown:  Markdown with code blocks (default)
  - json:      Structured JSON for programmatic consumption
  - html:      HTML with embedded CSS

Examples:
  python docgen.py --type class source.abap -o docs/
  python docgen.py --type table source.abap --format json -o docs/
  python docgen.py --type onboarding source.abap -o docs/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

# recon.py reads this script's stdout with text=True and encoding="utf-8", so a
# refusal that names a non-ASCII path must come back as bytes the parent can
# decode. Without this, the parent's strict decoder returns None for
# child.stdout and child.stdout + child.stderr raises TypeError -- recon then
# exits 1 with an empty stdout, and a refusal arrives in the form of a crash.
# report_qc.py and recon.py both reconfigure; this was the third script of the
# pipe that did not, and it is the one being read.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from checks.docgen import validate, validate_json, load_contract  # noqa: E402
from checks.source import has_content  # noqa: E402


def _die(msg: str, code: int = 2) -> None:
    """Print an error and exit with code 2.

    On stdout, like report_qc.py's die(): a caller that captures one stream and
    sees exit 2 should still see what was refused. stderr alone left the message
    invisible to the common case of reading stdout.
    """
    print(f"error  {msg}")
    sys.exit(code)


def _read_source(path: Path) -> str:
    """Read the ABAP source file with utf-8 validation."""
    if path.is_dir():
        # is_file() is False for a directory as well, so the "does not exist"
        # branch sent a reader hunting for a filename instead of telling them
        # they pointed at a folder. report_qc.py has a specific message for the
        # same input; this is the same refusal wearing a different shape.
        _die(f"source path is a directory, not a source file: {path}")
    if not path.is_file():
        _die(f"source path does not exist: {path}")
    if path.suffix.lower() in (".md", ".markdown"):
        # --validate only checks the document this tool just generated, so a
        # hand-written document handed in as the source gets parsed as ABAP, a
        # fresh document is generated about it, and the run ends with PASS.
        # That PASS was about the generated file, never about the document that
        # was handed in, and a caller reading the exit code could not tell.
        # Refusing here leaves that document without a verdict from this tool,
        # which is the honest answer: this is where it does have one.
        _die(f"source is a markdown file, not ABAP: {path} "
             f"(check a document with scripts/report_qc.py)")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _die(f"source is not utf-8: {path}")
    except OSError as e:
        # Kept apart from the clause above for the same reason recon.py keeps
        # them apart: a denial is not an encoding problem, and reporting it as
        # one sends a reader to re-save a file that was unreadable for another
        # reason. recon.py's OSError clause landed this release and this was the
        # third reader that missed it.
        _die(f"source cannot be read: {path} ({e})")
    if not has_content(text):
        # A source with nothing analysable in it yields a document about a program
        # that does not exist. --type onboarding and --type table both validated
        # that as PASS, because the validator checks structure and not whether the
        # document says anything. report_qc.py's --fidelity-only and recon.py
        # refuse the same shape, through the same predicate.
        _die(f"source has no analysable content: {path} (nothing to document)")
    return text


# ---------------------------------------------------------------------------
# Extraction functions - self-contained ABAP parsing
# ---------------------------------------------------------------------------

def _extract_subprograms(source: str) -> list[dict]:
    """Extract subprogram definitions from source."""
    subprograms = []
    seen_starts = set()

    # Method definitions
    # Two forms in the world: `METHOD foo.` (a class-pool implementation, by far
    # the common one) and `METHOD foo( EXPORTING ... )`. Anchoring on `\(` took
    # only the second, so a class with six methods was reported as having none
    # and the subprogram table fell back to the single event block. The
    # definition-block line `METHODS: constructor ,` is not matched: `\b` after
    # METHOD does not fire before the S, and `METHOD\s+` wants whitespace.
    #
    # The anchor indents with [ \t] rather than \s: \s also matches a newline,
    # so `^\s*METHOD` could start its match on the line above, and any
    # subprogram preceded by a blank line came back with an anchor one line
    # early. Horizontal whitespace only.
    method_re = re.compile(
        r"(?i)^[ \t]*METHOD\s+([A-Z0-9_]+)\b",
        re.MULTILINE,
    )
    for match in method_re.finditer(source):
        name = match.group(1)
        start = match.start()
        if start in seen_starts:
            continue
        seen_starts.add(start)

        # A METHOD block ends with ENDMETHOD, not END;. Searching for `END;`
        # found nothing and fell through to the +2000 default, so every method
        # body ran on past its own end into the next subprogram.
        body_end = _find_block_end(
            source, start, r"\bENDMETHOD\b")
        subprograms.append({
            "name": name,
            "kind": "METHOD",
            "start": start,
            "end": body_end,
            "anchor": _line_anchor(source, start),
        })

    # FORM definitions
    form_re = re.compile(
        r"(?i)^[ \t]*FORM\s+([A-Z0-9_]+)\b",
        re.MULTILINE,
    )
    for match in form_re.finditer(source):
        name = match.group(1)
        start = match.start()
        if start in seen_starts:
            continue
        seen_starts.add(start)

        body_end = _find_block_end(source, start, r"\bENDFORM\b")
        subprograms.append({
            "name": name,
            "kind": "FORM",
            "start": start,
            "end": body_end,
            "anchor": _line_anchor(source, start),
        })

    # Function module definitions
    func_re = re.compile(
        r"(?i)^[ \t]*FUNCTION\s+([A-Z0-9_]+)\b",
        re.MULTILINE,
    )
    for match in func_re.finditer(source):
        name = match.group(1)
        start = match.start()
        if start in seen_starts:
            continue
        seen_starts.add(start)

        body_end = _find_block_end(source, start, r"\bENDFUNCTION\b")
        subprograms.append({
            "name": name,
            "kind": "FUNCTION",
            "start": start,
            "end": body_end,
            "anchor": _line_anchor(source, start),
        })

    # Event blocks
    event_patterns = [
        (r"(?i)^AT\s+SELECTION-SCREEN\b", "AT SELECTION-SCREEN"),
        (r"(?i)^AT\s+PF\s+(\d+)\b", "AT PF"),
        (r"(?i)^AT\s+USER-COMMAND\b", "AT USER-COMMAND"),
        (r"(?i)^START-OF-SELECTION\b", "START-OF-SELECTION"),
        (r"(?i)^END-OF-SELECTION\b", "END-OF-SELECTION"),
        (r"(?i)^INITIALIZATION\b", "INITIALIZATION"),
        (r"(?i)^TOP-OF-PAGE\b", "TOP-OF-PAGE"),
    ]
    for pattern, kind in event_patterns:
        for match in re.finditer(pattern, source, re.MULTILINE):
            start = match.start()
            if start in seen_starts:
                continue
            seen_starts.add(start)
            subprograms.append({
                "name": match.group(0).strip(),
                "kind": kind,
                "start": start,
                "end": min(start + 500, len(source)),
                "anchor": _line_anchor(source, start),
            })

    return sorted(subprograms, key=lambda x: x["start"])


def _find_block_end(source: str, start: int, end_pattern: str) -> int:
    """Find the end of a block using a regex pattern.

    Callers pass the bare end keyword, e.g. `\\bENDMETHOD\\b`, not
    `ENDMETHOD method_name`. ABAP allows the terminator to carry the name
    (`ENDMETHOD zcl_test.`) but never requires it, and the shipped sources
    terminate bare. Requiring the name meant nothing matched, so every block
    ran to the end of the file and `end` was identical for every subprogram.
    """
    pattern = re.compile(end_pattern, re.IGNORECASE | re.MULTILINE)
    match = pattern.search(source, start + 10)
    return match.start() if match else min(start + 2000, len(source))


def _line_anchor(source: str, pos: int) -> str:
    """Return the 1-based line number for a position."""
    return str(source[:pos].count("\n") + 1)


def _extract_classes(source: str) -> list[dict]:
    """Extract class definitions from source."""
    classes = []

    class_def_re = re.compile(
        r"(?i)^[ \t]*CLASS\s+([A-Z0-9_]+)\s+DEFINITION\b",
        re.MULTILINE,
    )
    for match in class_def_re.finditer(source):
        class_name = match.group(1)
        body_start = match.end()

        # Find ENDCLASS
        endclass_re = re.compile(rf"(?i)ENDCLASS\s+{re.escape(class_name)}\b", re.MULTILINE)
        end_match = endclass_re.search(source, body_start)
        body_end = end_match.start() if end_match else len(source)
        body = source[body_start:body_end]

        # Extract methods
        methods = []
        method_re = re.compile(r"(?i)^[ \t]*METHOD\s+([A-Z0-9_]+)\b", re.MULTILINE)
        for m in method_re.finditer(body):
            methods.append(m.group(1))

        # Extract interfaces
        interfaces = []
        int_re = re.compile(r"(?i)^[ \t]*INTERFACES\s+([A-Z0-9_]+)\b", re.MULTILINE)
        for i in int_re.finditer(body):
            interfaces.append(i.group(1))

        # Extract inheritance
        inherits = None
        inh_re = re.compile(
            r"(?i)^[ \t]*(?:INHERITING\s+FROM|CREATE\s+(?:PUBLIC|PROTECTED|PRIVATE))\s+([A-Z0-9_]+)",
            re.MULTILINE,
        )
        inh_match = inh_re.search(body[:500])
        if inh_match:
            inherits = inh_match.group(1)

        # Extract class data
        class_data = []
        data_re = re.compile(r"(?i)^[ \t]*(?:DATA|TYPES|CONSTANTS)\s+([A-Z0-9_]+)\b", re.MULTILINE)
        for d in data_re.finditer(body):
            class_data.append(d.group(1))

        classes.append({
            "name": class_name,
            "methods": methods,
            "interfaces": interfaces,
            "inherits": inherits,
            "class_data": class_data[:20],  # Limit to 20
            "body_start": match.start(),
            "body_end": body_end,
        })

    return classes


def _extract_forms(source: str) -> list[dict]:
    """Extract FORM procedures from source."""
    forms = []
    form_re = re.compile(
        r"(?i)^[ \t]*FORM\s+([A-Z0-9_]+)\b",
        re.MULTILINE,
    )
    # The FORM header is the text up to its own terminating period, and it is
    # where USING lives. Three ways this has been wrong:
    #   grouping USING into the FORM regex with `.*?` matched empty, so no FORM
    #     ever reported a parameter;
    #   stopping at the first period only, which dropped everything after a
    #     CONTINUE in `USING p_b TYPE i CONTINUE p_c TYPE string.`;
    #   reading "everything after USING", which let a `PERFORM other USING` in
    #     the body masquerade as this FORM's own parameter list.
    # So the header must start with USING or CONTINUE, and the clause is split
    # on CONTINUE as well as on comma and AND.
    header_re = re.compile(r"(?i)^[ \t\n]*(?:USING|CONTINUE)\b[ \t\n]*(.+)\Z",
                           re.DOTALL)
    for match in form_re.finditer(source):
        form_name = match.group(1)

        body_start = match.end()
        end_marker = re.search(r"(?i)ENDFORM\b", source[body_start:], re.MULTILINE)
        body_end = body_start + end_marker.start() if end_marker else len(source)

        # Bounded to this FORM's own body: an unbounded search would walk past
        # the terminator and steal the next FORM's parameter list.
        scope = source[body_start:body_end]
        dot = scope.find(".")
        header = scope[:dot] if dot != -1 else scope
        params_expr = ""
        head = header_re.match(header)
        if head:
            params_expr = head.group(1).strip()

        # Parse parameters
        params = []
        if params_expr:
            for p in re.split(r",|\bAND\b|\bCONTINUE\b", params_expr):
                p = p.strip()
                if p:
                    params.append(p)

        forms.append({
            "name": form_name,
            "parameters": params,
            "body_start": match.start(),
            "body_end": body_end,
        })

    return forms


def _extract_tables(source: str) -> list[dict]:
    """Extract table references from SELECT statements."""
    tables = []
    seen = set()

    # SELECT ... FROM table_name
    select_re = re.compile(
        r"(?i)\bSELECT\s+(?:SINGLE\s+)?(?:\*|[A-Z0-9_.,\s+]+?)\s+FROM\s+([A-Z0-9_]+)",
        re.DOTALL,
    )
    for match in select_re.finditer(source):
        table_name = match.group(1).strip()
        if table_name not in seen and not table_name.startswith("("):
            seen.add(table_name)
            ctx_start = max(0, match.start() - 50)
            ctx_end = min(len(source), match.end() + 100)
            tables.append({
                "name": table_name,
                "context": source[ctx_start:ctx_end],
                "position": match.start(),
            })

    # INTO TABLE references
    into_table_re = re.compile(r"(?i)\bINTO\s+TABLE\s+([A-Z0-9_]+)", re.IGNORECASE)
    for match in into_table_re.finditer(source):
        name = match.group(1).strip()
        if name not in seen and not name.upper().startswith(("WS_", "LT_", "GT_")):
            seen.add(name)
            tables.append({
                "name": name,
                "context": source[max(0, match.start()-50):min(len(source), match.end()+100)],
                "position": match.start(),
            })

    return sorted(tables, key=lambda x: x["position"])


def _extract_calls(source: str) -> list[dict]:
    """Extract function and method calls from source."""
    calls = []

    # CALL FUNCTION. The name is usually quoted -- CALL FUNCTION 'Z_BC_LOG'. --
    # and the original character class took only [A-Z0-9_], so the most common
    # call form in ABAP produced no record at all.
    for match in re.finditer(r"(?i)\bCALL\s+FUNCTION\s+['\"]?([A-Z0-9_]+)['\"]?", source):
        func_name = match.group(1)
        line_end = source.find("\n", match.start())
        if line_end == -1:
            line_end = len(source)
        context = source[match.start():line_end]

        calls.append({
            "type": "FUNCTION",
            "name": func_name,
            "context": context[:200],
            "position": match.start(),
        })

    # CALL METHOD
    for match in re.finditer(r"(?i)\bCALL\s+METHOD\s+(.+?)\s*\(", source):
        method_expr = match.group(1).strip()
        calls.append({
            "type": "METHOD",
            "name": method_expr,
            "context": match.group(0)[:200],
            "position": match.start(),
        })

    # ->method( pattern
    for match in re.finditer(r"->[a-zA-Z_][a-zA-Z0-9_]*\s*\(", source):
        method_expr = match.group(0).rstrip("(").strip()
        calls.append({
            "type": "METHOD",
            "name": method_expr,
            "context": match.group(0)[:200],
            "position": match.start(),
        })

    return sorted(calls, key=lambda x: x["position"])


def _extract_events(source: str) -> list[dict]:
    """Extract event blocks from source."""
    events = []
    event_re = re.compile(
        r"(?i)^(?:AT\s+SELECTION-SCREEN|AT\s+PF\s+\d+|AT\s+USER-COMMAND|START-OF-SELECTION|END-OF-SELECTION|INITIALIZATION|TOP-OF-PAGE)\b",
        re.MULTILINE,
    )
    for match in event_re.finditer(source):
        events.append({
            "event": match.group(0).strip(),
            "position": match.start(),
            "line": _line_anchor(source, match.start()),
        })
    return events


# ---------------------------------------------------------------------------
# Document generation functions
# ---------------------------------------------------------------------------

def _generate_class_doc(source: str, classes: list[dict], calls: list[dict]) -> str:
    """Generate class documentation in markdown."""
    lines = []
    lines.append("# 类文档")
    lines.append("")

    if not classes:
        lines.append("*未发现 ABAP 类定义*")
        return "\n".join(lines)

    for cls in classes:
        lines.append(f"## 类 {cls['name']}")
        lines.append("")

        # Class info
        lines.append("### 类信息")
        lines.append("")
        lines.append(f"- **类名**: {cls['name']}")
        if cls.get("inherits"):
            lines.append(f"- **继承自**: {cls['inherits']}")
        if cls.get("interfaces"):
            lines.append(f"- **实现接口**: {', '.join(cls['interfaces'])}")
        lines.append("")

        # Methods
        lines.append("### 方法列表")
        lines.append("")
        if cls.get("methods"):
            lines.append("| 方法名 |")
            lines.append("|--------|")
            for m in cls["methods"]:
                lines.append(f"| `{m}` |")
        else:
            lines.append("*未发现方法定义*")
        lines.append("")

        # Class data
        if cls.get("class_data"):
            lines.append("### 类数据")
            lines.append("")
            for d in cls["class_data"]:
                lines.append(f"- `{d}`")
            lines.append("")

        # Dependencies (calls within this class)
        lines.append("### 依赖关系")
        lines.append("")
        cls_calls = [c for c in calls if cls["body_start"] <= c["position"] < cls["body_end"]]
        if cls_calls:
            func_calls = [c for c in cls_calls if c["type"] == "FUNCTION"]
            method_calls = [c for c in cls_calls if c["type"] == "METHOD"]

            if func_calls:
                lines.append("**函数调用**:")
                lines.append("")
                for c in func_calls:
                    lines.append(f"- `{c['name']}`")
                lines.append("")

            if method_calls:
                lines.append("**方法调用**:")
                lines.append("")
                for c in method_calls:
                    lines.append(f"- `{c['name']}`")
                lines.append("")
        else:
            lines.append("*未发现外部调用*")
        lines.append("")

    return "\n".join(lines)


def _generate_table_doc(source: str, tables: list[dict]) -> str:
    """Generate table documentation in markdown."""
    lines = []
    lines.append("# 数据表文档")
    lines.append("")

    # Table list
    lines.append("## 数据表清单")
    lines.append("")
    if tables:
        lines.append("| 表名 | 使用场景 |")
        lines.append("|------|----------|")
        for t in tables:
            ctx = t.get("context", "")
            if "SELECT" in ctx.upper():
                scenario = "SELECT 查询"
            elif "INTO" in ctx.upper():
                scenario = "INTO 目标"
            else:
                scenario = "数据访问"
            lines.append(f"| `{t['name']}` | {scenario} |")
    else:
        lines.append("*未发现数据表引用*")
    lines.append("")

    # Fields
    lines.append("## 字段使用")
    lines.append("")
    lines.append("*需要人工分析 SELECT 语句中的字段引用*")
    lines.append("")

    return "\n".join(lines)


def _generate_onboarding_doc(source: str, subprograms: list[dict], tables: list[dict], calls: list[dict], events: list[dict]) -> str:
    """Generate onboarding documentation in markdown."""
    lines = []
    lines.append("# 开发者入门指南")
    lines.append("")

    # Overview
    lines.append("## 程序概览")
    lines.append("")
    total_lines = len(source.splitlines())
    lines.append(f"- **总代码行数**: {total_lines}")
    lines.append(f"- **子程序数量**: {len(subprograms)}")
    lines.append(f"- **数据表引用**: {len(tables)}")
    lines.append(f"- **外部调用**: {len(calls)}")
    lines.append(f"- **事件块**: {len(events)}")
    lines.append("")

    # Setup
    lines.append("## 环境配置")
    lines.append("")
    lines.append("1. **SAP 系统访问**: 需要相应的系统权限")
    lines.append("2. **SE38/SE80**: 打开程序进行编辑和调试")
    lines.append("3. **传输请求**: 修改前需创建传输请求")
    lines.append("")

    # Run
    lines.append("## 运行方法")
    lines.append("")
    lines.append("1. **事务码**: 查看程序属性中的入口点")
    lines.append("2. **选择屏幕**: 输入必要的选择参数")
    lines.append("3. **执行**: F8 或点击执行按钮")
    lines.append("")

    # Debug
    lines.append("## 调试指南")
    lines.append("")
    lines.append("1. **断点设置**: 在 SE38 中设置断点")
    lines.append("2. **单步执行**: F5 (进入), F6 (跳出), F7 (单步)")
    lines.append("3. **变量监视**: 添加变量到监视列表")
    lines.append("4. **调用堆栈**: 查看程序调用堆栈")
    lines.append("")

    # Key subprograms
    if subprograms:
        lines.append("## 关键子程序")
        lines.append("")
        lines.append("| 子程序名 | 类型 | 起始行 |")
        lines.append("|----------|------|--------|")
        for sp in subprograms[:20]:
            kind = sp.get("kind", "unknown")
            anchor = sp.get("anchor", "?")
            lines.append(f"| `{sp['name']}` | {kind} | {anchor} |")
        if len(subprograms) > 20:
            lines.append(f"| ... | (还有 {len(subprograms) - 20} 个) | |")
        lines.append("")

    # Troubleshooting
    lines.append("## 常见问题")
    lines.append("")
    lines.append("1. **短转储**: 检查数据访问权限和表存在性")
    lines.append("2. **权限错误**: 确认用户角色包含必要的对象权限")
    lines.append("3. **选择屏幕**: 确保所有必填参数已填写")
    lines.append("4. **性能问题**: 检查 SELECT 语句是否有索引优化空间")
    lines.append("")

    return "\n".join(lines)


def _generate_json_doc(source: str, doc_type: str, source_file: str, **kwargs) -> dict:
    """Generate JSON documentation."""
    doc = {
        "document_type": doc_type,
        "source_file": source_file,
        "total_lines": len(source.splitlines()),
        "generated_at": datetime.now().isoformat(),
    }

    if doc_type == "class":
        doc["classes"] = kwargs.get("classes", [])
        doc["calls"] = kwargs.get("calls", [])
    elif doc_type == "table":
        doc["tables"] = kwargs.get("tables", [])
    elif doc_type == "onboarding":
        doc["subprograms"] = kwargs.get("subprograms", [])
        doc["tables"] = kwargs.get("tables", [])
        doc["calls"] = kwargs.get("calls", [])
        doc["events"] = kwargs.get("events", [])

    return doc


def _generate_html_doc(markdown_content: str) -> str:
    """Generate simple HTML from markdown content."""
    html_lines = []
    html_lines.append("<!DOCTYPE html>")
    html_lines.append("<html><head><meta charset='utf-8'>")
    html_lines.append("<style>")
    html_lines.append("body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; color: #333; }")
    html_lines.append("h1, h2, h3 { color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 8px; }")
    html_lines.append("code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: 'Fira Code', monospace; font-size: 0.9em; }")
    html_lines.append("pre { background: #f8f8f8; padding: 16px; border-radius: 6px; overflow-x: auto; border: 1px solid #e0e0e0; }")
    html_lines.append("table { border-collapse: collapse; width: 100%; margin: 16px 0; }")
    html_lines.append("th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }")
    html_lines.append("th { background: #f4f4f4; font-weight: 600; }")
    html_lines.append("tr:nth-child(even) { background: #f9f9f9; }")
    html_lines.append("li { margin: 4px 0; }")
    html_lines.append("</style></head><body>")

    in_table = False
    in_pre = False
    table_headers_done = False

    for line in markdown_content.splitlines():
        if line.startswith("# "):
            if in_table:
                html_lines.append("</table>")
                in_table = False
                table_headers_done = False
            html_lines.append(f"<h1>{_escape_html(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_table:
                html_lines.append("</table>")
                in_table = False
                table_headers_done = False
            html_lines.append(f"<h2>{_escape_html(line[3:])}</h2>")
        elif line.startswith("### "):
            if in_table:
                html_lines.append("</table>")
                in_table = False
                table_headers_done = False
            html_lines.append(f"<h3>{_escape_html(line[4:])}</h3>")
        elif line.startswith("```"):
            if not in_pre:
                html_lines.append("<pre><code>")
                in_pre = True
            else:
                html_lines.append("</code></pre>")
                in_pre = False
            continue
        elif in_pre:
            html_lines.append(_escape_html(line))
            continue
        elif line.startswith("|"):
            if "---" in line:
                table_headers_done = True
                continue
            if line.count("|") >= 2:
                cells = [_escape_html(c.strip()) for c in line.split("|")[1:-1]]
                if not in_table:
                    html_lines.append("<table><tr>")
                    html_lines[-1] = "<table><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>"
                    in_table = True
                elif table_headers_done:
                    html_lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
                else:
                    html_lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
                    table_headers_done = True
            continue
        elif line.strip() == "":
            if in_table:
                html_lines.append("</table>")
                in_table = False
                table_headers_done = False
            html_lines.append("")
        elif line.startswith("- "):
            html_lines.append(f"<li>{_escape_html(line[2:])}</li>")
        elif line.strip():
            html_lines.append(f"<p>{_escape_html(line)}</p>")

    if in_table:
        html_lines.append("</table>")
    if in_pre:
        html_lines.append("</code></pre>")
    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate documentation from ABAP source code",
    )
    parser.add_argument("source", help="Path to ABAP source file")
    parser.add_argument("--type", choices=["class", "table", "onboarding"], default="onboarding",
                        help="Document type to generate (default: onboarding)")
    parser.add_argument("--format", choices=["markdown", "json", "html"], default="markdown",
                        help="Output format (default: markdown)")
    parser.add_argument("-o", "--output", help="Output directory (default: same as source)")
    parser.add_argument("--validate", action="store_true", help="Validate document structure")

    args = parser.parse_args()

    # Load contract. A missing or unreadable schema is a refusal, not an empty
    # rule set: validating against nothing prints PASS, which is the false
    # reassurance --validate must not give. ValueError covers both
    # JSONDecodeError and the UnicodeDecodeError that read_text raises for a
    # non-UTF-8 schema, which the earlier pair let through as exit 1. KeyError
    # and TypeError are the presence and shape checks inside load_contract(): a
    # schema that parses but carries no document_types, or carries one that is not
    # an object, used to escape this guard and raise AttributeError out of
    # validate().
    try:
        contract = load_contract()
    except (OSError, ValueError, KeyError, TypeError) as e:
        _die(f"cannot read the contract at {Path(__file__).resolve().parent.parent / 'schemas' / 'docgen-contract.json'}: {e}")

    # Read source
    source_path = Path(args.source)
    source = _read_source(source_path)

    # Extract information
    subprograms = _extract_subprograms(source)
    classes = _extract_classes(source)
    forms = _extract_forms(source)
    tables = _extract_tables(source)
    calls = _extract_calls(source)
    events = _extract_events(source)

    # Generate documentation
    if args.type == "class":
        if args.format == "json":
            doc = _generate_json_doc(source, "class", str(source_path), classes=classes, calls=calls)
            output_content = json.dumps(doc, indent=2, ensure_ascii=False)
        else:
            output_content = _generate_class_doc(source, classes, calls)
    elif args.type == "table":
        if args.format == "json":
            doc = _generate_json_doc(source, "table", str(source_path), tables=tables)
            output_content = json.dumps(doc, indent=2, ensure_ascii=False)
        else:
            output_content = _generate_table_doc(source, tables)
    elif args.type == "onboarding":
        if args.format == "json":
            doc = _generate_json_doc(source, "onboarding", str(source_path),
                                      subprograms=subprograms, tables=tables, calls=calls, events=events)
            output_content = json.dumps(doc, indent=2, ensure_ascii=False)
        else:
            output_content = _generate_onboarding_doc(source, subprograms, tables, calls, events)
    else:
        _die(f"unknown document type: {args.type}")

    # Convert to HTML if needed
    if args.format == "html":
        output_content = _generate_html_doc(output_content)

    # Validate if requested. The format is passed through: without it validate()
    # fell back to "markdown" and checked an HTML document for markdown headings,
    # which it cannot contain by construction. And validation does not stop the
    # write -- the caller asked for a document, and rc=1 already says it carries
    # defects, so returning here left nothing on disk to look at.
    had_defects = False
    if args.validate:
        if args.format == "json":
            try:
                doc = json.loads(output_content)
                defects = validate_json(doc, args.type, contract)
            except json.JSONDecodeError:
                defects = ["invalid JSON"]
        else:
            defects = validate(output_content, args.type, contract, args.format)
        if defects:
            print(f"FAIL  document validation ({len(defects)} defect(s))")
            for d in defects:
                print(f"  - {d}")
            had_defects = True
        else:
            print("PASS  document validation")

    # Determine output path
    if args.output:
        output_dir = Path(args.output)
        if not output_dir.exists():
            _die(f"output path directory does not exist: {output_dir}")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            _die(f"output path directory is not writable: {output_dir} ({e})")
    else:
        output_dir = source_path.parent

    # Determine output filename
    base_name = source_path.stem
    ext_map = {"markdown": ".md", "json": ".json", "html": ".html"}
    output_ext = ext_map[args.format]
    output_file = output_dir / f"{base_name}.{args.type}{output_ext}"

    # Write output
    try:
        output_file.write_text(output_content, encoding="utf-8")
    except OSError as e:
        _die(f"cannot write output file: {output_file} ({e})")

    print(f"Generated: {output_file}")
    print(f"  Type: {args.type}")
    print(f"  Format: {args.format}")
    print(f"  Size: {len(output_content)} bytes")

    return 1 if had_defects else 0


if __name__ == "__main__":
    sys.exit(main())

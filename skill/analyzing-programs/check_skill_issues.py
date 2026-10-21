#!/usr/bin/env python3
"""Check for issues in the analyzing-programs skill."""
import json, os, sys

SKILL_DIR = r"D:\Workspace\Skills\analyzing-programs\skill\analyzing-programs"
os.chdir(SKILL_DIR)

issues = []

# 1. Version consistency
with open("SKILL.md", encoding="utf-8") as f:
    text = f.read()
lines = text.split("\n")
skill_version = skill_contract = None
for l in lines:
    if l.startswith("version:"):
        skill_version = l.split(":")[1].strip()
    elif l.startswith("contract:"):
        skill_contract = l.split(":")[1].strip()

sc = json.load(open("schemas/skill-contract.json", encoding="utf-8"))
rc = json.load(open("schemas/report-contract.json", encoding="utf-8"))

print("=== Version Consistency ===")
print(f"  SKILL.md version:       {skill_version}")
print(f"  SKILL.md contract:      {skill_contract}")
print(f"  report-contract version:{rc['version']}")
print(f"  report-contract ships:  {rc.get('release', {}).get('ships_with', 'N/A')}")
print(f"  skill-contract ships:   {sc['ships_with']}")

if skill_version != rc.get("release", {}).get("ships_with"):
    issues.append(f"SKILL.md version ({skill_version}) != report-contract ships_with ({rc.get('release', {}).get('ships_with', 'N/A')})")
if skill_contract != rc["version"]:
    issues.append(f"SKILL.md contract ({skill_contract}) != report-contract version ({rc['version']})")
if skill_version != sc["ships_with"]:
    issues.append(f"SKILL.md version ({skill_version}) != skill-contract ships_with ({sc['ships_with']})")

# 2. Check all scripts exist and are listed in SKILL.md
print("\n=== Script Inventory ===")
scripts_dir = "scripts"
actual_scripts = sorted(f for f in os.listdir(scripts_dir) if f.endswith(".py"))
skill_text = text

for s in actual_scripts:
    in_skill = s in skill_text
    print(f"  {s:40s} {'OK' if in_skill else 'MISSING from SKILL.md'}")
    if not in_skill:
        issues.append(f"Script {s} not documented in SKILL.md")

# 3. Check all tests exist
print("\n=== Test Inventory ===")
tests_dir = "tests"
actual_tests = sorted(f for f in os.listdir(tests_dir) if f.endswith(".py"))
for t in actual_tests:
    in_readme = t in open("README.md", encoding="utf-8").read()
    print(f"  {t:40s} {'OK' if in_readme else 'MISSING from README.md'}")

# 4. Check schemas
print("\n=== Schema Inventory ===")
schemas_dir = "schemas"
actual_schemas = sorted(f for f in os.listdir(schemas_dir) if f.endswith(".json"))
for s in actual_schemas:
    print(f"  {s}")

# 5. Check frontmatter
print("\n=== Frontmatter Check ===")
if not text.startswith("---"):
    issues.append("SKILL.md does not start with frontmatter delimiter '---'")
else:
    parts = text.split("---")
    if len(parts) >= 2:
        fm = parts[1]
        for field in ["name:", "version:", "contract:", "description:"]:
            if field not in fm:
                issues.append(f"Frontmatter missing field: {field}")
        desc_line = [l for l in fm.split("\n") if l.startswith("description:")]
        if desc_line:
            desc = desc_line[0].split(":", 1)[1].strip()
            if len(desc) < 50:
                issues.append(f"Description too short ({len(desc)} chars): {desc[:50]}...")

# 6. Check references
print("\n=== References Check ===")
refs_dir = "references"
if os.path.isdir(refs_dir):
    ref_files = sorted(os.listdir(refs_dir))
    print(f"  {len(ref_files)} files")
    # Check example-report exists
    if "example-report.md" not in ref_files:
        issues.append("references/example-report.md not found")
else:
    issues.append("references/ directory not found")

# 7. Check evals
print("\n=== Evals Check ===")
evals_dir = "evals"
if os.path.isdir(evals_dir):
    eval_files = sorted(f for f in os.listdir(evals_dir) if f.endswith(".json"))
    print(f"  {len(eval_files)} defect files")
else:
    issues.append("evals/ directory not found")

# 8. Check scripts/checks/
print("\n=== Scripts/checks/ Check ===")
checks_dir = "scripts/checks"
if os.path.isdir(checks_dir):
    check_files = sorted(f for f in os.listdir(checks_dir) if f.endswith(".py"))
    print(f"  {len(check_files)} modules: {', '.join(check_files)}")
else:
    issues.append("scripts/checks/ directory not found")

# 9. Check abaplint-deps
print("\n=== abaplint-deps Check ===")
deps_dir = "abaplint-deps"
if os.path.isdir(deps_dir):
    abap_files = sum(1 for root, _, files in os.walk(deps_dir) for f in files if f.endswith(".abap"))
    print(f"  {abap_files} .abap files")
else:
    issues.append("abaplint-deps/ directory not found")

# Summary
print("\n" + "=" * 60)
if issues:
    print(f"ISSUES FOUND ({len(issues)}):")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
else:
    print("NO ISSUES FOUND")

sys.exit(0)

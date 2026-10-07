# flow_logic 运行日志

每条记录：shell 命令原文 + 退出码。仅记录命令与退出码。

---

### 1

```powershell
Get-ChildItem -Recurse -Force "C:\Users\DzwU\.agents\skills\analyzing-programs" | Select-Object -ExpandProperty FullName
```

退出码：未在执行时捕获（PowerShell 管道，无原生退出码）

### 2

```powershell
Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"
```

退出码：未在执行时捕获（PowerShell cmdlet）

### 3

```powershell
(Get-Content "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" | Measure-Object -Line).Lines
```

退出码：未在执行时捕获（PowerShell cmdlet）

### 4

```powershell
$p="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"; $l=Get-Content -LiteralPath $p -Encoding UTF8; "lines=$($l.Count)"; "--- last 6 ---"; $l[-6..-1]
```

退出码：未在执行时捕获（PowerShell cmdlet）

### 5

```powershell
$p="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"; $l=Get-Content -LiteralPath $p -Encoding UTF8; "lines=$($l.Count)"; [System.IO.File]::ReadAllLines($p, [System.Text.Encoding]::UTF8)[-1]
```

退出码：未在执行时捕获（PowerShell cmdlet）

### 6

```powershell
$out="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; $src="D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; python --version; python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" --fidelity-only "$out\flow_logic.report.md" "$src"; "EXITCODE=$LASTEXITCODE"
```

退出码：1

### 7

```powershell
$out="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; $src="D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; @'
import sys, io, os
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"
srcp = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"
s = io.open(rep, encoding="utf-8").read()
src = io.open(srcp, encoding="utf-8", newline="").read()
sf = q._flat(src)
for st, bs, be, en, lang in q.fence_spans(s):
    if lang != "abap":
        continue
    base = q.line_of(s, st)
    for i, l in q._claims(s[bs:be]):
        probe = l.strip().rstrip(".")
        if probe and q._flat(probe) not in sf:
            print("report line %d: %r" % (base + 1 + i, l.strip()))
'@ | Set-Content -Path "$env:TEMP\opencode\fid.py" -Encoding UTF8; python "$env:TEMP\opencode\fid.py"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 8

```powershell
@'
import sys, io, re
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"
s = io.open(rep, encoding="utf-8").read().split("\n")
for n in (704,705,706,707,708):
    print(n, repr(s[n-1]))
probe = "cs_information     = rs_information )"
print("flat(probe) =", repr(q._flat(probe)))
print("in src?", q._flat(probe) in q._flat(io.open(r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap", encoding="utf-8", newline="").read()))
src = io.open(r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap", encoding="utf-8", newline="").read().split("\n")
print("src840 =", repr(src[839]))
print("flat(src840) =", repr(q._flat(src[839])))
'@ | Set-Content -Path "$env:TEMP\opencode\dbg.py" -Encoding UTF8; python "$env:TEMP\opencode\dbg.py"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 9

```powershell
@'
import sys, io
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"
srcp = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"
s = io.open(rep, encoding="utf-8").read()
sf = q._flat(io.open(srcp, encoding="utf-8", newline="").read())
for st, bs, be, en, lang in q.fence_spans(s):
    if lang != "abap":
        continue
    base = q.line_of(s, st)
    for i, l in q._claims(s[bs:be]):
        probe = l.strip().rstrip(".")
        if probe and q._flat(probe) not in sf:
            print("FAIL line", base+1+i)
            print("  raw l =", repr(l))
            print("  probe =", repr(probe))
            print("  flat  =", repr(q._flat(probe)))
            print("  chars =", [hex(ord(c)) for c in probe if not c.isalnum() and c != "_"])
'@ | Set-Content -Path "$env:TEMP\opencode\dbg2.py" -Encoding UTF8; python "$env:TEMP\opencode\dbg2.py"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 10

```powershell
@'
import sys, io
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
srcp = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"
sf = q._flat(io.open(srcp, encoding="utf-8", newline="").read())
for t in ["cs_information = rs_consolidate);", "cs_information = rs_consolidate)",
          "cs_information = rs_information);", "cs_information = rs_information)",
          "errors_from_transports(", "it_all_transports = lt_real_transports"]:
    print(repr(t), "->", t in sf)
src = io.open(srcp, encoding="utf-8", newline="").read()
i = sf.find("rs_consolidate")
print("ctx:", repr(sf[i-60:i+60]))
'@ | Set-Content -Path "$env:TEMP\opencode\dbg3.py" -Encoding UTF8; python "$env:TEMP\opencode\dbg3.py"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 11

```powershell
$out="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; $src="D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" --fidelity-only "$out\flow_logic.report.md" "$src"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 12

```powershell
$out="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; $src="D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" "$out\flow_logic.report.md" "$src"; "EXITCODE=$LASTEXITCODE"
```

退出码：1

### 13

```powershell
$out="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; $src="D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" "$out\flow_logic.report.md" "$src"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 14

```powershell
$out="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; $src="D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" --fidelity-only "$out\flow_logic.report.md" "$src"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

### 15

```powershell
Get-ChildItem -Recurse -Force "C:\Users\DzwU\.agents\skills\analyzing-programs" | Select-Object -ExpandProperty FullName | Out-Null; "EXITCODE=$LASTEXITCODE"
```

退出码：`$LASTEXITCODE` 为空（PowerShell 管道，非原生可执行文件）

### 16

```powershell
$r=@{}
$r['1'] = (Get-ChildItem -Recurse -Force "C:\Users\DzwU\.agents\skills\analyzing-programs" | Select-Object -ExpandProperty FullName | Out-Null; $?)
$r['2'] = (Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs"; Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; $?)
$r['3'] = ((Get-Content "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" | Measure-Object -Line).Lines; $?)
$p="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"
$r['4'] = ($l=Get-Content -LiteralPath $p -Encoding UTF8; "lines=$($l.Count)"; $l[-6..-1] | Out-Null; $?)
$r['5'] = ($l=Get-Content -LiteralPath $p -Encoding UTF8; [System.IO.File]::ReadAllLines($p, [System.Text.Encoding]::UTF8)[-1] | Out-Null; $?)
foreach($k in '1','2','3','4','5'){ "cmd$k success=$($r[$k])" }
```

退出码：ParserError（命令未执行）

### 17

```powershell
$p="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"
& { Get-ChildItem -Recurse -Force "C:\Users\DzwU\.agents\skills\analyzing-programs" | Select-Object -ExpandProperty FullName | Out-Null; "cmd1 ok=$?" }
& { Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs" | Out-Null; Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap" | Out-Null; "cmd2 ok=$?" }
& { (Get-Content "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" | Measure-Object -Line).Lines | Out-Null; "cmd3 ok=$?" }
& { $l=Get-Content -LiteralPath $p -Encoding UTF8; "lines=$($l.Count)" | Out-Null; $l[-6..-1] | Out-Null; "cmd4 ok=$?" }
& { $l=Get-Content -LiteralPath $p -Encoding UTF8; "lines=$($l.Count)" | Out-Null; [System.IO.File]::ReadAllLines($p, [System.Text.Encoding]::UTF8)[-1] | Out-Null; "cmd5 ok=$?" }
"EXITCODE=$LASTEXITCODE"
```

退出码：0（cmd1..cmd5 全部 `ok=True`；`$LASTEXITCODE` 为空）

### 18

```powershell
@'
import sys, io
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\flow_logic\run-1\outputs\flow_logic.report.md"
srcp = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"
s = io.open(rep, encoding="utf-8").read()
inv = q.inventory(io.open(srcp, encoding="utf-8", newline="").read())
blocks = len(list(q.source_blocks(s)))
named = sum(1 for n in inv if n.lower() in s.lower())
print("declared subprograms:", len(inv))
print("quoted abap blocks:", blocks)
print("density: %.2f" % (blocks/len(inv)))
print("named in text: %d/%d" % (named, len(inv)))
print("sections:", [n for n in inv if n.lower() not in s.lower()])
print("density_note:", q.density_note(s, io.open(srcp, encoding="utf-8", newline="").read()))
print("fidelity_note:", q.fidelity_note(s, io.open(srcp, encoding="utf-8", newline="").read()))
print("fix_lang_note:", q.fix_lang_note(s))
print("fix_mislabel:", q.fix_mislabel_note(s, io.open(srcp, encoding="utf-8", newline="").read()))
'@ | Set-Content -Path "$env:TEMP\opencode\stats.py" -Encoding UTF8; python "$env:TEMP\opencode\stats.py"; "EXITCODE=$LASTEXITCODE"
```

退出码：0

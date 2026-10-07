# flow_logic.run-log

本次执行（skill `analyzing-programs`，源码 `zcl_abapgit_flow_logic.clas.abap`）所执行过的全部 shell 命令原文与退出码。

---

## 1

```powershell
Get-ChildItem -LiteralPath "C:\Users\DzwU\.agents\skills\analyzing-programs" -Recurse -File | Select-Object -ExpandProperty FullName
```

退出码：`0`

---

## 2

```powershell
Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; (Get-Item -LiteralPath "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap").Length
```

退出码：`0`

---

## 3

```powershell
python --version; python -c "import sys; print(sys.executable)"
```

退出码：`0`

---

## 4

```powershell
New-Item -ItemType Directory -Force -Path "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\flow_logic\run-1\outputs" | Select-Object -ExpandProperty FullName
```

退出码：`0`

---

## 5

```powershell
python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" --fidelity-only "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\flow_logic\run-1\outputs\flow_logic.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; "EXIT=$LASTEXITCODE"
```

退出码：`1`

---

## 6

```powershell
$py = @'
import io, re, sys
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\flow_logic\run-1\outputs\flow_logic.report.md"
src = io.open(r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap", encoding="utf-8").read()
s = io.open(rep, encoding="utf-8").read()
sf = q._flat(src)
n = 0
for m in re.finditer(r"```%s\n(.*?)```" % q.QUOTE_LANG, s, re.S):
    base = s[:m.start()].count("\n") + 1
    for i, l in enumerate(q._claims(m.group(1))):
        n += 1
        probe = l.strip().rstrip(".")
        if probe and q._flat(probe) not in sf:
            print(base + 1 + i, "|", repr(l.strip()))
print("total claims", n)
'@
Set-Content -LiteralPath "C:\Users\DzwU\AppData\Local\Temp\opencode\fid.py" -Value $py -Encoding UTF8
python "C:\Users\DzwU\AppData\Local\Temp\opencode\fid.py"; "EXIT=$LASTEXITCODE"
```

退出码：`0`

---

## 7

```powershell
$p="D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\flow_logic\run-1\outputs\flow_logic.report.md"
$lines = Get-Content -LiteralPath $p
foreach($n in 320..345){ "{0}: {1}" -f $n, $lines[$n-1] }
"----"
foreach($n in 1414..1426){ "{0}: {1}" -f $n, $lines[$n-1] }
```

退出码：`0`

---

## 8

```powershell
$py = @'
import io, sys
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
src = io.open(r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap", encoding="utf-8").read()
sf = q._flat(src)
for probe in ['it_all_transports = lt_all_transports);',
              'ct_features = lt_features);',
              'ct_missing_remote = cs_information-missing_remote);']:
    print(repr(probe), "->", q._flat(probe) in sf)
for i, ln in enumerate(src.split("\n"), 1):
    if 'it_all_transports      = lt_all_transports' in ln or 'ct_features      = lt_features' in ln or 'ct_missing_remote = cs_information-missing_remote' in ln:
        print(i, repr(ln))
'@
Set-Content -LiteralPath "C:\Users\DzwU\AppData\Local\Temp\opencode\fid2.py" -Value $py -Encoding UTF8
python "C:\Users\DzwU\AppData\Local\Temp\opencode\fid2.py"; "EXIT=$LASTEXITCODE"
```

退出码：`0`

---

## 9

```powershell
$py = @'
import io, sys, re
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
src = io.open(r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap", encoding="utf-8").read()
sf = q._flat(src)
for m in re.finditer(re.escape("lt_all_transports"), sf):
    print(repr(sf[max(0,m.start()-70):m.start()+40]))
    print("---")
'@
Set-Content -LiteralPath "C:\Users\DzwU\AppData\Local\Temp\opencode\fid3.py" -Value $py -Encoding UTF8
python "C:\Users\DzwU\AppData\Local\Temp\opencode\fid3.py"; "EXIT=$LASTEXITCODE"
```

退出码：`0`

---

## 10

```powershell
Select-String -LiteralPath "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap" -Pattern "lt_all_transports \)\.|ct_features\s+= lt_features \)\.|ct_missing_remote = cs_information-missing_remote \)\." | ForEach-Object { "{0}: {1}" -f $_.LineNumber, $_.Line }
```

退出码：`0`

---

## 11

```powershell
python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" --fidelity-only "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\flow_logic\run-1\outputs\flow_logic.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; "EXIT=$LASTEXITCODE"
```

退出码：`0`

---

## 12

```powershell
python "C:\Users\DzwU\.agents\skills\analyzing-programs\scripts\report_qc.py" "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\flow_logic\run-1\outputs\flow_logic.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"; "EXIT=$LASTEXITCODE"
```

退出码：`0`

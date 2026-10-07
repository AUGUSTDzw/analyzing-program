# objects_program.run-log.md

分析对象：`D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap`
报告路径：`D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md`
技能路径：`C:\Users\DzwU\.agents\skills\analyzing-programs`

---

## 1

```powershell
Get-ChildItem -Recurse -File "C:\Users\DzwU\.agents\skills\analyzing-programs" | Select-Object FullName, Length | Format-Table -AutoSize | Out-String -Width 200
```

退出码：`0`

## 2

```powershell
Test-Path "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\"; Get-ChildItem "D:\Workspace\Skills\analyzing-programs" | Select-Object Name, Mode | Format-Table -AutoSize | Out-String -Width 200
```

退出码：`0`

## 3

```powershell
New-Item -ItemType Directory -Force -Path "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs" | Out-Null; "EXITCODE=$LASTEXITCODE"
```

退出码：`0`

## 4

```powershell
Test-Path -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs"; "EXITCODE=$LASTEXITCODE"
```

退出码：`0`

## 5

```powershell
Select-String -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" -Pattern '^### 3\.' | ForEach-Object { "$($_.LineNumber): $($_.Line)" }
```

退出码：`0`

## 6

```powershell
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md"
$bytes = [System.IO.File]::ReadAllBytes($p)
"first3=$($bytes[0]),$($bytes[1]),$($bytes[2])"
$text = [System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))
$lines = $text -split "`r?`n"
"total=$($lines.Count)"
$new = @()
for ($i = 0; $i -lt $lines.Count; $i++) { if (($i + 1) -ge 1652 -and ($i + 1) -le 1691) { continue } ; $new += $lines[$i] }
"after=$($new.Count)"
[System.IO.File]::WriteAllText($p, ($new -join "`r`n"), [System.Text.UTF8Encoding]::new($false))
"EXITCODE=$LASTEXITCODE"
```

退出码：`0`

## 7

```powershell
Select-String -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" -Pattern 'lines\( is_cua-fun \)' | ForEach-Object { "$($_.LineNumber): $($_.Line)" }; "---"; Select-String -LiteralPath "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" -Pattern '^### 3\.2' | ForEach-Object { "$($_.LineNumber): $($_.Line)" }
```

退出码：`0`

## 8

```powershell
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md"; $lines = [System.IO.File]::ReadAllLines($p); "total=$($lines.Count)"; $lines[($lines.Count-6)..($lines.Count-1)]
```

退出码：`0`

## 9

```powershell
cd "C:\Users\DzwU\.agents\skills\analyzing-programs"; python scripts/report_qc.py --fidelity-only "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"; "EXITCODE=$LASTEXITCODE"
```

退出码：`1`

## 10

```powershell
cd "C:\Users\DzwU\.agents\skills\analyzing-programs"; python scripts/report_qc.py --fidelity-only "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"; "EXITCODE=$LASTEXITCODE"
```

退出码：`0`

## 11

```powershell
cd "C:\Users\DzwU\.agents\skills\analyzing-programs"; python scripts/report_qc.py "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"; "EXITCODE=$LASTEXITCODE"
```

退出码：`1`

## 12

```powershell
cd "C:\Users\DzwU\.agents\skills\analyzing-programs"; python scripts/report_qc.py "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"; "EXITCODE=$LASTEXITCODE"
```

退出码：`0`

## 13

```powershell
cd "C:\Users\DzwU\.agents\skills\analyzing-programs"; python scripts/report_qc.py --fidelity-only "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.2\objects_program\run-2\outputs\objects_program.report.md" "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"; "EXITCODE=$LASTEXITCODE"
```

退出码：`0`
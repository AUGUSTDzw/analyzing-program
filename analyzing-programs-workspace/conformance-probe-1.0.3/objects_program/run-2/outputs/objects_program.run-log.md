# run-log: objects_program

每条记录：shell 命令原文 + 退出码。成功与失败都记录；重跑过的每一次各记一条。

---

## 1

```
$out = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$log = Join-Path $out "objects_program.run-log.md"
Set-Content -LiteralPath $log -Value "# run-log: objects_program" -Encoding utf8
"CMD1: New-Item -ItemType Directory -Force -Path ``$out``; Set-Content run-log header`nEXIT1: $LASTEXITCODE" | Add-Content -LiteralPath $log
Get-ChildItem -Recurse "C:\Users\DzwU\.agents\skills\analyzing-programs" -File | Select-Object -ExpandProperty FullName
```

exit_code: 0

---

## 2

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
Select-String -LiteralPath $p -Pattern "^### 3\.1[0-3]" | ForEach-Object { "$($_.LineNumber): $($_.Line)" }
```

exit_code: 0

---

## 3

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$txt = Get-Content -LiteralPath $p -Raw
"--- headings ---"
[regex]::Matches($txt, '(?m)^### 3\.\d+ .*$') | ForEach-Object { $_.Value }
"--- refs ---"
$refs = [regex]::Matches($txt, '3\.\d+') | ForEach-Object { $_.Value } | Group-Object | Sort-Object { [int]($_.Name -replace '\.','') }
$refs | ForEach-Object { "$($_.Name) x$($_.Count)" }
```

exit_code: 0

---

## 4

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$txt = [System.IO.File]::ReadAllText($p)
$m = [regex]::Match($txt, '配合它在 3\.7、3\.24 两处')
"found=$($m.Success)"
if ($m.Success) { $txt.Substring($m.Index - 40, 160) }
```

exit_code: 0

---

## 5

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$t = [System.IO.File]::ReadAllText($p)
$fix = @(
 @('（3.26 的 `CONCATENATE`）','（3.30 的 `CONCATENATE`）'),
 @('应与 `insert_program`（3.21）统一','应与 `insert_program`（3.23）统一'),
 @('对照 3.22 的 `get_program_title` 也是同样写法','对照 3.25 的 `get_program_title` 也是同样写法'),
 @('`get_program_title` 就是为此打的补丁','`get_program_title` 就是为此打的补丁'),
 @('（3.21 提到 SAP 自身有个 TTAB','（3.25 提到 SAP 自身有个 TTAB'),
 @('我在 3.30 展开','我在 3.33 展开'),
 @('反序列化侧（3.29）虽然有','反序列化侧（3.32）虽然有'),
 @('的空判断（见 3.29）','的空判断（见 3.32）'),
 @('（见 3.28 `uncondense_flow`）','（见 3.31 `uncondense_flow`）'),
 @('（3.24 里也把 CHECK 字段的 modific 改成','（3.29 里也把 CHECK 字段的 modific 改成'),
 @('反序列化侧（3.31）因此必须手工补','反序列化侧（3.34）因此必须手工补'),
 @('反序列化侧（3.31）用它决定','反序列化侧（3.34）用它决定'),
 @('`read_tpool`（3.35）是它的逆运算','`read_tpool`（3.37）是它的逆运算'),
 @('与 3.15 的可重复顺序原则','与 3.15 的可重复顺序原则'),
 @('的区分在 3.27、3.30、3.32 三处各出现一次','的区分在 3.21、3.26、3.30、3.32 四处各出现一次'),
 @('（见 3.28 `uncondense_flow`）','（见 3.31 `uncondense_flow`）')
)
foreach ($f in $fix) {
  $old = $f[0]; $new = $f[1]
  if ($old -eq $new) { continue }
  $c = ([regex]::Matches($t, [regex]::Escape($old))).Count
  "OLD[$old] count=$c"
  if ($c -gt 0) { $t = $t.Replace($old, $new) }
}
[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding $false))
"done"
```

exit_code: 0

---

## 6

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$t = [System.IO.File]::ReadAllText($p)
$lines = $t -split "`n"
$out = New-Object System.Collections.Generic.List[string]
$cur = ''
for ($i=0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match '^### (3\.\d+)') { $cur = $lines[$i].Substring(4).Split('（')[0].Split('(')[0].Trim() }
  foreach ($m in [regex]::Matches($lines[$i], '3\.\d+')) {
    $n = $m.Value
    if ($n -eq $cur.Split(' ')[0]) { continue }
    $seg = $lines[$i]
    $st = [Math]::Max(0, $m.Index - 30)
    $out.Add("[$cur] -> $n :: " + ($seg.Substring($st, [Math]::Min(70, $seg.Length-$st)) -replace '\s+',' '))
  }
}
$outFile = "C:\Users\DzwU\AppData\Local\Temp\opencode\refs.txt"
[System.IO.File]::WriteAllLines($outFile, $out, (New-Object System.Text.UTF8Encoding $false))
"refs=$($out.Count) -> $outFile"
```

exit_code: 0

---

## 7

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$t = [System.IO.File]::ReadAllText($p)
$fix = @(
 @('（见 3.10 与 3.29）','（见 3.10 与 3.32）'),
 @('三个字段**（见 3.31）','三个字段**（见 3.34）'),
 @('这条业务边界（见 3.12）','这条业务边界（见 3.13）'),
 @('不允许存非活动版本，所以置成 off','不允许存非活动版本，所以置成 off'),
 @('（见 3.19）——出口 Include 不允许存非活动版本','（见 3.22）——出口 Include 不允许存非活动版本'),
 @('（见 3.30 对 ABAP 传值规则的讨论）','（见 3.33 对 ABAP 传值规则的讨论）'),
 @('和 3.30 分析的 `auto_correct_cua_adm`','和 3.33 分析的 `auto_correct_cua_adm`'),
 @('这个判断在 3.24 又用了一次','这个判断在 3.29 又用了一次'),
 @('反序列化侧（3.24）会从 `mo_files->read_abap` 读同一段内容','反序列化侧（3.28）会从 `mo_files->read_abap` 读同一段内容'),
 @('（见 3.20 的 `insert_program`）','（见 3.23 的 `insert_program`）'),
 @('3.31 的"风险与改进"里给出了那一版示意','3.34 的"风险与改进"里给出了那一版示意'),
 @('字段较多（见 3.36 那个方法）','字段较多（见 3.15 那个方法）')
)
foreach ($f in $fix) {
  $old = $f[0]; $new = $f[1]
  if ($old -eq $new) { continue }
  $c = ([regex]::Matches($t, [regex]::Escape($old))).Count
  "count=$c for [$($old.Substring(0,[Math]::Min(20,$old.Length)))]"
  if ($c -gt 0) { $t = $t.Replace($old, $new) }
}
[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding $false))
"done"
```

exit_code: 0

---

## 8

```
$skill = "C:\Users\DzwU\.agents\skills\analyzing-programs"
$rep = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$src = "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
$env:PYTHONIOENCODING = "utf-8"
python "$skill\scripts\report_qc.py" --fidelity-only "$rep" "$src"
"EXITCODE=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code: 1

---

## 9

```
$tmp = "C:\Users\DzwU\AppData\Local\Temp\opencode"
@'
import io, sys, os
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
src = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
s = io.open(rep, encoding="utf-8").read()
ssrc = io.open(src, encoding="utf-8").read()
sf = q._flat(ssrc)
for st, bs, be, en, lang in q.fence_spans(s):
    if lang != "abap":
        continue
    base = q.line_of(s, st)
    for i, l in q._claims(s[bs:be]):
        probe = l.strip().rstrip(".")
        if probe and q._flat(probe) not in sf:
            print(base + 1 + i, repr(l))
'@ | Set-Content -LiteralPath "$tmp\qcheck.py" -Encoding utf8
python "$tmp\qcheck.py"
"EXITCODE=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code: 0

---

## 10

```
$src = "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
Select-String -LiteralPath $src -Pattern 'lv_object TYPE' | ForEach-Object { "$($_.LineNumber): [$($_.Line)]" }
"---- bytes ----"
$bytes = [System.IO.File]::ReadAllBytes($src)
$txt = [System.Text.Encoding]::UTF8.GetString($bytes)
[regex]::Matches($txt, 'DATA lv_object TYPE \S+') | ForEach-Object { $_.Value }
```

exit_code: 0

---

## 11

```
$p = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$t = [System.IO.File]::ReadAllText($p)
$c1 = ([regex]::Matches($t, [regex]::Escape('    DATA lv_object TYPE eqegraarg.'))).Count
$t = $t.Replace('    DATA lv_object TYPE eqegraarg.', '    DATA: lv_object TYPE eqegraarg.')
$c2 = ([regex]::Matches($t, [regex]::Escape('is_proapdir-name'))).Count
$t = $t.Replace('is_proapdir-name', 'is_progdir-name')
[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding $false))
"eqegraarg replaced=$c1 proapdir replaced=$c2"
```

exit_code: 0

---

## 12

```
$skill = "C:\Users\DzwU\.agents\skills\analyzing-programs"
$rep = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$src = "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
python "$skill\scripts\report_qc.py" --fidelity-only "$rep" "$src"
"EXITCODE=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code: 0

---

## 13

```
$skill = "C:\Users\DzwU\.agents\skills\analyzing-programs"
$rep = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$src = "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
python "$skill\scripts\report_qc.py" "$rep" "$src"
"EXITCODE=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code: 0

---

## 14

```
$tmp = "C:\Users\DzwU\AppData\Local\Temp\opencode"
@'
import io, sys
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
src = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
s = io.open(rep, encoding="utf-8").read()
ssrc = io.open(src, encoding="utf-8").read()
sf = q._flat(ssrc)
n = 0
for st, bs, be, en, lang in q.fence_spans(s):
    if lang != "abap-fix":
        continue
    n += 1
    probes = []
    for _i, l in q._claims(s[bs:be]):
        p = l.strip().rstrip(".")
        if p:
            probes.append((q._flat(p), l.strip()))
    if not probes:
        continue
    if all(f in sf for f, _t in probes):
        print("=== FLAGGED fence at line %d (fix fence #%d) ===" % (q.line_of(s, st), n))
        print(s[bs:be])
print("total abap-fix fences:", n)
'@ | Set-Content -LiteralPath "$tmp\qfixml.py" -Encoding utf8
python "$tmp\qfixml.py"
"EXITCODE=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code: 0

---

## 15

```
$skill = "C:\Users\DzwU\.agents\skills\analyzing-programs"
$rep = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
$src = "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
"--- fidelity-only ---"
python "$skill\scripts\report_qc.py" --fidelity-only "$rep" "$src"
"FIDELITY_EXIT=$LASTEXITCODE"
"--- shape ---"
python "$skill\scripts\report_qc.py" "$rep" "$src"
"SHAPE_EXIT=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code_fidelity_only: 0
captured_exit_code_shape: 0

---

## 16

```
$tmp = "C:\Users\DzwU\AppData\Local\Temp\opencode"
@'
import io, sys
sys.path.insert(0, r"C:\Users\DzwU\.agents\skills\analyzing-programs\scripts")
import report_qc as q
rep = r"D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs\objects_program.report.md"
src = r"D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
s = io.open(rep, encoding="utf-8").read()
ssrc = io.open(src, encoding="utf-8").read()
inv = q.inventory(ssrc)
blocks = list(q.source_blocks(s))
langs = {}
for _st, _bs, _be, _en, lang in q.fence_spans(s):
    langs[lang] = langs.get(lang, 0) + 1
secs = len([1 for rx, _h in q.SEC_RE if rx.search(s)])
rows = len(q.ROW.findall(s[q.PSEC_RE.search(s).start():]))
print("declared subprograms:", len(inv))
print("methods (minus class):", len([n for n in inv if n != 'zcl_abapgit_objects_program']))
print("quoted abap blocks:", len(blocks))
print("density:", round(len(blocks)/len(inv), 3))
print("fence languages:", langs)
print("sections found:", secs)
print("problem rows in section 5:", rows)
print("named subprograms in text:", sum(1 for n in inv if n.lower() in s.lower()))
print("section 3 headings:", len([1 for m in q.__dict__ and [] ]) )
import re
print("3.x headings:", len(re.findall(r"(?m)^### 3\.\d+ ", s)))
print("report lines:", s.count("\n")+1)
'@ | Set-Content -LiteralPath "$tmp\qstats.py" -Encoding utf8
python "$tmp\qstats.py"
"EXITCODE=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code: 0

---

## 17

```
$skill = "C:\Users\DzwU\.agents\skills\analyzing-programs"
$out = "D:\Workspace\Skills\analyzing-programs\analyzing-programs-workspace\conformance-probe-1.0.3\objects_program\run-2\outputs"
$rep = "$out\objects_program.report.md"
$src = "D:\Workspace\Skills\analyzing-programs\Test-source\real\abapGit__abapGit__zcl_abapgit_objects_program.clas.abap"
Get-ChildItem -LiteralPath $out -File | Select-Object Name, Length
python "$skill\scripts\report_qc.py" --fidelity-only "$rep" "$src"; "FIDELITY_EXIT=$LASTEXITCODE"
python "$skill\scripts\report_qc.py" "$rep" "$src"; "SHAPE_EXIT=$LASTEXITCODE"
"SHELL_EXIT=$LASTEXITCODE"
```

shell_exit_code: 0
captured_exit_code_fidelity_only: 0
captured_exit_code_shape: 0
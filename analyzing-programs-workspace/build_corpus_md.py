"""Regenerate Test-source/real/CORPUS.md from the manifest + construct scan."""
import io, json, os, re, subprocess, sys

OUT = sys.argv[1]
SCAN = sys.argv[2]
man = json.load(open(os.path.join(OUT, "MANIFEST.json"), encoding="utf-8"))

import collections
by_repo = collections.OrderedDict()
for m in man:
    d = by_repo.setdefault(m["repo"], {"files": 0, "lines": 0, "lic": set(),
                                       "note": m.get("note", "")})
    d["files"] += 1
    d["lines"] += m["lines"]
    d["lic"].add(m["license"])

scan = subprocess.run([sys.executable, SCAN, OUT], capture_output=True,
                      text=True, encoding="utf-8").stdout

rows = []
for line in scan.split("\n"):
    m = re.match(r"^(.{22}?)\s*(\d+)/(\d+)", line)
    if m and m.group(2).isdigit():
        rows.append((m.group(1).strip(), int(m.group(2)), int(m.group(3))))
rows.sort(key=lambda x: -x[1])
absent = re.findall(r"^   - (.+)$", scan, re.M)

sizes = sorted(m["lines"] for m in man)
enc = [m for m in man if m.get("upstream_was_utf16")]

L = [
    "# 真实 ABAP 语料清单（Test-source/real）",
    "",
    "全部来自公开开源仓库，逐文件在 `MANIFEST.json` 记录 URL、分支、许可证与 "
    "sha256。**没有引入任何私有代码。**",
    "",
    f"**{len(man)} 个文件 / {sum(m['lines'] for m in man):,} 行 / "
    f"{len(by_repo)} 个上游项目**"
    f"（中位 {sizes[len(sizes)//2]} 行，最大 {sizes[-1]:,} 行，最小 {sizes[0]} 行）",
    "",
    "对照：本仓库自有 `zr.abap` 159 行、`zvend.abap` 357 行；"
    "此前最大被测对象 332 行。",
    "",
    "## 项目分布",
    "",
    "| 项目 | 许可证 | 文件 | 行数 | 用途 |",
    "|---|---|---|---|---|",
]
for k, v in sorted(by_repo.items(), key=lambda x: -x[1]["lines"]):
    url = f"https://github.com/{k}"
    lic = "/".join(sorted(x for x in v["lic"] if x and x != "see-repo")) or "见仓库"
    L.append(f"| [{k.split('/')[1]}]({url}) | {lic} | {v['files']} | "
             f"{v['lines']:,} | 真实应用代码 |")

L += ["", "## 构造覆盖", "", "| 构造 | 文件数 |", "|---|---|"]
for n, a, b in rows:
    if a:
        L.append(f"| {n} | {a}/{b} |")

if absent:
    L += ["", "## 仍缺", ""]
    L += [f"- {a.strip()}" for a in absent]
    L += [
        "",
        "这些全部是 **ECC on-premise 专属**构造。GitHub 上的 ABAP 项目绝大多数跑在",
        "ABAP Cloud / Steampunk，这些语法在那里根本不存在；企业代码不开源；",
        "而 GitHub code search 匿名调用返回 401，无法按内容检索。",
        "换言之这是**可得性上限**，不是检索不足 —— 58 个文件、15 个项目、",
        "12.7 万行的全量本地扫描后仍然为 0。",
    ]

L += [
    "",
    "## 抓取过程中发现并修复的三个缺陷",
    "",
    "1. **AMDP 探测用错了签名**。原正则 `FOR SELECT|ALL FIELDS|COUNT` 匹配的是 "
    "SQLScript 的**方法体**，而语料里明明有 `zcl_demo_abap_amdp.clas.abap` 却报 0/19。"
    "正确签名是 `BY DATABASE PROCEDURE ... LANGUAGE SQLSCRIPT`。",
    "2. **`CLASS x IMPLEMENTATION.` 被漏判**。探测式以 `\\s*$` 收尾，但真实源码行尾",
    "有一个句点，于是**每一个**类的实现段都被判为不存在（报 0/57，实际 38/57）。",
    "3. **UTF-16 源码被存成乱码**。抓取器对字节做 `decode('utf-8', errors='replace')` "
    "后写文本，而 sha256 记的是解码前的原始字节。`ZCL_FI_TOOLKIT.abap` 是 "
    "UTF-16 LE 带 BOM，落盘文件因此变成乱码，且哈希链断裂。"
    "U+FFFD 本身是合法 UTF-8，所以\"能否解码\"检不出来 —— 必须直接查替换字符。"
    "已重新抓取并归一化为 UTF-8，manifest 记录 `upstream_encoding`。",
    "",
    "另外：zipball 内部路径自带 `<repo>-<branch>/` 前缀，抓取器给本地文件名剥了前缀",
    "却没给 manifest 的 `path` 剥，导致 28 条记录的 `url` 拼接错误（重新抓取时 404）。",
    "已全部修正。",
    "",
    "## 校验",
    "",
    "```bash",
    "python analyzing-programs-workspace/verify_corpus.py Test-source/real",
    "python analyzing-programs-workspace/scan_corpus.py   Test-source/real",
    "```",
    "",
    "`verify_corpus.py` 校验：文件齐全、sha256 匹配、行数匹配、"
    "全部为合法 UTF-8 且不含 U+FFFD、磁盘上无未登记文件。任一不满足即退出码 1。",
    "",
    "## 尚未分析",
    "",
    f"58 个文件里目前只有 3 份报告（`abapgit_flow_logic`、`abapgit_forms`、",
    "`abapgit_password_dialog`），全部来自 abapGit 一个项目。",
    "**跨项目通用性尚未验证** —— 需要优先分析",
    "`ZCL_FI_TOOLKIT`（1702 行 UTF-16 归一化后）、`z2ui5_cl_xml_view`（15,885 行）、",
    "`zcl_demo_abap_dynamic_prog`（6838 行）、`zcl_ave_*`（CLASS-POOL + CLASS-EVENTS）、",
    "以及函数组与 PBO/PAI 样例。",
]

io.open(os.path.join(OUT, "CORPUS.md"), "w", encoding="utf-8",
        newline="\n").write("\n".join(L) + "\n")
print(f"Wrote CORPUS.md: {len(man)} files, {sum(m['lines'] for m in man)} lines, "
      f"{len(by_repo)} projects, {len(absent)} constructs still absent")

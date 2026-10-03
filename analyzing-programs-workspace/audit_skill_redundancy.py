import io, os, re, sys

# Which skill rules are stated more than once? Duplication is what a model has
# to reconcile, and it is the cheapest thing to cut when length hurts.
s = io.open(sys.argv[1], encoding="utf-8").read()
lines = s.split("\n")

RULES = {
    "three-layer labels required": [r"三层", r"每[个一].*标签", r"标签.*缺一不可", r"不得.*省标签", r"带齐"],
    "split into ① ② ③ steps": [r"①\s*②\s*③", r"编号子标题", r"拆分步骤", r"按逻辑步骤拆分"],
    "compact bold-label form": [r"行内加粗", r"紧凑", r"\*{0,2}做什么\*{0,2}\s*—"],
    "unlabeled prose is anti-pattern": [r"反模式", r"无标签", r"散文"],
    "no line-number locators": [r"不用行号", r"行号", r"所在子程序"],
    "Mermaid label safety": [r"Mermaid 标签安全", r"保留字符", r"裸"],
    "location label format": [r"全局声明区", r"事件块"],
    "group by execution flow": [r"执行流程顺序", r"责任链"],
}

print(f"{'rule':34s}{'mentions':>9}  sections")
print("-" * 88)
for name, pats in RULES.items():
    hits = []
    for i, l in enumerate(lines):
        for p in pats:
            if re.search(p, l, re.I):
                hits.append(i + 1)
                break
    # cluster into sections by nearest preceding '## '
    secs = []
    for h in hits:
        for j in range(h - 1, -1, -1):
            if lines[j].startswith("## "):
                secs.append(lines[j].strip()[:26])
                break
    u = sorted(set(secs))
    print(f"{name:34s}{len(hits):9d}  {', '.join(u[:4]) if u else '-'}")

print()
print(f"total lines: {len(lines)}   chars: {len(s)}")
blank = sum(1 for l in lines if not l.strip())
print(f"blank lines: {blank} ({blank/len(lines)*100:.0f}%)")

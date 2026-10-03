# 真实 ABAP 语料清单（Test-source/real）

全部来自公开开源仓库，逐文件在 `MANIFEST.json` 记录 URL、分支、许可证与 sha256。**没有引入任何私有代码。**

**58 个文件 / 126,755 行 / 15 个上游项目**（中位 382 行，最大 29,565 行，最小 11 行）

对照：本仓库自有 `zr.abap` 159 行、`zvend.abap` 357 行；此前最大被测对象 332 行。

## 项目分布

| 项目 | 许可证 | 文件 | 行数 | 用途 |
|---|---|---|---|---|
| [AVE](https://github.com/ysichov/AVE) | MIT | 2 | 54,108 | 真实应用代码 |
| [abap-cheat-sheets](https://github.com/SAP-samples/abap-cheat-sheets) | Apache-2.0 | 20 | 23,718 | 真实应用代码 |
| [abap2UI5](https://github.com/abap2UI5/abap2UI5) | MIT | 2 | 21,635 | 真实应用代码 |
| [abap-to-json](https://github.com/SAP/abap-to-json) | Apache-2.0 | 2 | 6,649 | 真实应用代码 |
| [abap-db-browser](https://github.com/DevEpos/abap-db-browser) | MIT | 2 | 5,099 | 真实应用代码 |
| [abapGit](https://github.com/abapGit/abapGit) | MIT | 6 | 4,856 | 真实应用代码 |
| [ABAP-Library](https://github.com/Keremkoseoglu/ABAP-Library) | 见仓库 | 2 | 3,317 | 真实应用代码 |
| [ABAP-SDK-for-Azure](https://github.com/microsoft/ABAP-SDK-for-Azure) | MIT | 2 | 3,276 | 真实应用代码 |
| [abap-cloud-logger](https://github.com/greltel/abap-cloud-logger) | MIT | 2 | 2,709 | 真实应用代码 |
| [abap-log](https://github.com/fabianlupa/abap-log) | MIT | 2 | 550 | 真实应用代码 |
| [AbapToTheFuture03](https://github.com/hardyp/AbapToTheFuture03) | MIT | 9 | 256 | 真实应用代码 |
| [Mastering-SAP-ABAP](https://github.com/PacktPublishing/Mastering-SAP-ABAP) | MIT | 1 | 161 | 真实应用代码 |
| [cloud-abap-rap](https://github.com/SAP-samples/cloud-abap-rap) | Apache-2.0 | 2 | 159 | 真实应用代码 |
| [abap-platform-reuse-services](https://github.com/SAP-samples/abap-platform-reuse-services) | Apache-2.0 | 2 | 147 | 真实应用代码 |
| [abap-platform-code-samples-cloud](https://github.com/SAP-archive/abap-platform-code-samples-cloud) | Apache-2.0 | 2 | 115 | 真实应用代码 |

## 构造覆盖

| 构造 | 文件数 |
|---|---|
| class IMPLEMENTATION | 38/57 |
| STRING TEMPLATE | 30/57 |
| inline DATA() | 30/57 |
| VALUE #() | 26/57 |
| FIELD-SYMBOL | 22/57 |
| EXIT/CONTINUE | 21/57 |
| ASSERT | 15/57 |
| FORM ... TABLES | 10/57 |
| FUNCTION module | 8/57 |
| FOR ALL ENTRIES | 8/57 |
| BADI-ish (IF_ impl) | 6/57 |
| RFC / DESTINATION | 6/57 |
| REDUCE | 6/57 |
| CDS view entity | 4/57 |
| CL_HTTP_CLIENT | 4/57 |
| ENQUEUE | 3/57 |
| FILTER | 3/57 |
| RAP side effect | 2/57 |
| PBO/PAI module | 2/57 |
| CLASS-EVENTS | 2/57 |
| RAISE EVENT | 2/57 |
| AMDP proc/func | 1/57 |
| └ SQLScript | 1/57 |
| └ USING clause | 1/57 |
| CLASS-POOL | 1/57 |
| authorization | 1/57 |
| MESSAGE class | 1/57 |
| lock object | 1/57 |

## 仍缺

- dynamic SQL
- obsolete COMPUTE
- obsolete MOVE TO
- obsolete ADD TO
- obsolete SUBTRACT
- PERFORM ON COMMIT
- UPDATE TASK
- RANGES (live stmt)

这些全部是 **ECC on-premise 专属**构造。GitHub 上的 ABAP 项目绝大多数跑在
ABAP Cloud / Steampunk，这些语法在那里根本不存在；企业代码不开源；
而 GitHub code search 匿名调用返回 401，无法按内容检索。
换言之这是**可得性上限**，不是检索不足 —— 58 个文件、15 个项目、
12.7 万行的全量本地扫描后仍然为 0。

## 抓取过程中发现并修复的三个缺陷

1. **AMDP 探测用错了签名**。原正则 `FOR SELECT|ALL FIELDS|COUNT` 匹配的是 SQLScript 的**方法体**，而语料里明明有 `zcl_demo_abap_amdp.clas.abap` 却报 0/19。正确签名是 `BY DATABASE PROCEDURE ... LANGUAGE SQLSCRIPT`。
2. **`CLASS x IMPLEMENTATION.` 被漏判**。探测式以 `\s*$` 收尾，但真实源码行尾
有一个句点，于是**每一个**类的实现段都被判为不存在（报 0/57，实际 38/57）。
3. **UTF-16 源码被存成乱码**。抓取器对字节做 `decode('utf-8', errors='replace')` 后写文本，而 sha256 记的是解码前的原始字节。`ZCL_FI_TOOLKIT.abap` 是 UTF-16 LE 带 BOM，落盘文件因此变成乱码，且哈希链断裂。U+FFFD 本身是合法 UTF-8，所以"能否解码"检不出来 —— 必须直接查替换字符。已重新抓取并归一化为 UTF-8，manifest 记录 `upstream_encoding`。

另外：zipball 内部路径自带 `<repo>-<branch>/` 前缀，抓取器给本地文件名剥了前缀
却没给 manifest 的 `path` 剥，导致 28 条记录的 `url` 拼接错误（重新抓取时 404）。
已全部修正。

## 校验

```bash
python analyzing-programs-workspace/verify_corpus.py Test-source/real
python analyzing-programs-workspace/scan_corpus.py   Test-source/real
```

`verify_corpus.py` 校验：文件齐全、sha256 匹配、行数匹配、全部为合法 UTF-8 且不含 U+FFFD、磁盘上无未登记文件。任一不满足即退出码 1。

## 尚未分析

58 个文件里目前只有 3 份报告（`abapgit_flow_logic`、`abapgit_forms`、
`abapgit_password_dialog`），全部来自 abapGit 一个项目。
**跨项目通用性尚未验证** —— 需要优先分析
`ZCL_FI_TOOLKIT`（1702 行 UTF-16 归一化后）、`z2ui5_cl_xml_view`（15,885 行）、
`zcl_demo_abap_dynamic_prog`（6838 行）、`zcl_ave_*`（CLASS-POOL + CLASS-EVENTS）、
以及函数组与 PBO/PAI 样例。

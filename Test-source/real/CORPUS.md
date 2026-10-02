# 真实 ABAP 语料清单（Test-source/real）

全部来自公开开源仓库，逐文件记录 URL、分支、许可证与 sha256，由 `MANIFEST.json` 机器可读地固定。**没有引入任何私有代码。**

共 **30 个文件 / 28,880 行**，来自 **4 个上游项目**。

## 项目分布

| 项目 | 许可证 | 文件 | 行数 | 提供什么 |
|---|---|---|---|---|
| [abapGit](https://github.com/abapGit/abapGit) | MIT | 6 | 4,856 | 真实生产级开源应用：INCLUDE 层、FORM 过程式、`FIELD-SYMBOL`、全局类、SALV/Reuse ALV |
| [SAP-samples/abap-cheat-sheets](https://github.com/SAP-samples/abap-cheat-sheets) | Apache-2.0 | 20 | 23,718 | SAP 官方构造样例：AMDP/SQLScript、CDS view entity、RAP、动态调用、XML/JSON、日期时间、数值类型、异常处理 |
| [SAP-samples/cloud-abap-rap](https://github.com/SAP-samples/cloud-abap-rap) | Apache-2.0 | 2 | 159 | RAP 行为定义（BDL）+ side effects + CDS DDL 源 |
| [SAP-samples/abap-platform-reuse-services](https://github.com/SAP-samples/abap-platform-reuse-services) | Apache-2.0 | 2 | 147 | RAP 行为池、编号范围、变更文档、Adobe Forms |

## 规模分布

最小 16 行，中位 382 行，最大 6,838 行。

对照：本仓库自有的 `zr.abap` 159 行、`zvend.abap` 357 行。**语料最大对象比此前被测最大对象（332 行）大 20 倍。**

## 构造覆盖

| 构造 | 命中文件数 |
|---|---|
| STRING TEMPLATE | 16/29 |
| inline DATA() | 14/29 |
| VALUE #() | 12/29 |
| ASSERT | 12/29 |
| FIELD-SYMBOL | 9/29 |
| EXIT/CONTINUE | 9/29 |
| FORM ... TABLES | 5/29 |
| CDS view entity | 4/29 |
| REDUCE | 3/29 |
| FOR ALL ENTRIES | 3/29 |
| ENQUEUE | 2/29 |
| AMDP proc/func | 1/29 |
| └ SQLScript | 1/29 |
| └ USING clause | 1/29 |
| RAP side effect | 1/29 |
| RFC / DESTINATION | 1/29 |
| MESSAGE class | 1/29 |

## 仍缺（需私有代码或本地 SE38 导出）

- BADI impl class
- CLASS-POOL
- FUNCTION module
- dynamic SQL
- obsolete COMPUTE
- obsolete MOVE TO
- obsolete ADD TO
- obsolete SUBTRACT
- PBO/PAI module
- PERFORM ON COMMIT
- UPDATE TASK
- CL_HTTP_CLIENT
- CLASS-EVENTS
- RAISE EVENT
- FILTER
- authorization
- lock object
- obsolete RANGES

## 取舍说明

- **`abap-cheat-sheets` 占 20/30 文件**：它是 SAP 官方维护、覆盖构造最全的公开 ABAP 语料，且每行带官方注释，本身就是优秀的教学样本。
- **仍然只有 4 个上游项目**：GitHub 上星数 ≥300 的 ABAP 项目里，除 abapGit 外基本是静态检查工具（code-pal-for-abap、abapOpenChecks）或框架（abap2UI5、abap2xlsx）而非业务程序。**这是语料可得性的限制，不是选择的结果。**
- **遗留 ABAP 几乎不可得**：`CLASS-POOL`、函数模块、`PBO/PAI`、`COMPUTE`/`MOVE TO` 等过时语句、`AUTHORITY-CHECK`、后台 `UPDATE TASK`、动态 SQL 在公开仓库中几乎绝迹——因为开源 ABAP 项目都跑在 ABAP Cloud / Steampunk 上，而这些是 ECC on-premise 专属。企业代码不开源，GitHub 搜索也无法匿名使用（code search API 返回 401）。
- **本次修复了两个探测缺陷**：原始 `scan_gaps.py` 用 `FOR SELECT|ALL FIELDS` 识别 AMDP，那是 SQLScript **方法体**而非**声明**，导致语料里明明有 `zcl_demo_abap_amdp.clas.abap` 却报 0/19。正确签名是 `BY DATABASE PROCEDURE ... LANGUAGE SQLSCRIPT`。同一个脚本里 `RANGES` 被误列为「过时语句」——它至今是合法语句。

## 复现

```bash
# 校验每个文件的 sha256 与 MANIFEST 一致
python scripts/verify_corpus.py
# 重新统计构造覆盖
python scripts/scan2.py Test-source/real
```

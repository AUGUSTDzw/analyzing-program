# 真实 ABAP 语料清单（Test-source/real）

全部来自公开开源仓库，逐文件在 `MANIFEST.json` 记录 URL、分支、许可证与 sha256。**没有引入任何私有代码。**

**94 个文件 / 216,081 行 / 48 个上游项目**（中位 1,115 行，最大 29,565 行，最小 11 行）

2026-10 扩充：+36 文件 / +89,326 行 / +33 项目，目标是**跨项目通用性**与
语料完全没有的对象类型，不是补语法缺口（见下"仍缺"）。

## 项目分布

| 项目 | 许可证 | 文件 | 行数 |
|---|---|---|---|
| [AVE](https://github.com/ysichov/AVE) | MIT | 2 | 54,108 |
| [abap-cheat-sheets](https://github.com/SAP-samples/abap-cheat-sheets) | Apache-2.0 | 20 | 23,718 |
| [abap2UI5](https://github.com/abap2UI5/abap2UI5) | MIT | 2 | 21,635 |
| [ACE](https://github.com/ysichov/ACE) | MIT | 1 | 18,567 |
| [ztoad](https://github.com/marianfoo/ztoad) | GPL-3.0 | 1 | 9,430 |
| [Smart-Debugger](https://github.com/ysichov/Smart-Debugger) | MIT | 1 | 9,016 |
| [Simple-Data-Explorer](https://github.com/ysichov/Simple-Data-Explorer) | MIT | 1 | 7,925 |
| [abap-to-json](https://github.com/SAP/abap-to-json) | Apache-2.0 | 2 | 6,649 |
| [ZTCT](https://github.com/ZEdwin/ZTCT) | MIT | 1 | 5,478 |
| [abap-db-browser](https://github.com/DevEpos/abap-db-browser) | MIT | 2 | 5,099 |
| [abap2xlsx](https://github.com/abap2xlsx/abap2xlsx) | Apache-2.0 | 1 | 4,870 |
| [abapGit](https://github.com/abapGit/abapGit) | MIT | 6 | 4,856 |
| [ABAP-Library](https://github.com/Keremkoseoglu/ABAP-Library) | 见仓库 | 2 | 3,317 |
| [ABAP-SDK-for-Azure](https://github.com/microsoft/ABAP-SDK-for-Azure) | MIT | 2 | 3,276 |
| [open-abap-core](https://github.com/open-abap/open-abap-core) | MIT | 1 | 3,118 |
| [mcp](https://github.com/abap-ai/mcp) | MIT | 2 | 2,955 |
| [falv](https://github.com/fidley/falv) | GPL-3.0 | 1 | 2,713 |
| [abap-cloud-logger](https://github.com/greltel/abap-cloud-logger) | MIT | 2 | 2,709 |
| [abap_fm_json](https://github.com/cesar-sap/abap_fm_json) | Apache-2.0 | 1 | 2,487 |
| [zscv_search_cds_views](https://github.com/alwinvandeput/zscv_search_cds_views) | Apache-2.0 | 1 | 2,370 |
| [zJSON](https://github.com/se38/zJSON) | Apache-2.0 | 1 | 2,168 |
| [ai-abap-assistant-sample](https://github.com/google/ai-abap-assistant-sample) | Apache-2.0 | 1 | 1,991 |
| [zapcommander](https://github.com/tricktresor/zapcommander) | GPL-3.0 | 1 | 1,804 |
| [sapui5-deployer](https://github.com/Yelcho/sapui5-deployer) | 见仓库 | 1 | 1,777 |
| [gateway-odata-v4](https://github.com/SAP-samples/gateway-odata-v4) | Apache-2.0 | 1 | 1,628 |
| [abap-dev-utilities](https://github.com/jrodriguez-rc/abap-dev-utilities) | MIT | 1 | 1,483 |
| [abap-openapi](https://github.com/abap-openapi/abap-openapi) | MIT | 1 | 1,443 |
| [abapOpenReview](https://github.com/larshp/abapOpenReview) | GPL-2.0 | 1 | 1,440 |
| [xtt](https://github.com/bizhuka/xtt) | Apache-2.0 | 1 | 1,359 |
| [zllm](https://github.com/oisee/zllm) | MIT | 1 | 1,128 |
| [abap-search-tools](https://github.com/DevEpos/abap-search-tools) | MIT | 1 | 940 |
| [abap-alv-google-upload-sheet](https://github.com/SAP-samples/abap-alv-google-upload-sheet) | Apache-2.0 | 2 | 895 |
| [abap-platform-rap110](https://github.com/SAP-samples/abap-platform-rap110) | Apache-2.0 | 2 | 707 |
| [abap-log](https://github.com/fabianlupa/abap-log) | MIT | 2 | 550 |
| [abap-fm-logger](https://github.com/hhelibeb/abap-fm-logger) | Apache-2.0 | 1 | 431 |
| [eui](https://github.com/bizhuka/eui) | Apache-2.0 | 1 | 352 |
| [AbapToTheFuture03](https://github.com/hardyp/AbapToTheFuture03) | MIT | 9 | 256 |
| [abap-platform-code-samples-standard](https://github.com/SAP-archive/abap-platform-code-samples-standard) | Apache-2.0 | 1 | 245 |
| [abap_rap_blog](https://github.com/Xexer/abap_rap_blog) | 见仓库 | 1 | 170 |
| [Mastering-SAP-ABAP](https://github.com/PacktPublishing/Mastering-SAP-ABAP) | MIT | 1 | 161 |
| [cloud-abap-rap](https://github.com/SAP-samples/cloud-abap-rap) | Apache-2.0 | 2 | 159 |
| [abap-platform-reuse-services](https://github.com/SAP-samples/abap-platform-reuse-services) | Apache-2.0 | 2 | 147 |
| [abapGitServer](https://github.com/larshp/abapGitServer) | MIT | 1 | 144 |
| [abapOpenChecks](https://github.com/larshp/abapOpenChecks) | MIT | 1 | 130 |
| [Teched17](https://github.com/jasper07/Teched17) | MIT | 1 | 128 |
| [abap-platform-code-samples-cloud](https://github.com/SAP-archive/abap-platform-code-samples-cloud) | Apache-2.0 | 2 | 115 |
| [abap-cookbook](https://github.com/NTahaEgilli/abap-cookbook) | MIT | 1 | 22 |
| [New-ABAP-Tips-Tricks](https://github.com/suriyarasu/New-ABAP-Tips-Tricks) | 见仓库 | 1 | 12 |

## 构造覆盖

`scan_corpus.py` 探测结果，分母 93（不含 `MANIFEST.json` 与 `.xml`）。

| 构造 | 文件数 |
|---|---|
| class IMPLEMENTATION | 68/93 |
| inline DATA() | 52/93 |
| STRING TEMPLATE (legacy `\|...\{`) | 51/93 |
| FIELD-SYMBOL | 44/93 |
| EXIT/CONTINUE | 41/93 |
| VALUE #() | 40/93 |
| FORM ... TABLES | 22/93 |
| ASSERT | 21/93 |
| FOR ALL ENTRIES | 15/93 |
| BADI-ish (IF_ impl) | 9/93 |
| RAISE EVENT | 9/93 |
| FUNCTION module | 8/93 |
| RFC / DESTINATION | 8/93 |
| CL_HTTP_CLIENT | 7/93 |
| REDUCE | 6/93 |
| CDS view entity | 5/93 |
| PBO/PAI module | 5/93 |
| authorization | 5/93 |
| RAP side effect | 4/93 |
| FILTER | 4/93 |
| ENQUEUE | 3/93 |
| CLASS-EVENTS | 3/93 |
| AMDP proc/func | 2/93 |
| └ SQLScript | 2/93 |
| CLASS-POOL | 2/93 |
| MESSAGE class | 2/93 |
| └ USING clause | 1/93 |
| lock object | 1/93 |

STRING TEMPLATE 那一行用的是旧式管道语法 `\|...\{`，反引号形式（7.4+）在
全部 94 个文件里出现 **0 次**。也就是说语料里没有一个文件用现代字符串模板
—— 写报告时若声称"代码大量使用字符串模板"，依据的是旧语法。

## 本次扩充补上的对象类型

扩充前这些类型语料里一个都没有，或只有极少数：

| 类型 | 代表文件 | 说明 |
|---|---|---|
| RAP BDL (`.asbdef`) | `zbs_r_sasale.bdef.asbdef`、`zrap110_r_traveltp_sol.bdef.asbdef` | 业务行为、side effects、validation |
| CDS DDL 带关联 | `zhb_i_product.ddls.asddls`、`zc_te_connect2.ddls.asddls` | association、virtual column、计算属性 |
| BAPI 调用 | `zcl_e2e001_odata_v4_so_data.clas.abap` | OData v4 provider 调 `BAPI_SALESORDER_CHANGE` |
| IDOC | `zcl_aoc_check_68.clas.abap` | 读 IDOC 相关表、标记卡住单据 |
| OAUTH 2.0 + REST | `zcl_googlepoc_drive_impl.clas.abap` | token 处理、上传、重试 |
| 函数组 TOP include | `lzfg_eui_screentop.abap` | 屏幕数据、DDIC 表、模块声明 |
| 函数模块主体 | `lyui5_repository_loadp01.abap` | 1,777 行，XML 载荷组装 |
| 拆分类 LOCALS_IMP | `zcl_mcp_ajson.clas.locals_imp.abap`、`zrap110_bp_traveltp_sol.clas.locals_imp.abap` | 只有方法实现，无定义段 |
| ABAP Unit 大型套件 | `cl_ixml.clas.testclasses.abap` | 3,118 行生成测试类块 |
| 超大独立程序 | `z_ace_standalone.prog.abap` | 18,567 行，语句解析 + 语法遍历 |
| 微型片段 | `ZSOLID_REPORT_I01.abap`（22 行）、`ABAP_UPDATE_SQL.abap`（12 行） | 选择屏幕 + 单条 SQL；内联数据 + UPDATE |

## 仍缺

- dynamic SQL
- obsolete COMPUTE
- obsolete MOVE TO
- obsolete ADD TO
- obsolete SUBTRACT
- PERFORM ON COMMIT
- RANGES (live stmt)

这次用 zipball 全量扫了 **71 个仓库 / 3,783 个 ABAP 文件**，其中大部分不在
原语料里。`UPDATE TASK` 报了 3 个命中，逐个人工核过——全是**注释里的文字**
或**字符串常量**（ACE 的语法关键词表里有一项是字面量 `UPDATE TASK LOCAL`）。
把纯注释行和字符串常量剥掉再探，命中归零。所以原探测的"有 UPDATE TASK"
是探测方式造成的假象，已一并记进"仍缺"的判断里。

这些全部是 **ECC on-premise 专属**构造。GitHub 上的 ABAP 项目绝大多数跑在
ABAP Cloud / Steampunk，这些语法在那里根本不存在；企业代码不开源；
而 GitHub code search 匿名调用返回 401，无法按内容检索（本次复测仍为 401，
只能退而用 repo search + zipball 全扫）。
换言之这是**可得性上限**，不是检索不足 —— 现在扫描覆盖面是原来的 6 倍，
结论没有变化。

## 抓取过程中发现并修复的缺陷

1. **AMDP 探测用错了签名**。原正则 `FOR SELECT|ALL FIELDS|COUNT` 匹配的是 SQLScript 的**方法体**，而语料里明明有 `zcl_demo_abap_amdp.clas.abap` 却报 0/19。正确签名是 `BY DATABASE PROCEDURE ... LANGUAGE SQLSCRIPT`。
2. **`CLASS x IMPLEMENTATION.` 被漏判**。探测式以 `\s*$` 收尾，但真实源码行尾
   有一个句点，于是**每一个**类的实现段都被判为不存在（报 0/57，实际 38/57）。
3. **UTF-16 源码被存成乱码**。抓取器对字节做 `decode('utf-8', errors='replace')` 后写文本，而 sha256 记的是解码前的原始字节。`ZCL_FI_TOOLKIT.abap` 是 UTF-16 LE 带 BOM，落盘文件因此变成乱码，且哈希链断裂。U+FFFD 本身是合法 UTF-8，所以"能否解码"检不出来 —— 必须直接查替换字符。已重新抓取并归一化为 UTF-8，manifest 记录 `upstream_encoding`。
4. **zipball 根目录没剥**。zipball 内部路径自带 `<repo>-<branch>/` 前缀，抓取器给本地文件名剥了前缀却没给 manifest 的 `path` 剥，导致 28 条记录的 `url` 拼接错误（重新抓取时 404）。
5. **sha256 描述的不是落盘字节**。原抓取器记录的是 zip 里读到的原始字节哈希，
   但写盘时做了换行归一，于是哈希指向的字节从来不在磁盘上。现改为：先归一
   （剥 BOM、CRLF→LF、补行尾 LF），再对归一后的字节算哈希，`verify_corpus.py`
   直接 hash 磁盘文件比对。
6. **探测未区分代码与注释**。见"仍缺"，`UPDATE TASK` 的 3 个命中全在注释和
   字符串常量里。按内容下结论的探测必须先剥掉这两者。

## 校验

```bash
python analyzing-programs-workspace/verify_corpus.py Test-source/real
python analyzing-programs-workspace/scan_corpus.py   Test-source/real
```

`verify_corpus.py` 校验：文件齐全、sha256 匹配、行数匹配、全部为合法 UTF-8 且不含 U+FFFD、磁盘上无未登记文件。任一不满足即退出码 1。

本次额外做了一次上游回溯：36 个新文件全部重新从
`raw.githubusercontent.com`（或 GitHub contents API）拉取原文比对，
36/36 对上——其中 33 个逐字节相同，3 个只是上游缺行尾 LF。

## 尚未分析

94 个文件里目前只有 3 份报告（`abapgit_flow_logic`、`abapgit_forms`、
`abapgit_password_dialog`），全部来自 abapGit 一个项目。
**跨项目通用性尚未验证** —— 优先分析：

- `z_ace_standalone`（18,567 行，CLASS-POOL + CLASS-EVENTS + AMDP 三合一）
- `z_sde_standalone`（7,925 行）、`ztoad`（9,430 行）—— 独立工具的架构
- `zbs_r_sasale.bdef.asbdef` —— 语料里第一个 RAP BDL
- `zhb_i_product.ddls.asddls` —— 带 association 的 CDS DDL
- `zcl_mcp_ajson.clas.locals_imp.abap` —— 拆分类只有实现段，无定义段
- `zcl_e2e001_odata_v4_so_data.clas.abap` —— BAPI + OData v4
- `cl_ixml.clas.testclasses.abap` —— 3,118 行 ABAP Unit 套件
- 22 行的 `ZSOLID_REPORT_I01.abap` —— 极端短文本，测报告的边界行为

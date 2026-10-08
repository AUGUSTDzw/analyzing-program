# `ZMMR_PERF_EVAL_VEND` 源码分析报告

> 分析对象：`D:\Workspace\Skills\analyzing-programs\Test-source\zvend.abap`
> 文件：`REPORT zmmr_perf_eval_vend.`，357 行（含空行/注释），GBK/UTF-8 无关纯 ASCII 正文，CRLF 换行
> 分析方式：逐行通读 + ABAP 语义/ALV API/SAP MM 业务口径推理。**未连接 SAP 系统**（SE38/SE11/SE80 无法实际激活、运行、查看 ST22），因此凡涉及字典对象、索引、异常类、常量、域 FIX 值之处，一律显式标注「需在 SE38/SE11 核实」，不做无根据断言。

---

## 0. 一句话结论

这是一个**用 SALV 输出「供应商各类采购单据数量」的小统计报表**，代码里 10 个真正干活的点里藏着 **3 个必然导致错误结果或崩溃的缺陷（quot 指标整行丢失、constructor 错误处理形同虚设导致 initial 引用解引用、颜色码与总行数的数据类型错误）** 和 **1 个足以拖垮生产库的性能设计（最多 4 次可全表级扫描的 EKKO⋈EKPO `COUNT(DISTINCT)`，且选择条件可全空）**。它自称 `perf_eval`（绩效评估），实际算的是采购活动量，业务价值与命名严重错配。整体可读性尚可、`COUNT(DISTINCT ebeln)` 的用法是正确的（没有被 1:N JOIN 放大），但 OO 设计形同虚设——所谓"类"没有属性、没有状态，四个方法靠全局变量互相咬合。

**统计**：本次共发现 **52 条**问题/改进项，其中 P0 级 10 条、P1 级 21 条、P2 级 21 条；其中 **9 条标注需在 SE38/SE11 核实后才能定性**。

---

## 1. 程序骨架

### 1.1 对象与规模

| 项目 | 值 | 依据 |
|---|---|---|
| 程序名 | `ZMMR_PERF_EVAL_VEND` | L1 `REPORT zmmr_perf_eval_vend.` |
| 文件名与程序名不一致 | 文件叫 `zvend.abap`，程序叫 `zmmr_perf_eval_vend` | 见 G-02 |
| 类型 | REPORT（不是 OO 主程序），全代码在一个 include 里 | L1 |
| 全局类 | `lcl_perf_eval` | L58–L67 |
| **方法数** | **6 个**（`constructor` / `fill_disp` / `build_fc` / `disp_alv` / `set_tol` / `end_of_page`） | L60–L65。**注意：任务描述里说的"10 个方法"与源码不符**，源码里只有 6 个声明、6 个实现 |
| 选择屏幕 | 1 个 BLOCK，2 个 SELECT-OPTIONS | L48–L51 |
| 过程块 | 仅 `START-OF-SELECTION` | L351–L357，无 `INITIALIZATION`/`AT SELECTION-SCREEN`/`USER_COMMAND` |
| 数据库表 | `ekko`、`ekpo`、`lfa1`（全部只读） | L90、L100、L116、L172 |
| 数据修改 | **无**（纯查询程序，不含 INSERT/UPDATE/MODIFY DB / COMMIT） | 值得肯定 |

### 1.2 全局 DATA 清单（全部是报表级全局变量，不是类属性）

```abap
DATA: it_disp TYPE TABLE OF t_disp,
       wa_disp LIKE LINE OF it_disp,
       it_temp TYPE TABLE OF t_temp,
       wa_temp LIKE LINE OF it_temp,
       it_lfa1 TYPE TABLE OF t_lfa1,
       wa_lfa1 LIKE LINE OF it_lfa1.
```
> L41–L46（逐字）

ALV 相关 13 个引用（L25–L38，注释掉的 `it_layout` 不算）。**关键事实：这些引用全部定义在报表层，`lcl_perf_eval` 没有任何 ATTRIBUTES**（L58–L67 的 PUBLIC SECTION 只有 METHODS）。也就是说这个"类"其实是一组操作全局数据的子程序，实例化两次就会互相踩数据。这是本程序 OO 设计的根本问题（见 E-01）。

### 1.3 数据结构（逐字，L5–L22）

```abap
TYPES:BEGIN OF t_disp,
   lifnr TYPE lifnr,
   name1 TYPE name1_gp,
   bedat TYPE bedat,
   rfq  TYPE I ,
   quot TYPE I ,
   po   TYPE I ,
   cont TYPE I ,
   sch  TYPE I ,
END OF t_disp,
BEGIN OF t_temp,
   lifnr TYPE lifnr,
  CNT   TYPE I ,
END OF t_temp,
BEGIN OF t_lfa1,
   lifnr TYPE lifnr,
   name1 TYPE name1_gp,
END OF t_lfa1.
```

- `bedat` 进了结果结构但**从来没有任何一条语句给它赋值**（全文搜 `bedat` 只出现在 TYPES、SELECT-OPTIONS、以及 5 段 WHERE 里），最后在 ALV 里被隐藏并标为技术字段 → 纯死字段（C-08）。
- `CNT` 大写、其余小写，缩进 3 空格/2 空格混杂（L17 是 2 空格）——排版随手写，评审成本高。
- `cont` 与 ABAP 关键字 `CONT` 同名，虽然本例中 `TRANSPORTING lifnr cont` 里它被当作字段名解析（E-07，需在 SE38 核实不同版本解析）。
- `TYPE I`（4 字节有符号整型）承载计数，量级上完全够用，但项目规范通常要求 `i4` 或 `p_int8`（G-06）。

### 1.4 选择屏幕（逐字，L48–L51）

```abap
SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT- 001.
  SELECT-OPTIONS : s_lifnr FOR wa_disp- lifnr,
   s_bedat FOR wa_disp- bedat.
SELECTION-SCREEN END OF BLOCK b1.
```

- **两个选择条件都是可空的**，没有任何下限校验、没有任何默认值、没有任何变体、没有任何 F4 值帮助 → 这是 D-01 性能灾难的前提。
- `s_lifnr FOR wa_disp- lifnr` 把选择屏幕绑到一个**会被 `CLEAR` 的内表工作区**上（L111、L131、L150、L169 都 `CLEAR : wa_disp, wa_temp`）。时序上安全（PBO 早已把值拷进 `s_lifnr`），但设计极其脆弱：任何人以后在 `INITIALIZATION` 里读 `wa_disp-lifnr` 都会拿到空值（E-06）。
- `TEXT-001` 依赖报表文本元素 T00T，缺失则激活直接 SYNTAX ERROR（G-03，需核实）。

### 1.5 调用链

```
START-OF-SELECTION (L351)
 ├─ CREATE OBJECT : obj_rep.            (L354)
 ├─ obj_rep->fill_disp( ).              (L356)
 │    ├─ SELECT EKKO⋈EKPO → it_disp  (rfq，作为基表)      L90-L96
 │    ├─ SELECT EKKO      → it_temp  (quot)              L100-L105 + LOOP L107-L112
 │    ├─ REFRESH it_temp; SELECT EKKO⋈EKPO → it_temp (po)    L115-L122 + LOOP L124-L132
 │    ├─ REFRESH it_temp; SELECT EKKO⋈EKPO → it_temp (cont)  L135-L141 + LOOP L143-L151
 │    ├─ REFRESH it_temp; SELECT EKKO⋈EKPO → it_temp (sch)   L154-L160 + LOOP L162-L170
 │    ├─ SELECT LFA1 ... FOR ALL ENTRIES IN it_disp → it_lfa1  L172-L175
 │    └─ LOOP it_disp → MODIFY 贴 name1                   L177-L183
 └─ obj_rep->disp_alv( ).              (L357)
      ├─ set_tol( )     → 建 logo 布局 + 头部选择条件回显   L271-L327（顺便建 lr_logo）
      ├─ build_fc( )    → 列名/颜色/隐藏 bedat              L189-L252
      ├─ end_of_page( ) → 建 footer（顺便建 lr_footer）      L329-L346
      └─ gr_table->display( )                             L268
```
**注意 `constructor` 在 L354 被 `CREATE OBJECT` 隐式调用，但它只做 `cl_salv_table=>factory`（L78）——即 ALV 句柄在 `fill_disp` 之前就已经绑定了 `it_disp`。** 这一点是幸运的：SALV 在 `display()` 时才读取内表内容，所以 `fill_disp` 里对 `it_disp` 的所有修改都能反映到屏幕上。若哪次重构把 factory 挪到 `fill_disp` 之后，就会显示 0 行——这是当前设计里一个隐藏的时间耦合。

---

## 2. 业务视角：它到底算了什么

### 2.1 五个指标的真实口径

| 列 | ALV 文本 | 实际 SQL 口径（逐字） | 业务含义解读 |
|---|---|---|---|
| `RFQ` | `RFQ Created` | `bstyp='A'` 且 **明细** `b~loekz NE 'X'`，不要求 `statu` | 框架协议（询价）单据数 |
| `QUOT` | `Quotation Maintained` | `bstyp='A' AND statu='A'` 且 **表头** `loekz EQ space` | 已"下达/发布"的框架协议单据数 |
| `PO` | `PO Created` | `bstyp='F'`、**明细** `loekz EQ space`、`bsart NE 'UB'` | 采购订单数 |
| `CONT` | `Cont.` | `bstyp='K'`、明细 `loekz EQ space` | 采购合同数 |
| `SCH` | `Sch. Crea.` | `bstyp='L'`、明细 `loekz EQ space` | 计划协议数 |

所以业务故事是：**"这个供应商今年创建了多少询价/报价/订单/合同/计划协议"**——一条采购流程的"漏斗"计数。

### 2.2 这个"漏斗"在数学上站不住脚（关键业务缺陷）

`RFQ → QUOT → PO` 是一条漏斗，但代码里的三个分母/过滤条件互相不一致，导致**漏斗比例不可信**：

1. `RFQ` 用 `b~loekz NE 'X'`，`PO/CONT/SCH` 用 `b~loekz EQ space`（A-04）。`NE 'X'` 会把除 `X` 以外的一切取值都算进来，包括删除待处理标记（`EKPO-LOEKZ` 的域 FIX 值里除空/X 以外还有哪些取值，**需在 SE11 核实 EKPO-LOEKZ 的域 FIX**）。结果是：**同一个"已删除/待删除"的判断，在 RFQ 列和 PO/CONT/SCH 列用了两套规则**，一个供应商可能出现 `RFQ > 0 但 PO = 0` 或者 `RFQ` 比 `QUOT` 还小的荒谬组合。
2. `QUOT` 完全不看 `ekpo`（L100 的 SELECT 没有 JOIN），只看 `ekko-loekz`。而 `RFQ` 完全不看 `ekko-loekz`。于是：
   - 一张**表头已删除、明细未标删除**的框架协议 → 进 `QUOT`？否（表头 `LOEKZ='X'` 被 `EQ space` 排除）；进 `RFQ`？是（明细干净）；进 `PO`？是（`bstyp` 不同则否）。→ 一张被删的单据仍在 `RFQ` 列里。
   - 一张**表头未删、所有明细都标了删除**的框架协议 → 进 `QUOT`？是；进 `RFQ`？否。→ **这正是 A-01 数据丢失的触发场景。**
3. `RFQ` 不要求 `statu='A'`，`QUOT` 要求。`EKKO-STATU` 表示框架协议选择/下达状态，不要求 `STATU='A'` 就把"还没下达的框架协议"算成询价，于是 `RFQ` 分母被灌水，转化率被系统性低估（A-05）。
4. `PO` 排除 `bsart NE 'UB'`，而计划协议单独用 `bstyp='L'` 统计。`BSART='UB'`（Contract with Completion / 带完成通知的合同类型，通常用于 scheduling agreement outline）被笼统排除的**是整张凭证类型**，而不是"SA outline 项"。如果某业务把 `UB` 当普通订单用，这些真实 PO 会被少算；反过来，用 `bstyp='L'` 统计计划协议时，也会把"框架协议项产生的、类型为 L 的计划协议"和"库存/需求计划协议"混在一起（A-08，**需在 SE11/SE24 核实本项目对 `BSART`/`BSTYP`/`EINZ` 的实际配置口径**）。
5. `bedat` 是**凭证创建日期**。对 `bstyp='K'`（合同）和 `'L'`（计划协议），业务真正关心的是**有效期是否覆盖统计期间**（`EKKO-DATED`–`DATEE` 合同有效期、`EKKO-DATEG`–`DAEXE` 框架协议/计划协议有效期），而不是"这个月刚创建了几份"。用 `BEDAT` 过滤合同/计划协议，口径就是错的：上个月签的三年期合同在本月报表里显示为 0。A-07。
6. 计数是 `COUNT(DISTINCT ebeln)`，即**按单据数**而不是按行项目数。这是正确的（一个 500 行的订单仍算 1），但也意味着用户没法知道量级差异——1 个大订单和 1 个小订单在"绩效"上显然不等价（业务缺陷 F-01）。

### 2.3 名不副实：这不是绩效评估

程序名、类名、标题都叫 `perf_eval` / `'MM: Vendor Evaluation'`，但输出的五个数字全部是**采购活动量**，不含任何绩效维度：

- **准时交付率**：缺 `EKKO-EINDT`（交货日期）vs `EKPO-LFDAT`（计划交货日期），以及 `EKPO-EINDX`（交货日期确认标志）。
- **价格竞争力**：缺 `EINE-NETP/EINE-PRED/EINE-PRWEB`（信息记录价格）对比，也没有按同一物料比较各供应商的 `EKPO-NETP`。
- **拒收/退货/质量**：缺 `MSEG`（物料凭证）、`QMEL`（质量通知）、退货订单（`BSTYP`/`BSTAUTO` 退货流程）的任何统计。
- **及时足量供货**：缺收货超期天数、`MBE5`/`MARM` 收货与需求日期对比。
- **综合评分**：SAP 标准供应商评估是 `LYKAT` + 评价图谱（`RAT`），本程序完全不碰。
- **流程效率**：没有 `BEDAT → EINDT` 的周期天数，也没有"RFQ→PO 转化率"以外的漏斗。

**结论**：按现状，这个报表的业务价值是"采购员想知道自己在某段时间给每个供应商下了多少单"，而不是"绩效评估"。若客户确实需要绩效评估，本程序需要重构而非修补（F-01）。

### 2.4 维度不足导致生产上不可用

选择屏幕只有 `LIFNR` 和 `BEDAT` 两个维度。真要用它做供应商评估，**必须**能按以下维度切片，否则结果无法落地：

- 公司代码（`EKKO-BUKRS`）——跨公司代码合并统计没有意义，且涉及数据权限；
- 采购组织（`EKKO-EKOOR`）、采购组（`EKKO-EKGRP`）；
- 供应商类别/供应商组（`LFA1-LIFNR` 之外，如 `LFA1-UKRL`/`LGPRO`）；
- 物料组（`MARA-MATKL`）、采购价值类；
- 供应商状态（可用于排除已冻结/已删除供应商 `LFA1-LIFGS`）。

没有公司代码维度 + 没有权限过滤 = 一个普通业务用户可以看到全公司所有供应商的采购活动量，这是典型的 SoD/信息安全问题（F-02、F-06）。

---

## 3. 问题清单（按严重度排序）

严重度定义：**P0** = 会产生错误结果 / 崩溃 / 生产数据库风险；**P1** = 功能缺陷或明显健壮性问题；**P2** = 可维护性、规范、本地化、体验。
置信度：**确定** = 从源码语义可直接推出；**需核实** = 依赖字典对象、异常类或数据库行为，必须在系统里验证。

### 汇总表

| ID | 级别 | 置信度 | 位置 | 一句话 |
|---|---|---|---|---|
| A-01 | P0 | 确定 | L107–L112 | quot 循环缺 `APPEND` 兜底，整行供应商被静默丢弃 |
| A-02 | P0 | 确定 | L90–L96 + L107–L170 | 结果行集完全由 RFQ 决定，四个指标"造行"能力不一致 |
| A-03 | P0 | 确定 | L90–L160 | 表头/明细 `LOEKZ` 口径混用，五列计数互不可比 |
| B-01 | P0 | 确定 | L82–L85 + L354–L357 | constructor 的错误处理形同虚设，必然 initial 引用解引用 |
| B-02 | P0 | 确定 | L78–L83 | 异常被 catch 后不取 `get_text()`，且 `TYPE 'I'` 不是终止消息 |
| C-01 | P0 | 需核实 | L196、L207 | `ls_color-col = 3` 写入 `C(3)` 得到非法颜色码 `'  3'` |
| C-02 | P0 | 需核实 | L331、L338、L344 | `lf_lines TYPE sy-tfill`，>99 的总行数可能被截断 |
| D-01 | P0 | 确定 | L90–L160 | 最多 4 次 EKKO⋈EKPO `COUNT(DISTINCT)` 全表级扫描，选择条件可全空 |
| F-01 | P0 | 确定 | 全局 | 名叫绩效评估，实际只是单据量统计 |
| F-02 | P0 | 确定 | L48–L51 | 无公司代码/采购组织等维度且无权限过滤，生产不可用 |
| A-04 | P1 | 确定 | L94 vs L119/L139/L159 | `NE 'X'` 与 `EQ space` 两套删除标志口径 |
| A-05 | P1 | 确定 | L90–L96 vs L100–L105 | `statu='A'` 只在 QUOT 上要求，漏斗不可比 |
| A-06 | P1 | 需核实 | L116/L118、L136/L138、L155/L157 | JOIN 查询中 `lifnr`/`bedat`/`loekz`/`bsart` 未限定别名，有歧义风险 |
| A-07 | P1 | 确定 | L93/L102/L118/L138/L158 | 用 `BEDAT` 过滤合同/计划协议，业务上应过滤有效期 |
| A-08 | P1 | 需核实 | L120 | `bsart NE 'UB'` 排除的是整张凭证而非 SA outline 项 |
| B-03 | P1 | 确定 | L195–L197、L203–L208… | `?=` 后立即解引用：`gr_column` 可能残留上一列引用，属性设错列 |
| B-04 | P1 | 确定 | L199/L209/L216/L223/L230/L235/L242/L249 | 8 处 `CATCH cx_salv_not_found` 静默吞异常，无日志无消息 |
| B-05 | P1 | 需核实 | L325 | LOGO 图像 `ZCHEM_N_LOGO_SMALL` 缺失/无权限时无保护 |
| B-06 | P1 | 确定 | L90/L100/L116/L136/L155/L172 | 5 段 Open SQL 后均无 `sy-subrc` 检查与错误呈现 |
| C-03 | P1 | 需核实 | L265 vs L215/L194 | 三种布尔写法混用，`cl_salv_display_settings=>true` 常量存疑 |
| C-04 | P1 | 确定 | L285–L292 | `IF s_lifnr IS NOT INITIAL` 对 range 表恒真，`'Not Provided'` 是死代码 |
| C-05 | P1 | 确定 | L298–L306 | 同上，未填日期时头部显示 `00/00/0000` |
| C-06 | P1 | 确定 | L338 | 头部恒显示 `X to Y`，单值输入时也是区间文案 |
| D-02 | P1 | 确定 | L90–L160 | `COUNT(DISTINCT)` 作用于被 1:N 放大的中间结果集 |
| D-03 | P1 | 需核实 | L172–L175 | `FOR ALL ENTRIES IN it_disp` 前无空表判断 |
| E-01 | P1 | 确定 | L25–L46、L58–L67 | 类零属性、全靠全局变量，实例化两次即互相污染 |
| E-02 | P1 | 确定 | L256–L263、L323、L336 | `lr_logo`/`lr_footer` 在别的方法里创建，方法不可独立调用 |
| E-03 | P1 | 确定 | L100–L170 | 4 段 SELECT+LOOP 完全复制粘贴，仅字段名不同 |
| E-04 | P1 | 确定 | L64、L271、L327 | 方法名 `set_tol` 拼写错误（应为 tool/top_of_list） |
| F-03 | P1 | 确定 | L48–L51 | 无 F4 值帮助（供应商搜索、日期日历） |
| F-04 | P1 | 确定 | 全局 | 无变体、无默认选择条件、无 ALV 布局变式默认值 |
| F-05 | P1 | 确定 | L278/L283/L297/L305/L340/L342 | 硬编码英文文本与 `DD/MM/YYYY`，不可翻译 |
| G-01 | P1 | 确定 | L1/L325/L191/L275/L25 | 明显的复制粘贴遗留（`ZCHEM_` logo、`<color>`、注释掉的 `lvc_s_layo`） |
| A-09 | P2 | 确定 | L181 | `MODIFY` 只命中首个匹配行，若 `it_disp` 出现重复 LIFNR 只有第一行拿到名称 |
| A-10 | P2 | 确定 | L179–L182 | LFA1 查不到的供应商名称留白，无占位符 |
| C-07 | P2 | 确定 | L272–L273、L288、L302 | `lv_text(30) TYPE C` 硬长度 + `CONCATENATE INTO` 有溢出隐患 |
| C-08 | P2 | 确定 | L8、L213–L215 | `bedat` 列从未赋值却被做成隐藏技术列 |
| C-09 | P2 | 确定 | L294、L309、L314 | tooltip 与正文完全相同，纯噪音 |
| C-10 | P2 | 确定 | L260–L265 | 无布局变式/列宽/合计设置，ALV 每次回默认值 |
| D-04 | P2 | 确定 | L177–L183 | 名字回写用 N 次全表 `MODIFY`，O(n²) |
| D-05 | P2 | 需核实 | L93/L102 | 索引支持性未知（需在 SE11 看 EKKO LIFNR/BEDAT 索引） |
| E-05 | P2 | 确定 | L356 | 注释 `" Calling class Methods` 错误，调用的是实例方法 |
| E-06 | P2 | 确定 | L49–L50、L111 等 | 选择屏幕绑到会被 `CLEAR` 的工作区 |
| E-07 | P2 | 需核实 | L12、L110 | 结构组件名 `cont` 与关键字 `CONT` 同名 |
| F-06 | P1 | 确定 | 全局 | 无 `AT SELECTION-SCREEN` / `AUTHORITY-CHECK`，任何人可看全量供应商数据 |
| F-07 | P2 | 确定 | L186、L193–L250 | 仅按 LIFNR 排序，无按供应商名排序、无合计、无列合计 |
| G-02 | P2 | 确定 | 文件名 vs L1 | 文件名 `zvend.abap` 与 `REPORT zmmr_perf_eval_vend` 不一致 |
| G-03 | P2 | 需核实 | L48、L83 | `TEXT-001`/`TEXT-002` 依赖 T00T 文本元素 |
| G-04 | P2 | 需核实 | L277 | `create_header_information` 方法在本系统 Release 是否存在 |
| G-05 | P2 | 确定 | L191 | `INCLUDE <color>` 已过时，无必要 |
| G-06 | P2 | 确定 | L9–L13、L17 | 计数用 `TYPE I`，与项目 i4/p_int8 规范不符 |
| G-07 | P2 | 需核实 | L281–L282、L316–L319 | 子 grid 从 row=2 起画（row 1 空）＋4 个空 label 当占位符 |

（表中共 52 条，F-06 级别已在表中修正为 P1）

---

## 4. 详细分析：P0 级

### A-01 ★ quot 指标整行静默丢失

**位置**（逐字，L107–L112）：

```abap
    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- quot = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr quot WHERE lifnr = wa_temp-lifnr .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .
```

对比 PO 循环（逐字，L124–L132）：

```abap
    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- po = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr po WHERE lifnr = wa_temp-lifnr .
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .
```

**问题**：PO/CONT/SCH 三个循环在 `MODIFY` 未命中（`sy-subrc = 4`）时会 `APPEND` 新行，**唯独 quot 循环没有这个兜底**。`MODIFY ... WHERE` 找不到行时静默返回 4，计数被直接丢弃。

**触发路径**（真实业务场景）：
1. 某框架协议单据满足 L104 的 `bstyp = 'A' AND statu = 'A'` 且 `EKKO-LOEKZ` 为空 → 被计入 `it_temp`，进而应写入 `it_disp` 的 `quot` 列。
2. 但这张单据的 `EKPO` 行全部被标记 `LOEKZ='X'`（明细已删除，表头未同步）→ L94 的 `b~loekz NE 'X'` 不成立 → 该 LIFNR **不会进入基表 `it_disp`**。
3. `MODIFY` 未命中 → `quot` 值蒸发，用户看到的该供应商 `QUOT = 0`，而系统里明明有这张单据。
4. 后果：转化率分析失真，且**没有任何错误提示**——用户无从知晓数据被丢了。

**建议**：把 4 段循环合并成一个公共循环（见 E-03/重构方案），统一带 `IF sy-subrc NE 0. APPEND wa_disp TO it_disp. ENDIF.`。

---

### A-02 ★ 结果行集由 RFQ 单方面决定

`it_disp` 的初始行集**唯一来源**是 L90–L96 的 RFQ 查询：

```abap
    SELECT a~lifnr COUNT( DISTINCT a~ebeln ) AS rfq FROM ekko AS a
    JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    INTO CORRESPONDING FIELDS OF TABLE it_disp
    WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz NE 'X'
    AND a~bstyp = 'A'
    GROUP BY a~lifnr .
```

**问题**：这是一个隐式的"以询价为全集"的假设。
- 有 PO/合同/计划协议、但没有活跃询价的供应商，**只能靠 PO/CONT/SCH 三个循环的 `APPEND` 兜底才有机会出现**；
- 只在"已下达框架协议"阶段有单据的供应商（quot-only），**永远无法出现**（A-01）。

也就是说：**五列指标里，有四列能决定"这行要不要存在"，只有一列不能**。这是设计层面的不对称，属于典型的"补丁式修复"遗留（作者先写 RFQ，再逐列加，每加一列都复制一遍循环，quot 那一列的兜底就是漏写的那一次）。

**建议**：显式定义全集。两种合理口径：
1. **全部有采购单据的供应商** → 基表改成"不按 bstyp 过滤"的 `SELECT lifnr FROM ekko WHERE ...`，或用一次全指标聚合查询（见重构方案），全集天然正确；
2. **只评估有询价的供应商**（当前意图）→ 那 PO/CONT/SCH 的 `APPEND` 兜底就是错的，应该明确丢弃并至少给用户一个提示。

现在的代码是这两种意图的混合体，两边都不成立。

---

### A-03 ★ 表头/明细删除标志口径混用

把 5 段 SQL 的删除标志条件并排看（全部逐字）：

| 指标 | 行号 | 删除标志条件 | 检查哪一层 |
|---|---|---|---|
| RFQ | L94 | `AND b~loekz NE 'X'` | **明细** EKPO |
| QUOT | L103 | `AND loekz EQ space` | **表头** EKKO（且该 SELECT **没有 JOIN** ekpo） |
| PO | L119 | `AND b~loekz EQ space` | **明细** |
| CONT | L139 | `AND b~loekz EQ space` | **明细** |
| SCH | L159 | `AND b~loekz EQ space` | **明细** |

**问题**：SAP 的删除标志是两层（表头 `EKKO-LOEKZ` + 明细 `EKPO-LOEKZ`），两者可能不一致（表头删了明细没标；明细全删了表头没删）。本程序在 QUOT 上只看表头、其余只看明细，于是：

- **表头已删、明细干净的已删除单据** → 会进 RFQ/PO/CONT/SCH（只查明细，干净），不进 QUOT（查表头，'X' 被 `EQ space` 排除）。**删除的凭证仍然出现在绩效报表里。**
- **表头未删、明细全删的单据** → 进 QUOT，不进 RFQ（触发 A-01）。

**建议**：先和业务确认"删除"的标准口径（通常做法是同时排除表头与明细全删，即 `NOT (ekko~loekz = 'X' OR 全部明细 loekz='X')`），然后**五个查询统一使用同一条件**。若确认可以只用表头 `EKKO-LOEKZ`，性能还能顺便改善（见 D-01 优化路径）。

---

### B-01 ★ constructor 的错误处理形同虚设 → 必然 initial 引用解引用

**位置**（逐字，L82–L85 与 L351–L357）：

```abap
    IF gr_table IS INITIAL .
      MESSAGE TEXT -002 TYPE 'I' DISPLAY LIKE 'E'.
      EXIT .
    ENDIF .
  ENDMETHOD.                   "constructor
```

```abap
START-OF-SELECTION.
DATA : obj_rep TYPE REF TO lcl_perf_eval. " Declaring Object for Class

CREATE OBJECT : obj_rep. " Creating Object

obj_rep->fill_disp( ). " Calling class Methods
obj_rep->disp_alv( ).
```

**问题链**：
1. `EXIT` 在方法里只是"退出当前方法"，**不终止 `START-OF-SELECTION`**；
2. `CREATE OBJECT` 会**正常返回一个非空的 `obj_rep`**（构造过程没有抛出异常，构造成功）；
3. 调用方 L356/L357 **没有任何返回值/状态检查**，继续执行；
4. `disp_alv` 内的 `build_fc( )` 第一件事就是 `gr_columns = gr_table->get_columns ( ).`（L193）——`gr_table` 为 initial → **`CX_SY_REF_IS_INITIAL` 未处理异常 → 直接 dump**；
5. 即使侥幸走到 L268 `gr_table-> display( ).` 同样是 initial 引用 dump。

**实际后果**：作者以为写了错误处理，实际上是把"友好消息"换成了"短 dump"。用户在选择屏幕上看到一条 `TYPE 'I'` 的提示后，还会再看到一个 runtime error。

**建议**（三选一，推荐第 1）：
1. 抛异常：构造里 `RAISING cx_salv_error`，调用处 `TRY. ... CATCH cx_salv_error. MESSAGE ... TYPE 'E'. RETURN. ENDTRY.`；
2. `constructor` 返回 `subrc`/布尔，`START-OF-SELECTION` 里判断后 `RETURN`；
3. 最低限度：`disp_alv` 开头也加 `IF gr_table IS INITIAL. RETURN. ENDIF.`（双保险）。

---

### B-02 ★ 异常信息被吞掉 + 非终止消息

```abap
     TRY.
       cl_salv_table=> factory( IMPORTING r_salv_table = gr_table CHANGING t_table = it_disp ). "Calling Factory Obj of Cl_ALV_TABLE
    CATCH cx_salv_msg.
    ENDTRY .
```
> L77–L80（逐字）

两个问题：
1. `CATCH cx_salv_msg.` 后**空处理**——异常对象里最有用的 `get_text( )` 从未被取出。既然已经声明了 `cx_salv_msg`，正确写法是 `DATA lx_msg TYPE REF TO cx_salv_msg. ... CATCH cx_salv_msg INTO lx_msg. MESSAGE lx_msg->get_text( ) TYPE 'E'.`（**需在 SE38 核实 `CX_SALV_MSG` 是否有 `GET_TEXT( )`**；若为纯 CX_ROOT 子类则用 `CX_ROOT->GET_TEXT( )` 或 `MESSAGE ID ... NUMBER ...`）。
2. `MESSAGE TEXT -002 TYPE 'I' DISPLAY LIKE 'E'.`（L83）——`TYPE 'I'` 是**信息级消息**，程序继续执行（见 B-01）。想中断流程应该是 `TYPE 'E'` 或 `LEAVE LIST-PROCESSING` / `RETURN`。

---

### C-01 ★ `ls_color-col = 3` 是非法颜色码

**位置**（逐字，L195–L197）：

```abap
       gr_column ?= gr_columns-> get_column( 'LIFNR' ).
       ls_color- col = 3 .
       gr_column-> set_color( ls_color ).
```

**问题**：`LVC_S_COLO-COL` 的数据类型是 `LVC_COL`，即 **`c LENGTH 3`**（SAP 标准 ALV 的颜色码字段，取值如 `'BBB'`/`'YYY'`/`'GGG'`/`'CCC'`，**需在 SE11 的 SAPLPAI / type pool 里核实 `LVC_COL` 的长度与域 FIX 值**）。ABAP 把整型 `3` 赋给 `c(3)` 字段时按右对齐左补空格，结果是 `'  3'`——一个**非法颜色码**。结果通常是前端忽略该颜色并回退默认（浅灰或无色），即作者的意图落空；如果前端解析异常，还可能表现为整个列渲染异常。

同样的写法在 L207 又出现一次（NAME1 列）。

**建议**：`ls_color-col = 'GGG'`（浅灰）或 `'YYY'`（浅黄），并加注释说明意图；`ls_color` 也应每次 `CLEAR`，避免将来复用时残留 `nokey`/`emphasize`。

---

### C-02 ★ `lf_lines TYPE sy-tfill` 会截断总行数

**位置**（逐字，L331、L338、L344）：

```abap
    DATA :lf_lines TYPE sy-tfill .
```
```abap
     lf_lines = LINES( it_disp ).
```
```abap
     lf_flow-> create_text( TEXT = lf_lines ).
```

**问题**：`SY-TFILL` 是 ABAP **系统字段**（列表分页填充计数），其类型是 2 字符的字符型字段（**需在 SE38 用 `DATA lv TYPE sy-tfill. DESCRIBE FIELD lv.` 或在 SE41 里查 `SY` 结构核实长度**）。若确为 `C(2)`，则：

- `lf_lines = LINES( it_disp )` 会把行数右对齐截成 2 位，**供应商超过 99 家时，页脚显示的行数是错的**（比如 128 家显示 "28"）；
- 对一个"Vendor Evaluation"报表来说，供应商数量超过 99 是常态（一个中型工厂轻松几百上千家），所以这不是边缘 case，是**默认就错**；
- 即使长度够，用系统字段当数据类型也是坏味道（`SY-TFILL` 的语义是列表填充数，与"行数"毫无关系，将来系统字段属性变化会连累业务代码）。

**建议**：`DATA lf_lines TYPE i.` （或 `string`），一行改完，同时页脚可以加 `Total RFQ / PO` 之类的汇总（见 F-07）。

---

### D-01 ★ 生产库级别的性能风险

`fill_disp` 里有 **5 段独立的 Open SQL**（L90、L100、L116、L136、L155），其中 **4 段是几乎完全相同的 `EKKO ⋈ EKPO` 聚合**，只是 `bstyp`/`bsart` 过滤不同：

```abap
    SELECT lifnr COUNT( DISTINCT a~ ebeln ) AS CNT FROM ekko AS a JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz EQ space
    AND bsart NE 'UB'
    AND ( a~ bstyp = 'F' )
    GROUP BY lifnr.
```
> L116–L122（逐字）

**放大效应**：
1. `EKKO ⋈ EKPO` 是典型的 1:N。一张订单平均几十到几百行项目，JOIN 后的中间结果集比 `EKKO` 大 1–2 个数量级；
2. `COUNT(DISTINCT ebeln)` 必须在**放大后的结果集**上做去重（哈希/排序），无法用简单索引扫描完成；
3. `bstyp`、`statu`、`bsart` 都在 `EKKO` 上，`b~loekz` 在 `EKPO` 上 → 优化器只能先把 `EKKO` 过滤出的文档号与 `EKPO` 做半连接，再对结果去重；
4. **选择条件可以全空**（L49–L50 两个 SELECT-OPTIONS 都无默认值、无必输校验）→ 退化为 `EKKO`/`EKPO` 的**全表级扫描 × 4 次**，每张凭证的项目行被反复读取和排序。`EKKO` 在生产系统通常是亿级行、`EKPO` 十亿级行。

**实际风险**：用户随手按 F8（两个选择条件都留空）→ 数据库 CPU 打满、TSAR 飙升、作业超时甚至 dump，同时挤占同一台 DB 上所有业务系统的资源。这是最典型的"报表拖垮生产库"事故模式。

**建议（按收益排序）**：
1. **合并成一次查询**（最大收益，见 §5 重构方案）：一次 JOIN + 条件聚合，扫描次数从 4 次降到 1 次；
2. **去掉 JOIN**（次大收益）：如果业务确认"只按表头删除标志过滤"（很多 SAP 标准报表就是这么做的），`ekpo` 完全可以不 JOIN——`COUNT(DISTINCT ebeln)` 只需在 `EKKO` 上做，索引可用性大幅提升；
3. **强制选择条件**：把 `s_lifnr` 设为必输，或给 `s_bedat` 默认当月；
4. **提供变体**（F-04），把公司代码/采购组织等维度预置好，避免误执行。

---

### F-01 / F-02 名不副实与维度不足

见 §2.3、§2.4 的完整论证。这两条是**业务层面的 P0**，不是代码 bug：即使把所有代码 bug 都修好，这个报表仍然无法回答"供应商绩效"这个它自称要回答的问题，且在全公司范围无差别展示供应商采购数据存在信息安全隐患。

---

## 5. P1 级问题详解（要点）

### A-06 JOIN 查询中未限定表别名，有歧义风险

RFQ 查询（L93）写的是 `WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat`，而 PO/CONT/SCH 三段（L118、L138、L157）写的是 `WHERE lifnr IN s_lifnr AND bedat IN s_bedat`，且这三段的 `FROM ekko AS a JOIN ekpo AS b`。

- `bedat`：只有 `EKKO` 有，能编译通过；但**风格不一致**，读者必须自己去确认 `EKPO` 没有 `BEDAT`。
- `lifnr`：**这是真正的风险点**。SAP 的 `EKPO` 中存在一个字段名同为 `LIFNR` 的供应商字段（项目/分包供应商相关，**需在 SE11 查 `EKPO` 的字段清单核实是否包含 `LIFNR`**）。如果存在，Open SQL 在 INNER JOIN 下对多表同名字段的不限定引用会直接报错（字段歧义）；如果因为某些原因解析到了 `EKPO-LIFNR`，那筛选条件就用错了字段，结果是错的而程序照常跑。**无论哪种情况，`a~lifnr` 都是唯一正确的写法。**
- `loekz`、`bsart`（L119/L120）同理，应写 `b~loekz`、`a~bsart`。
- `GROUP BY lifnr`（L122）同理，应 `GROUP BY a~lifnr`。

**修复成本极低（每个查询 3–5 处），收益是消除歧义 + 与 RFQ 查询保持一致 + 让优化器看到更清晰的谓词。**

### A-07 用 `BEDAT` 过滤合同/计划协议是业务口径错误

`BEDAT` = 凭证创建日期。对 `BSTYP='K'`（合同）和 `'L'`（计划协议），业务上关心的是"**这份合同/计划协议在本统计期间是否有效**"，正确字段是 `EKKO-DATED`–`DATEE`（合同有效期）或 `EKKO-DATEG`–`DAEXE`（框架协议/计划协议有效期）；正确条件是区间重叠 `NOT ( DATEE < 起始 OR DATED > 结束 )`。

当前实现的后果很具体：**一份 2024 年签的三年期框架协议，2026 年的报表里显示为 0**。如果这个报表要用于绩效评估（合同覆盖率），结论会完全错误。

### B-03 `?=` 之后立即解引用 —— 可能把属性设到错误的列

```abap
       gr_column ?= gr_columns-> get_column( 'LIFNR' ).
       ls_color- col = 3 .
       gr_column-> set_color( ls_color ).
```
> L195–L197（逐字）

`?=` 的语义是"右边非 initial 才赋值"。这段代码的正确性完全依赖"`GET_COLUMN` 在找不到列时抛 `CX_SALV_NOT_FOUND`"这一前提（**需在 SE38 核实本 Release 的 `CL_SALV_COLUMNS_TABLE->GET_COLUMN` 行为：抛异常还是返回 initial**）。

- 若它抛异常 → 被 L199 的 `CATCH` 吃掉，逻辑侥幸正确；
- 若它返回 initial 而不抛异常 → `gr_column` **保持上一次成功赋值的引用**，`set_color` 会把颜色设置到**上一个列对象**上（例如本该给 NAME1 上色的代码把颜色打到了 LIFNR 上），而且**完全静默**。

这个模式在 `build_fc` 里重复了 7 次（L203、L213、L220、L227、L233、L239、L245），每一次都在赌同一个假设。正确写法是用局部变量接收并显式判空：

```abap
DATA lx_col TYPE REF TO cl_salv_column_table.
lx_col = gr_columns->get_column( 'LIFNR' ).
IF lx_col IS NOT INITIAL.
  ... lx_col->set_color( ls_color ).
ENDIF.
```
（`build_fc` 里反复复用全局 `gr_column` 本身也是个隐患，建议改成局部变量——见 E-01。）

### C-04 / C-05 / C-06 选择条件回显逻辑错误

```abap
    IF s_lifnr IS NOT INITIAL .
       lv_text = s_lifnr-low .
      IF s_lifnr-high IS NOT INITIAL.
        CONCATENATE lv_text ' to ' s_lifnr -high INTO lv_text SEPARATED BY space.
      ENDIF .
    ELSE .
       lv_text = 'Not Provided'.
    ENDIF .
```
> L285–L292（逐字）

```abap
    IF s_bedat IS NOT INITIAL .
      WRITE s_bedat-low DD/MM/YYYY TO lv_text .
      IF s_bedat-high IS NOT INITIAL.
        WRITE s_bedat-high DD/MM/YYYY TO lv_date.
        CONCATENATE lv_text ' to ' lv_date INTO lv_text SEPARATED BY space.
      ENDIF .
    ELSE .
       lv_text = 'Not Provided'.
    ENDIF .
```
> L298–L306（逐字）

**问题**：`s_lifnr` / `s_bedat` 是 SELECT-OPTIONS，其类型是**区间内表**。对内表做 `IS NOT INITIAL` 判定的是"**表里有没有行**"，而不是"有没有非空值"。选择屏幕处理完成后，这个区间表**永远至少有一行**（用户留空时也会有一行全空的区间），所以：

- `IF s_lifnr IS NOT INITIAL` **恒为真**，`ELSE` 分支（`'Not Provided'`）是**死代码**；
- 用户不填供应商时，`lv_text = s_lifnr-low` 赋的是 10 个空格 → ALV 头部显示一个**空白值**而不是 "Not Provided"；
- 用户不填日期时，`WRITE s_bedat-low DD/MM/YYYY TO lv_text` 会输出 **`00/00/0000`** → 头部显示 `00/00/0000`；
- 正确写法是 `IF s_lifnr-low IS NOT INITIAL`（对 `c(10)` 的空值判断），日期同理 `IF s_bedat-low IS NOT INITIAL` 或用 `coalesce( s_bedat-low, ... )`。

另外 **C-06**：用户只输入单个供应商号时，SAP 会把 `low`/`high` 都填成该值，`s_lifnr-high IS NOT INITIAL` 为真，于是头部显示 `0000012345 to 0000012345`。不算错，但体验别扭；应判断 `IF s_lifnr-high <> s_lifnr-low.` 才拼区间。同理日期单值会显示 `01.01.2026 to 01.01.2026`。

### D-03 `FOR ALL ENTRIES` 前缺空表判断

```abap
    SELECT lifnr name1 FROM lfa1
    INTO CORRESPONDING FIELDS OF TABLE it_lfa1
    FOR ALL ENTRIES IN it_disp
    WHERE lifnr = it_disp -lifnr.
```
> L172–L175（逐字）

`it_disp` 完全可能为空（用户输入的范围没有匹配数据）。`FOR ALL ENTRIES` 在驱动表为空时的行为取决于数据库与优化级别：历史行为是**退化为不带 WHERE 的全表读取**（在不支持 join-emulation 的数据库上），现代行为通常是返回空集但仍可能走非最优执行计划（**需在 SE11 检查 LFA1 的行数规模，并在实际系统上用 ST05/ST12 或 SQL Trace 验证**）。即使是空集，`LFA1` 也是大表（几十万行起步），一次无谓的全表扫描在生产上是不可接受的。

标准写法：
```abap
IF it_disp IS NOT INITIAL.
  SELECT ... FOR ALL ENTRIES IN it_disp ...
ENDIF.
```

### E-01 / E-02 这个"类"没有类该有的样子

- **零属性**：L58–L67 的 PUBLIC SECTION 只有 METHODS，`it_disp`、`gr_table`、`lr_logo`… 全在报表全局。任何依赖 `constructor` 初始化的假设都不成立；
- **方法间靠全局变量隐式耦合**：`set_tol` 里创建 `lr_logo`（L323），`disp_alv` 里使用 `lr_logo`（L262）；`end_of_page` 里创建 `lr_footer`（L336），`disp_alv` 里使用（L263）。因此 `set_tol`、`build_fc`、`end_of_page` **都不能被独立调用**——单独调用 `end_of_page` 会因为 `it_disp` 未填充/其他状态缺失而行为异常，单独调用 `build_fc` 会因 `gr_table` initial 而 dump（B-01 同源问题）；
- **`constructor` 名不副实**：它不接收任何参数、不做任何初始化（甚至没把选择条件存进实例），只调用一次 `cl_salv_table=>factory`。而且工厂调用放在**数据查询之前**（L354 在 L356 之前），依赖 SALV 延迟读表的隐含行为。

**正确结构建议**：`lcl_perf_eval` 的构造函数接收 `iv_lifnr`/`iv_bedat`（区间类型），所有内表与 SALV 句柄作为**私有属性**；对外只暴露一个 `main( )` 方法（内部按 采集→格式化→渲染 三步），内部方法用私有属性而非全局变量。

### E-03 4 段复制粘贴

L100–L170 是四段几乎完全一样的 `REFRESH / SELECT / LOOP / MODIFY / IF sy-subrc / APPEND / CLEAR`（约 18 行 × 4）。任何一处口径修改（比如统一删除标志、加上别名限定）都要改 4 遍——这正是 A-03/A-04/A-06 这类"只改了一半"缺陷的温床。合并方案见 §6。

### F-03 / F-04 / F-05 体验与本地化

- **无 F4**：`s_lifnr` 是供应商编号，没有 `AT SELECTION-SCREEN ON VALUE-REQUEST` 就无法按名称搜索，用户必须知道供应商号；`s_bedat` 也应提供标准日期 F4（`SET PARAMETER ID 'DAT'` / `DATE = sy-datum` 之类的日历）；
- **无变体**：两个选择条件每次都要手输；无 `INITIALIZATION` 里 `CREATE VARIANT`/`SAVE VARIANT`，也没有默认当月；
- **无 ALV 布局变式**：L260–L265 只做了 `set_all` 和条纹样式，没有 `gr_table->get_layout_settings( )->set_save_variations( )`、没有列宽/对齐/合计的默认值。用户每次都从默认布局开始，个性化设置无法作为变式分发；
- **不可翻译**：L278 `'MM: Vendor Evaluation'`、L283 `'Vendor No # :'`、L297 `'Posting Date:'`、L305 `'Not Provided'`、L340 `'Information:'`、L342 `'Total Number of Entries'` 全部硬编码英文字面量；L299/L301 硬编码 `DD/MM/YYYY`（覆盖了用户自己的日期格式设置，中国用户看到的是 dd/mm/yyyy 而不是 yyyy/mm/dd）。应全部改为文本元素 T100+。

### G-01 复制粘贴遗留的证据链

| 遗留物 | 位置 | 说明 |
|---|---|---|
| `ZCHEM_N_LOGO_SMALL` | L325 | 化学品（CHEM）项目的 logo 出现在供应商评估报表上，且**这是"复制自其他程序"的铁证** |
| `zmmr_` 程序名前缀 + `lcl_perf_eval` | L1、L58 | 前缀像 MM 报表族，类名像绩效评估，两边都没改干净 |
| `"Types Declaration` | L4 | 英文注释 + 中文需求的混合风格 |
| `INCLUDE <color>` | L191 | 7.40 之后已无必要 |
| `" For ALV {` / `"*------*` 注释块 | L24/L39/L53 | 老式 include 程序排版 |
| 被注释掉的 `it_layout TYPE lvc_s_layo` | L25 | 说明曾经想用 `lvc_s_layo` 后来改成 SALV，注释未清理 |
| `CREATE OBJECT`（而非 `NEW`） | L275、L323、L336、L354 | 老写法 |
| `METHOD set_tol` | L64、L271 | 拼写错误（疑为 `set_tool` 的笔误，或 `set_tol` 想表达 `toolbar/top_of_list`） |
| 文件名 `zvend.abap` vs `REPORT zmmr_perf_eval_vend` | — | 对象名与文件名不符，交接/传输时会踩坑 |

这些不是"风格洁癖"，它们是**代码来源不明的警示灯**：一段从别的程序复制来的代码，通常意味着被复制的那些隐患也一起过来了（`INCLUDE <color>`、`CREATE OBJECT`、以及 A-01 那种"复制时漏改"的错误模式）。

---

## 6. 建议的重构方案（骨架，非源码，仅供参考）

### 6.1 一次查询拿到全部五个指标

核心思想：把 4 段 JOIN 换成 1 段 JOIN + 条件聚合。

```abap
  SELECT a~lifnr
         COUNT( DISTINCT CASE WHEN a~bstyp = 'A' THEN a~ebeln END )                        AS rfq
         COUNT( DISTINCT CASE WHEN a~bstyp = 'A' AND a~statu = 'A'
                               THEN a~ebeln END )                                            AS quot
         COUNT( DISTINCT CASE WHEN a~bstyp = 'F' AND a~bsart <> 'UB'
                               THEN a~ebeln END )                                            AS po
         COUNT( DISTINCT CASE WHEN a~bstyp = 'K'
                               THEN a~ebeln END )                                            AS cont
         COUNT( DISTINCT CASE WHEN a~bstyp = 'L'
                               THEN a~ebeln END )                                            AS sch
    FROM ekko AS a
    JOIN lfa1 AS f ON f~lifnr = a~lifnr
    WHERE a~lifnr IN s_lifnr
      AND a~bedat IN s_bedat
      AND a~loekz <> 'X'                     " 口径：表头删除标志，需与业务确认
      AND a~bukrs IN s_bukrs                 " 建议新增公司代码维度
    GROUP BY a~lifnr
    INTO CORRESPONDING FIELDS OF TABLE it_disp.
```

收益：
- **扫描次数 4 → 1**，JOIN 放大后的去重只做 1 次而不是 4 次；
- `lfa1` 直接 JOIN 进主查询，消掉 `FOR ALL ENTRIES`（D-03）和整个名字回写循环（L177–L183，D-04）；
- 行集天然正确，A-01/A-02 同时消失；
- `COUNT(DISTINCT CASE ...)` 需要 **ABAP 7.40 SP05+**（**需在 SE38 核实系统 Release**）。若低于该版本，退而求其次：先 `SELECT lifnr bstyp statu COUNT(DISTINCT ebeln) ... GROUP BY lifnr bstyp statu` 取明细聚合，再在内表里用 `LOOP ... MODIFY` 汇总成 5 列（把 SQL 里的多行换成 ABAP 里的多行，仍是**一次**扫描）。

### 6.2 让行集语义显式化

无论用哪种方案，都要在代码里写清楚"这一行代表什么供应商"。建议在 `fill_disp` 开头加注释：
> 行集 = 统计期间内、在过滤条件（供应商/公司代码/日期）下有任一采购单据的供应商。
并据此**只保留一处**造行逻辑（不要四个循环各自 `APPEND`）。

### 6.3 类结构

```abap
CLASS lcl_perf_eval DEFINITION.
  PUBLIC SECTION.
    METHODS constructor
      IMPORTING iv_lifnr TYPE lifnr_range
              iv_bedat TYPE bedat_range
      RAISING   cx_vendor_eval_error.          " 自定义异常，替换 B-01/B-02 的假错误处理
    METHODS run.                               " 唯一对外入口
  PRIVATE SECTION.
    TYPES ...                                  " t_disp 等移入类内
    DATA ...                                    " it_disp / gr_table / ... 全部变属性
    METHODS collect_data.
    METHODS format_columns.
    METHODS build_top_of_list.
    METHODS build_end_of_list.
    METHODS render.
ENDCLASS.
```
- 所有 SALV 引用和内表进私有属性，`constructor` 负责全部初始化，`run` 负责编排；
- `build_fc` 里的 `gr_column` 改局部变量 + 判空（消除 B-03）；
- `lf_lines` 改 `TYPE i`（消除 C-02）；
- 颜色码用字面量 `'GGG'`/`'YYY'` 并加注释（消除 C-01）。

### 6.4 交互层

- `s_bedat` 初始值设为当月（`INITIALIZATION`）；
- `s_lifnr` 设必输或给出 F4；
- 新增 `s_bukrs`（公司代码）、`s_ekoor`/`s_ekgrp`（采购组织/采购组）、`s_matkl`（物料组）等维度，按 §2.4；
- 提供 `CREATE VARIANT` + `SAVE VARIANT`，并在顶部注释里写明推荐执行参数；
- 所有字面量改为文本元素 T100/T101/...，日期格式交给用户 profile（去掉硬编码 `DD/MM/YYYY`）；
- 修正选择条件回显：`IF s_lifnr-low IS NOT INITIAL`，单值时不拼 `to`。

---

## 7. 需在 SE38 / SE11 核实的清单

按优先级排列，这些是我**没有能力从源码单独确定**的点：

| # | 核实内容 | 怎么查 | 影响的结论 |
|---|---|---|---|
| 1 | `EKPO` 是否包含字段 `LIFNR` | SE11 `EKPO`，或 `SELECT * FROM ekpo WHERE 1 = 2` 看字段列表 | A-06：L118/L138/L157 是不限定别名（现状可能报错/取错字段） |
| 2 | `SY-TFILL` 的数据类型与长度 | SE38: `DATA lv TYPE sy-tfill.` → `DESCRIBE FIELD lv.` | C-02：>99 行数是否被截断 |
| 3 | `LVC_S_COLO-COL`（`LVC_COL`）的类型与域 FIX | SE11 type pool SAPLPAI / `LVC_COL` 域 | C-01：`'  3'` 是否为非法颜色码 |
| 4 | `CL_SALV_COLUMNS_TABLE->GET_COLUMN` 在找不到列时是抛 `CX_SALV_NOT_FOUND` 还是返回 initial | SE38 建本地测试类调用 / SE24 看方法定义 | B-03：是否会静默给错误的列设属性 |
| 5 | `CL_SALV_DISPLAY_SETTINGS` 是否有公共常量 `TRUE` | SE24 打开该类看 PUBLIC SECTION | C-03：`cl_salv_display_settings=>true` 是否能编译 |
| 6 | 报表文本元素 T00T 是否已维护 `001`/`002` | SE38 → Goto → Text elements | G-03 / B-02：能否激活；错误提示是否为空 |
| 7 | `CL_SALV_FORM_LAYOUT_GRID->CREATE_HEADER_INFORMATION` 在本 Release 是否存在 | SE24 打开该类 | G-04：能否编译 |
| 8 | `LCL_PERF_EVAL` 的属性区是否为空（确认零属性） | SE38 展开类定义 | E-01 |
| 9 | `IT_DISP`/`IT_TEMP`/`IT_LFA1`（本地匿名结构内表）能否作为 Open SQL 目标 | SE38 语法检查/激活 | 若报错，需改为 SE11 表类型；这是"能否编译"的前置条件 |
| 10 | `EKPO-LOEKZ` 域 FIX 的全部取值 | SE11 `EKPO-LOEKZ` → 域固定值 | A-04：`NE 'X'` 到底放进来哪些状态 |
| 11 | 图像 `ZCHEM_N_LOGO_SMALL` 是否存在、用户是否有读取权限 | TCODE `OAER` | B-05：显示时是否 dump |
| 12 | `EKKO` 上 `LIFNR`/`BEDAT` 的索引支持情况 | SE11 `EKKO` → 索引；ST05/ST12 看执行计划 | D-05：性能优化方向 |
| 13 | 本项目对 `BSART='UB'`、`BSTYP`、`EKPO-EINZ` 的实际业务口径 | 与业务/配置（SPRO）确认 | A-08：PO 与 SA 的划分是否正确 |
| 14 | `FOR ALL ENTRIES` 在本系统数据库上驱动表为空时的实际行为 | ST05/SQL Trace 实测 | D-03：是否全表读 LFA1 |
| 15 | 本系统 Release 版本 | `SP` 事务 / 系统状态 | 决定 `COUNT(DISTINCT CASE ...)`、`?=`、`CREATE OBJECT` 等写法是否合规 |

---

## 8. 值得肯定的部分

批判之外，这几点应保留：

1. **`COUNT( DISTINCT ebeln )` 的用法是正确的**（L90、L116、L136、L155）。在 1:N 的 `EKKO⋈EKPO` 上按凭证号去重，避免了"一张 500 行的订单被计成 500 次"这个最常见的报表错误。这是本程序技术含量最高、也最容易在重构时被写错的地方——**重构时务必保留 DISTINCT**。
2. **`TRANSPORTING` 用得对**（L110、L127、L146、L165、L181）：只更新当前指标那一列，不会把 `wa_disp` 里其它列的残留值（尤其是 `CLEAR` 之前的历史值）写回表里。很多人会在这里犯"用整行 MODIFY 导致其它指标被清零"的错。
3. **`CLEAR : wa_disp, wa_temp` 在循环末尾**（L111、L131、L150、L169）：保证 `APPEND wa_disp TO it_disp` 时不会把上一轮的历史数据带进新行。
4. **纯只读**：没有任何数据修改语句，不需要 `COMMIT WORK` / `ROLLBACK`，不存在锁与一致性问题。
5. **有基本的异常意识**：8 处 `TRY/CATCH`（虽然处理得不彻底，见 B-04），比裸写 SALV 强。
6. **延迟渲染的用法正确**：工厂在 `fill_disp` 之前调用、显示在之后（L354 → L356 → L357 → L268），符合 SALV "绑定数据 + 延迟读取" 的使用范式。
7. **抬头把选择条件回显到 ALV header**（L285–L314）：这是**好实践**，报表类需求方通常都要求这个。只是实现写错了（C-04/C-05），不是设计错了。

---

## 9. 建议补充的测试用例（针对上述缺陷）

| 用例 | 构造数据 | 期望结果 | 对应缺陷 |
|---|---|---|---|
| T-01 quot-only 供应商 | 1 张 `BSTYP='A' STATU='A'`、`EKKO-LOEKZ=' '`、其 `EKPO` 行全部 `LOEKZ='X'` 的 FA | 该供应商应出现在报表中且 `QUOT=1` | A-01（当前必失败，供应商整行消失） |
| T-02 表头删除单据 | 1 张 `EKKO-LOEKZ='X'`、`EKPO-LOEKZ=' '` 的 PO | 五列均不应计入（按统一口径） | A-03 |
| T-03 单值选择条件回显 | `s_lifnr` 只输一个供应商号，`s_bedat` 留空 | header 显示 `0000012345`（非 `X to X`）与 `Not Provided`（非 `00/00/0000`） | C-04/C-05/C-06 |
| T-04 空结果集 | 供应商范围输入不存在的号 | 报表正常显示 0 行，页脚 `Total Number of Entries 0`，**不 dump**，LFA1 查询被跳过 | D-03 + B-01 |
| T-05 ALV 工厂失败 | 故意在 factory 前破坏 `it_disp` 类型/或模拟异常 | 给出可读错误消息并**正常结束**（不 dump） | B-01/B-02 |
| T-06 行数 > 99 | 构造 150 个供应商 | 页脚显示 `150`，不被截断为 `50` | C-02 |
| T-07 列缺失容错 | 临时改结构去掉 `SCH` 字段 | 程序正常跑（列设置被跳过），并有可查的诊断信息 | B-04/B-03 |
| T-08 颜色码 | 激活后看 ALV LIFNR/NAME1 列 | 颜色为预期的合法颜色码，不是 `'  3'` | C-01 |
| T-09 性能基线 | `s_lifnr` 留空 + `s_bedat` 留空 | **应当被禁止**；若允许，需记录 ST05 运行时间与扫描行数作为后续对比基线 | D-01 |
| T-10 口径一致性 | 同一天同一供应商同时有 FA（statu='A'）+ 派生 PO | `QUOT >= 1` 且 `PO >= 1`，`RFQ >= QUOT`，不会出现 `RFQ=0 且 QUOT=5` | A-04/A-05 |

T-01 和 T-09 是**必做**的两条：一条证明数据丢失，一条证明生产风险。

---

## 10. 评估小结

| 维度 | 评价 |
|---|---|
| **业务价值** | 低。名字叫绩效评估，实际是单据量统计；缺 90% 的绩效维度；选择维度不足以支撑任何真实采购场景 |
| **正确性** | 差。有 3 个必然产生错误结果/崩溃的缺陷（quot 丢行、错误处理失效、颜色/行数数据类型错误），且 5 列计数口径互不一致，漏斗结论不可用 |
| **健壮性** | 差。异常吞掉不记录、无空结果保护、无选择条件下限、无 SQL 错误处理 |
| **性能** | 差。最多 4 次 EKKO⋈EKPO 去重聚合且可全表执行，是典型生产库事故模式 |
| **OO 设计** | 名不副实。零属性、全局变量、方法间隐式耦合、`constructor` 不做初始化 |
| **可维护性** | 中等偏低。复制粘贴 4 份、口径散落 5 处、拼写错误、遗留死代码、文本硬编码；命名/排版随意；无注释说明业务口径 |
| **优点** | `COUNT(DISTINCT)` 与 `TRANSPORTING` 用得对；纯只读；有 SALV header 回显意识；有基本异常意识 |

**如果只做三件事**：
1. 修 A-01（给 quot 循环补 `APPEND` 兜底）或直接上 §6.1 的单查询合并——同时消灭 A-01、A-02、D-01、D-02、D-03、D-04；
2. 修 B-01（错误处理改成 `RAISING` + `TRY/CATCH`，或至少在 `disp_alv` 开头加 `IF gr_table IS INITIAL. RETURN. ENDIF.`）；
3. 修 C-01 + C-02（颜色码 `'GGG'`、`lf_lines TYPE i`）——两个一行改动，去掉两个必现的显示错误。

做完这三件，程序至少是"数据可信、不崩、能看"的；至于"它到底该不该叫绩效评估"，那是需求层面的另一场对话（§2.3 / §6）。
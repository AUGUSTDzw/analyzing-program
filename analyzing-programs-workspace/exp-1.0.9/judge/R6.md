# 代码分析报告：`zmmr_perf_eval_vend`（Vendor Performance Evaluation）

- 源文件：`D:\Workspace\Skills\analyzing-programs\Test-source\zvend.abap`
- 规模：357 行（含空行与注释）
- 技术栈：ABAP 报表（`REPORT`）+ 本地类 + SALV OOALV
- 分析方式：全文逐行静态走读；**未在系统内执行/激活/跟踪**（无 SE80/SQL Trace/ST22 证据）
- 结论强度标注：`[确定]` 源码可直接判定 ｜ `[推断]` 基于 ABAP 语义的合理推断 ｜ `[需核实]` 需在目标系统验证

---

## 0. 一句话结论

这是一个**结构清晰但业务口径错误、性能不可控、且存在多处会导致 dump 的缺陷**的供应商采购绩效统计报表。它的价值主张（用 RFQ/报价/PO/合同/ Scheduling Agreement 的数量评价供应商绩效）在业务上**站不住脚**：只有数量没有金额，口径互相矛盾，且核心指标「QUOT」根本没有统计报价单。必须在限定选择范围、修正指标语义、增加权限校验与金额维度之后才能推给业务用户。

---

## 1. 程序骨架

### 1.1 对象清单

| 行 | 对象 | 说明 |
|---|---|---|
| 1 | `REPORT zmmr_perf_eval_vend.` | 程序名 `zmmr_perf_eval_vend` |
| 5–22 | `t_disp` / `t_temp` / `t_lfa1` | 三个本地结构 |
| 24–38 | ALV 对象引用声明 | `cl_salv_*` 一组 + `ls_color TYPE lvc_s_colo` |
| 41–46 | `it_disp` / `it_temp` / `it_lfa1` | **程序级全局内表** |
| 48–51 | 选择屏幕块 `b1` | `s_lifnr`、`s_bedat` |
| 58–67 | `CLASS lcl_perf_eval DEFINITION` | 6 个 public 方法，**零属性** |
| 75–348 | `CLASS lcl_perf_eval IMPLEMENTATION` | `constructor` / `fill_disp` / `build_fc` / `disp_alv` / `set_tol` / `end_of_page` |
| 351–357 | `START-OF-SELECTION` | 建对象 → `fill_disp` → `disp_alv` |

### 1.2 类型定义（逐字）

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
```

要点：
- `lifnr` 来自 LFA1-LIFNR（CHAR10），`name1` 来自 LFA1-NAME1，`bedat` 来自 EKKO-BEDAT（DATS）。`[确定]`
- 五个计数字段用 `TYPE I`（4 字节整数），计数上限约 21 亿，单供应商不可能溢出。`[推断：实际不构成缺陷，仅为风格]`
- `t_disp` 同时承担**输出结构**和**中间聚合载体**两个职责（既是 `MODIFY` 的工作区表，又是 ALV 的数据表）。`[确定]`

### 1.3 事件块与执行流

```
START-OF-SELECTION
  └─ CREATE OBJECT : obj_rep.
       └─ lcl_perf_eval=>constructor
            └─ cl_salv_table=>factory( CHANGING t_table = it_disp )   ← ALV 绑定全局内表
  └─ obj_rep->fill_disp( )
       ├─ SELECT #1 → it_disp（播种：RFQ，唯一一次初始化 it_disp）
       ├─ SELECT #2 → it_temp → LOOP → MODIFY it_disp (quot)        ← 无 APPEND 分支
       ├─ SELECT #3 → it_temp → LOOP → MODIFY/APPEND it_disp (po)
       ├─ SELECT #4 → it_temp → LOOP → MODIFY/APPEND it_disp (cont)
       ├─ SELECT #5 → it_temp → LOOP → MODIFY/APPEND it_disp (sch)
       ├─ SELECT #6 → it_lfa1  (FOR ALL ENTRIES IN it_disp)
       ├─ LOOP it_disp → READ TABLE it_lfa1（线性）→ MODIFY (name1)
       └─ SORT it_disp BY lifnr
  └─ obj_rep->disp_alv( )
       ├─ set_tol( )      → 造 top-of-list（标题 4 行 + 4 个空 label + logo）
       ├─ build_fc( )     → 列优化 / 标题 / 颜色 / 隐藏 BEDAT
       ├─ end_of_page( )  → 造 footer（Total Number of Entries）
       ├─ gr_functions-> set_all( abap_true )
       ├─ set_top_of_list( lr_logo ) / set_end_of_list( lr_footer )
       ├─ gr_display-> set_striped_pattern( ... )
       └─ gr_table-> display( )
```

---

## 2. 取数逻辑逐条走读（这是本程序的核心，也是问题最集中的地方）

### 2.1 RFQ（询价单数）

```abap
    SELECT a~lifnr COUNT( DISTINCT a~ebeln ) AS rfq FROM ekko AS a
    JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    INTO CORRESPONDING FIELDS OF TABLE it_disp
    WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz NE 'X'
    AND a~bstyp = 'A'
    GROUP BY a~lifnr .
```

这是**唯一一次向 `it_disp` 写入基础行**的语句（`INTO CORRESPONDING FIELDS OF TABLE`，非 `APPENDING`）。后续 4 个指标全部基于这批行做 `MODIFY` / `APPEND`。这一"播种"事实是 P06、P18 两处缺陷的共同根源。

### 2.2 QUOT（标注为 "Quotation Maintained"）

```abap
    SELECT lifnr COUNT( DISTINCT ebeln ) AS CNT FROM ekko
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND loekz EQ space
    AND ( bstyp = 'A' AND statu = 'A' )
    GROUP BY lifnr.

    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- quot = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr quot WHERE lifnr = wa_temp-lifnr .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .
```

注意与 PO/CONT/SCH 三个循环的**结构性差异**：这三个循环都有

```abap
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
```

而 QUOT 循环**没有**。详见 P06。

### 2.3 PO / CONT / SCH

```abap
    SELECT lifnr COUNT( DISTINCT a~ ebeln ) AS CNT FROM ekko AS a JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz EQ space
    AND bsart NE 'UB'
    AND ( a~ bstyp = 'F' )
    GROUP BY lifnr.
```

CONT 用 `bstyp = 'K'`，SCH 用 `bstyp = 'L'`，结构完全一致。

### 2.4 供应商名称

```abap
    SELECT lifnr name1 FROM lfa1
    INTO CORRESPONDING FIELDS OF TABLE it_lfa1
    FOR ALL ENTRIES IN it_disp
    WHERE lifnr = it_disp -lifnr.

    LOOP AT it_disp INTO wa_disp .
      READ TABLE it_lfa1 INTO wa_lfa1 WITH KEY lifnr = wa_disp-lifnr .
      IF sy-subrc EQ 0.
         wa_disp- name1 = wa_lfa1 -name1.
        MODIFY it_disp FROM wa_disp TRANSPORTING lifnr name1 WHERE lifnr = wa_disp- lifnr .
      ENDIF .
    ENDLOOP .
```

`it_lfa1` **从未 `SORT`**，因此 `READ TABLE` 是线性搜索；`it_disp` 也未排序，`MODIFY ... WHERE` 同样是线性扫描。详见 P17。

### 2.5 指标语义矩阵

| 输出列 | ALV 标题（源码原文） | 实际统计对象 | 业务含义是否对得上 |
|---|---|---|---|
| `LIFNR` | （无自定义标题） | 供应商号 | 建议设为热点/跳转键 |
| `NAME1` | `Vendor Name` | LFA1-NAME1 | 对 |
| `BEDAT` | 隐藏且 technical | 从未赋值，恒为 `00000000` | 无（P20） |
| `RFQ` | `RFQ Created` | EKKO，`BSTYP='A'`，按**项目级** LOEKZ 过滤 | 大体对 |
| `QUOT` | `Quotation Maintained` | EKKO，`BSTYP='A' AND STATU='A'` | **错**（P07/P08） |
| `PO` | `PO Created` | EKKO，`BSTYP='F'`，`BSART <> 'UB'`（恒真） | 基本对，过滤无效（P14） |
| `CONT` | `Cont. Created` | EKKO，`BSTYP='K'` | 基本对 |
| `SCH` | `Sch. Crea.` / `Sch. Agr. Created` | EKKO，`BSTYP='L'`（协议本体，非**调用/释放**） | 口径偏窄，需业务确认 |

---

## 3. 问题清单（共 48 项）

分级标准：**Blocker** = 程序无法运行或必然 dump；**Critical** = 程序能跑但数字错、丢数据、或存在安全/性能灾难；**High** = 数字口径偏差或用户可见故障；**Medium** = 可维护性与现代 ABAP 风格；**Low** = 细节与卫生；**文件层** = 源码文件自身的问题。

### 3.1 阻断级（Blocker）— 会编译失败或运行 dump

#### P01 ｜ `L265` 非法布尔字面量 `cl_salv_display_settings=>true` `[确定]`
```abap
     gr_display-> set_striped_pattern( cl_salv_display_settings =>true ).
```
`cl_salv_display_settings` 是一个类，**没有常量 `TRUE`**。SALV 的布尔参数类型是接口 `if_salv_c_bool_sap`，正确写法应是 `if_salv_c_bool_sap=>true`（同文件 `L215` 正好用对了）：
```abap
        gr_column-> set_technical( VALUE = if_salv_c_bool_sap=> true ).
```
同一份代码里两处布尔写法不一致，说明 `L265` 是复制粘贴/全局替换事故（把 `if_salv_c_bool_sap` 换成了 `cl_salv_display_settings`）。
- **影响**：作为文本文件存在即语法错误；程序无法激活。
- **需核实**：目标系统内是否存在本文件的另一版本已修正此行（若无修正，则该程序当前不可能被运行过——这与它的"生产报表"身份矛盾）。
- **修复**：改为 `gr_display->set_striped_pattern( if_salv_c_bool_sap=>abap_true )` 之类（本接口常量名为 `true`/`false`，具体常量名需核实）。

#### P02 ｜ `L93 / L102 / L118 / L138 / L157` JOIN 下 `bedat` 未加限定名 `[高置信推断]`
```abap
    WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
```
`ekko` 与 `ekpo` **两张表都含 BEDAT 字段**（EKKO-BEDAT 抬头过账日期、EKPO-BEDAT 项目过账日期）。前一个字段写了 `a~lifnr`，紧接着的 `bedat` 却没有写 `a~bedat`，是典型的"漏写限定名"。
- 若 EKPO-BEDAT 存在 → SQL 解析报"字段歧义"，**每次执行必 dump**。
- 若 EKPO-BEDAT 不存在 → 语句能跑，但**实际只按抬头 BEDAT 过滤**，与开发者"写漏了"的意图一致。
- **需核实**：`SE11` 查 `EKPO` 是否有 `BEDAT`；或对语句做 ABAP SQL 语法检查（`L1`/`Ctrl+F3`）；或 SQL Trace 看解析后的 SQL。
- **修复**：无条件改成 `a~bedat IN s_bedat`（并明确业务要的是抬头还是项目日期）。

#### P03 ｜ `L82-85` `EXIT` 只退出方法，不终止程序，后续必然空引用 dump `[确定]`
```abap
     IF gr_table IS INITIAL .
       MESSAGE TEXT -002 TYPE 'I' DISPLAY LIKE 'E'.
       EXIT .
     ENDIF .
```
`EXIT` 在方法内只跳出 `constructor`。控制流回到 `START-OF-SELECTION`，继续执行
```abap
obj_rep->fill_disp( ). " Calling class Methods
obj_rep->disp_alv( ).
```
`disp_alv` → `build_fc` → `L193 gr_columns = gr_table->get_columns ( )`，`gr_table` 仍为 initial → `CX_SY_REF_IS_INITIAL`。该异常**未被任何 CATCH 覆盖** → short dump。
- **影响**：SALV 工厂失败这条"优雅降级"路径实际上等于"提示一条消息然后 dump"。
- **修复**：把构造与 `IF gr_table IS INITIAL` 的判断上移到 `START-OF-SELECTION`，或让 `constructor` 抛 `RAISING cx_salv_error`、由调用方 `LEAVE LIST-PROCESSING`；最简单是失败即 `MESSAGE ... TYPE 'E'` + `LEAVE LIST-PROCESSING`（在事件块里才有效）。

#### P04 ｜ `L192-200` 在 `TRY` 之外解引用 `gr_columns` / `gr_column` `[确定]`
```abap
    TRY.
       gr_columns = gr_table->get_columns ( ).
       ...
    CATCH cx_salv_not_found.
    ENDTRY .

    TRY.
       gr_column ?= gr_columns-> get_column( 'NAME1' ).
```
第一个 `TRY` 只捕获 `cx_salv_not_found`。一旦 `gr_table` 为空（P03 的必然结果），这里抛出的是 `CX_SY_REF_IS_INITIAL`，**直接穿透**到运行时错误；而随后的 5 个 `TRY` 块全都在 `gr_columns` / `gr_column` 上继续解引用。
- **影响**：错误处理形同虚设；且 SALV 初始化失败无法被上层感知。
- **修复**：把 `get_columns` 提升为类的构造契约（构造失败即终止整个流程），列级配置全部放进同一个 `TRY ... CATCH cx_salv_not_found cx_salv_error` 内并逐列判空。

#### P05 ｜ `L325` Logo 名 `ZCHEM_N_LOGO_SMALL` —— 复制粘贴残留 + 缺图即 dump `[确定残留 / 需核实缺图行为]`
```abap
     lr_logo-> set_right_logo( 'ZCHEM_N_LOGO_SMALL' ). " Image From OAER T-code
```
- 程序名是 `zmmr_perf_eval_vend`，标题是 `'MM: Vendor Evaluation'`，Logo 却叫 `ZCHEM`（化工），高度疑似从另一支 ZCHEM 报表整体复制而来（注释里的 `OAER T-code` 也指向 SAP 标准示例代码）。
- **需核实**：SALV 在图片名不存在时是否抛未捕获异常（`CX_SALV_ERROR` 系）。本程序对此**零防护**。
- **业务影响**：即使能跑，任何用户都会看到**化工企业 Logo** 出现在采购绩效报表上——这是会被 PM 立刻打回的问题。
- **修复**：换成 `zmmr_` 前缀的真实图片名，或直接去掉 logo（顺便删掉 `L316-319` 四个占位 label）。

### 3.2 严重（Critical）— 结果错、数据错、安全

#### P06 ｜ `L110` QUOT 循环缺少 `APPEND` 分支：报价数被静默清零 `[确定]`
```abap
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr quot WHERE lifnr = wa_temp-lifnr .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .
```
对比 `L127-130`：
```abap
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr po WHERE lifnr = wa_temp-lifnr .
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
```
**后果链条**：`it_disp` 只由 RFQ 查询播种 → 某供应商若有 PO/合同但**没有任何 RFQ**，则它在 `it_disp` 里没有基础行。PO/CONT/SCH 循环会 `APPEND` 新行（有值），但 QUOT 循环不会。于是这类供应商显示为：
| 供应商 | 有 0 RFQ、有 3 PO、0 CONT、0 SCH | 结果行 | `QUOT` 列显示 |
|---|---|---|---|
| A | 无 RFQ、有 3 PO | 由 PO 循环 APPEND | `0`（"没有维护报价"）|
| B | 无 RFQ、**只有报价流程** | **整行不存在** | 供应商从报表中消失 |

两种都是**错误数字**，且用户无法察觉（B 还直接漏行）。
- **修复**：把 4 个循环统一为一个内部例程，统一"先 `READ`/`APPEND` 再写值"；或者彻底换掉 `MODIFY` 模式（见 §5 重构）。

#### P07 ｜ `L104` `statu = 'A'` 与列标题 "Quotation Maintained" 语义矛盾 `[确定矛盾 / 需核实 STATU 语义]`
```abap
    AND ( bstyp = 'A' AND statu = 'A' )
```
- `BSTYP='A'` 已经与 RFQ 指标完全同域；额外叠加的 `STATU='A'` 是**询价单处理状态**，绝无可能表示"已收到报价单"。ABAP/SAP 里"是否存在报价单"要靠**引用该询价单的 EKKO 文档**（`REFDOCNT/REFDOCNO` 指向原询价单）或报价相关表来判定，本查询完全没有涉及。
- ALV 里这一列的 medium text 是源码原文 `Quotation Maintained`，用户会**按字面理解**这个数字。
- **需核实**：客户端内 `EKKO-STATU` 的实际业务配置（确认 `'A'` 的含义），以及业务方期望的"报价"到底是哪张单据。
- **修复**：要么改口径为真正的报价单计数，要么改标题为 `RFQ Open（未决询价）`——**口径与标题必须一致，宁可先改标题**。

#### P08 ｜ QUOT 在数学上不可能大于 RFQ，且两列同源 `[确定]`
RFQ = `BSTYP='A'` 的全部文档数；QUOT = `BSTYP='A' AND STATU='A'` 的文档数。故恒有 `QUOT ≤ RFQ`。一个"报价数永远不超过询价数"的绩效表，业务方一眼就会看出不对，却又不报错——这种"看起来有数据、实际是废列"的状态最消耗信任。

#### P09 ｜ 无必输校验：留空选择范围即触发全表扫描 + 海量输出 `[确定]`
```abap
  SELECT-OPTIONS : s_lifnr FOR wa_disp- lifnr,
   s_bedat FOR wa_bedat.   "（源码原文见 L49-50）
```
（原文：`   s_bedat FOR wa_disp- bedat.`）
两个选择项都非必输，都可为空；程序甚至在表头主动打印
```abap
       lv_text = 'Not Provided'.   "L291 / L305
```
即**明确告知用户"你没填范围，我照样跑全库"**。空范围下的代价：
1. 5 次 `EKKO ⋈ EKPO` 的 `COUNT(DISTINCT)` 全量聚合（EKKO 常规量级 10^6~10^7）；
2. `FOR ALL ENTRIES IN it_disp` 在 `it_disp` 非空时会把**所有供应商**装进 `it_lfa1`（LFA1 通常 10^5~10^6 行）；
3. P17 的 O(n²) 循环；
4. 输出几十万行 ALV，用户既看不完也退不出。
- **修复**：`s_lifnr` 设为必输（或提供默认：采购组织/工厂范围），`s_bedat` 缺省给一个安全窗口（如近 12 个月）并限制最大跨度。

#### P10 ｜ `L331 / L338` `sy-tfill` 承载 `LINES( it_disp )`，上限 9999 `[确定风险]`
```abap
    DATA :lf_lines TYPE sy-tfill .
...
     lf_lines = LINES( it_disp ).
```
`SY-TFILL` 是 `P LENGTH 4`，有效值 0–9999。结合 P09 的无校验场景，行数轻易过万。
- **影响**：赋值时数值超界，运行期转换异常或数字被截断成错误值（`需核实`具体表现是 dump 还是静默截断），页脚显示一个错误的条目数。
- **修复**：改 `TYPE i` 或 `TYPE int8`，或直接用字符串模板 `|Total Number of Entries: { LINES( it_disp ) }|`。

#### P11 ｜ 全程无 `AUTHORITY-CHECK` `[确定]`
程序读取 `EKKO`/`EKPO`/`LFA1` 并向用户暴露"某供应商拿了多少 PO/合同/调度协议"——在采购域这属于商业敏感且通常与采购组织权限绑定的信息。程序既无 `AT SELECTION-SCREEN ON VALUE-REQUEST` 的 F4 权限过滤，也无运行期 `AUTHORITY-CHECK`。
- 叠加 `L261 gr_functions-> set_all( abap_true )`：**任意有事务权限的用户都可以把全量清单导出到本地文件**（见 P46）。
- **修复**：至少加 `AT SELECTION-SCREEN` 阶段对采购组织/采购组范围做授权校验，并对导出功能按需关闭。

#### P12 ｜ `L195 / L203 / L213 / L220 / L227 / L233 / L239 / L245` 共 8 处 `?=` 赋值语义风险 `[需核实，最高优先级]`
```abap
        gr_column ?= gr_columns-> get_column( 'BEDAT' ).
        gr_column-> set_visible( abap_false ).
```
`gr_column` 是**类属性**（`L29`），在 `build_fc` 内被反复复用。若当前系统版本中 `?=` 对引用类型的语义为"**仅当目标为初始引用时才赋值**"，那么从第二次起 `gr_column` 始终指向 `LIFNR` 列，后果是：
- `L214 set_visible( abap_false )` 会**把 LIFNR 供应商号列隐藏掉**；
- 所有 `set_short_text/medium_text/long_text/set_color` 全部写到 LIFNR 列上。
这与 P03/P04 的崩溃路径是同一类"作者用不熟的高级语法"的信号。
- **需核实**：用一段最小程序或查该关键字文档确认 `?=` 对引用的确切行为；或在系统内跑一次看 LIFNR 列是否可见。
- **修复**：无论语义如何，这里**没有使用 `?=` 的理由**，统一改成 `=`。零成本、零风险。

#### P13 ｜ `L172-175` `FOR ALL ENTRIES` 在空表时退化为全 LFA1 `[确定]`
```abap
    FOR ALL ENTRIES IN it_disp
    WHERE lifnr = it_disp -lifnr.
```
当 `it_disp` 为空（例如选择范围无匹配 RFQ）时，`FOR ALL ENTRIES` 不产生任何限制条件，整个条件变为 `LIFNR = 初始值`，**读入全部 LFA1**（这是 `FOR ALL ENTRIES` 的经典陷阱）。
- 好在随后的 `LOOP AT it_disp` 不执行，用户只看到空报表——**用户得到的是一个空报表，而背后已经吃掉了几十万行内存和一次全表扫描**。
- 此外，SAP 内核自 7.40 SP05 起已明确**不推荐 `FOR ALL ENTRIES`**（官方公告，建议改 join / 聚合下推）。`[确定]`
- **修复**：把名称取数合并进前面的聚合查询（一次 `JOIN lfa1`），彻底删掉 `it_lfa1` 与该循环。

### 3.3 高（High）

#### P14 ｜ `L120` `bsart NE 'UB'` 是恒真条件 `[高置信推断]`
```abap
    AND bsart NE 'UB'
```
`EKKO-BSART`（采购订单类型）长 4 字符，与 2 字符字面量 `'UB'` 比较时后者按空白补齐为 `'UB  '`，而有效订单类型不可能是 `UB  `，因此**该条件永远成立**，过滤从未生效。
- 作者真正的意图几乎肯定是排除"框架/伞形订单"，而伞形订单是 `EKKO-BSTYP`（单据类型）的取值，不是 `BSART`。`[需核实：本组织实际使用的排除单据类型字段与取值]`
- **修复**：确认要排除的单据类型后写成 `AND a~bstyp <> 'XX'`；若目的确实是排除某订单类型，改为 `AND bsart <> 'XXXX'`（4 字符）。

#### P15 ｜ 删除标记取自不同层级，5 个指标不可比 `[确定]`
- RFQ/PO/CONT/SCH：`AND b~loekz ...` → **项目级**删除标记（EKPO-LOEKZ）
- QUOT：`AND loekz EQ space`（FROM 只有 `ekko`）→ **抬头级**删除标记（EKKO-LOEKZ）
- 五个指标都**没有**过滤抬头删除标记 `a~loekz`。
后果：一个已删除抬头但项目未删的 PO 会被计入 `PO`；一个抬头删除的询价单却不计入 `QUOT`。同一张报表里 5 个数字来自两种不同的"删除"定义，横向比较无效。
- **修复**：统一为 `a~loekz = space AND b~loekz = space`，并与业务确认"部分删除的文档算不算"。

#### P16 ｜ `L94` 用 `NE 'X'`、其余用 `EQ space`，语义不等价 `[推断]`
```abap
    AND b~loekz NE 'X'
```
若数据中存在 `' '`/`'X'` 之外的值（例如 `'D'`），RFQ 会把它算进去而其他指标不会。至少是不一致，实际取值需核实。

#### P17 ｜ 全流程 O(n²)：线性 `MODIFY` + 未排序的线性 `READ TABLE` `[确定]`
- 4 个 `LOOP AT it_temp` 中的 `MODIFY it_disp ... WHERE lifnr = ...`：`it_disp` 是无显式主键的标准表，`MODIFY` 带 `WHERE` 为全表线性扫描 → O(n·m)。
- `L178 READ TABLE it_lfa1 ... WITH KEY lifnr = ...`：`it_lfa1` **从未 `SORT`**（全文件只有 `L186 SORT it_disp BY lifnr`），因此是线性查找 → O(n·m)。
- `L181 MODIFY it_disp FROM wa_disp TRANSPORTING lifnr name1 WHERE lifnr = ...` 又是一次线性扫描。
在 P09 的无校验场景下（供应商 10^5 量级），这一段足以让程序跑几十分钟到几小时。
- **修复**：`it_lfa1` 先 `SORT ... BY lifnr` 再 `READ ... BINARY SEARCH`；名称合并进 SQL 一次取回（最优）。

#### P18 ｜ `it_disp` 只由 RFQ 播种，"无 RFQ 供应商"靠初始值"碰巧"正确 `[确定]`
`rfq` 字段的唯一赋值来源是 RFQ 查询的 `INTO CORRESPONDING FIELDS OF TABLE it_disp`。由 PO/CONT/SCH 循环 `APPEND` 出来的行，其 `rfq` 是初始值 `0`——这个 `0` 恰好等于真实答案，但纯属巧合（没有任何代码在计算它）。任何一次字段复用/重排都可能把它变成脏值。**代码表达的不是意图，是运气。**

#### P19 ｜ 空结果集没有任何提示，直接进 ALV `[确定]`
`it_disp` 为空时，程序仍然走完 `set_tol`/`build_fc`/`end_of_page`/`display`。用户看到"只有标题、没有数据、页脚写着 Total Number of Entries: 0"的报表，**分不清是"没查到"还是"程序坏了"**。页脚虽然写了 0，但把总数放在一个 flow 的角落，可读性极低。

#### P20 ｜ `bedat` 是死字段，却被设成 technical 隐藏列 `[确定]`
`t_disp` 含 `bedat`，`s_bedat` 也基于它定义，但**任何语句都没有给 `bedat` 赋值**，全表恒为 `00000000`。随后
```abap
        gr_column-> set_visible( abap_false ).
        gr_column-> set_technical( VALUE = if_salv_c_bool_sap=> true ).
```
把一个恒空列设为 technical = 保留在布局变体和导出文件中。于是**用户导出的 Excel 里会有一列 00000000**，看起来像程序出错。

#### P21 ｜ 选择范围只填一端时，表头显示错乱 `[确定]`
```abap
     IF s_lifnr IS NOT INITIAL .
       lv_text = s_lifnr-low .
      IF s_lifnr-high IS NOT INITIAL.
        CONCATENATE lv_text ' to ' s_lifnr -high INTO lv_text SEPARATED BY space.
      ENDIF .
```
- 用户只填 `TO 9999`（low 为空）→ 表头变成 `" to 9999"`（前面一段空白）。
- 日期同理：`WRITE s_bedat-low DD/MM/YYYY TO lv_text`（`L299`）在 low 为初始值时输出 `00/00/0000`，表头变成 `"00/00/0000 to 20241231"`。
- 这是**很容易被普通用户踩到**的路径（很多用户习惯只填上限）。
- **修复**：分别判断 `low`/`high` 是否 initial，各自格式化后再拼接。

#### P22 ｜ `L344` 把 `sy-tfill`（P 类型）直接传给 `TEXT=` 形参 `[需核实渲染]`
```abap
      lf_flow-> create_text( TEXT = lf_lines ).
```
`create_text` 期望字符型参数，`sy-tfill` 是 `P LENGTH 4`。P→C 隐式转换会带入对齐用的空白位，页脚很可能渲染成 `"Total Number of Entries"    " 12 "` 这种带内部空格/尾随空格的文本。`[需核实：实际 SALV 渲染结果]`
- **修复**：`TEXT = |{ lf_lines ALPHA = OUT }|` 或先转字符串再传。

#### P23 ｜ 6 个空 `CATCH`，异常被完全吞掉 `[确定]`
```abap
    CATCH cx_salv_not_found.
    ENDTRY .
```
`build_fc` 里 7 处 `TRY` 有 6 处 handler 为空。这意味着：结构字段一旦改名（如 `rfq` → `zrfq`），ALV 列标题会**静默退回技术字段名**（`ZRFQ`），不会有任何报错，报表照常输出，用户看到的是一列看不懂的名字。
- **修复**：至少 `MESSAGE ... TYPE 'W'` 或写日志；更彻底的是把列名常量化 + 一次性校验。

#### P24 ｜ 指标口径零文档、无审计信息 `[确定]`
5 个指标的定义、过滤条件、删除标记取舍，**没有一行注释**（源码只有 `"RFQ`、`"Quot`、`"PO`、`"Cont. Created`、`"Sch Aggre` 这几个标签），而其中至少两个口径是错的（P07/P14）。同时页脚只写了条目数，没有生成时间、用户名、口径版本：
- 半年后没人说得清"上个月这张表的 QUOT 到底是什么"。
- 出错后无法追溯"这批数是什么时候、谁跑的、按哪个口径"。

### 3.4 中（Medium）— 可维护性与现代 ABAP 风格

| 编号 | 位置 | 问题 |
|---|---|---|
| **P25** | `L272-273, 286-288, 299-302` | `lv_text TYPE C LENGTH 30` + `WRITE ... TO` + `CONCATENATE ... INTO lv_text`：定长字段补的尾随空格会带进拼接结果与 tooltip（`TOOLTIP = lv_text`），提示框可能带一串空格。`[需核实 CONCATENATE 对尾随空白的具体处理]`。应改用字符串（`string`）或 `WRITE ... TO lv_text(10)` 精确截取。 |
| **P26** | `L24-39` | 用注释伪造括号：`"For ALV {` … `" For ALV }`。注释虽合法，但对不了解的人有误导性；`L25` 还留着一整行注释掉的 `it_layout TYPE lvc_s_layo` 死代码。 |
| **P27** | `L191` | `INCLUDE <color>.` 写在**方法体内**，且本方法未使用任何 `<color>` 宏（只用了 `lvc_s_colo` 类型）——位置可疑（`需核实`该版本是否允许在 METHOD 内使用 INCLUDE）且完全无用。 |
| **P28** | `L275, 323, 336, 354` | `CREATE OBJECT` / `CREATE OBJECT :` 为过时语句，新版本会产生语法警告，应用 `obj = new #( )`。 |
| **P29** | `L272-273, 331, 334` | 方法体内 `DATA` 声明（仅 `constructor` 的属性声明区放 `DATA` 是推荐做法）。把局部变量放到定义类的方法签名参数里更好。 |
| **P30** | `L58-67` | **类没有任何属性**。`fill_disp` 靠全局 `it_disp` 通信，`disp_alv` 靠全局 `it_disp` 取行数，`constructor` 靠全局 `gr_table`。这是"把过程式代码套了个类外壳"：不可测试、不可复用、无法多实例（两个实例会互相踩数据）。 |
| **P31** | `L29` | `gr_column` 作为类属性被 8 处 `?=` 复用 → 类方法有隐藏状态，`build_fc` 不能被安全地重复调用或重入。 |
| **P32** | `L256-263` | `set_tol`/`build_fc`/`end_of_page` 在 `disp_alv` 里被调用，但它们创建的 `lr_logo`/`lr_footer` 要到 `L262-263` 才被 `set_top_of_list`/`set_end_of_list` 消费。**创建与使用被割裂在两个方法里**，顺序一改就空引用。谁维护谁踩。 |
| **P33** | `L60-61` | `METHODS: constructor ,` / `fill_disp.` 与后面 4 个逐行 `METHODS` 风格混用；逗号前多余空格。另：`constructor` 用 ABAP 关键字作方法名，**语法合法性需核实**（若不合法，整个类定义无法激活）。 |
| **P34** | `L281, 316-319` | `lr_gridx` 内部从 `row = 2` 开始布局，而子 grid 本身挂在 `row = 2`，导致子表第一行永远为空（表头多一行空隙）；`L316-319` 连建 4 个空 label 当占位行来给 logo 腾高度——高度一旦变化（换图、改分辨率）布局就散架。 |
| **P35** | `L100` | 首个 `SELECT ... APPENDING it_temp` 之前没有 `REFRESH it_temp`，仅靠全局内表初始为空。后面三次都有 `REFRESH`。脆弱。 |
| **P36** | `L9-13, 41-46` | 缺 `TABLES: ekko, ekpo.`（隐式增强在新版本逐步淘汰）；计数用 `TYPE I` 而非 `int1`/`int8`；`it_lfa1`/`wa_lfa1` 用完不 `FREE`/`CLEAR`。 |
| **P37** | `L254-268` | ALV 无聚合、无合计行、无热点、无 `F4`、无法从供应商号跳转到其 PO 明细（`SET PARAMETER`/allocation relation）。对"绩效评估"这类要被追问"凭什么"的报表，**不能下钻 = 不可信**。 |

### 3.5 低（Low）— 细节与卫生

| 编号 | 位置 | 问题 |
|---|---|---|
| **P38** | `L9-13, 91, 108, 199` | 排版：`rfq  TYPE I ,` 的对齐空格与逗号前空格、`TYPE I` 大写、`AS rfq` 用小写别名与结构字段同名（靠 `CORRESPONDING FIELDS` 按名映射，脆弱）。 |
| **P39** | `L348` | `ENDCLASS.` 缺尾部注释（其他 6 处都有 `" lcl_perf_eval ...`）。 |
| **P40** | `L277-319` | 表单网格行列号全部硬编码（`row = 2..8`），加一行就要重排，且没有循环。 |
| **P41** | `L299-301` | `DD/MM/YYYY` 硬编码；US  locale 用户看到 `31/12/2024` 会误读。应 `DATE = USER`。 |
| **P42** | `L1-4` | 程序头无作者/版本/变更记录/需求单号注释，只有两个空行。 |
| **P43** | `L26-36` | 引用前缀混用：`gr_table`/`gr_column` vs `lr_grid`/`lr_logo`/`lr_label`/`lr_text`/`lr_footer`。 |
| **P44** | 全局 | **缺失金额维度**：`EKPO-NETWR`（订单净额）、`WRBAS`（订单币值）一次都没取。1 张 1000 万的 PO 与 20 张 100 元的 PO 在本表里都显示为 "1"。对"绩效评估"而言这是根本性缺失（详见 §6）。 |
| **P45** | `L278, 283, 297, 325, 340-342` | 所有文本硬编码英文（`'MM: Vendor Evaluation'`、`'Vendor No # :'`、`'Information:'`、`'Total Number of Entries'`），未用文本符号 → 无法支持 DE/中文用户。而 `L48` 的块标题却用了 `TEXT-001`，风格不统一。 |
| **P46** | `L261` | `gr_functions-> set_all( abap_true )` 无差别打开全部标准功能（含导出到本地文件、打印），与 P11 的鉴权缺失叠加形成数据外带路径。应按需 `set_data_export( abap_false )` 之类逐项开关。`[具体可用 set_ 方法名需核实]` |

### 3.6 文件 / 传输层

#### P47 ｜ 文件名与程序名不一致 `[确定]`
文件是 `zvend.abap`，但 `L1` 是：
```abap
REPORT zmmr_perf_eval_vend.
```
- 要么这是某个程序的一个 include（那本文件就不该带 `REPORT` 语句）；
- 要么文件名被改过（`zvend` 相比 `zmmr_perf_eval_vend` 短了 17 个字符，不像规范缩写）。
- **需核实**：传输请求里这个程序叫什么、有没有同名程序并存。

#### P48 ｜ 源文件里大量"多余空格"是转换产物，不是代码风格 `[确定]`
例如：
```abap
       wa_disp- lifnr = wa_temp -lifnr.
      SELECT lifnr name1 FROM lfa1 ... WHERE lifnr = it_disp -lifnr.
     JOIN ekpo AS b ON a~ ebeln = b ~ebeln
     lr_text = lr_gridx->create_text ( row = 4 column = 2
    TEXT = sy- datum tooltip = sy -datum ).
```
在 `-`、`~` 两侧被无规律插入空格。这不是人写的风格，而是**某种格式化/OCR/ABAP 语法高亮导出工具的产物**。ABAP 分词器能容忍，所以不影响编译，但：
- 用它做 diff / 代码评审会看到大量噪声；
- 也说明这份分析所依据的文件**未必与系统内激活版本一致**，所有"确定性"结论需在系统内复核。

---

## 4. 值得肯定的地方

为免评估失衡，先记优点：
1. 用 SALV OOALV 而非老的 `REUSE_ALV_GRID_DISPLAY`，技术选型方向正确。
2. 聚合逻辑用 SQL `GROUP BY` + `COUNT(DISTINCT)` 而非全量取明细进内存，思路正确。
3. `cl_salv_columns_table->set_optimize( abap_true )` 调了，列宽不会被硬撑开。
4. 列名 `LIFNR`/`NAME1` 与表头自定义标题分开设置，说明作者对 SALV API 有基本了解。
5. `fill_disp` 末尾 `SORT it_disp BY lifnr` 保证了稳定输出（虽然更应该在 SQL 里 `ORDER BY`）。
6. `wa_disp` 在循环尾 `CLEAR`，避免了跨轮次脏值（这是 P18 那种"靠运气"与"靠纪律"的边界）。

---

## 5. 重构建议（含可直接落地的骨架）

### 5.1 数据层：一次查询取代五次 + 一次 FAE

用单条聚合 SQL 直接产出完整数据集（要点：`a~bedat` 限定、抬头与项目双删除标记、`LEFT JOIN lfa1`、金额 SUM）：

```abap
SELECT a~lifnr AS lifnr
       l~name1 AS name1
       COUNT( DISTINCT CASE WHEN a~bstyp = 'A' THEN a~ebeln END ) AS rfq
       COUNT( DISTINCT CASE WHEN a~bstyp = 'F' THEN a~ebeln END ) AS po
       COUNT( DISTINCT CASE WHEN a~bstyp = 'K' THEN a~ebeln END ) AS cont
       COUNT( DISTINCT CASE WHEN a~bstyp = 'L' THEN a~ebeln END ) AS sch
       SUM( CASE WHEN a~bstyp = 'F' THEN b~netwr ELSE 0 END )     AS po_value
  FROM ekko AS a
  LEFT OUTER JOIN lfa1 AS l ON l~lifnr = a~lifnr
 WHERE a~lifnr IN @s_lifnr
   AND a~bedat IN @s_bedat
   AND a~loekz = @space
   AND b~loekz = @space
   AND a~bstyp IN ('A','F','K','L')
 GROUP BY a~lifnr, l~name1
 ORDER BY a~lifnr.
```

这一改动的收益是**结构性的**：
- 消除 P06/P18（播种与子集问题不再存在，所有指标天然同域）；
- 消除 P13/P17（FAE 与 O(n²) 全部消失）；
- 消除 P02（限定名明确）；
- 名称一次取回，`it_lfa1` 与 `READ TABLE` 循环整体删除；
- 顺带补上 P44 的金额维度。

> 需注意：`EKPO-LOEKZ` 在 `WHERE` 中会把项目级过滤隐含成 inner join 语义，`COUNT(DISTINCT)` 仍正确，但需在测试环境比对结果。

### 5.2 结构层：让类真正持有状态

```abap
CLASS lcl_perf_eval DEFINITION.
  PUBLIC SECTION.
    METHODS constructor
      IMPORTING it_data TYPE tt_disp
      RETURNING VALUE(ro_self) TYPE REF TO lcl_perf_eval.
    METHODS render.
  PRIVATE SECTION.
    DATA: mv_table TYPE REF TO cl_salv_table.
    METHODS build_header.
    METHODS build_footer.
    METHODS raise_if_incomplete.
ENDCLASS.
```
- 数据由构造参数传入 → 可单元测试、可复用、可多实例；
- `raise_if_incomplete` 在构造函数末尾调用并 `RAISING`，彻底解决 P03/P04 的"错误处理形同虚设"；
- `build_header` / `build_footer` 与它们的消费点收拢在 `render` 内一处，解决 P32。

### 5.3 交互层

```abap
AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_lifnr
  PERFORM restrict_vendor_range.

AT SELECTION-SCREEN.
  AUTHORITY-CHECK OBJECT ... .
  IF s_lifnr IS INITIAL.
    MESSAGE '请至少输入一个供应商范围' TYPE 'S' DISPLAY LIKE 'E'.
    LEAVE LIST-PROCESSING.
  ENDIF.
  IF s_bedat IS INITIAL.
    s_bedat = ... " 默认近 12 个月
  ENDIF.
```
`PERFORM` 里用 `CALL FUNCTION 'LIFNR_GET_LIST'` 之类做 F4 授权过滤（P11）。

### 5.4 修 P01/P12 的一行级改动清单

```diff
-     gr_display-> set_striped_pattern( cl_salv_display_settings =>true ).
+     gr_display->set_striped_pattern( if_salv_c_bool_sap=>true ).

-        gr_column ?= gr_columns-> get_column( 'LIFNR' ).
+        gr_column  = gr_columns->get_column( 'LIFNR' ).   " 8 处全部改 =
-       IF gr_table IS INITIAL . MESSAGE ... EXIT.        " constructor 内
+       " 改为 RAISING cx_salv_error，由事件块捕获后 LEAVE LIST-PROCESSING
```

---

## 6. 业务视角的批判性评估

抛开代码，这个报表的产品设计有三个更根本的问题：

1. **只有"个数"，没有"金额"和"质量"。**
   绩效评估的真实问题从来不是"你中过几次标"，而是"你带来的采购额、单均金额、按时交付率、质量合格率、账期遵守"。本表 5 列全是文档计数，且是**未经任何权重**的原始计数。一个接了 500 张小额 PO 的供应商和一个接了 3 张千万级 PO 的供应商，得分完全无法区分。对采购经理来说，这张表**不足以支撑任何供应商分级/淘汰决策**。
2. **口径未定义就上线。**
   "绩效"必须先定义评价维度与计算规则。当前 5 个指标的定义只存在于开发者脑子里（源码里没有任何注释），其中 2 个还是错的（P07/P14）。业务方从来没有机会确认"报价"指哪张单据——这是需求阶段缺失，不是编码阶段失误。
3. **时间窗口与"绩效周期"脱节。**
   `s_bedat` 基于 **EKKO-BEDAT（过账日期）**。绩效评价通常关心的是**单据创建日期**（`ERDAT`）或**履约/交货日期**。过账日期会随收货、开票而漂移，把一份 PO 归到哪一年，取决于对方什么时候开发票。这会系统性地扭曲年度排名。

**如果我是业务负责人，我会问三个问题，而这张表一个都答不了**：这个供应商今年贡献了多少采购额？交付准时率如何？报价响应速度如何？

---

## 7. 性能评估

| 场景 | 预估代价 | 结论 |
|---|---|---|
| `LIFNR` 限 1–5 家 + 半年 | 5 次带 LIFNR 范围索引的 EKKO 聚合 + 1 次 FAE | 可接受（秒级） |
| `LIFNR` 限 1 家 + 不限日期 | 全量 EKPO 扫描 + `COUNT(DISTINCT)` + O(n²) | 慢（分钟级） |
| **留空 + 半年** | 全表 JOIN × 5 + 全 LFA1 + O(n²) + 数十万行 ALV | **不可用（小时级 / dump / 超时）** |
| 超大 `COUNT(DISTINCT)` | 排序中间结果落盘 | 数据库侧瓶颈 |

关键放大器：P09（无校验）+ P17（O(n²)）+ P13（FAE 退化）三者叠加。**只补必输校验就能挡掉最坏情况**，是性价比最高的第一步。

---

## 8. 需核实清单（请在目标系统逐项确认）

| # | 待核实项 | 验证方法 |
|---|---|---|
| 1 | `EKPO` 是否存在 `BEDAT` 字段（决定 P02 是否是"每次执行必 dump"） | `SE11` → `EKPO` |
| 2 | `?=` 对引用的确切赋值语义（决定 P12 是否导致 LIFNR 列被隐藏） | 查关键字文档 / 最小测试程序 |
| 3 | `L265` 的 `cl_salv_display_settings=>true` 在系统内是否已被修正为 `if_salv_c_bool_sap` | `SE38` 查实际激活版本 |
| 4 | `EKKO-STATU = 'A'` 在本客户端的业务含义（决定 P07 的修正方向） | `SE24` 看值帮助 + 问业务 |
| 5 | 业务方期望的"报价单"到底是哪张单据/哪张表 | 需求访谈 |
| 6 | `bsart NE 'UB'` 想排除的到底是什么（`BSTYP`？某 4 位订单类型？） | 查 `EKKO-BSTYP` 值帮助 / 问业务 |
| 7 | `SY-TFILL` 超 9999 时的实际行为（dump 还是截断） | 最小测试程序 |
| 8 | `create_text( TEXT = <packed field> )` 的实际渲染（是否带空格） | 本地 ALV 实跑 |
| 9 | 图片 `ZCHEM_N_LOGO_SMALL` 是否存在、缺失时是否抛未捕获异常 | `OAER`/`SE91` + 最小测试 |
| 10 | `INCLUDE` 语句在 `METHOD` 内是否被该版本编译器接受 | 语法检查 |
| 11 | `METHODS constructor.` 中 `constructor` 作方法名是否合法 | 语法检查 |
| 12 | 文本元素 `TEXT-001`、`TEXT-002` 是否已在传输请求中维护 | `SE61` |
| 13 | 本文件与系统内激活版本是否一致（受 P48 影响） | `SE38` 版本管理对比 |
| 14 | 传输请求中该程序的真实名称（受 P47 影响） | `SE09`/`SE80` |
| 15 | 文件传输格式（UTF-8 有无 BOM / CRLF）是否与原系统一致 | 十六进制查看首字节 |

---

## 9. 建议行动顺序

**立即（阻断上线）**
1. 核实并修复 P01、P02 —— 否则程序根本无法运行。
2. 补 `s_lifnr` 必输校验（P09）+ 日期默认值 → 一次性消除最坏性能场景。
3. 修复 P03/P04 的异常传播路径。
4. 加 `AUTHORITY-CHECK`（P11），关闭无差别导出（P46）。

**短期（口径正确性）**
5. 与业务重定义 5 个指标（P07/P08/P14/P15），把定义写进代码注释与报告页脚（P24）。
6. 决定 QUOT 是"未决询价"还是"报价单"，**同步修正列标题**。
7. 修 P06 的 `APPEND` 缺失（或直接上 §5.1 的一次查询重构）。
8. 修 P21（半填选择范围）、P10（`sy-tfill`）、P20（删掉死字段 `bedat`）。

**中期（架构与可用性）**
9. 落地 §5.1 的单查询重构（顺带解决 P13/P17/P18/P44）。
10. 重构类结构（§5.2），补 `RAISING`，让类可测试。
11. 全量替换 `?=`→`=`（P12）、`CREATE OBJECT`→`new`（P28）、`INCLUDE <color>` 移除（P27）、去掉化工 Logo（P05）。
12. 下钻能力与聚合合计（P37）、文本符号化（P45）、日期格式本地化（P41）。

---

## 10. 问题统计

| 级别 | 数量 | 编号 | 后果 |
|---|---|---|---|
| 阻断（Blocker） | 5 | P01–P05 | 语法错误 / 运行 dump / 品牌事故 |
| 严重（Critical） | 8 | P06–P13 | 数字错误、静默丢数、越权、O(n²) 性能崩溃 |
| 高（High） | 11 | P14–P24 | 指标不可比、显示错乱、异常被吞、口径无文档 |
| 中（Medium） | 13 | P25–P37 | 可维护性、ABAP 风格、结构缺陷 |
| 低（Low） | 9 | P38–P46 | 排版、本地化、能力缺失 |
| 文件/传输层 | 2 | P47–P48 | 文件与程序不一致、文本被工具改写 |

**合计：48 项。** 其中"需在系统内核实后才能定性"的项目共 15 项（见 §8），`[推断]` 级 3 项，纯风格偏好、不影响运行的约 5 项（P38、P39、P42、P43、P26 的括号部分）。

按"是否会给出错误结果"归因：**13 项**直接导致数据错误或缺失（P02、P06、P07、P08、P10、P12、P14、P15、P16、P18、P20、P21、P22）；**9 项**导致运行失败或不安全（P01、P03、P04、P05、P09、P11、P13、P19、P46）；**26 项**为质量/可维护性/可用性缺陷。

---

*本报告基于静态阅读生成，未执行编译、激活或运行时跟踪。所有标注 `[需核实]` 的结论请以目标系统的实际行为为准。*
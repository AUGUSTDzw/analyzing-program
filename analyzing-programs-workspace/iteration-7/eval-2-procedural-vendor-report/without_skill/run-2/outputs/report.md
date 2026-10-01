# ZMMR_VEND_LIST 报表程序分析报告

> 源码：`evals/zmmr_vend_list.abap`（58 行，`REPORT`，非 OO，SLIS 全屏 ALV）
> 分析视角：业务问题 / 架构 / 执行流程 / 分模块讲解 / 问题清单 / 改进建议

---

## 一、这程序在回答什么业务问题

**"按采购组织范围内，统计每个供应商参与了多少张采购订单（PO 数量）。"**

拆开看输入与输出：

| 维度 | 内容 |
|---|---|
| 输入 | 供应商范围 `s_lifnr`（LFA1-LIFNR）、采购组织范围 `s_ekorg`（EKKO-EKORG） |
| 固定过滤 | `EKKO-BSTYP = 'F'` —— 只要采购订单，排除框架协议、采购计划等其它单据类型 |
| 输出 | 三列：供应商号 `LIFNR`、供应商名称 `NAME1`、订单数 `PO_CNT` |
| 粒度 | 按 `LIFNR + NAME1` 分组（一行一供应商） |
| 用途判断 | 采购分析/供应商评估类清单：谁参与得多、对比供应商活跃度。**不含金额、不含行项目、不含交货状态** |

所以它是一个**只做计数、不取金额的轻量统计报表**。注意 `COUNT( DISTINCT b~ebeln )`：因为 join 之后一个供应商在同一张单据下可能出现多行（同一 `EBELN` 会有多个采购凭证行项目），用 DISTINCT 才是"订单张数"，否则会算成"订单行数"。这一点代码处理是正确的。

---

## 二、架构与设计骨架

程序是典型的**经典 ABAP 报表三层骨架**：选择屏幕 → 单一事件块 → 三个 FORM 顺序执行。

```abap
REPORT zmmr_vend_list.
TYPE-POOLS: slis.                      " SLIS 类型池（REUSE_ALV_* 需要）

TABLES: lfa1, ekko.                    " 供 SELECT-OPTIONS 引用

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,   " ALV 输出内表（DDIC 结构）
      gt_fcat TYPE slis_t_fieldcat_alv,    " ALV 字段目录
      gs_layo TYPE slis_layout_alv.        " ALV 布局

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg.

START-OF-SELECTION.
  PERFORM get_data.          " ① 取数
  PERFORM build_fieldcat.    " ② 造字段目录
  PERFORM display_alv.       " ③ 显示
```

几个架构层面的关键取舍：

1. **输出结构来自 DDIC `ZMMR_VEND_S`**，而不是手写字段目录。这意味着程序对 ALV 列的描述权交给了数据字典（字段文本、长度、币种、日期格式、转换例程全部免费获得），这在本程序里体现为 `REUSE_ALV_FIELDCATALOG_MERGE` 一句话搞定。
2. **数据源与展示完全解耦**：`gt_out` 是唯一的"交接面"。取数只负责填 `gt_out`，展示只负责读 `gt_out`，两段代码互不知晓对方实现细节，这是本程序最值得肯定的一点。
3. **全局内表传递而非参数传递**：三个 FORM 之间靠全局变量通信（`gt_out`），没有 `USING`/`CHANGING` 参数。这在报表里是传统习惯，但代价是单元测试难写、依赖靠约定而非签名。
4. **技术栈是 SLIS (`REUSE_ALV_GRID_DISPLAY`)**，而不是 OO ALV / SALV。好处是零框架成本、字段目录自动化；代价是无法复用 SALV 的聚合、导出、变式、图表等能力。
5. **没有校验、没有用户命令、没有标题行**：三个 FORM 只干"取数—描述—显示"，业务逻辑极薄，所有复杂度都在那一条 SQL 上。

---

## 三、执行流程

```
┌─ 选择屏幕 PAA ───────────────────────────────────────────┐
│  S_LIFNR (供应商范围) / S_EKORG (采购组织范围)           │
└───────────────┬─────────────────────────────────────────┘
                │ 用户按 F8，空格进入 START-OF-SELECTION
                ▼
   PERFORM get_data  ──────────────────────────────────────┐
   ┌────────────────────────────────────────────────────┐  │
   │ SELECT a~lifnr, a~name1,                            │  │
   │        COUNT(DISTINCT b~ebeln) AS po_cnt            │  │
   │   FROM lfa1 a INNER JOIN ekko b ON a~lifnr=b~lifnr  │  │
   │  WHERE a~lifnr IN @s_lifnr                          │  │
   │    AND b~ekorg  IN @s_ekorg                         │  │
   │    AND b~bstyp  = 'F'                               │  │
   │  GROUP BY a~lifnr, a~name1                          │  │
   │   INTO TABLE @DATA(lt_vend)                         │  │
   │                                                     │  │
   │ sy-subrc = 0 → gt_out = VALUE #( FOR ... )         │  │
   │ sy-subrc ≠ 0 → MESSAGE '无符合条件的供应商' I       │  │
   │                 STOP  ← 程序在此结束，不进 ALV       │  │
   └────────────────────────────────────────────────────┘  │
                │                                          │
                ▼                                          │
   PERFORM build_fieldcat ──────────────────────────────────┤
   ┌────────────────────────────────────────────────────┐  │
   │ REUSE_ALV_FIELDCATALOG_MERGE                        │  │
   │   i_structure_name = 'ZMMR_VEND_S' → gt_fcat        │  │
   │ sy-subrc ≠ 0 → MESSAGE '字段目录生成失败' TYPE 'E'  │  │
   └────────────────────────────────────────────────────┘  │
                │                                          │
                ▼                                          │
   PERFORM display_alv ────────────────────────────────────┐
   ┌────────────────────────────────────────────────────┐  │
   │ gs_layo-zebra = 'X'; gs_layo-get_sel_info = 'X'    │  │
   │ REUSE_ALV_GRID_DISPLAY                               │  │
   │   is_layout=gs_layo  it_fieldcat=gt_fcat            │  │
   │   TABLES t_outtab = gt_out                          │  │
   │ → 弹出全屏 ALV 网格                                  │  │
   └────────────────────────────────────────────────────┘  │
                ▼                                          │
              结束（LEAVE PROGRAM）                          │
```

流程特点是**严格单向、无回退、无分支循环**：`get_data` 里的失败分支用 `STOP` 直接掐断流程，是整个程序唯一的控制流分叉。三段之间是硬编码顺序调用，改动顺序就坏。

---

## 四、按子程序分组讲解

### 4.1 `FORM get_data` —— 唯一的业务核心（18–36 行）

```abap
FORM get_data.
  SELECT a~lifnr,
         a~name1,
         COUNT( DISTINCT b~ebeln ) AS po_cnt
    FROM lfa1 AS a
    INNER JOIN ekko AS b ON a~lifnr = b~lifnr
    WHERE a~lifnr IN @s_lifnr
      AND b~ekorg IN @s_ekorg
      AND b~bstyp = 'F'
    GROUP BY a~lifnr, a~name1
    INTO TABLE @DATA(lt_vend).
  IF sy-subrc = 0.
    gt_out = VALUE #( FOR ls IN lt_vend
                      ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ).
  ELSE.
    MESSAGE '无符合条件的供应商' TYPE 'I'.
    STOP.
  ENDIF.
ENDFORM.
```

设计要点：

- **JOIN + GROUP BY 一次取完**：聚合在数据库侧完成，传输回 ABAP 的只有"每个供应商一行"，比"把凭证拉回内表再 LOOP 统计"好得多。这是正确的性能取向。
- **`INNER JOIN` 的语义取舍**：只统计**在 `s_ekorg` 内有采购订单**的供应商。选了某供应商但他没订单 → 该供应商不出现（而非出现一行 0）。这是"活动供应商"口径；如果业务想要"范围内所有供应商，含 0 单"，必须改 `LEFT JOIN` + `COUNT(b~ebeln)`。**这是本程序最需要向业务确认的口径问题。**
- **别名 `a`/`b` 屏蔽了 `TABLES` 工作区**：这里用到了 `lfa1`/`ekko` 的别名，内表层面不再引用 `TABLES` 生成的隐式工作区（`lfa1`/`ekko` 结构本身被 `SELECT-OPTIONS ... FOR` 引用而必须声明，所以 `TABLES` 保留合理，但工作区是死的）。
- **内联声明 `@DATA(lt_vend)`**：匿名结构，字段顺序/类型由 SQL 推导；随后用 `VALUE #( ... )` 逐字段显式映射到 `gt_out`。这一层转换**纯属重复搬运**（见 5.1）。
- **`sy-subrc = 0` 判定**：对 `SELECT ... INTO TABLE`，`sy-subrc = 0` 表示至少取到一行，判定正确。
- **失败即停**：空结果 → 提示 + `STOP`，用户永远看不到空 ALV。

### 4.2 `FORM build_fieldcat` —— 字段目录自动化（38–47 行）

```abap
FORM build_fieldcat.
  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING
      i_structure_name = 'ZMMR_VEND_S'
    CHANGING
      ct_fieldcat     = gt_fcat.
  IF sy-subrc <> 0.
    MESSAGE '字段目录生成失败' TYPE 'E'.
  ENDIF.
ENDFORM.
```

- **DDIC 驱动**：不手写 `REUSE_ALV_FIELDCATALOG` 的 `IT_FIELDCAT`。新增列只需 SE38 里扩 `ZMMR_VEND_S`，程序零改动 —— 扩展性极好。
- **代价**：列顺序 = DDIC 序号，用户无法在看程序里调整排序意图；也没留 `it_sort` / `i_default_layout` 的钩子。
- **失败分支靠消息驱动**（详见 5.3）：错误消息本身未必能终止后续流程。

### 4.3 `FORM display_alv` —— 展示层（49–58 行）

```abap
FORM display_alv.
  gs_layo-zebra = 'X'.
  gs_layo-get_sel_info = 'X'.
  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout   = gs_layo
      it_fieldcat = gt_fcat
    TABLES
      t_outtab    = gt_out.
ENDFORM.
```

- `zebra = 'X'`：斑马纹，全屏 ALV 上提升可读性 —— 唯一有 UX 考量的地方。
- `get_sel_info = 'X'`：允许用户在 ALV 里选行，会在 ALV 底部显示选中行数信息。**但程序没有 `FORM user_command`**，即用户选完行没有任何反应 —— 这是一个**悬空配置**（详见 5.4）。
- `t_outtab` 是 `TABLES`（非绑定）参数，符合 SLIS 惯例；输出后程序 `LEAVE PROGRAM`，ALV 数据不会丢失是因为 SLIS 自己接管了显示。

---

## 五、问题清单

按严重度排序。

### 5.1 `VALUE #( ... )` 是纯搬运，中间隔了一层匿名结构（严重度：低，但属明确冗余）

`lt_vend`（匿名）与 `gt_out`（`zmmr_vend_s`）字段一一对应，中间 6 行 `VALUE` 循环做了逐字段复制：

```abap
gt_out = VALUE #( FOR ls IN lt_vend
                  ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ).
```

直接一句即可，ABAP 的结构赋值会做隐式类型转换：

```abap
gt_out = lt_vend.      " 或 SELECT 直接 INTO TABLE @gt_out
```

更彻底的做法是直接让 SQL 写进 `gt_out`（列名与结构字段同名时可行），彻底消灭 `lt_vend`。当前写法让读者误以为两者字段名/类型有差异，其实没有。

### 5.2 空结果用 `MESSAGE 'I' + STOP`（严重度：中，兼有设计与运行风险）

```abap
MESSAGE '无符合条件的供应商' TYPE 'I'.
STOP.
```

三个问题：

1. **后台作业风险**：`STOP` 在后台执行中会中断整个作业（作业被标记为取消/系统终止），且不可控。报表被 SM37 批量调用时，"查不到数据"不应该杀掉作业。
2. **语义别扭**：信息类（'I'）消息本身**不会**终止程序，紧跟的 `STOP` 才终止。报表里的惯例是 `MESSAGE ... TYPE 'S'`（状态条提示）+ `LEAVE LIST-PROCESSING`，或 `TYPE 'W'` 警告后继续显示空 ALV。
3. **业务体验**：用户想要的是"我选了范围但没数据，告诉我原因，并让我放宽条件重查"，而不是被踢回初始屏幕、白跑一趟。

### 5.3 `TYPE 'E'` 的错误处理不可靠（严重度：高）

```abap
MESSAGE '字段目录生成失败' TYPE 'E'.
```

`E` 消息在**前台**通常会弹出并结束程序，但**后台执行时只写入作业日志、程序继续往下跑** —— 也就是说本意是"拦下来"，实际可能带着空的 `gt_fcat` 继续调 `REUSE_ALV_GRID_DISPLAY`，产生空列 ALV 甚至短转储。同理，这里也没有 `IF` 之后的 `STOP`/`RETURN` 兜底。

正确做法是显式终止，不依赖消息类型的隐式语义：

```abap
IF sy-subrc <> 0.
  MESSAGE '字段目录生成失败' TYPE 'S' DISPLAY LIKE 'E'.
  STOP.        " 或 LEAVE LIST-PROCESSING
ENDIF.
```

### 5.4 `get_sel_info` 是悬空配置（严重度：低）

`gs_layo-get_sel_info = 'X'` 让用户在 ALV 里可以选中行并看到选中数量，但程序**没有实现 `FORM user_command`**（`UCOMM` / `FORM user_command`），也没有 `it_fieldcat-...` 的选中事件处理。结果是：用户能选、能看到"已选 N 行"，然后按什么都没发生。要么补上 `FORM user_command`（比如导出、跳转凭证清单），要么删掉这个配置。

### 5.5 硬编码 `'F'` 与字面量消息（严重度：中）

```abap
AND b~bstyp = 'F'
MESSAGE '无符合条件的供应商' TYPE 'I'.
MESSAGE '字段目录生成失败' TYPE 'E'.
```

- `BSTYP = 'F'` 是 SAP 单据类型"采购订单"的硬编码值。应从 DDIC 取（`TABLES ekko TYPE ekko` → `ekko-bstyp` 的值帮助 / `CHECK-TRANSP`）或至少定义常量并加注释，避免后续扩展时漏改。
- 消息全是字面量、不带消息类（隐含 `00`）：无法被 SE63 翻译、无法被替换、无法统一维护文案。在多语言系统里这是硬伤。正确形式：

```abap
MESSAGE ID 'ZMM' NUMBER '001' TYPE 'I'.
```

### 5.6 选择屏幕无校验，范围全空会全表扫（严重度：中，性能）

两个 `SELECT-OPTIONS` 都没有 `AT SELECTION-SCREEN` 校验。如果 `s_lifnr` 和 `s_ekorg` 都留空（初始屏幕就是空的），用户按 F8 就是**在 LFA1 × EKKO 上做全量 join + group by**，在生产系统上可能是分钟级甚至超时。至少要拦：

```abap
AT SELECTION-SCREEN BEGIN OF BLOCK.
  IF s_lifnr[] IS INITIAL AND s_ekorg[] IS INITIAL.
    MESSAGE '请至少限制供应商或采购组织' TYPE 'S' DISPLAY LIKE 'E'.
    LEAVE LIST-PROCESSING.
  ENDIF.
AT SELECTION-SCREEN END OF BLOCK.
```

另外 `s_lifnr` 加 `NO-INTERVALS`（供应商号不需要区间）、`s_ekorg` 可以加 `NO-EXTENDS`，都是常见优化。

### 5.7 `PO_CNT` 的整数宽度隐患（严重度：低～中）

`COUNT( DISTINCT b~ebeln )` 在多数数据库上返回 8 字节整型；若 `ZMMR_VEND_S-PO_CNT` 定义为 `ZMMR_VEND_S-PO_CNT TYPE INT2/INT4`，超出范围时会**转储或截断**（ABAP 的整数赋值溢出即 runtime error）。另外还应检查 `ZTEXT` 里 `PO_CNT` 是否带了转换例程。建议 `PO_CNT` 用 `TYPE INT8` 或 `LENGTH`-自适应的类型。

### 5.8 `TABLES: lfa1, ekko.` 只用了一半（严重度：很低）

`TABLES` 会额外生成全局工作区 `lfa1`、`ekko`，而本程序用了 `AS a` / `AS b` 别名，从没引用过这两个工作区。保留 `TABLES` 本身是必要的（`SELECT-OPTIONS ... FOR lfa1-lifnr` 需要该类型可见），但如果以后有人误写 `lfa1-lifnr`，会隐式取全表第一行 —— 这是 `TABLES` 的经典陷阱。属于认知负担，不是功能缺陷。

### 5.9 其它细节

| 项 | 说明 |
|---|---|
| 无 `IT_SORT` | 结果按数据库返回顺序显示，用户想按订单数降序必须全选排序，无默认排序。 |
| 无标题/合计行 | 没有 `slis_layout_alv-info`、没有 `T_GROUPS` 合计，页面无上下文说明。 |
| `NAME1` 尾空 | `LFA1-NAME1` 是定长 `CHAR(30)` 带尾部空格，导出到 Excel 会出现多余空格，需 `CONDENSE` 或在 DDIC 侧处理。 |
| 无变式/保存 | `i_save = 'A'`、`I_SAVE(1)=''` 未设置，用户的列宽/筛选无法保留。 |
| 无测试载体 | 全局内表 + 无参数，使得这段取数逻辑无法写单元测试。 |
| 无 OO 封装 | 若后续要复用（比如加第二个"按物料"的报表），只能复制粘贴。 |

---

## 六、改进建议

### 6.1 立即可做（小改、零风险、收益明确）

1. **删掉 `VALUE #( ... )`**，改为 `gt_out = lt_vend;`，甚至直接 `INTO TABLE @gt_out`（前提：`ZMMR_VEND_S` 字段名与 SQL 列名一致）。省掉一次全表复制 + 6 行噪音。
2. **补 `AT SELECTION-SCREEN` 校验**：两个范围全空时拦下并提示；`s_lifnr` 加 `NO-INTERVALS`。
3. **错误处理改成显式终止**：`TYPE 'S' DISPLAY LIKE 'E'` + `STOP`，或 `MESSAGE ... TYPE 'E'` 后紧跟 `STOP`，不依赖消息隐式语义。
4. **空结果处理改成**：`MESSAGE '无符合条件的供应商' TYPE 'S'.` + `LEAVE LIST-PROCESSING.`（后台安全），或 `TYPE 'W'` 后照常显示空 ALV，让用户看到"列都在、就是没数据"。
5. **消息全部改用消息类** `ZMM` + `MESSAGE ID ... NUMBER ...`，纳入 SE63 翻译。
6. **`'F'` 换成可维护的常量或 DDIC 取值**（`ekko-bstyp` 的 check table），并加注释说明是采购订单。
7. **删掉 `get_sel_info`**，除非同时补 `FORM user_command`。
8. **确认 `PO_CNT` 字段宽度**与 `COUNT(DISTINCT)` 匹配（INT8），必要时 `ZTEXT` 里清掉转换例程。

### 6.2 中期优化（体验与可维护性）

```abap
" 1) 默认按订单数降序
DATA: ls_sort TYPE slis_sortinfo_alv.
ls_sort-sfieldname = 'PO_CNT'.
ls_sort-sorder     = 'D'.
ls_sort-spriority  = 1.
APPEND ls_sort TO gs_layo-sort.

" 2) 标题 + 空表提示
gs_layo-info       = '供应商采购订单统计'.
gs_layo-no_data    = '无符合条件的供应商'.
```

9. **加 `it_sort`**：默认 `PO_CNT` 降序 —— 统计报表的价值 90% 来自"谁排前面"。
10. **加 `gs_layo-info` 标题**与 **`no_data`** 空清单提示，替代现在的 `STOP`。
11. **加 `i_save = 'A'` + `is_variant`** 让用户保存个人布局。
12. **`NAME1` 用 `ZTEXT` 定义转换例程 `CONDENSE`**（或取数时 `MOVE a~name1 TO lv_name1` 后压缩），导出干净。
13. **加合计行**（`slis_t_totals_info_alv` + `do_totals` FORM），给出区间总单数 —— 报表用户几乎总会问"一共多少张"。

### 6.3 长期/重构（若程序要长期演进）

14. **封装成 OO 类**，例如 `ZCL_ZMMR_VEND_LIST`：
    - `ZIF_ZMMR_VEND_LIST~GET_DATA( IMPORTING it_lifnr it_ekorg RETURNING VALUE(rt_out) )` —— **取数变成可单元测试的方法**；
    - 一个 ZDDIC 类型 `ZMM_VEND_SEL`（范围结构）替代 `SELECT-OPTIONS` 全局变量；
    - ALV 用 SALV（`REUSE_ALV_GRID_DISPLAY` → `CL_SALV_TABLE`），白拿聚合、导出、变式、图表能力。
15. **口径参数化**：把"是否含 0 单供应商"做成选项（`LEFT JOIN` vs `INNER JOIN`），把"订单数 / 订单金额 / 行项目数"做成可选列，通过 `LEFT JOIN ekpo` 扩展到金额级别。
16. **性能兜底**：如果真实使用中范围经常很大，评估是否需要"先在 EKKO 上用 `ekorg + bstyp` 缩窄 LIFNR 集合，再用主键范围查 `LFA1`"的两步走法，而不是让数据库自由决定 join 顺序。

---

## 七、一句话总结

**结构上是教科书式的干净**（单向流程、DDIC 驱动字段目录、取数与展示解耦、聚合下推到数据库），**风险点集中在健壮性而非架构**：`MESSAGE 'E'` 在后台不终止、空结果用 `STOP` 会杀作业、选择屏幕无校验可能导致全量扫描、消息无消息类不可翻译、还有一处 `get_sel_info` 悬空配置。

按 6.1 的 8 条改完（大致 30 行以内改动、零架构影响），这个程序就能从"能跑"提升到"敢放进批量作业"。
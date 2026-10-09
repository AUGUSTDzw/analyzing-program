# ZMMR_PERF_EVAL_VEND 代码分析报告

- 分析对象：`Test-source/zvend.abap`（357 行，`REPORT zmmr_perf_eval_vend`）
- 分析日期：2026-10-08
- 分析方式：全文静态走读 + ABAP/SALV/采购业务语义审查
- 引用约定：所有代码片段逐字摘自源码。源码中大量出现 `wa_disp- lifnr`、`a~ ebeln = b ~ebeln`、`s_lifnr -high`、`sy- datum` 这类连字符/波浪号前后带空格的形式。这很可能是从 SAP 内核导出到文本文件时插入的排版噪声（ABAP 本身对空白不敏感），但也不排除源文件确实如此——已列入"需核实"。

---

## 0. 一句话结论

这是一个**借 SALV 输出供应商文档数量的报表**，程序结构上把"取数"和"ALV 外观"塞进同一个全局状态污染的本地类里，用 5 条独立的大表分组扫描拼出 5 个计数器——**但它既没有做"评价"，也没有做"性能"**：既没有比率/金额加权/期间对比/评级，也没有公司代码维度。更要命的是 5 个计数器互相不可比（第 4 节），所以它输出的数字**在业务上不能直接用来给供应商打分**。同时存在一条确定的 dump 路径（第 3.1 节）。

---

## 1. 报告画像

| 项 | 内容 |
|---|---|
| 类型 | 列表报表（List Report），`REPORT` + `START-OF-SELECTION`，无 Dialog / PAI |
| 输出 | SALV Grid（`cl_salv_table`），带 Logo 页眉 + 页脚 |
| 主数据 | `EKKO`（采购凭证抬头）、`EKPO`（采购凭证项目）、`LFA1`（供应商主数据） |
| 逻辑结构 | 1 个本地类 `lcl_perf_eval`，6 个 public 方法 + `START-OF-SELECTION` 驱动 |
| 全局状态 | 6 个 `it_*`/`wa_*` 内表、11 个 SALV 引用、6 个 `s_*` …全部全局 `DATA` |
| 命名意图 | 采购模块（MM）供应商绩效评价，按供应商列出 询价单/报价单/采购订单/合同/计划协议 的数量 |

**命名与实现的不匹配（第一个信号）**：程序名 `perf_eval`（Performance Evaluation，供应商绩效评价）。但代码里没有任何一行计算"比率"、"得分"、"等级"、"环比"，`end_of_page( )` 甚至只统计了总行数：

```abap
     lf_lines = LINES( it_disp ).
```

所以它是一个 **document counter**，不是一个 evaluation。

---

## 2. 执行流程逐段走读

```
启动
 │
 ├─ Selection Screen（b1 block, TEXT-001）
 │     s_lifnr (供应商范围，可空 = 全部)
 │     s_bedat (凭证日期范围，可空 = 全部)
 │
 └─ START-OF-SELECTION
      │
      ├─ CREATE OBJECT obj_rep
      │     └─ constructor
      │          cl_salv_table=>factory( ... CHANGING t_table = it_disp )
      │          CATCH cx_salv_msg → 空处理
      │          IF gr_table IS INITIAL → MESSAGE I + EXIT
      │
      ├─ fill_disp
      │     ① RFQ  : EKKO⋈EKPO  group by lifnr  → it_disp (rfq)
      │     ② QUOT : EKKO       group by lifnr  → it_temp → MODIFY (quot)
      │     ③ PO   : EKKO⋈EKPO  group by lifnr  → it_temp → MODIFY (po)
      │     ④ CONT : EKKO⋈EKPO  group by lifnr  → it_temp → MODIFY (cont)
      │     ⑤ SCH  : EKKO⋈EKPO  group by lifnr  → it_temp → MODIFY (sch)
      │     ⑥ FAE : SELECT lifnr name1 FROM lfa1 FOR ALL ENTRIES IN it_disp
      │     ⑦ 回填 name1：LOOP it_disp → READ it_lfa1 → MODIFY
      │     ⑧ SORT it_disp BY lifnr
      │
      └─ disp_alv
            set_tol( )      页眉网格 + Logo（4 个空 label 当空行）
            build_fc( )     列目录：改文本、设颜色、隐藏 BEDAT
            end_of_page( )  页脚：总行数
            set_all(abap_true) 打开全部标准功能
            gr_table->display( )
```

**关键观察**：数据在 `fill_disp` 里一条条"打补丁"式地 MODIFY 进 `it_disp`，而 `it_disp` 在 `constructor` 时就已经被 SALV 的 factory **按引用绑定**了。也就是说，这个内表是"传输带"：ALV 直接持有它，任何对它的直接修改都会立刻反映到界面上。程序没有区分"取数结果"和"展示结果"，这为后面的坑埋了雷。

---

## 3. P0 问题（会导致 dump / 结果错误 / 业务不可用）

### 3.1 [I01] 确定存在的 Dump 路径：工厂失败后程序不会停

```abap
  METHOD constructor.
    TRY.
       cl_salv_table=>factory( IMPORTING r_salv_table = gr_table CHANGING t_table = it_disp ). "Calling Factory Obj of Cl_ALV_TABLE
    CATCH cx_salv_msg.
    ENDTRY .

    IF gr_table IS INITIAL .
      MESSAGE TEXT -002 TYPE 'I' DISPLAY LIKE 'E'.
      EXIT .
    ENDIF .
  ENDMETHOD.
```

三个问题叠在一起：

1. **`CATCH cx_salv_msg.` 后面是空的** —— 工厂抛出异常的唯一后果是被吃掉，调用方拿不到任何原因。（I02）
2. **`MESSAGE ... TYPE 'I'` 不中断报表流程**。消息类型 `I` 只弹提示，随后 `START-OF-SELECTION` 会继续往下跑；`DISPLAY LIKE 'E'` 只是换个皮肤，不改变控制流。（I03）
3. **`EXIT` 退出的是构造方法本身，不是报表**。构造方法结束后 `START-OF-SELECTION` 照样执行：

```abap
obj_rep->fill_disp( ). " Calling class Methods
obj_rep->disp_alv( ).
```

于是 `disp_alv` → `build_fc` 第一行就踩空：

```abap
       gr_columns = gr_table->get_columns ( );
```

`gr_table` 初始 → `CX_SY_REF_IS_INITIAL` 未捕获 → **短 dump**。（`EXIT` 在构造方法中的合法性本身随版本有差异，已列入需核实；但无论它是否被接受，**它最多只能退出构造方法，无法阻止主流程**这个结论不变。）

**正确写法**：`MESSAGE 'xxx' TYPE 'E'.`（`E` 会终止整个程序），或 `MESSAGE ... TYPE 'S' DISPLAY LIKE 'E'. LEAVE LIST-PROCESSING.`，或最稳的：

```abap
IF gr_table IS INITIAL.
  cl_demo_output=>display( 'ALV 初始化失败' ).
  LEAVE LIST-PROCESSING.
ENDIF.
```

### 3.2 [I04] 成功判定是死代码

`cl_salv_table=>factory` 要么成功给 `gr_table` 赋值，要么抛 `CX_SALV_MSG`。既然异常被 catch 掉了，`IF gr_table IS INITIAL` 这个检查在本程序的现实路径里几乎不会被触达——但它本该是唯一的护栏。**一个失败路径上写的防护，往往是失败路径本身写错了**（这里是失败路径静默 + 通知方式不中断）。

### 3.3 [I05] 询价单与报价单用两种完全不同的粒度计数

```abap
    "RFQ
    SELECT a~lifnr COUNT( DISTINCT a~ebeln ) AS rfq FROM ekko AS a
    JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    INTO CORRESPONDING FIELDS OF TABLE it_disp
    WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz NE 'X'
    AND a~bstyp = 'A'
    GROUP BY a~lifnr .
```

```abap
    "Quot
    SELECT lifnr COUNT( DISTINCT ebeln ) AS CNT FROM ekko
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND loekz EQ space
    AND ( bstyp = 'A' AND statu = 'A' )
    GROUP BY lifnr.
```

RFQ 走了 `JOIN ekpo`（**项目级**），QUOT 根本没连 EKPO（**抬头级**）。后果：

| 场景 | RFQ 计数 | QUOT 计数 |
|---|---|---|
| 抬头未删、3 个项目全删 | **不计**（连不到活项目） | **计**（抬头 LOEKZ = ' '） |
| 抬头未删、3 个项目全活 | 计 | 计 |

两个计数器描述的是**同一类文档**（`BSTYP = 'A'`），却用不同的存活判定，且分母不一致。业务上看 RFQ > QUOT 无法解释成"报价转化率"。这是本程序最容易被误读的地方。

### 3.4 [I06] QUOT 循环缺 APPEND 兜底，导致整行供应商静默消失

对比三段几乎复制粘贴的循环：

```abap
    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp-lifnr.
       wa_disp- quot = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr quot WHERE lifnr = wa_temp-lifnr .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .
```

```abap
    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp-lifnr.
       wa_disp- po = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr po WHERE lifnr = wa_temp-lifnr .
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .
```

PO / CONT / SCH 三段都有 `IF sy-subrc NE 0. APPEND wa_disp TO it_disp.`，**只有 QUOT 段没有**。结合 I05 的粒度差异（RFQ 走项目级、QUOT 走抬头级），会出现：

> 某供应商有一条已结束（`STATU = 'A'`）、抬头未删的询价/报价记录，但该项目下所有项目行都已删除 →
> RFQ 段不产生该 `lifnr` → `it_disp` 里没有这行 → QUOT 段的 `MODIFY` 找不到 → **`APPEND` 缺失 → 这一行被完全丢弃**。

用户看到的就是"这个供应商怎么不见了"。程序没有任何提示。（该组合的实际发生频率需核实，但在逻辑上路径是通的。）

### 3.5 [I07] 5 个计数器的过滤条件互不一致

把 5 段 WHERE 摊平对比：

| 计数器 | 表 | 删除标志 | 文档类型 | 额外过滤 | 制单状态 |
|---|---|---|---|---|---|
| RFQ | EKKO⋈EKPO | `b~loekz NE 'X'`（项目级） | `bstyp='A'` | — | **无** |
| QUOT | EKKO | `loekz EQ space`（抬头级） | `bstyp='A'` | — | `statu='A'` |
| PO | EKKO⋈EKPO | `b~loekz EQ space`（项目级） | `bstyp='F'` | `bsart NE 'UB'` | 无 |
| CONT | EKKO⋈EKPO | `b~loekz EQ space`（项目级） | `bstyp='K'` | — | 无 |
| SCH | EKKO⋈EKPO | `b~loekz EQ space`（项目级） | `bstyp='L'` | — | 无 |

四类问题：

- **(a) 删除标志语义不一致**：`NE 'X'` 会把 `'D'`（LIFNR 侧的其它删除标志取值，需核实本系统是否启用）也算进去，而其余四个用 `EQ space`。（I08）
- **(b) RFQ 不过滤 `STATU`，QUOT 强制 `STATU='A'`**。对 `BSTYP='A'`，`STATU` 区分"已结束 / 未结束 / 不相关"（具体码值需核实）。这意味着 **RFQ 包含大量仍在进行中的、最终可能不产生报价的询价单，而 QUOT 只认已结束的**。用户会看到 RFQ=100 / QUOT=10，直觉理解成"10% 报价率"，实际是"10 条已结束询价产生了报价，另外 90 条还开着"。**转化率被结构性夸大。**（I09）
- **(c) `bsart NE 'UB'` 是 SAP 前 SRVO 时代的写法**。在 SRVO=1/2（增强采购凭证类型）启用后，`BSTYP='F'` 的单据 `BSART` 一律为 `'NB'`，真正的凭证类型落在 `EKKO-LTYP`。此时这条过滤**形同虚设**，老式框架订单会被计进 PO。（I10，需核实本系统是否启用了 SRVO）
- **(d) SCH 用 `BSTYP='L'` 一网打尽**。`BSTYP='L'` 同时覆盖计划协议（`BSART='LB'`）、调度协议（`BSART='LF'`）**以及针对计划协议开的释放订单**（`BSART='LA'`，通过 `EKKO-KDAUF` 关联）。也就是说，SCH 列很可能**把同一次采购行为数了两遍**。（I11，需核实业务期望）

### 3.6 [I12] 五个计数器彼此独立，没有做单据链路关联

MM 的采购链路是 询价 → 报价 → （可挂框架）→ 订单 → （可挂合同/计划协议）。SAP 里这层关系存在 `EKKO-KDANR`（框架订单号）、`EKKO-KDAUF`（上级单据）等字段。本程序把这些链路**完全忽略**，五个计数器各数各的。后果：

- 一张挂在框架订单下的 PO：PO 列 +1，框架订单本身因为 `bsart NE 'UB'` 没能被计进 PO（也不在任何其它列），**采购量被拆散了**。
- 从合同框架下的订单：PO +1、CONT +1，同一笔业务落在两个"能力指标"上。

所以"供应商做了 30 个 PO"和"供应商做了 30 个 PO 其中 20 个挂在框架协议下"在报表上无法区分，**对供应商的谈判力/集中度评估失效**。（需业务确认是否要做链路归因。）

### 3.7 [I13] 没有公司代码（BUKR）维度

```abap
    WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
```

`EKKO` 是跨公司代码的采购凭证抬头表，选择屏只有供应商和日期。结果：**所有公司代码的采购活动被合并成一行**。对一个集团型用户来说，这是这个报表最直接的业务可用性缺陷——用户看到"供应商 A 有 500 个 PO"，但他自己只经手了 30 个。（I14）

### 3.8 [I14] 空选择 = 全量扫描，且无任何性能护栏

`s_lifnr` 留空时 `IN s_lifnr` 不构成限制，报表会尝试聚合**全库所有供应商、所有期间的 EKKO/EKPO**（通常是千万级项目行）。结合第 5 节的 5 次扫描，用户只按了 F8 就等着看报超时。（I15）

### 3.9 [I16] 空结果无任何反馈

`fill_disp` 结束后没有检查 `sy-subrc`，也没有 `IF it_disp IS INITIAL` 的分支。用户选了一个不存在的供应商，ALV 会干净地显示 0 行 + 一个"Total Number of Entries: 0000000000"的页脚（见 I35），**看起来像"正常但没数据"，而不是"你的选择条件有问题"**。

---

## 4. 业务视角批判：它不做"绩效评价"

即使把上面所有技术问题都修好，输出仍然是一个"数字表"。真正的供应商绩效评价至少需要：

| 维度 | 本程序 | 说明 |
|---|---|---|
| 文档数量 | 有 | 但口径不可比（见 I07） |
| 金额加权 | **无** | 1 张 1000 万的 PO 与 100 张 1 千的 PO 等权 |
| 转化率 | **无** | 有 rfq/quot 却没有 `quot/rfq`，且分母失真（I09） |
| 期间对比 | **无** | 不能看趋势，只有一个静态截面 |
| 目标/评级 | **无** | 没有 A/B/C 分档、没有与年度目标对比 |
| 交付表现 | **无** | 交货及时率、逾期次数完全没有（这才是绩效的核心） |
| 单据链路 | **无** | 见 I12 |
| 公司代码 | **无** | 见 I13 |
| 采购组织/采购员 | **无** | 无法定位责任归属 |

**结论**：这个程序的名字承诺了 `performance evaluation`，代码交付的是 `document counting`。要么改名（`ZMM_DOC_COUNT_BY_VENDOR`），要么补齐至少"比率 + 期间对比 + 评级"三件事，否则业务上很容易被拿去做供应商打分，那结论是不可靠的。

---

## 5. 性能剖析

### 5.1 [I17] 5 条独立的分组扫描

`fill_disp` 里 4 段是 `EKKO ⋈ EKPO ... GROUP BY lifnr`（RFQ/PO/CONT/SCH），1 段是 `EKKO GROUP BY lifnr`（QUOT）。每次都要：

1. 按 `EKKO-LIFNR` / `EKKO-BEDAT` 过滤出目标期间；
2. 与 `EKPO` 按 `(EBELN)` 关联（`EKPO` 主键是 `(EBELN, POSNR)`，本身走索引），但**一对多扇出**成海量项目行；
3. 对扇出结果做 `GROUP BY lifnr`；
4. `COUNT( DISTINCT ebeln )` 需要对每组内 ebeln 再去重排序。

**同一个 join 被做了 4 遍**，4 遍的差别只是 WHERE 里的 2–3 个常量。这是典型的"本可以用一次 `CASE` 聚合搞定"的写法。5 年数据量下这是最大的性能风险。

**建议**：单次扫描 + 条件聚合（需要 7.40 SP05+ / Open SQL 语法）：

```abap
SELECT a~lifnr
       name1
       COUNT( DISTINCT CASE WHEN a~bstyp = 'A' AND b~loekz NE 'X'
                            THEN a~ebeln END ) AS rfq,
       COUNT( DISTINCT CASE WHEN a~bstyp = 'A' AND b~loekz EQ space
                            AND a~statu = 'A' THEN a~ebeln END ) AS quot,
       COUNT( DISTINCT CASE WHEN a~bstyp = 'F' AND b~loekz EQ space
                            AND a~bsart NE 'UB' THEN a~ebeln END ) AS po,
       COUNT( DISTINCT CASE WHEN a~bstyp = 'K' AND b~loekz EQ space
                            THEN a~ebeln END ) AS cont,
       COUNT( DISTINCT CASE WHEN a~bstyp = 'L' AND b~loekz EQ space
                            THEN a~ebeln END ) AS sch
  FROM ekko AS a
  INNER JOIN ekpo AS b ON b~ebeln = a~ebeln
  LEFT OUTER JOIN lfa1 AS c ON c~lifnr = a~lifnr
 WHERE a~lifnr IN s_lifnr
   AND a~bedat  IN s_bedat
   AND a~bukr   IN s_bukr
 GROUP BY a~lifnr, name1
```

**更进一步**：连接 EKPO 的唯一目的就是判断"是否至少有一个未删项目"。用 `EXISTS` 子查询可以**彻底消除扇出**，连 `DISTINCT` 都不需要，速度再快一个数量级：

```abap
       COUNT( CASE WHEN a~bstyp = 'A' THEN a~ebeln END ) AS rfq
  FROM ekko AS a
  LEFT OUTER JOIN lfa1 AS c ON c~lifnr = a~lifnr
 WHERE a~lifnr IN s_lifnr
   AND a~bedat  IN s_bedat
   AND EXISTS ( SELECT 1 FROM ekpo AS b
                 WHERE b~ebeln = a~ebeln AND b~loekz EQ space )
```

### 5.2 [I18] 内存 O(n²) 循环

三处线性扫描嵌套：

```abap
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr po WHERE lifnr = wa_temp-lifnr .
```
`it_disp` 是标准内表（无 `SORTED`/`HASHED` 键），每个供应商一次全表线性查找，n 个供应商 = O(n²)。

```abap
      READ TABLE it_lfa1 INTO wa_lfa1 WITH KEY lifnr = wa_disp-lifnr .
```
`it_lfa1` 同理，也是标准表，每次 READ 线性。n = 2 万时约 2 亿次比较。

**建议**：`it_lfa1` 用带 hashed 键的局部表，或先 `SORT it_lfa1 BY lifnr` 再 `READ ... BINARY SEARCH`；更彻底的是把 `lfa1` 直接 join 进第一条 SELECT（见 5.1），整个回填循环（第 177–183 行）可以删掉。

### 5.3 [I19] 排序放错位置，白白错过优化机会

```abap
    SORT it_disp BY lifnr .
```

这句在**名字回填循环之后**。如果放在 `READ TABLE` 之前并改成 `BINARY SEARCH`，上面的 O(n²) 就能降到 O(n log n)。同时，从业务上讲，**默认按供应商号排序对"绩效评价"毫无意义**——用户更想看"谁表现最差/最好"。这里没有任何综合评分列，也没有 `gr_table->set_layout( )->set_sort_field( )`。（I20）

### 5.4 [I21] QUOT 的 `DISTINCT` 是冗余的

```abap
    SELECT lifnr COUNT( DISTINCT ebeln ) AS CNT FROM ekko
```

`EKKO` 是抬头表，一个 `EBELN` 只有一行，没有扇出，`COUNT(DISTINCT)` 和 `COUNT(*)` 完全等价。写了 `DISTINCT` 会让人误以为这里也有 join，掩盖了 I05 里"QUOT 是抬头级粒度"这个关键事实。

### 5.5 [I22] `FOR ALL ENTRIES` 前的空表短路缺失

```abap
    SELECT lifnr name1 FROM lfa1
    INTO CORRESPONDING FIELDS OF TABLE it_lfa1
    FOR ALL ENTRIES IN it_disp
    WHERE lifnr = it_disp -lifnr.
```

没有 `CHECK it_disp IS INITIAL` 时的 `EXIT`。**功能上是安全的**（空内表时 FAE 直接返回空结果，不会全表扫描），但缺少这个惯用法会让读代码的人误判为"全表扫描供应商主数据"。另外当 `s_lifnr` 为空时 `it_disp` 可能很大，FAE 构造的 OR 条件表是否需要 DB 侧分批、以及实际会不会触发多趟 SELECT，**需在系统上核实**。

---

## 6. 健壮性与错误处理

### 6.1 [I23] 四个空 CATCH 吞掉所有列配置错误

```abap
     TRY.
        gr_column ?= gr_columns-> get_column( 'PO' ).
        gr_column-> set_short_text( 'PO Created' ).
     CATCH cx_salv_not_found.
     ENDMETHOD.
```

`CX_SALV_NOT_FOUND` 意味着**列名与 ALV 生成的实际列名不匹配**——也就是字段被重命名、类型被改、或者被标成 technical 后不可见。这属于"代码和数据不一致"的开发期错误，却被静默吞掉：SAP 打开报表，列名保持 `PO`（自动取字段名），标题文案没生效，**没人会发现**。四个 `TRY` 四段一模一样的 `CATCH` 空块，暴露的是作者知道会抛但不知道怎么处理。

**建议**：要么在 catch 里 `MESSAGE` 出来（便于维护期发现），要么干脆不 catch、用 `get_columns( )->get_column( )` 前先校验。空 catch 是反模式。

### 6.2 [I24] 无任何兜底

`fill_disp` 里的 `MODIFY`/`APPEND`/`READ` 都没有 `sy-subrc` 检查（除了三处 `IF sy-subrc NE 0` 用于 APPEND）。任何一处数据异常只会得到一个空行或一个被吞掉的错。整个报表没有 `TRY ... CATCH cx_sy_conversion_error`、没有 `LEAVE LIST-PROCESSING`，dump 时用户看到的是 SAP 标准短转储，没有任何业务上下文。

### 6.3 [I25] 供应商选择屏没有 F4 帮助

```abap
  SELECT-OPTIONS : s_lifnr FOR wa_disp- lifnr,
   s_bedat FOR wa_disp- bedat.
```

`s_lifnr` 背后没有任何 `SEARCH HELP`（既没有 `WITH KEY` 也没有 `SEARCH HELP FOR ...` 的辅助对象），也没有 `AT SELECTION-SCREEN ON VALUE-REQUEST` 的 F4 代码。**一个供应商报表，输入供应商号的地方没有值帮助**，用户只能手敲 10 位编码。这对可用性的伤害远大于任何性能问题。同时也没有 `SET_PARAMETER ID 'LIF'` 之类的参数传递，无法从其它交易带供应商进来。

### 6.4 [I26] 选择屏绑在会被清空的工作区上

```abap
  SELECT-OPTIONS : s_lifnr FOR wa_disp- lifnr,
```

`wa_disp` 是 `LIKE LINE OF it_disp` 的工作区，而在 `fill_disp` 的每个循环末尾都会：

```abap
      CLEAR : wa_disp, wa_temp.
```

把 `wa_disp` 整个清空。**选择屏的范围结构绑定在这个会被中途清空的对象上**，虽然因为 `s_lifnr` 自身持有一份拷贝而不会立刻出错，但这是一个明确的耦合地雷：任何人把 `wa_disp` 改成循环外的局部变量、或者调整 CLEAR 的位置，都可能踩到选择屏回显的坑。正确做法是绑到一个独立的 `DATA` 对象：

```abap
DATA gv_lifnr TYPE lifnr.
SELECT-OPTIONS s_lifnr FOR gv_lifnr.
```

（I27）

### 6.5 [I28] `CORRESPONDING FIELDS` 的按名映射是静默失败源

```abap
    INTO CORRESPONDING FIELDS OF TABLE it_disp
```

`INTO CORRESPONDING FIELDS` 按**名字**匹配 select list 和内表字段。如果有人把 `rfq` 改名或删掉，SQL 不会报错，`it_disp-rfq` 静静保持 0，报表照常显示，**所有供应商的询价单数都变成 0**。这是"改了字段名 → 报表数字全错但没有任何错误"的典型陷阱。至少应该把 select list 与目标字段的对应关系用注释锁住，或改用 `INTO TABLE` + 显式内表结构。

### 6.6 [I29] `TYPE I` 承载 `COUNT` 结果

```abap
   rfq  TYPE I ,
```

`COUNT(...)` 在 Open SQL 里返回 8 字节整型，赋给 4 字节的 `TYPE I` 会发生窄化。实际业务数据下不可能溢出，但**类型选小了**：同表其它计数列也一样。建议 `TYPE i` → `TYPE int8`，或者干脆声明为 `COUNT-LIKE` 的 `TYPE n`（更利于 ALV 对齐/导出）。属于低风险但应修正的类型卫生问题。

---

## 7. 类设计与代码组织

### 7.1 [I30] 局部类直接读写全局变量，封装为零

`lcl_perf_eval` 的 6 个方法里没有任何一个 `ATTRIBUTES`，所有状态都在报表顶部的全局 `DATA`：

```abap
DATA: "it_layout   TYPE lvc_s_layo,
       gr_table TYPE REF TO cl_salv_table,
       gr_functions TYPE REF TO cl_salv_functions,
       ...
       ls_color TYPE lvc_s_colo
      .
```

以及：

```abap
DATA: it_disp TYPE TABLE OF t_disp,
       wa_disp LIKE LINE OF it_disp,
       it_temp TYPE TABLE OF t_temp,
       ...
```

后果：
- 类与报表**强耦合**，无法被测试（ABAP Unit 里没法构造一个带 SALV 的报表环境）；
- 方法之间的数据流完全靠全局变量传递（`fill_disp` 写 `it_disp`，`end_of_page` 读 `it_disp`），调用顺序错一步就出错，且**编译器不会提示**；
- `lr_logo`、`lr_grid`、`lr_footer`、`lr_label`、`lr_text` 声明成全局却在方法里当局部用（`CREATE OBJECT lr_grid.`），可读性极差。

**正确做法**：`lcl_perf_eval` 持有 `it_disp` 和 `gr_table` 作为 `PRIVATE SECTION ATTRIBUTES`，构造方法接收数据。

### 7.2 [I31] 类的职责混杂

`lcl_perf_eval` 同时承担：取数（`fill_disp`）、列目录（`build_fc`）、页眉 Logo（`set_tol`）、页脚（`end_of_page`）、显示（`disp_alv`）。这五个关注点没有一个共性。至少应拆成 `lcl_data_provider`（取数）+ `lcl_alv_builder`（展示）。

### 7.3 [I32] 方法命名有误导性

- `set_tol` —— 大概率是 `set_top_of_list` 被截断了，但它实际做的事是"构建页眉网格 + Logo"，名字里既没有 top 也没有 header。
- `end_of_page` —— 名字和 ABAP 的 `END-OF-PAGE` 报表事件同名，但实际是"构建页脚"（footer），而真正的 `END-OF-PAGE` 在本程序里并没有用到（ALV 自带分页由 SALV 处理）。

这类命名会让维护者找错地方。

### 7.4 [I33] 新旧语法混用

```abap
     CREATE OBJECT lr_grid.
```

全篇用 `CREATE OBJECT`（`CLASSIC` 风格）而不是 `NEW`（现代写法），却同时用了 SALV 这套全新的 OO API（`cl_salv_table=>factory( )`、`?=`、`cl_salv_display_settings=>true`）。风格上不统一。对比同一个类里：

```abap
       gr_column-> set_technical( VALUE = if_salv_c_bool_sap=>true ).
```

这里用了完整的现代 `VALUE =` 命名参数，而上面 `create_label ( row = 2 column = 1 TEXT = ... )` 却是位置参数的写法混搭。

### 7.5 [I34] `INCLUDE <color>` 是死代码且位置可疑

```abap
  METHOD build_fc.

    INCLUDE <color>.
```

颜色是通过 `ls_color- col = 3` 设的，`INCLUDE <color>` 提供的 `cc_yellow` 等常量**一个都没用到**。而且 `INCLUDE` 出现在方法实现的中间位置（`METHOD build_fc.` 之后直接跟 `INCLUDE`）是否符合各版本的语法要求，需核实。无论如何这句应该删掉。

---

## 8. ALV 展示层问题

### 8.1 [I35] 页脚数字带前导零

```abap
     DATA :lf_lines TYPE sy-tfill .
...
      lf_lines = LINES( it_disp ).
...
     lf_flow-> create_text( TEXT = lf_lines ).
```

`sy-tfill` 是 4 字节整型，隐式转成文本会得到 `0000012` 这种带前导零的串。页脚显示 `Total Number of Entries   0000012`，很业余。正确写法：

```abap
     lf_flow->create_text( TEXT = |Total Number of Entries: { lf_lines }| ).
```

（`sy-tfill` 作为 `LINES( )` 的返回类型本身是合适的，保留。）

### 8.2 [I36] 运行日期未格式化

```abap
     lr_text = lr_gridx->create_text ( row = 4 column = 2
    TEXT = sy- datum tooltip = sy -datum ).
```

页眉里采购日期是格式化过的：

```abap
      WRITE s_bedat-low DD/MM/YYYY TO lv_text .
```

而"Run Date"直接把 `sy-datum`（`YYYYMMDD` 内部格式）丢给文本控件，界面上会显示 `20261008`，tooltip 也一样。**同一块页眉里两种日期风格**。建议：

```abap
    DATA(lv_rundate) = |{ sy-datum DATE = USER }|.
```

### 8.3 [I37] `set_visible` 与 `set_technical` 两行互相矛盾

```abap
        gr_column ?= gr_columns-> get_column( 'BEDAT' ).
        gr_column-> set_visible( abap_false ).
        gr_column-> set_technical( VALUE = if_salv_c_bool_sap=>true ).
```

两个问题：

1. **`if_salv_c_bool_sap=>true` 的静态属性访问**。`IF_SALV_C_BOOL_SAP` 是 SALV 的 "IntelliSwitch" 接口，其 `true`/`false` 是接口的 **DATA 成员**（不是 CONSTANTS），静态访问时取的是接口的初始值，即 `abap_false`。也就是说这行很可能**等于 `set_technical( abap_false )`**，与紧邻的 `set_visible( abap_false )` 撞车。（需在系统上核实 `IF_SALV_C_BOOL_SAP` 的具体声明。）
2. 无论第 1 点如何，**这两行的意图本身是矛盾的**。`BEDAT` 在数据层面是个死字段（见 I41），程序却同时想"隐藏它"和"标记它为技术字段"。如果 `set_technical` 真的生效了，那 Export/Download 出来的数据里就少一列；如果没生效，`BEDAT` 会以初始日期值出现在导出文件里，成为一列垃圾。**两种结果都需要明确决策，而不是两行都写。**

### 8.4 [I38] 硬编码颜色，无配置入口

```abap
        ls_color- col = 3 .
        gr_column-> set_color( ls_color ).
```

`LVC_S_COLO-COL` 的具体色值映射需核实，但更值得注意的是：**两个关键列被硬编码着色，其余六列没有**；`ls_color` 是全局变量且没有 `CLEAR`（两处都只赋 `col`，所以当前恰好正确）；颜色不可通过 ALV variant 调整，用户改不了。着色规则应该走配置表或至少集中在类的一个私有方法里。

### 8.5 [I39] 硬编码英文文案，没走 Text Elements

选择屏标题用了 `TEXT-001`，消息用了 `TEXT-002`，但界面上的所有文案都是字面量：

```abap
    TEXT = 'MM: Vendor Evaluation' ),
...
    TEXT = 'Vendor No # :' tooltip = 'Vendor #.' ).
...
    TEXT = 'Posting Date:' tooltip = 'Posting Date' ).
...
        lv_text = 'Not Provided'.
...
     lf_label-> set_text( 'Information:' ).
     lf_flow-> create_text( TEXT = 'Total Number of Entries' ).
```

外加 `set_short_text( 'V.Name' )` / `set_medium_text( 'Quotation Maintained' )` / `set_long_text( 'Schedule Agreement Created' )` 等 10 余处。**`TEXT-001` 的存在说明作者知道有 Text Elements，却只用了 2 个**。结果：这个报表**无法 SE63 翻译**，中文用户看到满屏英文；文案改动要改程序、要重新传输。

### 8.6 [I40] 四个空 label 当"空行"是无效代码

```abap
     lr_label = lr_gridx->create_label ( row = 5 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 6 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 7 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 8 column = 1 ).
```

创建一个**没有 `TEXT` 的 label**，只是把 4 行占位。作者想用它们撑出版面下方的空白，但空 label 在 SALV 里几乎不产生可见行（Grid 布局是自动计算高度的）。这四行的实际效果大概率是零，属于"以为自己做了、其实没做"的典型。若目的是让 Logo 与页眉网格垂直居中或留白，应显式研究 `cl_salv_form_layout_logo` / `set_top_of_list` 的布局属性，而不是造空对象。

### 8.7 [I41] `t_disp-bedat` 是彻头彻尾的死字段

```abap
   bedat TYPE bedat,
```

第一段 SELECT 的 select list 只有 `a~lifnr` 和 `COUNT(...) AS rfq`，后续所有查询都用 `CORRESPONDING FIELDS` 只写 `lifnr` 和一个计数器。**`bedat` 在 `it_disp` 的任何一行里都永远是初始值**。它存在的唯一理由是选择屏 `s_bedat FOR wa_disp- bedat` 需要一个 `DATE` 类型的载体——而这个需求本该由一个独立变量满足（见 I27 的修复）。随后又为了"藏起"这个字段，专门写了 `set_visible` + `set_technical` 两行代码（I37）。**一个纯粹为绕过选择屏绑定而存在的字段，牵出了后面的展示层三处妥协。**

### 8.8 [I42] `set_all( abap_true )` 无差别打开全部功能

```abap
     gr_functions = gr_table->get_functions ( ).
     gr_functions-> set_all( abap_true );
```

打开 Export / Print / Graphical / Sort / Filter 等全部标准功能。数据量可能很大（供应商 × 全库），Export 一次可能产生几 MB CSV。同时**没有 `set_save_data( )` 之类的 Layout Variant 保存入口**，用户调好的列顺序、筛选、排序无法保存——下次打开全部丢失。

### 8.9 [I43] 无输出审计信息

页脚只有总行数。没有"生成人（`sy-uname`）"、"生成时间（`sy-timet`）"、"选择条件回显（供应商范围 / 日期范围）"。当这张表被截图进供应商评估会议时，**无法追溯当时是用什么条件跑的**。选择条件其实已经在页眉里部分回显了（页眉有 Vendor No # 和 Posting Date），这一点是对的，但缺少人/时间。

---

## 9. 其它问题

### 9.1 [I44] 没有变式内存

报表没有 `gv_variant` / `SAVE` 相关逻辑，用户每次都要重输供应商范围和日期。对一个高频使用的评价报表，这是明显的可用性缺口。标准做法：

```abap
DATA gv_variant TYPE slis_vari.
INITIALIZATION.
  gv_variant = VALUE #( ( NAME = 'ZMMR_PERF_EVAL_VEND' ) ).
AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_bedat.
  CALL FUNCTION 'DATE_PERIOD_MENU' ...
```

### 9.2 [I45] `WRITE ... TO` 对定长变量的静默截断隐患

```abap
       lv_text = s_lifnr-low .
      IF s_lifnr-high IS NOT INITIAL.
        CONCATENATE lv_text ' to ' s_lifnr -high INTO lv_text SEPARATED BY space.
```

`lv_text( 30 )` 里装 `10 + 4 + 10 = 24` 字符，当前安全。但 `CONCATENATE` 不做长度检查，一旦将来换成 `name1`（30 字符）之类的长值就会静默截断。属于"现在没问题、改一下就出事"的脆弱点。同时 `lv_date` 的存在也说明作者已经意识到长度问题，但只在第二段用了单独变量，第一段没有。

### 9.3 [I46] `TO CREATE_OBJECT` 后立即 `SET_RIGHT_LOGO` 硬编码图像名

```abap
     lr_logo-> set_right_logo( 'ZCHEM_N_LOGO_SMALL' ). " Image From OAER T.code
```

图像名硬编码。若目标 client's 的 `OAER`（业务对象/图像管理）里没有 `ZCHEM_N_LOGO_SMALL`，`set_right_logo` 的行为（静默忽略 / 抛 `CX_SALV_ERROR` / 渲染成 X）**需核实**。注释里写明来自 OAER，说明这个依赖是跨系统搬来的——**部署到其它 client 时这是一个硬依赖但代码里没有任何保护**。

### 9.4 [I47] 无测试、无断言

`fill_disp` 里全是 `MODIFY`/`APPEND` 的位运算式拼装，没有任何针对业务不变量的断言。最小可行的自检应该是：

```abap
  ASSERT it_disp IS INITIAL
         OR line_exists( it_disp[ 1 ]-rfq ).
```

至少在 CI 或手工验证时对比 5 个计数器的一致性（例如 `cont` 或 `sch` > 0 时 `po` 是否应该有值）。

### 9.5 [I48] 空 CATCH + 空 CATCH + 空 CATCH + 空 CATCH 之外，`ENDTRY` 写法也不规范

```abap
    CATCH cx_salv_msg.
    ENDTRY .
```

ABAP 的惯用写法是 `ENDTRY.` 不带 `ENDTRY .` 后的空格——这只是格式，但说明代码未经格式化规范处理（整篇都有 `~ ` 前后空格、`TEXT -002` 这类噪声），建议用 **ABAP Cleaner / pretty-printer** 统一格式化，能一次性消除大量肉眼噪声，也便于 code review。

---

## 10. 重构建议（按优先级）

### P0：先让它不 dump、且数字可信

```abap
START-OF-SELECTION.
  DATA lobj TYPE REF TO lcl_perf_eval.
  lobj = NEW #( it_lifnr = s_lifnr[] it_bedat = s_bedat[] ).

  IF lobj->fill_disp( ) IS INITIAL.
    MESSAGE '未找到符合条件的数据' TYPE 'S'.
    RETURN.
  ENDIF.

  lobj->show_alv( ).
```

```abap
  METHOD fill_disp RETURNING VALUE(rv_rows) TYPE i.
    " 5 个计数器统一口径：全部抬头级 + EXISTS 项目级
    " 统一删除标志 loekz EQ space、统一 STATU 策略（由业务确认）
    SELECT lifnr name1
           COUNT( CASE WHEN bstyp = 'A' THEN ebeln END ) AS rfq
      FROM ekko
      LEFT OUTER JOIN lfa1 ON lfa1~lifnr = ekko~lifnr
     WHERE lifnr  IN it_lifnr
       AND bedat  IN it_bedat
       AND bukr   IN it_bukr
       AND EXISTS ( SELECT 1 FROM ekpo
                     WHERE ekpo~ebeln = ekko~ebeln
                       AND ekpo~loekz EQ space )
     GROUP BY lifnr name1
     INTO TABLE @DATA(lt_all).
  ENDMETHOD.
```

要点：
1. 一次扫描、一次 group by、一次 join lfa1（干掉 177–183 行的回填循环和 5 个 `it_temp` 复用）；
2. 全部统一抬头级删除标志，项目级存活判定收进 `EXISTS`；
3. `it_bukr` 加入选择屏并强制走公司代码；
4. 口径统一后，再在 ALV 层加派生指标（`po_rf = po / rfq`）和综合评分。

### P1：ALV 层修正确认性问题

- 删掉 `bedat` 字段和为它写的那两行 `set_visible`/`set_technical`（I37/I41）；
- 所有文案进 Text Elements；
- `sy-datum` 用 `|{ sy-datum DATE = USER }|` 格式化；
- `lf_lines` 用字符串模板输出（I35）；
- 删掉四个空 label（I40）和 `INCLUDE <color>`（I34）；
- 空 CATCH 改成 `MESSAGE` 或去掉（I23）；
- 打开 layout variant 保存：`gr_table->get_layout( )->set_save_data( abap_true )`；
- 加变式内存（I44）；加 `s_lifnr` 的 F4（I25）；
- 页脚补 `sy-uname` / `sy-timet`。

### P2：结构清理

- 把 `it_disp` / `gr_table` 收进 `PRIVATE SECTION ATTRIBUTES`；
- 拆 `lcl_data_provider` / `lcl_alv_builder`；
- `CREATE OBJECT` → `NEW`；
- 方法改名 `set_header_grid` / `build_footer`；
- 走 ABAP Cleaner 统一格式；
- 补 SE38 语法检查 + ABAP Unit。

---

## 11. 需核实清单

以下是我无法仅凭本文件确定、需要在系统上确认的点：

| # | 待核实项 | 影响 |
|---|---|---|
| V1 | `EXIT` 在 `CLASS ... CONSTRUCTOR` 方法内的合法性（各版本有差异） | 决定 I01 是"dump"还是"语法错误"——两者都是 P0 |
| V2 | `IF_SALV_C_BOOL_SAP` 的 `true` 是 CONSTANTS 还是 DATA 成员 | 决定 `set_technical` 是否真生效（I37） |
| V3 | `APPENDING CORRESPONDING FIELDS OF TABLE it_temp` 这一关键字组合是否为合法语法（文件中 4 处出现，均无前置 `INTO TABLE`，而第一处 RFQ 写的是正确的 `INTO CORRESPONDING FIELDS OF TABLE it_disp`） | 若非法则整个程序无法激活；本报告按"意图为追加进 it_temp"理解 |
| V4 | `EKKO-LOEKZ` / `EKPO-LOEKZ` 在本系统是否使用 `'D'` 取值 | 决定 `NE 'X'` 与 `EQ space` 的实际差异（I08） |
| V5 | `BSTYP='A'` 时 `EKKO-STATU` 的具体码值语义（'A'/'B'/'N' 各自含义） | 决定 QUOT 口径是否真的只算"已结束"（I09） |
| V6 | 本系统是否启用 SRVO=1/2 增强采购凭证类型 | 决定 `bsart NE 'UB'` 是否已失效（I10） |
| V7 | `BSTYP='L'` 下的计划协议 / 调度协议 / 释放订单，业务上 SCH 列期望统计哪一类 | 决定是否重复计数（I11） |
| V8 | 业务方对 5 个计数器的真实口径定义，以及是否需要 KDAUF/KDANR 链路归因 | 决定 I06/I12 怎么改 |
| V9 | `ZCHEM_N_LOGO_SMALL` 在目标 client 的 OAER 中是否存在 | 决定 I46 |
| V10 | 源码中 `wa_disp- lifnr` 这类连字符前后空格是导出噪声还是源文件原样 | 影响是否要提代码整洁度问题 |
| V11 | `LVC_S_COLO-COL = 3` 的实际色值 | 影响 I38 的严重度 |
| V12 | FAE 在 `it_disp` 极大时是否触发多趟 SELECT | 影响 I22 |
| V13 | 业务上是否需要按采购组织 / 采购员 / 公司代码拆分 | 影响 I13/I14 |

---

## 12. 问题登记表

| 严重度 | 编号 | 数量 |
|---|---|---|
| P0 | I01–I16 | 16 |
| P1 | I17–I26 | 10 |
| P2 | I27–I48 | 22 |
| **合计** | | **48** |

**分布概览**：取数与业务口径 16 条（最集中在 `fill_disp`），性能 7 条，展示/ALV 10 条，类设计与封装 8 条，健壮性与错误处理 7 条。

**如果只改三处**：
1. **统一 5 个计数器的过滤口径并加上 `BUKR`**（I05/I07/I13）——否则报表输出的数字在业务上是错的。
2. **修好失败路径，让工厂异常真的能终止程序**（I01–I04）——否则存在确定的 dump。
3. **把 5 次 `EKKO⋈EKPO` 扫描合成 1 次 `EXISTS` + `GROUP BY`**（I17）——否则空选择屏必超时。

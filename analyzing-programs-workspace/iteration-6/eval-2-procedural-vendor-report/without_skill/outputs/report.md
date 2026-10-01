# ZMMR_VEND_LIST 供应商采购订单统计报表 · 走读报告

分析对象：`evals/zmmr_vend_list.abap`（58 行，REPORT，经典 ALV 全屏报表）

---

## 0. 结论速览

这是一个**结构标准但业务口径不完整**的经典报表骨架：入口用 `START-OF-SELECTION` 线性驱动三个 `PERFORM`（取数 → 生成字段目录 → 展示 ALV），数据层用一条 `LFA1 INNER JOIN EKKO + GROUP BY` 的 Open SQL 一次性完成"按供应商聚合采购订单数"，输出层用 `REUSE_ALV_FIELDCATALOG_MERGE` + `REUSE_ALV_GRID_DISPLAY` 做全屏表格。

工程上值得肯定的两点：**输出行数远小于明细行数**（按供应商聚合，避免把 EKKO 全量读进内表）、**性能瓶颈集中在一条 SQL** 而不是分散在 ABAP 循环里（这是对的选择）。

工程上必须修的四点：**统计口径没有时间区间**（全量历史 PO 数，业务上基本无意义）、**未过滤已逻辑删除的采购凭证**（`LOEKD`）、**没有任何权限过滤**（供应商主数据与采购量越权可见）、**消息文本硬编码中文**且无消息类。

---

## 1. 它回答什么业务问题

从命名和代码推断的业务意图：

> "给我一份供应商清单，显示每个供应商的名称和他名下有多少张采购订单（文档类型 = F，采购订单），可按供应商号和采购组织过滤。"

典型使用场景是**采购主数据盘点 / 供应商活跃度分析**：找出"哪些供应商从来没有采购订单"、"哪些供应商订单量特别高需要做采购额集中度分析（集中采购合规）"、"按采购组织维度切分采购盘子"。

需要注意的是，程序实现的业务口径比这个意图**窄了一层**：

| 业务上通常需要 | 本程序是否具备 |
|---|---|
| 统计期间（订单日期区间） | ❌ 没有，统计的是"全部历史" |
| 采购金额合计 | ❌ 没有，只数了张数 |
| 最近一次下单日期 | ❌ 没有，无法判断活跃度 |
| 已删除凭证排除 | ❌ 没有 |
| 凭证类型可配置 | ❌ 硬编码 `'F'` |
| 权限过滤（FI 供应商主数据 / 采购组责任） | ❌ 没有 |
| 合计行 / 排序 / 标题 | ❌ 没有 |

---

## 2. 架构与依赖地图

```
代码骨架（58 行，单文件，FORM 划分职责）
├── 声明区
│   ├── TYPE-POOLS: slis          → 经典 ALV 类型池（REUSE_ALV_* 必需）
│   ├── TABLES: lfa1, ekko       → 遗留语句：隐式生成工作区 + 绑定字典对象
│   ├── DATA: gt_out  TABLE OF zmmr_vend_s   → 输出结构（DDIC 表结构，非行结构）
│   ├── DATA: gt_fcat slis_t_fieldcat_alv    → 字段目录
│   ├── DATA: gs_layo slis_layout_alv        → ALV 布局
│   └── SELECT-OPTIONS s_lifnr / s_ekorg    → 选择屏幕
├── START-OF-SELECTION          → 唯一流程入口，线性 3 步
├── FORM get_data               → 数据层：1 条 Open SQL
├── FORM build_fieldcat        → 元数据层：DDIC → ALV 字段目录
└── FORM display_alv            → 展现层：全屏 ALV Grid
```

**对象依赖**

| 类型 | 依赖 | 说明 |
|---|---|---|
| 数据库 | `LFA1`（供应商主数据） | 取 `LIFNR` / `NAME1`，提供文本 |
| 数据库 | `EKKO`（采购凭证头） | 取 `EBELN`（计数）、`EKORG`、`BSTYP`（过滤） |
| DDIC | `ZMMR_VEND_S` | 输出结构，至少含 `LIFNR NAME1 PO_CNT`；字段目录的唯一来源 |
| 类型池 | `SLIS` | 经典 ALV |
| FM | `REUSE_ALV_FIELDCATALOG_MERGE` | 结构 → 字段目录 |
| FM | `REUSE_ALV_GRID_DISPLAY` | 全屏 ALV Grid |

**数据流（一句话）**

```
LFA1 + EKKO ──SQL 聚合──> lt_vend(匿名结构) ──VALUE #──> gt_out(ZMMR_VEND_S) ──T_OUTTAB──> ALV
                                                             ↑
                                          ZMMR_VEND_S ──FM──> gt_fcat ──IT_FIELDCAT─┘
```

注意 `gt_out TYPE TABLE OF zmmr_vend_s`：这是**表结构**（深结构/含字段）而不是 `TABLE OF ANY` 风格的对象类型。字段名和顺序能对上 `ZMMR_VEND_S` 时，ALV 能正常映射；但一旦结构里含有 BSEG/LOBM 之类字段就会出问题。本程序只查了 3 个标量字段，属于安全用法。

---

## 3. 执行流程（时间线）

```
用户进入程序
   │
   ├─ ABAP 运行时：加载 TYPE-POOLS SLIS
   │                解析 TABLES: lfa1, ekko（生成工作区，供选择屏幕取字段）
   │                SELECT-OPTIONS 隐式生成选择屏幕（未写任何屏幕代码）
   │
   ├─ 显示选择屏幕 → 用户录入 S_LIFNR / S_EKORG → 按 F8
   │
   ▼
START-OF-SELECTION（zmmr_vend_list.abap:13）
   │
   ├─(1) PERFORM get_data                (:14 → :18-36)
   │      · 一条 Open SQL：INNER JOIN + GROUP BY + COUNT(DISTINCT)
   │      · 结果写入内联声明的 lt_vend
   │      · IF sy-subrc = 0 → VALUE # 逐行转换 → gt_out
   │      · ELSE（无行）→ MESSAGE '无符合条件的供应商' TYPE 'I' + STOP → 程序结束，
   │        空列表，不进入 ALV
   │
   ├─(2) PERFORM build_fieldcat         (:15 → :38-47)
   │      · 以 ZMMR_VEND_S 为结构源合并生成字段目录 → gt_fcat
   │      · 失败 → MESSAGE '字段目录生成失败' TYPE 'E' → 错误终止
   │
   └─(3) PERFORM display_alv             (:16 → :49-58)
          · 填布局：zebra（斑马纹）、get_sel_info（状态栏显示选中行数）
          · CALL FUNCTION REUSE_ALV_GRID_DISPLAY → 控制权交给 ALV Grid Control
          · 全屏列表呈现；用户排序/筛选/导出，PAI 在 FM 内部被接管
          · 用户返回 → FM 结束 → 程序自然结束（无显式 LEAVE LIST）
```

流程特征：**没有分支、没有状态机、没有循环**，一条直线走到底，这是经典报表最易读也最易改的结构。代价是取数逻辑不可复用（其他程序想用"供应商 PO 统计"只能复制粘贴这段 SQL）。

---

## 4. 分模块走读

### 4.1 声明区（:1-11）

```abap
REPORT zmmr_vend_list.
TYPE-POOLS: slis.

TABLES: lfa1, ekko.

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,
      gt_fcat TYPE slis_t_fieldcat_alv,
      gs_layo TYPE slis_layout_alv.

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg.
```

- `TYPE-POOLS: slis`：`REUSE_ALV_*` 系列 FM 的参数类型来自 `SLIS` 类型池，必须声明。7.40 之后仍然合法且普遍使用，只是它把报表绑死在了经典 ALV 上。
- `TABLES: lfa1, ekko`：遗留语句。实际效果是生成同名工作区 + 把字典对象登记给选择屏幕用。本程序中 `LFA1`/`EKKO` 工作区在后续代码里**一次都没被用到**（SQL 全部用别名 `a`/`b`），它唯一的作用是给 `SELECT-OPTIONS` 提供 `FOR` 引用。正确写法是内联声明：

  ```abap
  DATA lfa1 TYPE lfa1.
  DATA ekko TYPE ekko.
  SELECT-OPTIONS s_lifnr FOR lfa1-lifnr.
  ```

  更干净的做法是不引用字典对象，直接声明选择表类型 + 显式挂 search help（`search help` 只能挂在 DDIC/程序对象的选择屏幕字段上，需要在 `SELECT-OPTIONS` 所在的选择屏幕对象上配置），这样选择屏幕与业务表解耦。
- 命名符合 ABAP 风格指南：选择项 `S_` 前缀。`s_lifnr` 绑定 `LFA1-LIFNR`（CHAR10），`s_ekorg` 绑定 `EKKO-EKORG`，用户可获得标准的采购组织 F4——这是绑定字典字段的隐式好处之一。
- `gt_fcat` / `gs_layo` 声明为全局，实际只在 FORM 之间传递，作用域偏大但无害。

### 4.2 `FORM get_data` —— 数据层（:18-36）

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

**SQL 语义**：对 `LFA1` × `EKKO` 按 `LIFNR` 做内连接（一条 EKKO 头记录挂一个供应商，连接必然 1:N 展开），过滤条件三层：

1. `a~lifnr IN @s_lifnr` —— 供应商范围（空选择 = 不过滤）
2. `b~ekorg IN @s_ekorg` —— 采购组织范围（空选择 = 不过滤）
3. `b~bstyp = 'F'` —— **凭证类型硬编码为采购订单**，框架订单 `'L'`、计划订单等一律排除

`GROUP BY a~lifnr, a~name1` + `COUNT(DISTINCT b~ebeln)` 得到"每供应商订单张数"。`NAME1` 放进分组键带来两个后果：① 相同 `LIFNR` 若存在多语言名称行则会被拆成多行（LFA1 供应商主数据通常单一名称行，风险低但要知道）；② 数据库不能用 `LIFNR` 唯一走索引聚合并直接带出文本，只能先聚合再回表取名。**更好的形态是先聚合 EKKO，再单独取名称**（见 §6）。

**判断无数据的方式**（:29）：Open SQL 的 `INTO TABLE` 会设置 `sy-subrc`（读到数据 = 0，无数据 = 4），紧接着判断在语义上成立。但这里真正想问的是"结果集为空"，用数据本身表达更稳健，也不会把 `sy-subrc` 的其他分支误判为"无数据"：

```abap
IF gt_out IS INITIAL.
  MESSAGE '无符合条件的供应商' TYPE 'S'.
  RETURN.
ENDIF.
```

顺带：这里用 `STOP` 而不是 `RETURN`，二者都能退出，但 `RETURN` 从 `FORM` 返回更符合语义，也不会连带终止后续 PERFORM（虽然此时并没有后续）。

**`VALUE #( FOR ... )` 的角色**（:30-31）：把匿名结构 `lt_vend`（字段 `LIFNR NAME1 PO_CNT`，`PO_CNT` 是 ABAP 计数器类型）逐行映射进 `ZMMR_VEND_S` 的对应字段。它做的是**类型转换**——如果 `ZMMR_VEND_S-PO_CNT` 是 `CHAR(10)`，ABAP 会把计数器 `3` 写成 `'0000000003'`，这大概率是作者要的（ALV 对齐好看），所以这个转换**不是纯冗余**，是有意为之。但它的写法成本偏高：若字段名与顺序恰好匹配，`gt_out = lt_vend.` 一次赋值就够；语义上更准确的写法是保留显式转换但配合注释说明"需要字符型计数以右对齐"。真正要注意的是**若 `PO_CNT` 字段长度小于计数值范围（如 `I(2)`），转换会溢出抛异常**，DDIC 上必须核对字段定义。

**`COUNT(DISTINCT b~ebeln)`**：`EKKO` 的主键是 `(MANDT, EBELN)`，一张凭证头只有一行，因此在本查询里 `COUNT(*)` 与 `COUNT(DISTINCT b~ebeln)` 结果等价，`DISTINCT` 只增加排序/去重开销。保留它表达了"我想要的是凭证数而不是连接展开行数"的意图，属于防御性冗余；如果将来把 `EKPO` 或 `EKEK` 拉进连接，`DISTINCT` 就变成必需的——所以这条不改也无害，但应意识到它现在是"为将来付费"。

### 4.3 `FORM build_fieldcat` —— 元数据层（:38-47）

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

这是**当前架构中最值得表扬的一处设计**：字段目录从 DDIC 自动合并，而不是手写 `APPEND VALUE #( ... )` 逐字段维护。好处是：

- `ZMMR_VEND_S` 增删字段 / 改标签，ALV 自动跟随，不需要动 ABAP 代码；
- 避免了字段目录与输出内表"对不上"这类最常见的经典 ALV 事故（`CT_FIELDCAT` 与 `T_OUTTAB` 结构不一致 → 整列空白或 short dump）；
- 排序键自动生成，DDIC 上打的技术字段标记生效。

代价：**ALV 的显示形态完全受制于 DDIC**。没有标题、没有合计、不能隐藏尾随零位、不能用 `NO_OUTLEN` 让长文本溢出显示——想做这些都得改代码。因此"字段目录自动化"和"界面定制"之间存在张力，中等复杂度的报表更适合"合并 + 用户自改 layout variant"。

`MESSAGE ... TYPE 'E'` 在此 FORM 内会直接终止程序（错误信息 + 退出码非零），后台运行时能被 Job Monitor 识别，这是对的；不足之处是没有把错误写日志（`MESSAGE ... INTO` + 应用日志表），排障时只能看到短文本。

### 4.4 `FORM display_alv` —— 展现层（:49-58）

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

- `is_layout` / `it_fieldcat` 放在 `EXPORTING`，`t_outtab` 放在 `TABLES`（这就是 `REUSE_ALV_GRID_DISPLAY` 的历史签名，不统一，不要"顺手改成 EXPORTING"）。
- `zebra = 'X'` 斑马纹、`get_sel_info = 'X'` 状态栏显示选中行数——两个都是低成本的可用性加分项，选得不错。
- `GRID` 变体是全屏 ALV Grid，支持排序/筛选/汇总/导出/Excel 粘贴，比 `REUSE_ALV_ALV_GRID_DISPLAY`（那个是弹窗）选对了。但 `GRID` **在后台批处理下无法显示**（ALV Grid 是 SAP GUI 控件，批处理里会短 dump 或输出空），本程序没有 `sy-batch` 分支。
- 缺少：`it_sort`（让 `PO_CNT` 默认降序，用户一进来就看到重点供应商）、`i_grid_title` / 标题行、`slis_totals_alv` 合计、以及 `i_callback_pf_status_set`（自设工具栏，例如"导出""加采购组明细"）。
- 返回值 `SUBRC` 未检查：ALV Grid 调用失败（比如前端控件不可用）时不会静默，但也没给用户任何提示。

---

## 5. 问题清单（按严重度排序）

### 高

| # | 问题 | 影响 |
|---|---|---|
| 1 | **统计口径无时间区间**（无 `BEDAT` 范围） | "采购订单总数"是全量历史值，随系统运行年限单调增长，无法回答"今年采购活跃度"这类实际问题，报表价值接近于零 |
| 2 | **未排除已逻辑删除凭证** | EKKO 的删除策略下被删除凭证的 `LOEKD = 'X'`，仍会计入计数，导致数字虚高；建议 `AND b~loekd <> 'X'`（需按本系统实际删除方式确认） |
| 3 | **无任何权限过滤** | 未做供应商主数据授权（`F_LIFNR` 等）、未按采购组责任（`EKKO-EKGRP` → `T042G`）过滤，等于把全公司供应商与采购量对所有能执行本事务码的人开放，是内审/合规高风险项 |
| 4 | **后台批处理不可用** | 无 `sy-batch` 分支，`REUSE_ALV_GRID_DISPLAY` 在后台不可用，月度/年度定期跑批场景直接失败 |

### 中

| # | 问题 | 影响 |
|---|---|---|
| 5 | `bstyp = 'F'` 硬编码 | 凭证类型不可配置，排除框架订单 `'L'`、服务采购等；建议改为 `SELECT-OPTIONS` 或常量维护表 |
| 6 | 缺业务度量 | 无采购金额合计、最近下单日期、采购组、采购组织汇总维度，无法做集中度分析 |
| 7 | 多币种风险（若加金额） | `EKKO-NETWR` 不带币种，跨币种 `SUM` 得出无意义的数——加金额时必须按 `WAERS` 再分组或分币种输出 |
| 8 | `sy-subrc = 0` 判空 | 应用 `IF <内表> IS INITIAL`，语义更准，不依赖 `sy-subrc` 副作用 |
| 9 | `MESSAGE` 文本硬编码中文 | 无消息类，无法 SE91 维护、无法翻译、无法集中改文案；应建消息类（如 `ZMM001`） |
| 10 | 性能未经 ST05 验证 | 采购组织选择范围宽时（甚至为空时）需要扫描/聚合海量 `EKKO`；优化器可能在 `LFA1` 侧起步做嵌套循环。应 ST05 + DBACockpit 实测，并考虑"先聚合 EKKO、再取 LFA1 文本"的两步式写法 |

### 低（可维护性 / 现代化）

| # | 问题 | 说明 |
|---|---|---|
| 11 | `TABLES: lfa1, ekko` | 遗留语句，工作区从未被使用，仅为 `SELECT-OPTIONS` 服务；改内联声明 |
| 12 | 取数逻辑不可复用 | 逻辑沉在 `PERFORM` 里，其他程序要"供应商 PO 统计"只能复制 SQL；应下沉为 provider 类 |
| 13 | 无合计、无默认排序、无标题 | 打开就是无序列表，用户需手工排序才能看重点 |
| 14 | 无执行耗时/结果行数反馈 | 大结果集时用户等待无感知 |
| 15 | `COUNT(DISTINCT)` 为"将来付费" | 当前与 `COUNT(*)` 等价 |
| 16 | 无 layout variant 持久化 | `REUSE_ALV_GRID_DISPLAY` 未传 variant，用户每次重排；应加 `is_save_variant` / `i_save_variant` 或做 `SPACEFUNC` |

---

## 6. 改进建议与参考改写

### 6.1 最小必要修复（优先级最高）

```abap
REPORT zmmr_vend_list.

TYPE-POOLS: slis.

DATA lfa1 TYPE lfa1.
DATA ekko TYPE ekko.

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,
      gt_fcat TYPE slis_t_fieldcat_alv,
      gs_layo TYPE slis_layout_alv,
      gt_sort TYPE slis_t_sortinfo_alv.

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg,
                s_bedat FOR ekko-bedat,
                s_bstyp FOR ekko-bstyp.

START-OF-SELECTION.
  PERFORM get_data.
  PERFORM build_fieldcat.
  PERFORM display_alv.

FORM get_data.
  SELECT a~lifnr,
         a~name1,
         COUNT( DISTINCT b~ebeln ) AS po_cnt,
         MAX( b~bedat )           AS last_po
    FROM lfa1 AS a
    INNER JOIN ekko AS b ON  a~lifnr = b~lifnr
    WHERE a~lifnr IN @s_lifnr
      AND b~ekorg IN @s_ekorg
      AND b~bstyp IN @s_bstyp
      AND b~bedat IN @s_bedat
      AND b~loekd <> 'X'
    GROUP BY a~lifnr, a~name1
    INTO TABLE @gt_out.

  IF gt_out IS INITIAL.
    MESSAGE ID 'ZMM001' TYPE 'S' NUMBER '001'.
    RETURN.
  ENDIF.
ENDFORM.
```

配套要求：

1. **DDIC 追加字段** `LAST_PO`（DATE）到 `ZMMR_VEND_S`——若字段目录由 `ZMMR_VEND_S` 合并生成，不追加字段就无法输出该列。
2. **建消息类** `ZMM001`，文本 `无符合条件的供应商` / `字段目录生成失败`。
3. `PO_CNT` 字段类型若为 `CHAR` 保留原样（右对齐美观）；若改为计数器类型，赋 `gt_out = lt_vend.` 即可，去掉 `VALUE #( )`。

### 6.2 性能：拆掉跨表聚合

当前形态要求数据库同时承担"连接 + 分组 + 去重计数 + 取名称"。改成**先聚合事实表、再取维度文本**，让两个表各自走自己的索引：

```abap
FORM get_data.
  SELECT lifnr, COUNT( * ) AS po_cnt, MAX( bedat ) AS last_po
    FROM ekko
    WHERE lifnr IN @s_lifnr
      AND ekorg IN @s_ekorg
      AND bstyp IN @s_bstyp
      AND bedat IN @s_bedat
      AND loekd <> 'X'
    GROUP BY lifnr
    INTO TABLE @DATA(lt_cnt).

  IF lt_cnt IS INITIAL.
    MESSAGE ID 'ZMM001' TYPE 'S' NUMBER '001'.
    RETURN.
  ENDIF.

  SELECT lifnr, name1
    FROM lfa1
    WHERE lifnr IN @s_lifnr
    FOR ALL ENTRIES IN @lt_cnt
    INTO TABLE @DATA(lt_txt).

  SORT lt_txt BY lifnr.

  LOOP AT lt_cnt INTO DATA(ls_cnt).
    DATA(ls_txt) = VALUE #( lt_txt[ lifnr = ls_cnt-lifnr ] OPTIONAL ).
    APPEND VALUE #( lifnr = ls_cnt-lifnr
                    name1 = ls_txt-name1
                    po_cnt = ls_cnt-po_cnt
                    last_po = ls_cnt-last_po ) TO gt_out.
  ENDLOOP.
ENDFORM.
```

`lt_cnt` 行数 = 命中供应商数（几百到几万），`FOR ALL ENTRIES` 的性能代价可接受，且 `EKKO~LIFNR`、`EKKO~EKORG` 等索引能被独立利用。是否真的更快必须用 ST05 对比两种写法，不能凭直觉。

### 6.3 权限过滤（合规必需）

```abap
FORM check_authority USING iv_lifnr TYPE lfa1-lifnr.

  DATA ls_lfa1 TYPE lfa1.

  SELECT SINGLE * FROM lfa1 WHERE lifnr = @iv_lifnr INTO @ls_lfa1.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  AUTHORITY-CHECK OBJECT 'F_LIFNR'
    ID 'LIFNR' FIELD iv_lifnr
    ID 'ACTVT'  FIELD '01'.
  IF sy-subrc <> 0.
    DELETE gt_out WHERE lifnr = iv_lifnr.
  ENDIF.

ENDFORM.
```

采购组织/采购组维度的责任隔离应按业务实际选用 `EKKO-EKGRP` 关联 `T042G` 或 `M_MSEG` 类对象——这一条必须与业务方确认适用范围后再实现，不要凭猜测上过滤。

### 6.4 展现层增强

```abap
FORM display_alv.
  APPEND VALUE #( s_fieldname = 'PO_CNT'
                  s_sortdown  = abap_true ) TO gt_sort.

  gs_layo-zebra        = 'X'.
  gs_layo-get_sel_info = 'X'.
  gs_layo-grid_title   = '供应商采购订单统计'.
  gs_layo-no_title     = abap_true.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout        = gs_layo
      it_fieldcat      = gt_fcat
      it_sort          = gt_sort
      i_save_variant   = 'ZMMR_VEND_LIST'
      is_variant       = 'ZMMR_VEND_LIST'
    TABLES
      t_outtab         = gt_out.
ENDFORM.
```

若需要合计行，可加 `slis_totals_alv`（`PO_CNT` 汇总），或直接在 SQL 末尾追加一行 `'合计'`（DDIC 上预留 `LIFNR = '总计'` 的行并置底色）。

### 6.5 后台兼容分支

```abap
FORM display_alv.
  IF sy-batch = abap_true.
    CALL FUNCTION 'REUSE_ALV_GRID_LIST_DISPLAY'
      EXPORTING
        is_layout   = gs_layo
        it_fieldcat = gt_fcat
      TABLES
        t_outtab    = gt_out.
  ELSE.
    CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
      EXPORTING
        is_layout   = gs_layo
        it_fieldcat = gt_fcat
        it_sort     = gt_sort
      TABLES
        t_outtab    = gt_out.
  ENDIF.
ENDFORM.
```

### 6.6 现代化路径（可选，收益最大的一条）

若这个"供应商 + 采购统计"逻辑会被多张报表复用，做成 provider 类 + 统一 ALV 组件，一次投入长期受益：

```abap
DATA gt_out TYPE TABLE OF zmmr_vend_s.

lo_provider = NEW zcl_zmmr_vend_provider( iv_lifnr = s_lifnr[]-low iv_ekorg = s_ekorg[]-low ).
gt_out = lo_provider->get_vendor_po_summary( ).

lo_alv = NEW zcl_alv( ).  " 统一封装 REUSE_ALV_GRID_DISPLAY + variant + 导出
lo_alv->show( io_data = REF #( gt_out ) ).
```

或者直接上 `SALV`（无需类型池、无需 layout 结构）：

```abap
lo_alv = cl_salv_table_factory#( r_data = gt_out ).
lo_alv->get_field_catalog( )->get_all_fields( ).
lo_alv->display( ).
```

取舍建议：字段目录已由 DDIC 自动合并（4.3 节），说明团队接受了"DDIC 驱动展示"的思路，`SALV` 能顺带摆脱 `TYPE-POOLS: slis` 与遗留 `TABLES` 语句；但 `SALV` 的布局/合计/自定义单元格能力弱于经典 ALV，若报表要大量定制就保留 `REUSE_ALV_GRID_DISPLAY` 并把"取数"下沉到类里——**这是最务实的折中**。

---

## 7. 改造路线图

| 阶段 | 内容 | 收益 |
|---|---|---|
| P0（当天） | 加 `BEDAT` 区间、`LOEKD` 过滤、`IS INITIAL` 判空 | 报表从"不可用"变"可用" |
| P1（一周） | 凭证类型参数化、消息类化、`ZMMR_VEND_S` 追加 `LAST_PO`、排序与标题 | 可配置 + 可交付业务 |
| P2（两周） | ST05 实测两种 SQL 形态并择优、补后台 `sy-batch` 分支、合计行 | 性能可承诺、批处理可用 |
| P3（合规评审后） | 供应商主数据授权 + 采购组责任隔离 | 关闭内审风险项 |
| P4（架构演进） | 取数逻辑下沉为 provider 类，ALV 统一封装，考虑 SALV | 可复用、可演进 |
# ZMMR_VEND_LIST 报表程序走读报告

> 分析对象：`evals/zmmr_vend_list.abap`（58 行，报表程序 / 非 OO）
> 关注点：业务问题、程序架构、执行流程、按子程序讲解、问题清单与改进建议

---

## 0. 一句话结论

这是一个**结构教科书般标准**的 ALV 报表（三段式：`get_data` → `build_fieldcat` → `display_alv`），分层清楚、代码风格偏现代（`@DATA` 内联声明、行结构器）；但正因为"看起来很干净"，它隐藏了三个真正的缺陷：**两处 `SY-SUBRC` 误用（其中一处是死代码、一处逻辑不可靠）**、**完全未设限的查询范围（默认全表聚合）**，以及**报表未做授权/后台可执行性/结果集完整性**三方面的防护。修复成本很低，收益很高。

---

## 1. 业务问题与设计目标

| 维度 | 内容 |
| --- | --- |
| 业务诉求 | 给采购/物料管理岗（MM）一个按供应商汇总的视角：某段供应商范围 × 某采购组织范围内，**每个供应商有多少张采购订单** |
| 输入 | `s_lifnr`（供应商编号区间，源自 `LFA1-LIFNR`）、`s_ekorg`（采购组织区间，源自 `EKKO-EKORG`），均为可空 Select-Option |
| 输出 | 一个全屏 ALV 表格，三列：供应商号、供应商名称、采购订单张数（`COUNT(DISTINCT EBELN)`） |
| 数据来源 | `LFA1`（供应商主数据）× `EKKO`（采购订单抬头） |
| 使用场景假设 | 前台 F8 执行、查看/排序，不保存布局变式，不打印，不做后台调度 |

### 隐含的业务假设（程序没写，但代码依赖）

1. **只要有采购订单的供应商才会出现在报表里**——`INNER JOIN` 决定了"零订单供应商"不可见。如果用户的真实问题是"哪些供应商没下单/需要催单"，这个程序天然查不出来，必须改 `LEFT JOIN` + `COALESCE`。
2. **`BSTYP = 'F'` 即"采购订单"**——硬编码的文档类别魔法值，程序里没有任何注释说明它来自哪个文档类别范围。
3. **订单张数就是"活跃度"指标**——已作废、已拒绝、被冻结的订单同样被计入。

---

## 2. 程序架构

```
┌─ 声明区（全局 DATA / SELECT-OPTIONS / TABLES）───────────────────┐
│  gt_out  : TABLE OF ZMMR_VEND_S   ← 数据载体 + 字段目录来源（双重身份）│
│  gs_layo : SLIS_LAYOUT_ALV                                        │
│  TYPE-POOLS slis  : ALV 类型池显式引入                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─ START-OF-SELECTION ── 严格顺序编排的三个 PERFORM ──────────────┐
│                                                              │
│  FORM get_data ────────── 数据层（Open SQL 聚合）              │
│    LFA1 ⨝ EKKO  → GROUP BY LIFNR, NAME1 → COUNT(DISTINCT EBELN)│
│    → 内表 lt_vend → VALUE# 行结构器 → gt_out                   │
│                                                              │
│  FORM build_fieldcat ─── 表现层（元数据层）                     │
│    REUSE_ALV_FIELDCATALOG_MERGE('ZMMR_VEND_S') → gt_fcat       │
│                                                              │
│  FORM display_alv ─────── 渲染层                                │
│    REUSE_ALV_GRID_DISPLAY( layout=gs_layo,                     │
│                           fieldcat=gt_fcat,                    │
│                           t_outtab=gt_out )                    │
└─────────────────────────────────────────────────────────────────┘
```

### 架构评价

**优点（这是全篇最值得肯定的部分）：**

- **三段式分解与 SAP 官方推荐模板完全一致**（取数 / 建字段目录 / 显示），阅读成本极低，新人接手不用猜。
- **单一 DDIC 真源**：`ZMMR_VEND_S` 同时定义输出结构和 ALV 列结构，改一次 DDIC 就同时改完数据和列名，字段重命名不会留下"代码与清单不同步"的坑。这个设计决定是加分项。
- **无全局 SELECT 的"过程式反模式"**：所有查询都在 `FORM` 内显式带字段列表，没有 `SELECT *`、没有隐式宿主变量填充。
- **7.40 语法**：内联 `INTO TABLE @DATA(lt_vend)`、host variable 转义 `@`，已摆脱 3.4 时代的 `lt_xxx[]` 派生活型。

**缺点（架构层面的）：**

- **全局状态驱动**：三个 FORM 全靠 `gt_out` / `gt_fcat` / `gs_layo` 通信，没有参数、没有返回值。后果是：无法在别的程序里复用取数逻辑（只能整体复制）、**无法单元测试**、同程序内多次调用会造成状态污染。
- **`FORM` 时代的包袱**：整个程序是过程式 + 全局变量，正确做法应是 `zcl_mm_vend_po_count=>get_data(...)` + 独立的 `zcl_mm_vend_alv=>show(...)`（数据服务与表现分离）。当前形态对"报表"够用，但把一段可复用的统计逻辑锁死在了报表里。
- **无法后台运行**：见 §6 P1-4。

---

## 3. 执行流程（逐行时序）

```
用户进入 ZMMR_VEND_LIST
  └─► 选择屏幕：s_lifnr（可空）、s_ekorg（可空）
        │   ⚠ 没有 AT SELECTION-SCREEN，两个区间都可留空
        ↓
  ① START-OF-SELECTION
        │ PERFORM get_data
        │   ├─ Open SQL: SELECT ... LFA1 INNER JOIN EKKO
        │   │    WHERE lifnr IN s_lifnr AND ekorg IN s_ekorg AND bstyp='F'
        │   │    GROUP BY lifnr, name1
        │   │    → lt_vend（内联声明的匿名结构表）
        │   ├─ IF sy-subrc = 0  →  VALUE# 逐行映射 → gt_out
        │   └─ ELSE            →  MESSAGE '无符合条件的供应商' TYPE 'I' + STOP
        │                         （STOP 终止整个 START-OF-SELECTION 剩余流程）
        │
        │ PERFORM build_fieldcat
        │   └─ REUSE_ALV_FIELDCATALOG_MERGE( 'ZMMR_VEND_S' ) → gt_fcat
        │      └─ IF sy-subrc <> 0 → MESSAGE '字段目录生成失败' TYPE 'E'  ← 永远不会按预期触发
        │
        └─ PERFORM display_alv
            ├─ gs_layo-zebra      = 'X'     （遗留属性，Grid 下已失效）
            ├─ gs_layo-get_sel_info = 'X'   （已废弃，被 i_default_pm 取代）
            └─ REUSE_ALV_GRID_DISPLAY( ... t_outtab = gt_out )
                 └─ 返回到选择屏幕；后续的排序/筛选/导出全部由 ALV 框架承担
```

**流程上的两个隐含依赖：**

1. `get_data` 失败时靠 `STOP` 拦住后面的两个 PERFORM。`STOP` 与 `RETURN` 的作用域不同（`STOP` 终止整个程序块，`RETURN` 只退出当前 FORM），这里依赖的是一个**很容易被后续维护者误改成 `RETURN` 的隐式语义**——一旦改成 `RETURN`，程序会静默地弹出一个空 ALV。
2. `build_fieldcat` 排在 `get_data` 之后，意味着**要先跑一次全量聚合，才可能发现字段目录配置有问题**。字段目录与数据无关，失败时应该"先失败"。

---

## 4. 分程序讲解

### 4.1 声明区

```abap
TABLES: lfa1, ekko.
```

`lfa1` / `ekko` 是 2.5 时代的隐式工作区声明，本程序里**它们从头到尾没有被真正用作宿主变量**，只为 `SELECT-OPTIONS ... FOR` 提供字段参照：

```abap
SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg.
```

这是合法的，但代价是引入了两张表的"幽灵主数据读取"（在程序 SQL 视图/Where-Used 里会被误列为访问对象）。现代写法用显式工作区即可，无需 `TABLES`。

> 附带一个容易忽略的点：`BSTYP` 不是"采购订单"这个业务概念，而 EKKO 上的**文档类别**字段。程序把它等同于"采购订单"，注释缺失的情况下，接手人无法判断这个 `'F'` 是否覆盖了业务上认定的所有单据类型（例如后续新增的自定义单据类型）。应至少用常量 + 注释把语义钉死。

### 4.2 `FORM get_data` —— 数据层

核心查询：

```abap
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
```

逐条拆解：

- **聚合位置是对的**。在 SQL 层 `GROUP BY` + `COUNT`，而不是"把明细拉回 ABAP 再循环计数"。在 HANA/ORACLE 上这是正确做法，避免了几十万行的 ABAP 侧传输。
- **`COUNT(DISTINCT b~ebeln)` 当前是冗余的**。`LFA1` 按 `LIFNR` 唯一，`EKKO` 是抬头表（一个 `EBELN` 一行），JOIN 后每行仍是一个订单抬头，所以 `COUNT(*)` 与 `COUNT(DISTINCT EBELN)` 结果相同。
  - 但**必须保留**：一旦有人为了显示订单金额/行项目而改成 JOIN `EKPO`（一行抬头 JOIN N 行项目），`COUNT(*)` 会瞬间膨胀 N 倍，而 `DISTINCT` 会自动兜住。
  - 反过来说，`DISTINCT` 也**掩盖了潜在的扇出（fan-out）**：如果哪天加了第二个多行 JOIN，聚合数字不会报错，只会静默变对或变错。`DISTINCT` 是一层安全带，不是一层校验。
- **`GROUP BY lifnr, name1` 中的 `name1` 是"技术必需"而非业务必需**。`LIFNR` 已是 LFA1 主键，`NAME1` 函数依赖于它，分组维度上它不产生任何额外分组。留着无害（DB 层同样走主键索引），但它暴露了一个信号：**作者当时不确定 LIFNR 是否唯一**——这种不确定性本该通过表的主键/唯一索引来确认，而不是靠 GROUP BY 掩盖。
- **`INNER JOIN` 的方向选择**。先 JOIN 再聚合，意味着 `EKKO` 里符合条件的所有行都要参与 JOIN，再被聚合掉。如果改成"先在 `EKKO` 上聚合出 `LIFNR → COUNT`，再拿这个小结果集去 `LFA1` 取名称"，传输量会从"全部符合条件订单行"降到"供应商数量行"，在宽范围查询下差距可能是几个数量级（见 §6 P1-2 的改写）。

结果搬运：

```abap
IF sy-subrc = 0.
  gt_out = VALUE #( FOR ls IN lt_vend
                    ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ).
ELSE.
  MESSAGE '无符合条件的供应商' TYPE 'I'.
  STOP.
ENDIF.
```

**这是全篇最重要的缺陷。**

- **`SY-SUBRC` 在 `INTO TABLE`（内表目标）之后不是可靠的"是否有数据"判据**。`SY-SUBRC` 的可靠语义定义只覆盖写入平坦宿主的 `SELECT ... INTO`（以及部分 `SELECT ... SINGLE`）。目标为内表时，正确且唯一的判断是 `IF lt_vend IS INITIAL`。
- 实际后果有两个方向：要么**无数据时 `SY-SUBRC` 不为 0，`ELSE` 分支被跳过，用户看到一个空白的 ALV 表**（体验差、且掩盖了"没查到"这一事实）；要么 `SY-SUBRC` 恰好为 0 而走了 `VALUE#`，`gt_out` 被赋为空表但用户**没有任何提示**。无论哪种，"无数据"这条业务信息都没有可靠地传给用户。
- **`VALUE #( FOR ... )` 在这里是纯样板**。`lt_vend` 是匿名结构内表，`gt_out` 是 DDIC 结构内表，两者字段同名同序，直接 `gt_out = lt_vend.` 就够了（ABAP 的表间赋值会自动做结构兼容检查）。当前写法：
  - 没有增加任何安全性（类型不兼容时直接赋值同样报错）；
  - 多出一次逐行遍历；
  - 反而**制造了"这里在做字段映射"的错觉**——它把"两个结构恰好字段同名"这件重要事实掩盖掉了。后来者改匿名结构字段名时，会在这里收到一个不指向真正原因的错误。
- **`MESSAGE ... TYPE 'I'` + `STOP`**：
  - 消息文本是中文硬编码字面量，不走消息类 → 无法翻译、无法统一维护；源码编码依赖也成了隐患。
  - `TYPE 'I'` 在后台运行时不可显示，会导致作业被终止，**程序不具备后台可执行性**。
  - 用户看到弹窗后流程直接结束，回到选择屏幕，无法"放宽条件再试"。

### 4.3 `FORM build_fieldcat` —— 元数据层

```abap
CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
  EXPORTING
    i_structure_name = 'ZMMR_VEND_S'
  CHANGING
    ct_fieldcat     = gt_fcat.
IF sy-subrc <> 0.
  MESSAGE '字段目录生成失败' TYPE 'E'.
ENDIF.
```

- **做法本身是干净的**：只给结构名，标题全部来自 DDIC 短描述。这正是 4.2 中"单一真源"设计的收益兑现点。
- **`IF sy-subrc <> 0` 是死代码，而且是一颗定时炸弹**。`CALL FUNCTION` 只有在声明了 `EXCEPTIONS` 时才会写 `SY-SUBRC`；这里没声明任何异常，所以**这个 `SY-SUBRC` 是上一条语句残留的值**。
  - 此刻的残留值恰好来自 4.2 的 `SELECT`（正常路径为 0），所以这段检查"看起来一直在正常工作"——这是它能活到今天的原因。
  - 但任何人只要在 `get_data` 之后新增一条会置 `SY-SUBRC <> 0` 的语句（比如某个 `READ TABLE` 失败后没清标志），这个 `MESSAGE '字段目录生成失败' TYPE 'E'` 就会在**完全正常**的查询后弹出来，把排查方向直接引向错误的地方。
  - 正确写法是声明异常（`EXCEPTIONS not_found = 1 ...`）或检查 `IF gt_fcat IS INITIAL`。而且这不只是"代码洁癖"：`ZMMR_VEND_S` 一旦被删除、被改成非结构（变成透明表）、或传输不完整，MERGE 是会失败的——这个检查本来是想做校验的，只是**它永远不会执行**。
- **缺一个前置检查**：MERGE 完成后若某字段在 DDIC 里没有短描述，ALV 会直接显示技术名称（如 `LIFNR`）并弹一条提示。用户看到的是"供应商报表里有一列叫 LIFNR"。建议在 FORM 末尾统一回填业务标签作为兜底。

### 4.4 `FORM display_alv` —— 渲染层

```abap
gs_layo-zebra      = 'X'.
gs_layo-get_sel_info = 'X'.
CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
  EXPORTING
    is_layout   = gs_layo
    it_fieldcat = gt_fcat
  TABLES
    t_outtab    = gt_out.
```

- **`gs_layo-zebra` 与 `gs_layo-get_sel_info` 都是遗留属性**。斑马线在 Grid ALV 中已由 `SAPLIST` 布局对象控制，`GET_SEL_INFO` 已被 `I_DEFAULT_PM` / `SEL_MODE` 取代。这两行要么无效（误导性代码），要么仅在老版本上生效（跨版本行为不一致）。它们传递出的信息是："这段 ALV 代码是照着老教程抄的，之后没人维护过显示层。"
- **`TABLES t_outtab = gt_out` 绑死了全局变量**。ALV 的标准写法是用 `CHANGING it_outtab = <传入参数>`，这样同一个显示子程序可以被复用来展示不同结果集（也是后续迁移到 `REUSE_ALV_GRID_DISPLAY_LVC` 的必要一步）。绑全局表的直接后果：这个 FORM 调一次之后，`gt_out` 的内容会被 ALV 交互（如排序）改写，**再次调用显示的是被改过的数据**。
- **未声明 `EXCEPTIONS`**：一旦 ALV 初始化失败（无 GUI 的上下文、字段目录非法），用户看到的是 short dump 而不是一句可读的报错。
- **未设置任何可用性能力**：`i_save = 'A'`（用户保存/调用布局变式）、`it_sort`（默认按订单数倒序）、合计行（`slis_totals`）、列表标题/页眉（`slis_listinfo`，打印/PDF 时必看）、页脚。一个采购岗用得最多的动作——"按订单数排序""导出""保存我的列宽"——现在全靠用户自己点表头，或者干脆做不到。

---

## 5. 数据流一览

| 阶段 | 输入 | 输出 | 存放位置 |
| --- | --- | --- | --- |
| 选择屏幕 | 用户输入 | `S_LIFNR[]` / `S_EKORG[]` | 屏幕字段（基于 `LFA1-LIFNR` / `EKKO-EKORG`） |
| 取数 | 上述区间 | `LIFNR`, `NAME1`, `PO_CNT` | `LT_VEND`（内联匿名结构，FORM 局部） |
| 搬运 | `LT_VEND` | 同行同构数据 | `GT_OUT`（`TABLE OF ZMMR_VEND_S`，全局） |
| 建目录 | `ZMMR_VEND_S` | 列定义 + 标题 | `GT_FCAT`（`SLIS_T_FIELDCAT_ALV`，全局） |
| 显示 | `GS_LAYO` + `GT_FCAT` + `GT_OUT` | 屏幕表格 | ALV 内部（成功后交由用户交互） |

`GT_OUT` 被两处消费（数据载体 + 字段目录来源），这是本程序设计上最聪明的一处——代价是**数据与表现被绑在同一个 DDIC 对象上**，任何列的微调都必须改 DDIC，不能通过 FM 参数局部调整。

---

## 6. 问题清单（按严重度分级）

### P0 —— 必须修（功能不可信）

| # | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| **P0-1** | `get_data:29` | `SY-SUBRC` 在 `INTO TABLE` 后不可靠 | "无数据"分支可能永不执行；用户要么看空表、要么收不到任何提示。**这是唯一一处会导致用户看到错误业务结论的地方**（把"查无数据"误读成"没有这批数据"） |
| **P0-2** | `build_fieldcat:44` | `CALL FUNCTION` 未声明 `EXCEPTIONS`，`SY-SUBRC` 是上一条语句的残留值 | 检查形同虚设；且随时会被上游新增语句"误触发"，弹出误导性的 `'E'` 消息 |
| **P0-3** | `get_data:33` | 中文消息硬编码字面量，不走消息类/文本符号 | 不可翻译、不可统一维护、编码依赖；后台运行时 `TYPE 'I'` 导致作业终止 |

### P1 —— 应修（正确性 / 可运维性风险）

| # | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| **P1-1** | 整个查询 | 选择屏幕**完全不设限**：`s_lifnr` 与 `s_ekorg` 均可留空，留空即"全部供应商 × 全部采购组织 × 全部采购订单" | 生产系统上一次全表 JOIN + GROUP BY 足以拖垮 BW；且这是**报表里最容易出现的误操作**（两个框都空着直接 F8） |
| **P1-2** | `get_data:22-27` | 先 `LFA1 ⨝ EKKO` 再聚合，宽度无法收敛 | 宽范围查询时传输/聚合量按**订单行数**而非**供应商数**增长。应改成"先聚合 EKKO，再与小结果集 JOIN 取名称" |
| **P1-3** | `INNER JOIN` | 零订单供应商不可见 | 若业务意图包含"未下单/待催单供应商"，这是**功能缺失**而非缺陷——需先确认口径 |
| **P1-4** | 无 `AT SELECTION-SCREEN`、无异常声明 | 无输入校验；`STOP` + `TYPE 'I'` 组合使程序**不能后台运行**（`SUBMIT`/定时任务会挂） | 报表无法纳入批处理体系 |
| **P1-5** | `get_data:26` | `b~bstyp = 'F'` 魔法值，无注释、无常量 | 口径不可追溯；单据类型口径变更时无从判断影响面 |
| **P1-6** | 全程序 | 无任何权限检查 | `LFA1`（供应商主数据）/ `EKKO`（采购数据）属于敏感对象。若报表挂到面向多用户的角色，全量供应商名单 + 采购活跃度等于向无权限用户泄露供应网络信息（分析权限体系下尤其明显） |

### P2 —— 建议修（可维护性）

| # | 位置 | 问题 |
| --- | --- | --- |
| **P2-1** | `TABLES: lfa1, ekko` | 2.5 Word 时代隐式工作区，本程序从未真正使用；用 `DATA ls_lfa1 TYPE lfa1.` 替代 |
| **P2-2** | `get_data:30-31` | `VALUE #( FOR ... )` 纯样板；改为直接赋值 `gt_out = lt_vend.`（如需类型/字段对齐检查，直接赋值反而会显式报错） |
| **P2-3** | 全局 `DATA` | 全局可变状态 + `FORM` 过程式通信 → 不可测、不可复用。抽 `zcl_mm_vend_po_count` + `zcl_mm_vend_alv` |
| **P2-4** | `display_alv:50-51` | `zebra` / `get_sel_info` 已废弃或失效，删除或迁移到 `SAPLIST` / `i_default_pm` |
| **P2-5** | `display_alv:56` | `TABLES t_outtab` 绑全局表 → ALV 会改写 `gt_out`，不可重复调用；改用 `it_outtab` 形参 |
| **P2-6** | 字段目录 | 无 `no_text = 'X'` 兜底、无 `refname`、无列格式/对齐/小数位控制 |
| **P2-7** | 无 `EXCEPTIONS` | ALV 初始化失败 → short dump 而非可读报错 |

### P3 —— 体验/业务增强（非缺陷）

| # | 建议 |
| --- | --- |
| **P3-1** | 默认排序：`it_sort` 按 `PO_CNT` 倒序，用户一进来就看到重点 |
| **P3-2** | `i_save = 'A'` + `is_variant`：允许用户保存/调用列布局（MM 岗几乎必需要） |
| **P3-3** | 合计行 `SLIS_T_TOTALS` + `slis_totals = 'X'`：底部显示总订单数（数字型字段天然支持） |
| **P3-4** | `SLIS_LISTINFO`：加标题/页眉/页脚，否则打印或导出 PDF 时是一张没有出处的裸表 |
| **P3-5** | 增加价值型指标：订单总金额（`EKPO-NETWR`）、最近下单日期（`EKKO-LEINZ`）、`COUNT(DISTINCT EBELN)` 之外的订单状态分布。只有"张数"这一个指标的报表，业务价值有限 |
| **P3-6** | 考虑迁移到 `REUSE_ALV_GRID_DISPLAY_LVC`（`LVC_FCAT` + `LVC_S_LAYOUT`）：渲染一致性、PDF/OOXML 导出、后续维护成本都更优 |
| **P3-7** | 确认单据口径：`EKPO` 的行项目类型（`ITAB` 退货、`KTA` 费用）、采购订单整体状态、冻结标志是否要排除 |

---

## 7. 改进建议与参考实现

### 7.1 最小修复版（保留现有结构，只修 P0/P1）

```abap
REPORT zmmr_vend_list.
TYPE-POOLS: slis.

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,
      gt_fcat TYPE slis_t_fieldcat_alv,
      gs_layo TYPE slis_layout_alv.

CONSTANTS gc_bstyp_po TYPE ekko-bstyp VALUE 'F'.  " 采购订单文档类别

DATA ls_lfa1 TYPE lfa1.
DATA ls_ekko TYPE ekko.
SELECT-OPTIONS: s_lifnr FOR ls_lfa1-lifnr,
                s_ekorg FOR ls_ekko-ekorg.

AT SELECTION-SCREEN.
  IF s_lifnr[] IS INITIAL AND s_ekorg[] IS INITIAL.
    MESSAGE '请至少指定供应商范围或采购组织，以避免全量扫描。' TYPE 'S' DISPLAY LIKE 'W'.
  ENDIF.

START-OF-SELECTION.
  PERFORM build_fieldcat.   " 与数据无关，先建；配置有问题立即失败
  PERFORM get_data.
  PERFORM display_alv.

FORM get_data.
  " 两步取数：先在抬头表上聚合出「供应商 → 订单张数」，
  " 再用这个小结果集去 LFA1 取名称，避免把全部订单行送进 JOIN
  SELECT lifnr, COUNT( DISTINCT ebeln ) AS po_cnt
    FROM ekko
   WHERE lifnr IN @s_lifnr
     AND ekorg IN @s_ekorg
     AND bstyp  = @gc_bstyp_po
   GROUP BY lifnr
    INTO TABLE @DATA(lt_cnt).

  IF lt_cnt IS INITIAL.                       " ← 修 P0-1：内表用 IS INITIAL
    MESSAGE '无符合条件的供应商' TYPE 'S'.
    RETURN.
  ENDIF.

  SELECT a~lifnr, a~name1, c~po_cnt
    FROM @lt_cnt AS c
    INNER JOIN lfa1 AS a ON a~lifnr = c~lifnr
   INTO TABLE @DATA(lt_src).

  gt_out = CORRESPONDING lt_src.              " ← 修 P2-2：字段同名，直接赋值

  " 兜底：DDIC 无短描述时，避免用户看到技术名称
  MODIFY gt_fcat FROM VALUE #( ( fieldname = 'LIFNR'
                                refname   = 'ZMMR_VEND_S-LIFNR'
                                no_text   = 'X' ) )
         TRANSPORTING no_text
       WHERE fieldname = 'LIFNR'.
ENDFORM.

FORM build_fieldcat.
  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING
      i_structure_name = 'ZMMR_VEND_S'
    CHANGING
      ct_fieldcat     = gt_fcat
    EXCEPTIONS
      inconsistent_structure = 1
      program_error          = 1
      others                 = 1.            " ← 修 P0-2：真正的错误来源
  IF sy-subrc <> 0 OR gt_fcat IS INITIAL.
    MESSAGE '字段目录生成失败(ZMMR_VEND_S)' TYPE 'E'.
  ENDIF.
ENDFORM.

FORM display_alv.
  DATA ls_variant TYPE slis_variant_info.
  DATA lt_sort    TYPE slis_sortinfo_alv.
  DATA lt_totals  TYPE slis_totals_alv.

  APPEND VALUE #( fieldname = 'PO_CNT' updown = 'D' ) TO lt_sort.   " ← P3-1
  APPEND VALUE #( is_sum = 'X' ) TO lt_totals.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout   = VALUE #( zebra = 'X' grid_title = '供应商采购订单统计'
                             info_notfound = '无符合条件的供应商'
                             slis_tab_default = 'ZMMR_VEND_LIST' )  " ← P3-4
      it_fieldcat = gt_fcat
      it_sort      = lt_sort
      slis_totals = 'X'
      i_save      = 'A'                                               " ← P3-2
      is_variant  = ls_variant
    CHANGING
      it_outtab   = gt_out                                            " ← P2-5
      it_totals   = lt_totals
    EXCEPTIONS
      others = 1.
  IF sy-subrc <> 0.
    MESSAGE 'ALV 显示失败' TYPE 'E'.
  ENDIF.
ENDFORM.
```

要点说明：

- `INFORMATION_NOTFOUND` 配合"不再 `STOP`"的做法，把"无数据"从**弹窗中断**降级为**ALV 区域内的状态提示**——用户能立刻看到原因并调整选择条件，这是报表类程序的标准做法。
- `it_outtab` 改为 `CHANGING` 传参后，这个 FORM 就成了可复用的"把内表画成 ALV"通用例程。
- 若暂时保留 `REUSE_ALV_GRID_DISPLAY`，`zebra` 字段是否仍生效取决于 ALV 版本，建议在测试系统上确认后再决定保留或删除。

### 7.2 优化版（两段式取数，可扩展到 OO）

```abap
  " 第一段：EKKO 上聚合 —— 结果集大小 = 供应商数，与订单总量无关
  SELECT lifnr, COUNT( DISTINCT ebeln ) AS po_cnt
    FROM ekko
   WHERE lifnr IN @s_lifnr
     AND ekorg IN @s_ekorg
     AND bstyp  = @gc_bstyp_po
   GROUP BY lifnr
    INTO TABLE @lt_cnt.

  " 第二段：只对已命中的供应商取名称
  SELECT lifnr, name1
    FROM lfa1
   WHERE lifnr IN @lt_cnt
    INTO TABLE @lt_names.
```

这个改写在宽范围场景下把 JOIN 的输入规模从 **N 条订单行**降到 **M 个供应商**（M ≪ N），且不改变任何业务口径。

### 7.3 长期演进建议

```
zcl_mm_vend_po_count        （领域服务，纯取数，可单元测试）
  ├─ get_po_count( is_lifnr  TYPE s_lifnr_i
  │                 is_ekorg  TYPE s_ekorg_i
  │                 RETURNING VALUE(rs_cnt) TYPE ty_vend_po_count )
  └─ get_vendor_name( )      （主数据读取，与聚合分离）

zcl_mm_vend_alv             （表现层，只依赖 DDIC 字段目录）
  └─ show( it_out TYPE ty_vend_po_count )

ZMMR_VEND_LIST              （报表，只做编排 + 选择屏幕 + 权限检查）
```

同时补上两处本程序完全缺失的横切关注点：

- **权限**：`AT SELECTION-SCREEN` 中的 `AUTHORITY-CHECK ON TABLE lfa1` / 组织范围校验，或接入分析权限对象，把"用户能看到哪些采购组织"交给后端判定，而不是靠选择屏幕自觉。
- **可测试性**：取数逻辑无 UI 依赖后，可对 `get_po_count` 做 ABAP Unit 测试，断言"给定供应商+组织区间，返回的单号集合与预期一致"——当前形态下这 impossible。

---

## 8. 快速检查清单

- [ ] 修 `SY-SUBRC` → `IS INITIAL`（`get_data`）
- [ ] 为 `REUSE_ALV_FIELDCATALOG_MERGE` 声明 `EXCEPTIONS`，删除失效的 `sy-subrc` 检查
- [ ] 消息文本移出源码（文本符号 / 消息类），并评估后台可执行性
- [ ] 至少让一个选择屏幕字段必填或加输入检查，堵住全表扫描
- [ ] 确认零订单供应商是否需要出现在报表里（`INNER JOIN` vs `LEFT JOIN`）
- [ ] `'F'` 提为常量并加注释，确认业务口径（含退货/费用行、冻结、已取消单据）
- [ ] 确认 `PO_CNT` 在 `ZMMR_VEND_S` 中的类型与 `COUNT` 返回类型（8 字节整数）的兼容性及显示格式
- [ ] 补权限检查；补 `EXCEPTIONS`；补 `i_save` / `it_sort` / 合计 / 标题
- [ ] 删除或迁移 `zebra` / `get_sel_info` 两个遗留属性

---

## 附：分析假设声明

本报告基于唯一可读源码做出，以下信息无法从源码证实，已在正文中以"需确认"标注：

1. `ZMMR_VEND_S` 的实际字段定义与短描述（报告假设其为包含 `LIFNR` / `NAME1` / `PO_CNT` 的 DDIC 结构，且与匿名内表结构字段兼容）。
2. `BSTYP = 'F'` 在本系统配置下的确切单据类型范围。
3. 报表的实际使用方式（前台/后台、是否需要 PDF、是否挂到多用户角色）。
4. 生产系统上的数据量级与 `EKKO` 相关索引（`LIFNR` / `EKORG` / `BSTYP`）的覆盖情况。
# ZMMR_VEND_LIST 供应商采购订单统计报表 — 源码走读

分析对象：`zmmr_vend_list.abap`（58 行，`REPORT`，非 OO，SLIS 全屏 ALV）
分析视角：业务意图 → 架构分层 → 执行流程 → 逐子程序细节 → 缺陷与改进

---

## 1. 这份程序在解决什么业务问题

一句话：**给采购/财务/物控人员一张"每个供应商手上压着多少张采购订单"的清单**，并支持按供应商、采购组织两个维度收窄范围。

拆开看它的业务假设：

| 维度 | 程序中的选择 | 隐含的业务口径 |
|---|---|---|
| 统计对象 | `LFA1`（供应商主数据） | 口径落在**供应商**视角，不是订单视角 |
| 关联事实 | `INNER JOIN EKKO`（采购订单表头） | 只统计**已存在采购订单**的供应商 |
| 范围过滤 | `BSTYP = 'F'` | 只统计**标准采购订单**，排除框架协议、库存调拨等 |
| 聚合方式 | `COUNT( DISTINCT ebeln )` | 一张订单无论几个行项目/几个凭证段，只算 **1 单** |
| 采购组织 | `EKKO-EKORG IN @s_ekorg` | 按采购组织（不是公司代码）分权统计 |
| 数量字段 | 仅订单数 | **不含金额**、不含已过账情况、不含交货进度 |

这个口径组合是典型的"供应商负荷盘点"：采购员用它回答"这批供应商一共压了多少单要跟"，而不是"花了多少钱"。

**口径上必须先跟业务确认的四件事**（程序没写、只能推断）：

1. `BSTYP = 'F'` 是硬编码的。要不要把框架协议（`'A'`）、调拨（`'K'`）、后续交货（`'C'`）也算进来？
2. 已删除/已作废的采购订单（EKKO 上的删除标记字段，不同版本为 `LOEKE`，以及交货记录删除标记 `EBKLV`）**没有过滤**，会被计入。
3. 供应商主数据的删除标记（LFA1-LOEVM）、冻结标记（LFA1-BLOKS/BLOCKN）、生命周期状态（LFA1-LIFID）**没有过滤**。也就是说冻结/已删除的供应商照样出现在清单里，甚至会出现在 `SELECT-OPTIONS` 空选时的全量结果里。
4. 报表名叫 `vend_list`，但统计的是订单数。**只有订单数没有金额**，对财务和成本视角是明显不够用的（金额要另接 EKEK 采购凭证费用表或 EBPOC 已过账凭证，且要按凭证币种汇总）。

---

## 2. 架构：教科书式的"三段式"报表，但耦合方式偏旧

```
┌──────────────────────────────────────────────────────────────┐
│  声明层（全局作用域）                                          │
│  TABLES: lfa1, ekko        → 把 DDIC 表结构载入 ABAP 字典      │
│  DATA: gt_out / gt_fcat / gs_layo  → 三个全局变量              │
│  SELECT-OPTIONS: s_lifnr, s_ekorg                              │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  START-OF-SELECTION  （唯一的流程入口，硬编码 3 步）            │
│    PERFORM get_data        → 取数                            │
│    PERFORM build_fieldcat  → 造列目录                          │
│    PERFORM display_alv     → 弹 ALV                           │
└──────────────────────────────────────────────────────────────┘
        ↓                    ↓                      ↓
   get_data              build_fieldcat         display_alv
  （数据访问层）           （展示元数据层）          （呈现层）
  Open SQL JOIN          FM 从 DDIC 反推列         REUSE_ALV_
  + GROUP BY             ZMMR_VEND_S 字段         GRID_DISPLAY
  + 行结构转换
```

架构特征评估：

- **分层是对的**：取数 / 造目录 / 显示三件事分给了三个 FORM，各 20 行以内，互不越界。这一点比很多几百行的 Z 报表强得多。
- **数据契约靠全局变量传递**：`gt_out`、`gt_fcat`、`gs_layo` 都是 REPORT 级全局 DATA，FORM 内部**没有任何 DATA 声明**。这意味着：
  - 每个 FORM 都隐式依赖全局状态，无法独立调用、独立单元测试；
  - FORM 无法参数化（`get_data` 的输入其实是选择屏幕，但没写成参数/返回值）；
  - 复用这个逻辑（比如做后台变式、做接口取数）只能整体复制。
- **DDIC 结构 `ZMMR_VEND_S` 同时承担两个角色**：既是 Open SQL 的结果落点（数据容器），又是 ALV 的列契约（`i_structure_name = 'ZMMR_VEND_S'`）。两个职责耦合在一个结构上——将来要加"采购金额"字段，就必须改这个结构，而它是报表的直接输出契约。
- **`TYPE-POOLS: slis`**：说明用的是 ALV 的 Simple List 时代的类型池。SAP 官方已把 `SLIS` 标记为不再推荐（no longer recommended），建议方向是 `cl_gui_alv_grid`（配合 `slis_fieldcat_alv`）或 SALV。功能上没问题，属于技术债。
- **语法是 7.40 风格**：`INTO TABLE @DATA(lt_vend)` 内联声明 + `IN @s_lifnr` 主机变量转义。所以程序有明确的版本下限（ABAP 7.40 / NetWeaver 7.4），但结构上仍是完全的老式 `FORM` + `TABLES` 写法——**语法新、架构旧**，是这一代 Z 代码的典型混合体。

---

## 3. 执行流程（按运行时刻走一遍）

```
[1] 启动 → 生成选择屏幕
      LIFNR  供应商编号   (lfa1-lifnr, 空 = 全部)
      EKORG  采购组织     (ekko-ekorg, 空 = 全部)
      两个都不是必填，没有默认值，没有 F4 帮助，没有变式

[2] 用户回车 → 进入 START-OF-SELECTION
      （注意：没有 INITIALIZATION / AT SELECTION-SCREEN 逻辑）

[3] PERFORM get_data
      单条 Open SQL：
        FROM lfa1 a  INNER JOIN ekko b ON a~lifnr = b~lifnr
        WHERE a~lifnr IN s_lifnr
          AND b~ekorg IN s_ekorg
          AND b~bstyp = 'F'
        GROUP BY a~lifnr, a~name1
        → 一次往返数据库完成"筛选 + 关联 + 聚合"
      → 结果落到内联声明的 LT_VEND

[4]   IF sy-subrc = 0  →  逐行把 LT_VEND 的三个字段搬进 GT_OUT
      ELSE             →  信息提示"无符合条件的供应商" + STOP   ← 事实上走不到（见 5.1）

[5] PERFORM build_fieldcat
      REUSE_ALV_FIELDCATALOG_MERGE 按 ZMMR_VEND_S 的 DDIC 定义
      自动生成列清单（列文本、技术序号全部取自 DDIC）
      失败 → 错误弹窗"字段目录生成失败"

[6] PERFORM display_alv
      布局：斑马纹 + 允许行选择信息
      REUSE_ALV_GRID_DISPLAY 全屏显示 GT_OUT

[7] 结束（没有 SET TITLEBAR，没有 user_command，没有 ALV 内的任何交互）
```

一次数据库访问、一个 FM 生成目录、一次全屏 ALV 输出。**性能结构是干净的**：没有循环里查库（N+1 问题），没有嵌套 SELECT，没有 `MODIFY`/`INSERT` 写操作，全程只读。

---

## 4. 按子程序分组讲解

### 4.1 `get_data` —— 数据访问层

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

**做对的地方（值得肯定）：**

1. **`COUNT( DISTINCT b~ebeln )` 是这个程序最关键的一个正确决定。** 因为用了 `INNER JOIN`，一个供应商在 EKKO 里会按订单头 × 订单行项目被放大成多行，`COUNT(*)` 得到的会是"行项目数"而不是"订单数"。用 `DISTINCT` 把 EBELN 去重后，语义才回到"这张报表要回答的问题"。很多同类报表就是在这里写错，结果和业务对不上。
2. **一次查询解决筛选 + 关联 + 聚合**，没有 N+1。
3. **`a~lifnr` 在 SELECT 和 GROUP BY 里同时出现**，供应商编号既是分组键又是过滤键——LFA1 主键命中，效率上没问题。
4. **7.40 语法**：`@` 转义、内联 `@DATA`，写法是当前推荐的。

**写得不好的地方：**

1. **行结构转换是纯冗余**（见 4.1 转换段）。
2. **`INNER JOIN` 决定了"0 单供应商不显示"**（见 5.3）。这不是 bug，但它是业务假设，代码里既没有注释也没有说明。
3. **过滤条件全部下推 SQL 之外没有二次收敛**：`s_lifnr` / `s_ekorg` 都空选时，就是全库范围聚合（见 5.4）。
4. **无删除/冻结标记过滤**（见 1.第 2、3 点）。

```abap
IF sy-subrc = 0.
  gt_out = VALUE #( FOR ls IN lt_vend
                    ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ).
ELSE.
  MESSAGE '无符合条件的供应商' TYPE 'I'.
  STOP.
ENDIF.
```

`VALUE #( ... )` 在这里没有带来任何价值。`LT_VEND` 的行结构和 `GT_OUT` 的行结构（`ZMMR_VEND_S`）字段名、类型、顺序**完全一致**（因为 SELECT 列表的列名就是 `lifnr` / `name1` / `po_cnt`），所以下面这行和上面这 7 行等价：

```abap
gt_out = lt_vend.
```

这是典型的"把简单事写复杂"：7 行样板代码 + 一个 FOR 循环，换来零收益。反而增加了维护成本（将来 SELECT 里加一列，就得记得同步改这里），也让读者以为结构不兼容。

---

### 4.2 `build_fieldcat` —— 展示元数据层

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

**优点：零维护。** 列目录完全从 DDIC 反推，报表本身一行都不用改；文本、输出长度、技术设置都跟着 DDIC 走。这比手工 `ls_fcat` + `APPEND` 几十行要好得多，方向正确。

**问题：**

- **这个 FM 会设置 `sy-subrc`，所以这里的 `sy-subrc` 检查是合法的**（和 `get_data` 里的错误用法形成鲜明对比）。但它只区分"成功/失败"两个态，把 `subrc = 1`（参数错误）和 `subrc = 2`（DDIC 结构不存在）等诊断信息全丢了，用户看到的是一句没有信息量的"字段目录生成失败"。
- **DDIC 结构成为列契约的唯一来源**，别名/显示文本无法在程序层覆盖（FM 有 `i_excl_tech` / `it_exclude`，但不能改名）。将来想显示"供应商名称"而不是"名称"就得改 DDIC 或改用手动维护目录。
- 中文硬编码消息，无消息类无消息号（见 5.6）。

---

### 4.3 `display_alv` —— 呈现层

```abap
gs_layo-zebra = 'X'.
gs_layo-get_sel_info = 'X'.
CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
  EXPORTING
    is_layout   = gs_layo
    it_fieldcat = gt_fcat
  TABLES
    t_outtab    = gt_out.
```

**问题最集中的一段：**

1. **`get_sel_info = 'X'` 是无效配置。** 这个参数的作用是让 FM 走"取选中行"（`ET_GET_SEL_INFO_OUT`）的模式，但程序既没有 `USER_COMMAND`，也没有接收 `ET_GET_SEL_INFO_OUT`，输出参数一个都没 EXPORT。等于付了性能代价（行选择信息追踪 + ALV 内部维护）却拿不到任何东西。正确做法：要么删掉，要么配 `it_fieldcat` 里的 `NO_OUTTAB = 'X'` 伪列并实现选中行后的逻辑。
2. **没有 `SET TITLEBAR`**：ALV 标题栏空着或显示默认，用户无法确认自己在哪张报表里。对一个要发给业务用户用的报表，这是明显遗漏。
3. **没有预置排序**（`it_sort`）：ALV Grid 允许用户自己点列排序，所以不是"不能用"，但默认按 `LIFNR` 升序意味着用户每次都要手动点一次 `PO_CNT` 才能看到"单最多的供应商"。一个"负荷盘点"报表默认应该按数量降序。
4. **没有变式保存**（`i_save = 'A'`）：`slis_layout_alv` 支持，但没开。用户调好的列宽排序无法复用。
5. **没有交互**：`user_command` / `hotspot`。一个供应商号摆在屏幕上却不能双击跳到供应商主数据（`SET PARAMETER ID 'LIF'`），用户必须记下来另开事务查——报表的实用价值被浪费。
6. **没有权限检查**：采购数据是敏感数据，全屏 ALV 无条件输出全部供应商清单（见 5.7）。
7. **`t_outtab` 用 `TABLES` 传值**：这个 FM 确实是这样设计的，属于 API 约束，不算问题。

---

## 5. 问题清单

按严重程度排序。每条给出**证据 → 后果 → 修法**。

### 5.1 【严重·功能性】`Open SQL` 之后用 `sy-subrc` 判断结果 → 空结果分支是死代码

```abap
  INTO TABLE @DATA(lt_vend).
  IF sy-subrc = 0.
```

ABAP 的硬性规定：**`sy-subrc` 在 `Open SQL` 语句之后不被设置**，不能用来判断 `SELECT` 是否取到了数据。`INTO TABLE` 形式下，失败会 dump，正确做法是检查内表是否为空。

后果：这里判断的是**上一个操作残留的 `sy-subrc`**。在 `START-OF-SELECTION` 首次进入时 `sy-subrc` 恒为 `0`，所以 `IF` 分支**永远成立**，`ELSE`（`'无符合条件的供应商'` + `STOP`）**永远不执行**。

用户视角的实际表现是：查不到任何数据时，程序静默进入 `build_fieldcat` + `display_alv`，弹出一张**空白 ALV 报表**——用户以为程序坏了，或以为"0 条结果是一种正常表达"。`STOP` 那条路径是纯粹的幻觉分支。

更危险的是它并不总是错：如果这段逻辑被复制到别处、在前面有别的 FM 改过 `sy-subrc`，行为会变得不可预测——**这类代码是线上偶发问题的经典温床**。

修法：

```abap
IF lt_vend IS INITIAL.
  MESSAGE '无符合条件的供应商' TYPE 'S'.
  LEAVE LIST.   " 或 EXIT / 直接返回选择屏幕
ELSE.
  gt_out = lt_vend.
ENDIF.
```

> 顺便：`build_fieldcat` 里同样的 `IF sy-subrc <> 0.` 写法**是对的**（普通 FM 会设置 `sy-subrc`）。两个 FORM 长得像、其中一半是错的，这种"复制粘贴式防御代码"比完全没检查更有害——它会让人误以为整个程序都做了错误检查。

### 5.2 【中·健壮性】`INTO TABLE` 没有数据库异常处理

`INTO TABLE` 的 `Open SQL` 在发生数据库错误（超时、死锁、字段不存在）时是 **dump**，不会返回空表。而 `sy-subrc`（已经错误地）也接不住。程序里既没有 `TRY/CATCH`（7.40 可用），也没有 `AT SELECTION-SCREEN` 前置检查。

修法：加 `START-OF-SELECTION` 之前的外层保护，或改用 `EXEC SQL ... CATCH`，或在 `BEGIN-OF-SELECTION` 里对选择屏幕做范围与权限校验，尽早失败、给出友好消息。

### 5.3 【中·业务语义】`INNER JOIN` 静默丢掉了"零订单供应商"

```abap
INNER JOIN ekko AS b ON a~lifnr = b~lifnr
```

如果业务问题其实是"我们签了多少供应商，其中哪些是**零采购订单**的僵尸供应商？"（这在供应商清理/降级场景很常见），这个报表**结构上就答不了**——没有订单的供应商在 JOIN 时就被丢掉了，界面上和"没查到"长得一模一样。

改成 `LEFT OUTER JOIN` 即可，注意 `COUNT( DISTINCT b~ebeln )` 在 LEFT JOIN 下会忽略 NULL，仍然正确得到 0：

```abap
  FROM lfa1 AS a
  LEFT OUTER JOIN ekko AS b ON a~lifnr = b~lifnr
 WHERE a~lifnr IN @s_lifnr
   AND b~ekorg IN @s_ekorg
   AND b~bstyp = 'F'
```

（`WHERE` 里对 `b` 的条件会隐式变回 INNER JOIN 的语义，若要保留"零单供应商"必须把这些条件挪进 `ON` 子句——这是 `LEFT JOIN` 改写最常见的坑，要小心。）

无论选哪种，**至少要在代码里写注释说明口径**，否则下一个维护者无从判断 `INNER` 是刻意的还是手滑。

### 5.4 【中·性能】两个选择项都空选 = 全库聚合

`s_lifnr` / `s_ekorg` 都非必填，全空时展开成"全 LFA1 × 全 EKKO"的 JOIN + GROUP BY，数据量取决于 EKKO 的订单存量。SAP 落地表在生产系统里 EKKO 往往是百万行量级，这在应用服务器上会产生显著的工作进程/DB CPU 压力（甚至在集团关账期间引发批处理争用）。

可以做的：

- 用 `SELECT-OPTIONS` 的选择屏幕变式 / 默认值，把常见场景（某个采购组织、某个供应商范围）预置好；
- 加 `AUTHORITY-CHECK`，用采购订单显示权限对象（系统上一般形如 `ME_DISP_PO`，具体以本系统配置为准）把结果限制在用户有权的组织内；
- 数据库层确认 EKKO 上是否存在覆盖 `LIFNR` / `EKORG` 的二级索引，并用 `ST05` / `ST12` / `DBACUDB` 验证优化器实际选中的索引（SAP 标准附带若干 EKKO 二级索引，但**不要凭记忆猜索引 ID，要在目标系统里查**）；
- 拆成两次访问，让聚合只发生在小表上：

```abap
  SELECT lifnr, COUNT( DISTINCT ebeln ) AS po_cnt
    FROM ekko
    WHERE ekorg IN @s_ekorg
      AND bstyp   = 'F'
      AND lifnr   IN @s_lifnr
    GROUP BY lifnr
    INTO TABLE @DATA(lt_cnt).

  IF lt_cnt IS NOT INITIAL.
    SELECT lifnr, name1 FROM lfa1
      WHERE lifnr IN @lt_cnt
      INTO TABLE @DATA(lt_nam).
  ENDIF.
```

这样聚合在 EKKO 的索引扫描上完成，名称回填走 LFA1 主键 `FOR ALL ENTRIES` 式的范围查找，比"大表 JOIN + GROUP BY 两个字段（含 `NAME1` 排序键）"更省。

### 5.5 【中·正确性】缺失的过滤条件

结合 1. 节，程序没有排掉：

| 表 | 应考虑的过滤 | 目的 |
|---|---|---|
| EKKO | 删除/不适用标记（`LOEKE`，字段以本系统 DDIC 为准） | 不把已删订单算进"在办订单" |
| EKKO | 交货记录删除标记 `EBKLV` | 同上 |
| LFA1 | 删除标记 `LOEVM` | 不显示已删除供应商 |
| LFA1 | 冻结标记（`BLOKS` / `BLOCKN`） | 冻结供应商是否应纳入 |
| LFA1 | 生命周期状态（`LIFID`） | 只统计在用供应商 |

字段名请以所用 SAP 版本的 DDIC 为准核对后再加，别照抄。

### 5.6 【中·可维护性】中文硬编码消息，无消息类

```abap
MESSAGE '无符合条件的供应商' TYPE 'I'.
MESSAGE '字段目录生成失败'     TYPE 'E'.
```

三个问题：

1. **没有消息类 / 消息号**（应建 `ZMMR` 之类的自定义消息类，用 `MESSAGE 'ZMMR 001' TYPE 'I'`）。裸文本消息无法被 SE91 收集、无法被 SE63 翻译、无法被代码扫描工具识别。
2. **中文硬编码在非中文登录语言下会出问题**。SAP 的消息原文如果是中文，在非 Unicode 系统、或 `MESSAGE` 走对话框类（`S`/`I` 在某些场景取的是 GUI 标题）时存在显示异常风险；这属于"能跑但会偶发难看"的隐患。
3. `MESSAGE 'I' + STOP` 的组合：这类"查询无结果"更适合 `MESSAGE ... TYPE 'S'` + `LEAVE LIST`，或干脆**显示空 ALV**（行业惯例：空报表也是一种明确答案，还保住了选择屏幕上的筛选条件）。`STOP` 会终止整个程序回到选择屏幕，用户得重输一遍条件。

### 5.7 【中·安全】完全没有权限校验

报表无条件输出范围内全部供应商及其订单数。采购数据属于敏感数据，至少应该：

- 对 `s_ekorg` 校验用户是否有权查看该采购组织（结合采购订单显示权限对象）；
- 或用组织的 GTS / 权限对象过滤结果集。

这类报表在权限设计上属于"谁都能看到全公司供应商清单"，上线前应与安全团队确认。

### 5.8 【低·健壮性】`ZMMR_VEND_S` 的 `PO_CNT` 元素类型未验证

如果 `PO_CNT` 是 `CHAR`/`NUMC` 而不是整型（`INT1` / `INT2` / `INT4` / `DEC`），会出现：ALV 排序按字典序（`'9' > '10'`）、ALV 求和失效、导出到 Excel 后被当文本、后续消费方转换出错。**这一项请去 DDIC 确认**；如果确实是字符型，应改结构。

### 5.9 【低·可维护性】技术债清单

- `TABLES: lfa1, ekko` —— 加载透明表到 ABAP 字典的老写法（现代写法用 `SELECT-OPTIONS ... FOR` 配参照字段类型定义，或直接用 `TYPES` 声明结构）。`TABLES` 在现代 ABAP 里已属遗留概念。
- `REUSE_ALV_*` / `slis_t_fieldcat_alv` —— SAP 官方已不建议在新开发中使用 SLIS，新代码应走 `cl_gui_alv_grid` 或 SALV。存量代码可继续用，但不应作为模板。
- REPORT 名 `ZMMR_VEND_LIST` 与结构 `ZMMR_VEND_S` 命名不同源（`LIST` vs `S`），命名规范不统一。
- 变量名 `gs_layo` 在 `display_alv` 里被改写，而不是在初始化阶段一次性设好（无害，但布局配置应集中在 DATA 初始化处更清晰）。
- `SELECT-OPTIONS` 无 `OBLIGATORY`、无 `DEFAULT`、无 F4 值帮助（`EKORG` 建议挂采购组织 F4 帮助，避免用户手输无效代码）。
- 无 `INITIALIZATION` / `AT SELECTION-SCREEN OUTPUT`：没有变式恢复、没有权限字段的动态限制。

### 5.10 【低·健壮性】空行删除/一致性

`get_data` 未在开头 `CLEAR gt_out`，也未清 `gt_fcat` / `gs_layo`。当前只调用一次所以无害，但一旦有人把 `START-OF-SELECTION` 改成支持多选屏幕执行，或将来在 `FORM` 里做二次调用，这就是残留数据的来源。

---

## 6. 汇总：问题严重度一览

| 编号 | 问题 | 严重度 | 类型 |
|---|---|---|---|
| 5.1 | `Open SQL` 后误用 `sy-subrc`，空结果分支永不执行 | 严重 | 功能性 |
| 5.2 | `INTO TABLE` 无数据库异常处理（会 dump） | 中 | 健壮性 |
| 5.3 | `INNER JOIN` 排除零订单供应商（口径未说明） | 中 | 业务语义 |
| 5.4 | 全选即全库 JOIN + GROUP BY | 中 | 性能 |
| 5.5 | 缺删除/冻结/生命周期标记过滤 | 中 | 正确性 |
| 5.6 | 中文硬编码 `MESSAGE`，无消息类 | 中 | 可维护性 |
| 5.7 | 无权限校验 | 中 | 安全 |
| 5.8 | `PO_CNT` 元素类型待确认 | 低 | 正确性 |
| 5.9 | `TABLES` / SLIS / 命名等技术债 | 低 | 可维护性 |
| 5.10 | 未 `CLEAR` 全局缓冲 | 低 | 健壮性 |

---

## 7. 改进建议（含参考实现）

**优先级排序（如果要动手，按这个顺序）：**

1. **修 `sy-subrc`**（5.1）—— 一行改动，消除死代码，恢复"无数据"的正确反馈。
2. **确认并写死业务口径**（5.3 / 5.5 / 1.）—— 口径错比代码错危害大。至少在代码头部注释里写清"统计标准采购订单、排除已删、是否含零单供应商"。
3. **加 `SET TITLEBAR` + `it_sort` 预置排序**（4.3）—— 两行改动，可用性提升最明显。
4. **补消息类**（5.6）。
5. **补权限校验**（5.7）。
6. **性能优化**（5.4）—— 建议先用 `ST05` 测出真实耗时再决定是否拆查询，不要凭直觉重写。
7. **删掉 `VALUE #(` 冗余转换和 `get_sel_info`**（4.1 / 4.3）—— 纯减法。
8. 长期再看 OO 化 / `cl_gui_alv_grid` 迁移（5.9）。

**参考实现（7.40 语法，保留 `REUSE_ALV` 以最小化改动面）：**

```abap
REPORT zmmr_vend_list.

TYPE-POOLS: slis.

DATA: gt_fcat TYPE slis_t_fieldcat_alv,
      gs_layo TYPE slis_layout_alv.

SELECT-OPTIONS s_lifnr FOR lfa1-lifnr,   " TABLES 已删，改用参照结构
                s_ekorg FOR ekko-ekorg.

START-OF-SELECTION.
  PERFORM get_data       USING s_lifnr[] s_ekorg[].
  PERFORM build_fieldcat.
  PERFORM display_alv.

FORM get_data USING it_lifnr TYPE ANY TABLE
                   it_ekorg TYPE ANY TABLE.
  DATA: lt_cnt TYPE STANDARD TABLE OF zmmr_vend_s WITH EMPTY KEY.

  SELECT lifnr, COUNT( DISTINCT ebeln ) AS po_cnt
    FROM ekko
    WHERE ekorg IN @it_ekorg
      AND bstyp  = 'F'
      AND lifnr  IN @it_lifnr
    GROUP BY lifnr
    INTO TABLE @DATA(lt_cnt).

  IF lt_cnt IS INITIAL.
    MESSAGE 'ZMMR 001' TYPE 'S'.     " 无符合条件的供应商
    LEAVE LIST.
  ENDIF.

  SELECT lifnr, name1
    FROM lfa1
    WHERE lifnr IN @lt_cnt
    INTO TABLE @DATA(lt_nam).

  gt_out = VALUE zmmr_vend_t( FOR ls_cnt IN lt_cnt
                              ( lifnr  = ls_cnt-lifnr
                                name1  = lt_nam[ table_line = zmmr_vend_s-lifnr lifnr = ls_cnt-lifnr ]-name1
                                po_cnt = ls_cnt-po_cnt ) ).
ENDFORM.

FORM build_fieldcat.
  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING
      i_structure_name = 'ZMMR_VEND_S'
    CHANGING
      ct_fieldcat     = gt_fcat
    EXCEPTIONS
      inconsistent_interface = 1  merge_error   = 2
      program_error          = 3  others        = 4.
  IF sy-subrc <> 0.
    MESSAGE ID sy-msgid TYPE sy-msgty NUMBER sy-msgno
      WITH '字段目录生成失败(RETURN)'.
  ENDIF.
ENDFORM.

FORM display_alv.
  SET TITLEBAR 'ZMMR 900'.

  gs_layo-zebra       = 'X'.
  gs_layout-no_outtab = 'X'.          " 原 get_sel_info 无配套逻辑，改为 no_outtab

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout   = gs_layo
      it_fieldcat = gt_fcat
      it_sort     = VALUE #( ( sp_field = 'PO_CNT' sp_sortdir = 'DESC' ) )
    TABLES
      t_outtab    = gt_out.
ENDFORM.
```

（示例中的表查找写法偏啰嗦，落地时建议直接内联 `SELECT ... FOR ALL ENTRIES` 把名称一起读进一个工作表再 `CORRESPONDING`，或干脆保留原来的 JOIN 版本但把 `sy-subrc` 改对——**最小改动是只改判断，不重写查询**。`it_sort` 中的 `sp_field` 需与字段目录技术名一致，可用 `slis_sortinfo_alv` 精确指定。）

---

## 8. 一句话总结

**这是一个结构清晰、SQL 写得不错（`COUNT(DISTINCT)` 用对了、零 N+1）的入门级 ALV 报表，但它最严重的问题是第 18 行下面那句 `IF sy-subrc = 0.`**——Open SQL 不设置 `sy-subrc`，导致"无数据"的分支永远走不到；同时还存在"空选即全库聚合"、缺权限校验、口径未与业务书面确认等一系列中等问题。**先修那一行，再补口径和标题栏，报表就能拿给业务用了。**

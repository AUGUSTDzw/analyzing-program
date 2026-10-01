# ZFG_MATERIAL_PRICE 函数组走读报告

- 对象：函数组 `ZFG_MATERIAL_PRICE`（主程序 `zfg_material_price.fg.abap`）
- 成员：`LZFG_MATERIAL_PACETOP`（全局数据）+ `LZFG_MATERIAL_PACU01`（函数实现）+ `LZFG_MATERIAL_PACUXX`（主程序 INCLUDE 引用）+ `lcl_helper`（本地助手类）
- 业务归属：MM Purchasing（价格/重量维护）
- 分析基线：仅基于以上三个源文件，未参考运行时配置与上游调用方

---

## 0. 结论先行（TL;DR）

1. **当前代码无法通过编译。** 至少两处硬性语法/语义错误：`lt_desc` 未声明；`lcl_helper=>normalise_uom( is_row = ... )` 用了不存在的形参名 `is_row`（方法签名是 `iv_uom`）。
2. **即使修掉编译错误，写数据库逻辑依然不安全。** `Z_UPDATE_NET_PRICE` 的定位条件只有 `matnr`，而 `MARC` 的完整主键是 `MATNR/WERKS/LGORT`——一个物料有多条工厂/库存地点记录时，`SELECT SINGLE` 会随机命中一条，随后被 `MODIFY marc` 无条件写回，**存在写错工厂采购信息的现实风险**。
3. **`MODIFY marc FROM ls_row.` 没有 WHERE 子句**，Open SQL 中 `MODIFY` 必须限定行范围；这一行既是编译问题，也是"全表改写"的信号灯。
4. **币种被硬编码成 `'USD'`**，原币种被静默覆盖，没有汇率换算，等于把非美元物料的价格贴上美元标签。
5. **`UPDATE mard SET mstock = mstock` 是一条无意义但有副作用的写操作**：值没变，但会强制更新未清库存数量、触发库存/会计侧重新处理与变更记录，并覆盖该物料全部工厂/库存地点/批次的行。
6. **所有业务规则都"算完就扔"**：`normalise_uom` 的换算结果、`gc_weight_tol` 的重量钳制结果、`lcl_helper=>is_valid_price` 的校验方法，三者都没有被真正使用。
7. **全局表 `gt_cache` 只进不出**：每次调用都 `APPEND`，主键为 `EMPTY KEY` 不去重，函数组全局内存跨调用驻留，越用越胖；而且全组无人读取它。

---

## 1. 函数组构成与职责边界

| 单元 | 角色 | 内容 |
|---|---|---|
| `zfg_material_price.fg.abap` | 函数组主程序 | `INCLUDE TOP` + `INCLUDE UXX` + 定义 `lcl_helper` 类 |
| `lzfg_material_pacetop.abap` | 全局类型/变量/常量 | `ty_price_row`、`ty_price_rows`、`gt_cache`、`gv_*`、`gc_*` |
| `lzfg_material_pacu01.abap` | 函数实现 | `z_read_price_rows`、`z_update_net_price` |
| `lzfg_material_pacuxx` | 主程序 INCLUDE 引用 | 承载其余 `U02/U03...`（当前未提供，本报告未覆盖） |

设计上作者已经把"公共逻辑"下沉成了 `lcl_helper`（UOM 归一化、价格合法性），方向是对的；问题出在**这些逻辑接到了错误的载体上**——`lcl_helper=>normalise_uom` 形参类型是 `marc-uom`（计量单位），调用处却把 `waers`（币种）喂了进去。这说明 `ty_price_row` 结构里**根本缺少 `uom` 字段**，整个"单位归一化"的需求在数据结构层面就没落地。

---

## 2. 全局数据结构与常量（TOP）

### 2.1 `ty_price_row`

```abap
TYPES: BEGIN OF ty_price_row,
         matnr   TYPE mara-matnr,
         werks   TYPE marc-werks,
         lgort   TYPE marc-lgort,
         eina    TYPE mara-eina,
         brgew   TYPE mara-brgew,
         ntgew   TYPE mara-ntgew,
         netpr   TYPE marc-netpr,
         waers   TYPE marc-waers,
         eifn    TYPE marc-eifn,
       END OF ty_price_row.
```

这是本函数组的**核心结构**，同时被三个地方用，做法上是对的（一处定义、读写共用）。问题：

- **缺 `uom`** → `z_update_net_price` 里算出的 `lv_uom` 无处落库，归一化形同虚设。
- **缺价格单位 `peinh`（价格单位/条件单位）、缺有效期 `eprbp`** → `netpr` 单独存在没有解释口径，"净价"到底对应多少数量单位无法判定。
- **缺 `einr`（采购单位）** → `brgew / eina` 的分母语义只能靠猜。
- 它是一个**部分结构**（9 个字段），而 `MARC` 有 60+ 字段。任何 `SELECT ... INTO ls_row` / `MODIFY marc FROM ls_row` 都要求结构与表结构匹配，直接用会炸（详见 §7.2）。
- 字段跨表取类型（`mara-eina`、`mara-brgew`、`mara-ntgew`）：`MARC` 上确实也存在同名字段，功能上没问题，但与 `MARA` 混用会让人误以为读的是物料主数据。

### 2.2 `ty_price_rows` 与 `gt_cache`

```abap
TYPES ty_price_rows TYPE STANDARD TABLE OF ty_price_row WITH EMPTY KEY.

DATA: gt_cache    TYPE ty_price_rows,
      gv_run_date TYPE datum,
      gv_user     TYPE sy-uname,
      gv_language TYPE sy-langu.
```

- `WITH EMPTY KEY`：无主键 → 无法 `READ`、无法去重、只能全表扫。缓存表不带主键是典型的"只写缓存"反模式。
- `gt_cache` 只在 `z_read_price_rows` 里 `APPEND`，**全函数组没有任何一处读取**。
- `gv_run_date` / `gv_user` 在 FM 里赋值了，但**从未写入任何日志或审计记录**，起不到追踪作用。
- `gv_language` 声明了却从未赋值，`makt` 查询直接硬编码 `spras = '1'`（德语）——非德语系统或用户语言不符时，物料描述会静默查不到。
- `gv_language` 类型是 `sy-langu`（1 位），与 `makt-spras`（1 位）恰好匹配，作者显然想用它，只是忘了用。

### 2.3 常量

```abap
CONSTANTS gc_weight_tol  TYPE p DECIMALS 4 VALUE '0.5'.
CONSTANTS gc_cap_currency TYPE c LENGTH 3 VALUE 'USD'.
```

- `gc_cap_currency` 用裸 `c LENGTH 3` 而不是 `marc-waers`（`cuky`），丢掉了币种域的校验能力，赋任意 3 位串都不会被编译器拦下。
- `gc_weight_tol = 0.5`：命名是"容差"，实际被当作**上限钳制值**使用（见 §5），语义与命名不符；且重量值涉及 `BRGEW/EINA`，钳制前没有单位换算，也无下限。

---

## 3. 公共助手类 `lcl_helper`

```abap
CLASS lcl_helper DEFINITION.
  PUBLIC SECTION.
    METHODS normalise_uom
      IMPORTING iv_uom  TYPE marc-uom
      RETURNING VALUE(rv_uom) TYPE marc-uom.
    METHODS is_valid_price
      IMPORTING is_row  TYPE ty_price_row
      RETURNING VALUE(rv_ok) TYPE abap_bool.
ENDCLASS.

CLASS lcl_helper IMPLEMENTATION.
  METHOD normalise_uom.
    CASE iv_uom.
      WHEN 'PC' OR 'PA'.
        rv_uom = 'EA'.
      WHEN OTHERS.
        rv_uom = iv_uom.
    ENDCASE.
  ENDMETHOD.

  METHOD is_valid_price.
    rv_ok = COND #( WHEN is_row-netpr IS INITIAL THEN abap_false
                     ELSE abap_true ).
  ENDMETHOD.
ENDCLASS.
```

- 类定义写在 FG 主程序里，**是全局类**，U01 中可以正常调用，这一点没问题。
- `normalise_uom`：把打包单位 `PC`（包）/`PA`（托）折算成基本单位 `EA`，业务意图清楚，是"每 EA 净价"口径的前置步骤。
- `is_valid_price`：只判断 `netpr` 是否非 0 初始值。**判定标准过弱**：负价格、极小价格、超过价格上限都会通过；`IS INITIAL` 对类型 `NETPR`（CURR）而言等价于 `netpr = 0`。
- **两个方法在全函数组里：`normalise_uom` 被调用但返回值丢弃，`is_valid_price` 一次都没被调用。**

---

## 4. `Z_READ_PRICE_ROWS` 走读

### 4.1 接口

```abap
IMPORTING
  VALUE(IV_MATNR) TYPE MARA-MATNR
TABLES
  IT_ROWS        TYPE ZFG_MATERIAL_PRICE=>TY_PRICE_ROWS
EXCEPTIONS
  NO_DATA        1
```

### 4.2 职责

按物料号读取 `MARC`（采购视图）中的价格/重量相关字段，附带抓取 `MAKT` 物料描述（德语），最后写入会话级缓存 `gt_cache`；无数据时抛异常。

### 4.3 逐行走读

```abap
  SELECT matnr werks lgort eina brgew ntgew netpr waers eifn
    FROM marc
    INTO TABLE it_rows
    WHERE matnr = iv_matnr.
```

- 字段清单与 `ty_price_row` **完全对齐**——这是全文里唯一写得规范的地方。
- 只按 `matnr` 过滤 = 取该物料**全部工厂 + 全部库存地点**的记录。采购视角通常应至少限定 `WERKS`，否则单次返回行数可能上百，且调用方无法从 FM 参数上表达"我要哪个工厂"。
- `INTO TABLE it_rows` 直接写 `TABLES` 形参：语法可行，`SELECT ... INTO TABLE` 会先清空目标表再填，因此调用方传入的非空表会被覆盖（行为需在接口文档中说明）。

```abap
  SELECT maktx FROM makt
    INTO TABLE lt_desc
    FOR ALL ENTRIES IN it_rows
    WHERE matnr = it_rows-matnr
      AND spras = '1'.
```

三个问题叠加：

1. **`lt_desc` 根本没有声明** → 语法错误，程序不能激活。（`DATA lt_desc TYPE ty_...` 缺失。）
2. **空表检查在 FOR ALL ENTRIES 之后**。`it_rows` 为空时，这条 SQL 会以"无有效 IN 列表"的方式执行，退化为 `MAKT` 全表扫描，然后才在下面 `RAISE` 抛异常。**异常路径 = 一次大表全扫**，属于典型的 `FOR ALL ENTRIES` 反模式。正确顺序是先判空、再查描述。
3. **数据只进不出**：查到的 `lt_desc` 既没有 `TABLES`/`EXPORTING` 传出，也没有被使用（`makt` 键为 `MATNR/SPRAS`，每个物料只有一条描述，这里会为每个 `marc` 行重复查同一条文本）。这是纯粹的无效 DB 负载。

```abap
  lv_count = lines( it_rows ).

  gv_run_date = sy-datum.
  gv_user     = sy-uname.

  IF lv_count = 0.
    RAISE EXCEPTION TYPE cx_sy_no_data.
  ENDIF.
```

- `gv_language` 未赋值（见 §2.2）。
- **异常契约不匹配**：接口声明的是**数值异常 `NO_DATA = 1`**，代码抛的却是 **CX 类 `cx_sy_no_data`**。调用方写 `EXCEPTIONS no_data` 永远不会命中；`CX_SY_NO_DATA` 属于 `CX_ROOT` 分支，未在接口中声明为异常类时会在调用端以未处理异常逃逸，通常表现为 short dump。**接口声明与抛出方式必须二选一统一。**
- 判空使用 `lines( it_rows )`，但 `SELECT ... INTO TABLE` 出 dump/空表两态下都靠它区分，没用 `sy-subrc`，此处可接受但风格不一致。

```abap
  APPEND LINES OF it_rows TO gt_cache.
```

- **`gt_cache` 的问题集中在这里**：
  - `EMPTY KEY` 主键 → `APPEND` 不去重，同一物料被重复调用两次，表里就有两份完全相同的记录。
  - 函数组全局内存在整个会话中**跨调用驻留**，批量场景（循环若干物料）下每轮都把整批 `marc` 行追加进去，内存单调增长，长会话有 dump 风险。
  - **没有任何地方读取它**，所以"缓存"既不缓存也不提供价值；正确做法是改成 `gt_cache` 以 `matnr/werks/lgort` 为唯一键做 upsert（`INSERT ... INTO TABLE @gt_cache` + 主键冲突覆盖），或者干脆删掉。
- 顺带一提：异常抛出在 `APPEND` 之前，这点顺序是对的（空结果不污染缓存）。

### 4.4 数据流

```text
iv_matnr
   │
   ├──► SELECT marc (WHERE matnr = ?) ──► it_rows (TABLES 传出) ──► 调用方
   │                    │
   │                    ├──► FOR ALL ENTRIES ──► SELECT makt ──► lt_desc  ✗ 未声明 / 未传出
   │                    │
   │                    └──► APPEND ──► gt_cache  ⚠ 只写不读、不去重、无上限
   │
   └──► 0 行 ──► RAISE cx_sy_no_data  ⚠ 与 EXCEPTIONS no_data 不匹配
```

---

## 5. `Z_UPDATE_NET_PRICE` 走读

### 5.1 接口

```abap
IMPORTING
  VALUE(IV_MATNR) TYPE MARA-MATNR
  VALUE(IV_NETPR) TYPE MARC-NETPR
EXPORTING
  VALUE(EV_UPDATED) TYPE ABAP_BOOL
```

**接口层面的第一性问题：没有 `IV_WERKS`。** `MARC` 主键是 `MATNR + WERKS + LGORT`，而这个 FM 只拿到物料号，从签名上就无法唯一定位一条采购信息记录。

### 5.2 逐行走读

```abap
  DATA ls_row    TYPE ty_price_row.
  DATA lv_uom    TYPE marc-uom.
  DATA lv_weight TYPE p DECIMALS 4.

  SELECT SINGLE * FROM marc INTO @ls_row
    WHERE matnr = iv_matnr.
```

- `SELECT SINGLE *` 取 `MARC` 全部 60+ 字段，目标是**只有 9 个字段的 `ty_price_row`** → 结构不匹配，运行时结构不一致错误（short dump）。即使能通过，也不可能拿全表字段。
- `WHERE matnr = ...` + `SINGLE`：物料有多工厂时 ABAP 返回**存储顺序上的任意一条**，行为不可复现，也不可重入。这里应当显式传 `werks`（必要时 `lgort`），或改用 `SELECT ... FOR ALL ENTRIES` 批量按完整键更新。
- 没有 `sy-subrc` 检查：物料不存在时 `ls_row` 全是初始值，直接流进下一步。

```abap
  lv_uom = lcl_helper=>normalise_uom( is_row = ls_row-waers ).
```

- **编译错误**：形参名写成 `is_row`（那是 `is_valid_price` 的形参），应为 `iv_uom`。
- **类型/语义双重错误**：即使改名，传入的也是 `ls_row-waers`（**币种**），而形参要的是 `marc-uom`（**计量单位**）。`WAERS` 是 5 位币种、`UOM` 是 3 位单位，会被隐式截断；`'USD'` 恰好过不了 `'PC'/'PA'` 分支，于是"归一化"结果就是一个截断后的币种字符串。
- 根因：`ty_price_row` 里没有 `uom` 字段（§2.1）。

```abap
  lv_weight = ls_row-brgew / ls_row-eina.
```

- `eina` 为初始值/0（新建采购信息、或异常数据）时 → **`CX_SY_ZERODIVIDE` 除零 dump**，且前面没有任何非零判断。
- 业务口径也未交代：`BRGEW` 是物料毛重、`EINA` 是采购单位数量，`BRGEW/EINA` 得到的是"每个采购单位的毛重"，单位是物料基本计量单位体系，与净重、订单单位并不天然可比。

```abap
  IF lv_weight > gc_weight_tol.
    lv_weight = gc_weight_tol.
  ENDIF.
```

- 只做上限钳制、无下限、无异常反馈；钳制后的 `lv_weight` **后面一次都没用**，紧接着就被丢弃。所谓的"重量容差校验"实际不存在。

```abap
  ls_row-netpr = iv_netpr.
  ls_row-waers = gc_cap_currency.
```

- **`ls_row-waers = 'USD'` 硬编码币种**：无论原币种是什么，一律改成美元，且没有汇率换算。这会把 EUR/JPY 等物料的价格数值配上 USD 币种，直接破坏采购价格一致性，属于**数据损坏级**问题。
- `iv_netpr` 完全没有校验：`lcl_helper=>is_valid_price` 在此可用却没用；负价、超大价、`netpr` 与 `waers` 不匹配都不拦截。
- `ty_price_row` 里也没有 `peinh`（价格单位），`netpr` 落库后缺少解释口径。

```abap
  MODIFY marc FROM ls_row.
```

- **没有 WHERE 子句**：Open SQL 中 `MODIFY dbtab FROM wa` 必须带 WHERE 才合法（无 WHERE 无法确定更新范围）。这一行既有编译/语法层面的致命问题，也是最危险的信号——一旦被"修成"可执行且范围不受限，就是全表改写。
- 目标是 9 字段的部分结构，`MODIFY` 要求目标结构与表结构匹配，同样会结构不一致 dump。
- `MODIFY` 语义是"整行写回"，用部分字段填充的结构做整行写，会把未提供的字段写成初始值。**正确做法是 `UPDATE marc SET netpr = ... waers = ... WHERE matnr = ... AND werks = ...`**，只碰要改的字段。

```abap
  UPDATE mard SET mstock = mstock WHERE matnr = iv_matnr.
```

- **这是一条"值不变但真实写库"的语句**：`SET mstock = mstock` 不会让数据库认为值未变更（ABAP 无脏值优化判定到字段级这种语义保护），会真正更新 `MARD-MSTOCK`。
- 由此产生的连锁影响：`MARD` 由库存管理维护，直接改写会触发库存数量重算/重估（valuation）、可能生成凭证相关副作用、产生无业务含义的变更记录；`MARD` 主键是 `MATNR/WERKS/LGORT/CHARG`，只按 `matnr` 限定 = 覆盖该物料**全部工厂 + 全部库存地点 + 全部批次**的行。
- 与价格更新**毫无业务关系**：一个价格维护 FM 去写库存数量表，属于典型的"顺手加的 UPDATE"，是脏写的高发地带，也是最容易被审计/一致性检查挑出来的点。

```abap
  ev_updated = abap_true.
```

- 无论 `MODIFY`/`UPDATE` 是否成功都返回成功：`ABAP_SQL` 默认 `DBSQL_INVALID` 之类错误会 dump 而非置 `sy-subrc`，这里至少应结合 `sy-subrc` / 异常，把"更新了几行"如实返回。
- 没有 `COMMIT WORK`（依赖调用方事务边界，尚可），但也没有错误分支、没有消息、没有异常出口。

### 5.3 缺失的工程实践（整个 FM）

| 项 | 现状 | 风险 |
|---|---|---|
| 授权检查 | 无（未 `authority-check` MARC/MARD 或采购组织权限） | 任意调用方可改任意物料价格 |
| 记录锁 | 无（未 `enqueue_e_marc` / `enqueue_mard`） | 并发/RFC 并行调用下丢失更新、DB 死锁 |
| 事务控制 | 无 `COMMIT WORK` / `ROLLBACK` 约定 | 与调用方事务耦合不清 |
| 变更记录 | 无 | 价格改动不可追溯（`gt_cache` 里的 `gv_user`/`gv_run_date` 形同虚设） |
| 错误处理 | 无 `sy-subrc`、无异常 | 静默失败 + 除零 dump |
| 单位/币种治理 | UOM 归一化未落地、币种硬编码 | 价格口径错误 |

---

## 6. 两个 FM 之间的数据流全景

```text
                    ┌───────────────────────── ZFG_MATERIAL_PRICE (会话态全局) ─────────────────────────┐
                    │  ty_price_row / ty_price_rows        gt_cache(EMPTY KEY, 只写)                    │
                    │  gv_run_date  gv_user  gv_language    gc_weight_tol   gc_cap_currency('USD')       │
                    └───────────────────────────────────────────────────────────────────────────────────┘
                                             ▲                                        │
  Z_READ_PRICE_ROWS                         │                                        │ APPEND (永不去重/永不清空)
   in : iv_matnr                            │ 只读，不回写                            ▼
   out: it_rows(TABLES) ────────────────────┘                                    gt_cache ← 无人读取 ⚠
                                              ╳
   Z_UPDATE_NET_PRICE   ─── 与 Z_READ_PRICE_ROWS 之间的唯一"接口"是数据库本身，两者无内存传参 ───
   in : iv_matnr, iv_netpr                    ✗ 未把读到的 werks/lgort/uom 传递下去
   out: ev_updated(恒为 true)
   DB : marc  ← MODIFY（无 WHERE、部分结构）⚠ 写错行 / 全表风险
   DB : mard  ← UPDATE mstock = mstock（无业务理由、跨全部工厂/批次）⚠
```

**架构层面的核心观察**：这是典型的 **"读一个 FM + 写一个 FM、靠数据库而不是内存传状态"** 的设计。它的直接后果是——读 FM 辛苦查出来的 `werks`、`lgort`、`eina/brgew` 这些**定位与校验必需的数据，在写 FM 里被全部丢弃**，被迫重新用 `iv_matnr` 盲查 MARC。这正是"写错工厂"风险的来源。正确形态应该是：读 FM 返回带完整键的行，或写 FM 显式接收 `iv_werks/iv_lgort`。

---

## 7. 写数据库专项评审

### 7.1 能否编译

不能。两处硬错误（激活即失败）：

| # | 位置 | 问题 |
|---|---|---|
| C1 | `lzfg_material_pacu01.abap:26` | `lt_desc` 未声明 |
| C2 | `lzfg_material_pacu01.abap:62` | `lcl_helper=>normalise_uom( is_row = ... )` 形参名不存在，应为 `iv_uom` |

`MODIFY marc FROM ls_row.` 缺 WHERE 亦属 Open SQL 非法写法，同样会挡激活。

### 7.2 写在哪、写到多大范围

| 语句 | 表 | 范围 | 判定 |
|---|---|---|---|
| `MODIFY marc FROM ls_row.` | `MARC` | **无 WHERE** → 范围不受限 | 🔴 致命 |
| `UPDATE mard SET mstock = mstock WHERE matnr = iv_matnr.` | `MARD` | 该物料**所有工厂/库存地点/批次** | 🔴 危险 |

### 7.3 正确性风险（即使编译通过也会踩）

1. **写错工厂/库存地点**：`SELECT SINGLE ... WHERE matnr = ?` 命中哪一行不可控 → 修 A 工厂的价格结果写到 B 工厂。
2. **币种被强制改成 USD**：无换算、无校验 → 价格数值与币种不匹配。
3. **部分结构整行写回**：`ty_price_row` 不含全部字段，`MODIFY` 语义下未提供字段会被写成初始值（若能跑通），等于把整条采购信息记录的其余字段清空。
4. **单位归一化未落库**：`ty_price_row` 无 `uom`，`lv_uom` 被丢弃 → "每 EA 净价"口径不成立。
5. **价格无校验**：`is_valid_price` 未调用，负价/异常价可入库；`netpr` 无 `peinh` 配套。
6. **除零**：`eina` 为 0 时 `CX_SY_ZERODIVIPE`（除零 dump）。

### 7.4 一致性与副作用

1. **`MARD-MSTOCK` 无意义写**：绕过库存管理直接改库存数量表，可能引发重估、凭证、变更记录副作用，并污染该物料全部批次的更新时点。
2. **无锁**：并发/RFC 场景下 lost update + 死锁。
3. **无授权检查**：任意调用方均可改任意物料价格。
4. **无变更记录/日志**：价格变动不可审计，而 `gv_user`/`gv_run_date` 被赋值后丢弃。
5. **无事务约定**：`ev_updated` 恒真，调用方无法据此判断成败。

### 7.5 性能与资源

1. **异常路径上的 `FOR ALL ENTRIES` 全表扫**：`MAKT` 很大，判空前先查描述 = 每次"物料无数据"都付一次大表扫描代价。
2. **`makt` 查询完全无效**：`lt_desc` 未传出、未使用，纯负载。
3. **`gt_cache` 无界增长**：`EMPTY KEY` + `APPEND` + 会话驻留，批量场景内存单调增长。
4. `MARC` 按 `matnr` 单条件查（`MARC-PK` 有 MATNR，索引层面尚可），但返回全工厂全库存地点行数无上限。

---

## 8. 问题清单（按严重度）

### 🔴 P0 — 阻断 / 数据损坏

| ID | 位置 | 问题 | 后果 |
|---|---|---|---|
| P0-1 | U01:73 | `MODIFY marc FROM ls_row.` 无 WHERE | 语法非法；修成可执行即全表改写风险 |
| P0-2 | U01:59-60 | `SELECT SINGLE ... WHERE matnr = ?` 无 `werks` | 写错工厂采购信息（业务事故级） |
| P0-3 | U01:71 | `ls_row-waers = gc_cap_currency` 硬编码 `'USD'` | 非美元物料价格被贴美元标签，价格数据损坏 |
| P0-4 | U01:75 | `UPDATE mard SET mstock = mstock` | 污染库存数量/批次、触发重估与无意义变更记录 |
| P0-5 | U01:59-60 + U01:73 | 目标结构 `ty_price_row` 与 `MARC` 不匹配 | 结构不一致 dump；整行写回会清空未提供字段 |

### 🟠 P1 — 编译/运行崩溃

| ID | 位置 | 问题 | 后果 |
|---|---|---|---|
| P1-1 | U01:26 | `lt_desc` 未声明 | 不能激活 |
| P1-2 | U01:62 | 形参名 `is_row` ≠ `iv_uom` | 不能激活 |
| P1-3 | U01:62 | 把 `waers` 当 `uom` 传 | 语义错误 + 隐式截断 |
| P1-4 | U01:64 | `brgew / eina` 无非零校验 | `CX_SY_ZERODIVIDE` |
| P1-5 | U01:37 | 抛 `cx_sy_no_data`，接口声明 `NO_DATA = 1` | 调用方 `EXCEPTIONS no_data` 永不命中，异常逃逸/short dump |

### 🟡 P2 — 设计缺陷 / 性能

| ID | 位置 | 问题 | 后果 |
|---|---|---|---|
| P2-1 | U01:40 / TOP:21 | `gt_cache` `EMPTY KEY` + 只 `APPEND` 不读 | 内存单调增长、无去重、无任何价值 |
| P2-2 | U01:25-29 | `FOR ALL ENTRIES` 在判空之前 | 异常路径触发 `MAKT` 全表扫描 |
| P2-3 | U01:25-29 | `lt_desc` 不传出不使用 | 无效 DB 负载 |
| P2-4 | U01:29 | `spras = '1'` 硬编码，`gv_language` 未用 | 非德语场景描述查不到 |
| P2-5 | TOP:7-17 | `ty_price_row` 缺 `uom`/`peinh`/`einr` | 归一化与价格口径无处落地 |
| P2-6 | U01:66-68 / U01:62 | `lv_weight`、`lv_uom` 算完丢弃 | 重量容差校验形同虚设 |
| P2-7 | U01:39-42 | `lcl_helper=>is_valid_price` 从未被调用 | 价格合法性无任何拦截 |
| P2-8 | 全组 | 无 `authority-check`、无 `enqueue`、无变更记录、无 `sy-subrc` | 安全/并发/可追溯性缺口 |
| P2-9 | U01:77 | `ev_updated` 恒 `abap_true` | 调用方误判成功 |
| P2-10 | U01:20-23 | 只按 `matnr` 过滤，返回全工厂行 | 行数膨胀、调用方无法限定工厂 |

---

## 9. 建议修复方案

### 9.1 分阶段策略

**第一步：止血（防止跑出脏数据）**
1. 删掉 `UPDATE mard SET mstock = mstock` 这一行——它没有任何业务理由。
2. 把 `MODIFY marc FROM ls_row.` 换成带完整键的 `UPDATE marc SET ... WHERE matnr = ? AND werks = ?`。
3. 接口新增 `IMPORTING iv_werks TYPE marc-werks`（必要时 `iv_lgort`），强制调用方指明工厂。
4. 币种不再硬编码：保留 `waers`，或新增 `iv_target_waers` 并走 `TCURR` 汇率换算 + 取整规则。
5. `eina` 非零校验前置；`ev_updated` 按实际更新结果返回。

**第二步：修编译与异常契约**
6. 补 `DATA lt_desc ...`，或直接删除 `makt` 查询（描述没传给调用方，纯浪费）。
7. `normalise_uom( iv_uom = ls_row-uom )`，并在 `ty_price_row` 中新增 `uom TYPE marc-uom`。
8. 异常二选一：接口声明 `EXCEPTIONS no_data = 1` 就 `MESSAGE no_data TYPE 'A'`（或 `RAISE` 已声明的类）；接口声明异常类就把 `NO_DATA = 1` 换成异常类名。

**第三步：修设计**
9. `FOR ALL ENTRIES` 前先判空；或改 `SELECT ... WHERE matnr = @iv_matnr AND spras = @gv_language`（`matnr` 已知，根本不需要 `FOR ALL ENTRIES`）。
10. `gt_cache` 要么改成 `PRIMARY KEY matnr werks lgort` 并用 `INSERT ... ON DUPLICATE` 语义做 upsert，要么直接删除。
11. `spras` 用 `gv_language`（并在 FM 开头赋值 `gv_language = sy-langu`）。
12. 补 `authority-check`、`enqueue_e_marc`、必要的变更记录与日志，把 `gv_user`/`gv_run_date` 真正用起来。
13. 调用 `lcl_helper=>is_valid_price` 或加强它（`<= 0` 判否、加上限）。

### 9.2 参考改法（`z_update_net_price` 骨架）

```abap
FUNCTION z_update_net_price.
  DATA lv_row_found TYPE abap_bool.

  CHECK iv_werks IS NOT INITIAL.

  SELECT SINGLE matnr werks lgort uom eina brgew ntgew netpr waers eifn
    FROM   marc
    INTO   @DATA(ls_row)
    WHERE  matnr = @iv_matnr
      AND  werks = @iv_werks.

  IF sy-subrc <> 0.
    RAISE EXCEPTION TYPE cx_sy_no_data.
  ENDIF.

  IF ls_row-eina <= 0.
    RAISE EXCEPTION TYPE cx_sy_no_data.   " 或业务异常：采购单位数量非法
  ENDIF.

  IF NOT lcl_helper=>is_valid_price( is_row = ls_row-netpr ).  " 需相应调整方法签名
    RAISE EXCEPTION TYPE cx_sy_no_data.
  ENDIF.

  DATA(lv_uom) = lcl_helper=>normalise_uom( iv_uom = ls_row-uom ).

  DATA(lv_weight) = ls_row-brgew / ls_row-eina.
  IF lv_weight > gc_weight_tol.
    MESSAGE e001(zfg_material_price) WITH iv_matnr iv_werks.   " 超出重量容差，先提示
  ENDIF.

  CALL FUNCTION 'ENQUEUE_E_MARC'
    EXPORTING   matnr = iv_matnr werks = iv_werks
    EXCEPTIONS  lock_is_active = 1.
  IF sy-subrc = 1.
    RAISE EXCEPTION TYPE cx_sy_no_data.
  ENDIF.

  UPDATE marc SET netpr = @iv_netpr waers = @iv_waers
    WHERE matnr = @iv_matnr AND werks = @iv_werks.

  ev_updated = COND #( WHEN sy-subrc = 0 THEN abap_true ELSE abap_false ).

  CALL FUNCTION 'DEQUEUE_E_MARC'
    EXPORTING matnr = iv_matnr werks = iv_werks.
ENDFUNCTION.
```

要点：只 `UPDATE` 需要的字段、键完整、带锁、`ev_updated` 反映真实结果、币种来自参数而非常量、单位归一化结果落到 `uom`。

---

## 10. 验证与测试要点

修复后至少覆盖：

1. **多工厂物料**：同一 `MATNR` 在 WERKS A/B/C 都有 `MARC` 行，验证只改到指定工厂（改前留 `MARC-NETPR` 快照对比）。
2. **币种**：EUR 物料传入净价，验证 `WAERS` 未被改成 `USD`；若要求换算，比对 `TCURR` 结果与取整位。
3. **除零**：`EINA` = 0 / 初始的物料，验证抛业务异常而非 dump。
4. **非法价格**：`NETPR` = 0、负数、超过价格上限，验证被 `is_valid_price` 拦截。
5. **无数据路径**：不存在的物料，验证 `FOR ALL ENTRIES` 之前就判空（用 ST05/STAD 确认没有全表扫描）且 `EXCEPTIONS no_data` 真的能被调用方捕获。
6. **`MARD` 副作用**：改价前后用 `MARD` 的更新时点/变更记录确认 `MSTOCK` 无变更时间戳推进。
7. **缓存**：同一会话内重复调用读 FM，用内存快照确认 `gt_cache` 不重复膨胀。
8. **并发**：两个会话同时改同一 `MATNR/WERKS`，验证锁生效、无丢失更新、无死锁。
9. **权限**：无权限用户调用写 FM，验证被 `authority-check` 拒绝。

---

## 11. 待确认事项

1. `lzfg_material_pacuxx` 里是否还有 `U02+` 定义了其他 FM（未提供源文件，本报告只覆盖 U01 的两个 FM）。
2. 该函数组是否 RFC 启用？若启用，则 §5.3 的并发/授权缺口优先级进一步上升（RFC 可被远程非交互调用）。
3. `gv_language` 的设计意图是否为"跟随用户语言读描述"？若是，则 `spras = '1'` 是待修 bug；若是"固定德语"，则 `gv_language` 应删除。
4. `gc_cap_currency = 'USD'` 是刻意的集团政策（统一美元记账）还是笔误？若为政策，必须补汇率换算与取整规则，不能直接改 `WAERS`。
5. `gc_weight_tol = 0.5` 的业务口径：每个采购单位的毛重上限？单位是什么？超过后是截断还是报错？当前实现是"截断但丢弃"。

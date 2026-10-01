# ZFG_MATERIAL_PRICE 函数组走读报告

分析对象：`zfg_material_price.fg.abap`（主程序）、`lzfg_material_pacetop.abap`（全局定义）、`lzfg_material_pacu01.abap`（两个 FM 实现）。

**一句话结论**：这个函数组的意图是"读采购视图 + 按物料改净价"。读的那一半有编译级缺陷、内存泄漏和异常契约错配；写的那一半问题更重——它对 `MARC` 做 `SELECT SINGLE *` 读进一个非 `MARC` 结构体、基于这个结果做整行 `MODIFY`、无条件把币种改成 `USD`、无条件返回 `abap_true`，并且中间还有一个必然可以触发的除零。**数据库写入部分不能上线**。

---

## 1. 骨架：谁包含谁

```abap
FUNCTION-POOL zfg_material_price.

*"*" use this source for any type of program (pool)
*"*"   function group ZFG_MATERIAL_PRICE

  INCLUDE lzfg_material_pacetop.    "session data, type declarations
  INCLUDE lzfg_material_pacuxx.    "function implementations

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

| Include | 实际内容 | 主程序是否 INCLUDE | 说明 |
| --- | --- | --- | --- |
| `lzfg_material_pacetop` | 类型、全局 DATA、CONSTANTS | 是 | 常规 TOP |
| `lzfg_material_pacuxx` | 未知（源码里没有） | 是 | 注释写的是 "function implementations" |
| `lzfg_material_pacu01` | **两个 FM 的全部实现** | **否** | 关键缺陷，见下 |

**结构性问题 A：主程序没有 INCLUDE U01。** `zfg_material_price.fg.abap:12-13` 只 include 了 TOP 和 UXX，而 `Z_READ_PRICE_ROWS` / `Z_UPDATE_NET_PRICE` 的实现全部位于 `lzfg_material_pacu01.abap`。两处注释互相矛盾——主程序说 UXX 是 "function implementations"，而 U01 自己的头部说自己是 "Function module implementations"。如果 UXX 里没有再 include U01，这个函数组**一个函数模块都不存在**，SE37 里查不到，调用方直接 SYNTAX/function not found。这是落地前第一件要确认的事（`SE37` → ZFG_MATERIAL_PRICE → F4 激活，或直接看 UXX 源码）。

**结构性问题 B：本地类定义位置。** `lcl_helper` 定义在主程序的 INCLUDE 之后，而使用它的 `lzfg_material_pacu01.abap:62` 位于更早被 include 的代码里。ABAP 允许同一程序内的类前向引用，但把类塞在主程序尾部、再由各 Uxx 反向引用是脆弱写法——一旦 U01 真的被 include 到 TOP 之后就会变成"类未定义"类错误。建议独立成 `lcl_helper` 的 class include，或直接挪进 TOP。

**结构性问题 C：函数组未声明 RFC 可用性。** 源码里看不到 `SE37` 属性。两个 FM 里有直接数据库写入，如果外部是通过 `CALL FUNCTION ... IN BACKGROUND DESTINATION` 或 `IN UPDATE TASK` 调用，FM 必须是 remote-enabled，否则后台/远程调用不可用。`UPDATE`/`MODIFY` 在 update task 里是允许的，但直接写表这件事本身就该有明确的使用场景约束（见第 6 节）。

---

## 2. TOP：全局状态与常量

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

TYPES ty_price_rows TYPE STANDARD TABLE OF ty_price_row WITH EMPTY KEY.

DATA: gt_cache    TYPE ty_price_rows,
      gv_run_date TYPE datum,
      gv_user     TYPE sy-uname,
      gv_language TYPE sy-langu.

CONSTANTS gc_weight_tol TYPE p DECIMALS 4 VALUE '0.5'.
CONSTANTS gc_cap_currency TYPE c LENGTH 3 VALUE 'USD'.
```

- **`ty_price_row` 是一个 9 字段的扁平投影**，刻意只挑了"业务看得懂的"列。`mara-eina/brgew/ntgew` 从 `MARA` 取类型，但这些字段在 `MARC` 上确实也存在（引用字段），所以 SELECT 时从 `MARC` 读它们是合法的——只是说明这个结构体是一个**手工维护的"业务视图"**，不是任何一张表的行结构。这一点是后面写库出事的根因。
- **`ty_price_rows ... WITH EMPTY KEY`**：无键表。追加 O(1) 没问题，但一旦想"去重"或"按 key 查"只能全表扫描。作为"缓存"容器，这个 key 设计直接决定它没法被真正用起来。
- **`gt_cache`**：只在 `z_read_price_rows` 末尾被 `APPEND`，**在整个函数组里从未被读取过一次**。名字叫 cache，实际是只写的内存垃圾桶。
- **`gv_run_date` / `gv_user`**：在读 FM 里赋值，全函数组无任何读取点。看不出意图（大概是想写变更凭证或打时间戳），实际效果是零。
- **`gv_language`**：声明为 `sy-langu` 但**从未被赋值**，而读 FM 里语言条件是硬编码 `'1'`。两个变量各说各话。
- **`gc_weight_tol = 0.5`（P DECIMALS 4）** 和 **`gc_cap_currency = 'USD'`** 是常量写死的：容差不可配置，币种不可配置，且对所有物料、所有公司代码统一生效。

---

## 3. FM 之一：`Z_READ_PRICE_ROWS`

**职责（设计意图）**：按物料号读出所有 `MARC` 行（含价格、重量、币种、库存地点），顺带取物料描述，命中 0 行就报"无数据"。

**接口**：

```abap
FUNCTION z_read_price_rows.
  IMPORTING VALUE(IV_MATNR) TYPE MARA-MATNR
  TABLES        IT_ROWS    TYPE ZFG_MATERIAL_PRICE=>TY_PRICE_ROWS
  EXCEPTIONS    NO_DATA    1
```

逐段走读：

```abap
  DATA lv_count TYPE i.

  SELECT matnr werks lgort eina brgew ntgew netpr waers eifn
    FROM marc
    INTO TABLE it_rows
    WHERE matnr = iv_matnr.

  SELECT maktx FROM makt
    INTO TABLE lt_desc
    FOR ALL ENTRIES IN it_rows
    WHERE matnr = it_rows-matnr
      AND spras = '1'.

  lv_count = lines( it_rows ).

  gv_run_date = sy-datum.
  gv_user     = sy-uname.

  IF lv_count = 0.
    RAISE EXCEPTION TYPE cx_sy_no_data.
  ENDIF.

  APPEND LINES OF it_rows TO gt_cache.
```

### 问题清单

| 编号 | 位置 | 问题 | 后果 |
| --- | --- | --- | --- |
| R-1 | `:25-29` | **`lt_desc` 全文没有任何 DATA 声明**，既不是 FM 接口参数，也不在 TOP 的全局 DATA 里 | 编译错误，整个函数组无法激活 |
| R-2 | `:25-29` | 查了 `maktx` 之后**结果既没返回给调用方，也没被使用** | 纯粹的死查询成本；`FOR ALL ENTRIES` 在 `MARC` 有 N 个库存地点时会放大成 N 次匹配 |
| R-3 | `:29` | 语言硬编码 `spras = '1'`（德语），而 `gv_language` 存在却没赋值 | 只取德语描述；要么调用方拿不到描述，要么将来接了 `gv_language` 却仍然读德语 |
| R-4 | `:31-38` | **先查 `MAKT` 再判空**。`lv_count = 0` 的判断排在两个 SELECT 之后 | 物料不存在时白跑一次 `MAKT` 读；`FOR ALL ENTRIES` 拿到空内表 |
| R-5 | `:36-38` | 声明了 `EXCEPTIONS no_data`，实际抛的是 `RAISE EXCEPTION TYPE cx_sy_no_data` | **两套异常机制混用**。调用方写 `EXCEPTIONS no_data` 捕不到 `CX_SY_NO_DATA`；`CX_` 类异常也不在 `EXCEPTIONS` 列表里，调用方只能 `CATCH cx_sy_no_data` 或直接吃 short dump。异常契约等于不存在 |
| R-6 | `:40` | `APPEND LINES OF it_rows TO gt_cache`，`gt_cache` 从不清空、不去重 | 同一 dialog step 内每次调用都往会话内表里追加一遍，**第 n 次调用内存里堆 n 份数据**；且这份数据永远不会被读 |
| R-7 | `:13` | 用 `TABLES` 传内表 | 语义过时（真实传表、非引用语义），与 `:59` 混用新旧语法；建议 `it_rows TYPE ty_price_rows` |
| R-8 | 全 FM | `gv_run_date` / `gv_user` 赋值后无人读取 | 死代码，说明审计意图（打时间戳/用户）没有落地 |
| R-9 | `:20-23` | 无 `ORDER BY`、无 `LOCK`、无 `INTO @DATA` 新语法 | 结果行序不确定；后续任何"取第一条"的逻辑都会不稳定 |

### 一个容易被忽略的业务点

`MARC` 的主键是 `MATNR + WERKS + LGORT`，**一个物料通常有多个工厂 / 多个库存地点**，也就是 `z_read_price_rows` 会返回多行价格。返回给调用方是合理的，但调用方如果直接取第一行当"这个物料的价格"，就隐含了一个错误假设。这个假设在写 FM 里被放大了（见下一节）。

---

## 4. FM 之二：`Z_UPDATE_NET_PRICE`

**职责（设计意图）**：按物料号改净价；改之前做"单位归一 + 重量合理性"校验；改完顺便刷一下库存。

**接口**：

```abap
FUNCTION z_update_net_price.
  IMPORTING VALUE(IV_MATNR) TYPE MARA-MATNR
           VALUE(IV_NETPR) TYPE MARC-NETPR
  EXPORTING VALUE(EV_UPDATED) TYPE ABAP_BOOL
```

逐段走读：

```abap
  DATA ls_row    TYPE ty_price_row.
  DATA lv_uom    TYPE marc-uom.
  DATA lv_weight TYPE p DECIMALS 4.

  SELECT SINGLE * FROM marc INTO @ls_row
    WHERE matnr = iv_matnr.

  lv_uom = lcl_helper=>normalise_uom( is_row = ls_row-waers ).

  lv_weight = ls_row-brgew / ls_row-eina.

  IF lv_weight > gc_weight_tol.
    lv_weight = gc_weight_tol.
  ENDIF.

  ls_row-netpr = iv_netpr.
  ls_row-waers = gc_cap_currency.

  MODIFY marc FROM ls_row.

  UPDATE mard SET mstock = mstock WHERE matnr = iv_matnr.

  ev_updated = abap_true.
```

### 问题清单

| 编号 | 位置 | 问题 | 后果 |
| --- | --- | --- | --- |
| W-1 | `:59-60` | **`SELECT SINGLE * FROM marc INTO @ls_row`，而 `ls_row` 是 `ty_price_row`（9 字段投影），不是 MARC 行结构**。`SELECT ... *` 要求目标与表结构兼容 | 编译期就应报"目标结构不兼容"；即使绕过，`MODIFY marc FROM ls_row` 也类型不匹配。**这是整个写库逻辑的地基塌陷** |
| W-2 | `:62` | `normalise_uom` 的形参是 `iv_uom TYPE marc-uom`，这里却用具名实参 `is_row =` 传，并且**传的值是 `ls_row-waers`（币种字段）** | ① 形参名不匹配 → 形参未赋值；② 即使对上，也是把**币种**当**计量单位**传。字段串位 + 语义串位双重错误 |
| W-3 | `:64` | `ls_row-brgew / ls_row-eina`：基准重量除以 **EAN 码** | ① `eina = 0`（绝大多数无 GTIN 的物料）→ **`CX_SY_ZERODIVIDE` short dump**；② 公式本身在业务上无意义 |
| W-4 | `:57` + W-3 | `lv_weight TYPE p DECIMALS 4`（默认长度 8 → 上限 999999.9999），而 `MARA-BRGEW` 是 `QUAN(13,3)` | `brgew = 1000000`、`eina = 1`（EAN 为 1 是真实存在的）→ 赋值溢出 → `CX_SY_CONVERSION_NO_NUMBER`。**除零和溢出两条 dump 路径都通** |
| W-5 | `:66-68` | 算出的 `lv_weight` **算完就丢**。既不比较门限后返回错误，也不写消息 | 所谓的"重量校验"是纯粹的空转。即使它算对了也**不阻止任何写操作** |
| W-6 | `:62` | 算出的 `lv_uom` **同样算完就丢**，且 `MARC` 根本没有"每 EAN 的计量单位"字段（那在 `MARM` 里：`MARM-EANR` / `MARM-UOM`） | 单位归一化对结果零影响；想按 EA 定价却查错了表 |
| W-7 | `:71` | `ls_row-waers = gc_cap_currency`（硬编码 `'USD'`），**无参数、无判断、无消息** | **静默币种篡改**：传进来一个 EUR 价格，写库时被贴上 USD 标签。金额不变、币种变错，是最难被发现的一类数据损坏 |
| W-8 | `:70` | `iv_netpr` **零校验**直接赋值。`lcl_helper=>is_valid_price` 存在但**全函数组从未被调用** | 负价、0 价、超长值、非法价格单位全部照写不误。校验钩子写了不用，是最典型的"半成品上线" |
| W-9 | `:73` | `MODIFY marc FROM ls_row`，`:59` 的 `SELECT SINGLE` 只有 `matnr` 一个条件 | `MARC` 主键是 `MATNR+WERKS+LGORT`，`SELECT SINGLE` 按 MATNR 命中多行时**结果不确定**。于是"改这个物料的价格"变成"随机改某一个工厂/库存地点的价格" |
| W-10 | `:59` + `:73` | 典型 **`SELECT *` + `MODIFY` 丢更新反模式**：即便把 `ls_row` 改成真正的 `MARC` 结构，也会在"读—算—写"窗口内把**别人并发改过的所有字段一起覆盖回旧值**。`MARC` 有 400+ 字段 | 丢失更新，影响面远超 `NETPR` 一个字段。应改为**带 WHERE 的 `UPDATE`**，只碰 `NETPR`/`WAERS` |
| W-11 | `:73` | `MODIFY` 后**不检查 `sy-subrc`** | 物料不存在 / 0 行命中时不报错，直接往下走 |
| W-12 | `:75` | **`UPDATE mard SET mstock = mstock WHERE matnr = iv_matnr`** —— 把字段赋给它自己 | ① 什么也没改；② 仍然付出一次 `MARD` 的 DB 往返（该表行数极大）；③ 仍可能触发变更文档、STXL、更新任务日志等副作用。若目的是"让净价重新生效"，那这是**没有依据的民间偏方**：SAP 里价格生效由 `EINE-NETPR_D` 的有效期/价格确定逻辑控制，碰 `MSTOCK` 不会刷新任何东西 |
| W-13 | `:75` | `MARD` 主键是 `MATNR+LGORT`，`WHERE matnr = ?` 会**扫全部库存地点行** | 即使是空操作，代价也是全库存地点级别 |
| W-14 | `:77` | `ev_updated = abap_true` **无条件赋值**，且 FM **没有任何 `EXCEPTIONS`** | 调用方拿到"成功"却可能一行都没改（物料不存在、MODIFY 0 行、更新被拒）。失败既不报错也不回传，只有 dump 路径能暴露问题 |
| W-15 | 全 FM | **无 `AUTHORITY-CHECK`** | 任何能进入该 dialog step 的用户都能改净价。价格直接进采购成本，这是财务敏感字段 |
| W-16 | 全 FM | **无任何 enqueue / lock**（`SET LOCK` / E_TABLE 锁） | 并发改价静默互相覆盖；也可能在别的 MM 事务持有该记录时互相破坏 |
| W-17 | 全 FM | 无 `COMMIT WORK` | 写入留在调用方的 LUW 里，由调用方提交。对 `IN UPDATE TASK` 场景是正确行为，但需要在文档里写明调用契约，否则容易被人以为已经落库 |
| W-18 | `:59` | `SELECT SINGLE` 后不查 `sy-subrc` | 物料不存在 → `ls_row` 全 initial → `eina = 0` → 又回到 W-3 的除零 dump。**"不存在的物料"不是干净报错，是 dump** |
| W-19 | 全 FM | 直接写 `MARC`，绕过 MM 应用层 | 跳过所有一致性检查、消息、凭证流；如果客户已切到 `EINE`/`EINF` 采购信息记录（现代价格确定），手写 `MARC-NETPR` 可能**根本不参与价格计算** |

---

## 5. 数据怎么流转

```text
                      ┌──────────────────────────────────────────┐
   调用方 ──CALL────> │ Z_READ_PRICE_ROWS                        │
                      └──────────────────────────────────────────┘
  iv_matnr ──────────────────────────────> SELECT ... FROM marc  ──> it_rows ──> 调用方(TABLES)
                                              │  0..N 行            │
                                              │                     └──> APPEND ──> gt_cache  (只写，永不读)
                                              v
                                    SELECT ... FROM makt FOR ALL ENTRIES  ──> lt_desc  (未声明 / 不返回 / 不用)
                                              │
                                    lines(it_rows) = 0 ?
                                              │ 是
                                              v
                                    RAISE EXCEPTION TYPE cx_sy_no_data   ← 与 EXCEPTIONS no_data 不匹配
  ───────────────────────────────────────────────────────────────────────────────

                      ┌──────────────────────────────────────────┐
   调用方 ──CALL────> │ Z_UPDATE_NET_PRICE                       │
                      └──────────────────────────────────────────┘
  iv_matnr, iv_netpr ──> SELECT SINGLE * FROM marc WHERE matnr  ──> ls_row (类型不匹配/不确定行)
                                              │
                                              ├─> lcl_helper=>normalise_uom(is_row = waers) ──> lv_uom   [算完丢弃]
                                              ├─> lv_weight = brgew / eina                ──> [可能被 cap]
                                              │                                                    [算完丢弃]
                                              ├─> ls_row-netpr = iv_netpr   (无校验)
                                              ├─> ls_row-waers = 'USD'     (无判断)
                                              │
                              MODIFY marc FROM ls_row     <── 写库点 1：整行、结构不匹配、无 subrc
                              UPDATE mard SET mstock=mstock WHERE matnr  <── 写库点 2：空操作
                                              │
                              ev_updated = abap_true        <── 无条件"成功"
```

**两条链路的交叉问题**

1. **读写不共享事务/锁**：读和写是两个独立 FM，之间没有任何版本号、时戳或锁的保护。典型 TOCTOU——读时看到的价格在校验之后、写入之前可能已被人改掉。
2. **读写字段集不一致**：读返回 `matnr werks lgort eina brgew ntgew netpr waers eifn`，写只用 `matnr` 定位。读回来的 `werks`/`lgort` 定位信息在写路径里被完全丢弃，这正是 W-9 不确定性的来源。
3. **校验横跨两个 FM 却无处落地**：`is_valid_price` 在 helper 类里，`lv_weight` 在写 FM 里，两者都不影响写库结果，也没有异常出口。**当前实现里"校验"和"写库"是解耦的，写库不会因为校验失败而被拦下。**
4. **审计信息断链**：`gv_user` / `gv_run_date` 在读 FM 采集，却没在写 FM 使用——写库动作没有任何"谁在什么时候改的"痕迹（除了可能的表级变更文档兜底）。

---

## 6. 数据库写入：结论是"有，而且比较严重"

把写库相关问题按上线阻断程度分三级。

### P0 — 阻断上线（当前状态下 FM 无法正确执行）

1. **`SELECT SINGLE *` 目标结构不匹配**（`lzfg_material_pacu01.abap:59-60`）。`ty_price_row` 不是 `MARC` 行结构，整条读写链路的类型基础就是错的。**这一条不修，后面所有讨论都无从谈起。**
2. **`MODIFY marc FROM <非 MARC 结构>`**（`:73`）。字段不全、key 不明确、无 `sy-subrc`。这是会写坏主数据的语句形态。
3. **除零 / 溢出 dump**（`:64`）。`brgew / eina`，`eina = 0` 或 `eina = 1 && brgew > 999999` 都是真实数据形态，且没有 `TRY/CATCH`。
4. **无条件改币种为 USD**（`:71`）。财务数据静默损坏，用户不会收到任何提示。
5. **无条件返回 `ev_updated = abap_true`**（`:77`）。0 行命中也算成功，调用方无法判断，且 FM 无任何 `EXCEPTIONS`。

### P1 — 数据正确性与一致性

6. **`SELECT SINGLE` 只按 MATNR 命中多行**（`:59`）→ 改到哪个工厂/库存地点是随机的。
7. **`SELECT *` + `MODIFY` 丢更新**（`:59`/`:73`）→ 并发下覆盖他人改动，影响 `MARC` 全部 400+ 字段，不止 `NETPR`。
8. **`UPDATE mard SET mstock = mstock`**（`:75`）→ 零收益的写库，代价是全库存地点扫描 + 副作用。**建议直接删除**，而不是"留着以防万一"。
9. **无授权检查** → 价格字段可被任意越权修改。
10. **无锁** → 并发改价互相覆盖。
11. **绕过 MM 应用层直写 `MARC`** → 无一致性校验/无消息/无凭证；在使用 `EINE` 采购信息记录的客户系统上可能根本不生效。

### P2 — 正确但粗糙

12. `ev_updated` 未在入口初始化；无异常出口（`no_data` / `validation_failed` / `not_permitted` 都缺）。
13. `is_valid_price` 存在但从未调用；`iv_netpr` 负值/0/单位/长度全无校验。
14. `lv_uom` / `lv_weight` 算完丢弃；`normalise_uom` 的具名实参 `is_row` 与形参 `iv_uom` 不匹配。
15. `spras = '1'` 硬编码，`gv_language` 声明未用。
16. `gv_user` / `gv_run_date` 采集了但没用于写库审计。

### 修法建议

定位（`MARC` 是 `MATNR + WERKS + LGORT` 的主键，FM 接口缺工厂/库存地点，所以必须么补参数、么明确"按 MATNR 批量改"的语义）：

```abap
FUNCTION z_update_net_price.
  IMPORTING VALUE(IV_MATNR) TYPE mara-matnr
           VALUE(IV_WERKS) TYPE marc-werks
           VALUE(IV_LGORT) TYPE marc-lgort
           VALUE(IV_NETPR) TYPE marc-netpr
           VALUE(IV_WAERS) TYPE marc-waers
  EXPORTING VALUE(EV_UPDATED) TYPE abap_bool
  EXCEPTIONS not_found not_permitted validation_failed sy_subrc_error.

  DATA lv_subrc TYPE sy-subrc.

  AUTHORITY-CHECK OBJECT ...
  IF sy-subrc <> 0.
    RAISE EXCEPTION not_permitted.
  ENDIF.

  " 只读需要的字段，绝不 SELECT *
  SELECT netpr waers brgew eina
    FROM marc
    WHERE matnr = iv_matnr AND werks = iv_werks AND lgort = iv_lgort
    INTO @DATA(ls_net)
    UP TO 1 ROWS.

  IF sy-subrc <> 0.
    RAISE EXCEPTION not_found.
  ENDIF.

  " 校验必须能拦住写库
  IF iv_netpr <= 0.
    MESSAGE e000(zfg_material_price) WITH iv_matnr.
    RAISE EXCEPTION validation_failed.
  ENDIF.

  IF ls_net-waers <> iv_waers.
    MESSAGE w000(zfg_material_price) WITH ls_net-waers iv_waers.
    RAISE EXCEPTION validation_failed.
  ENDIF.

  " 只更新目标字段 + 锁 + 检查 sy-subrc
  CALL FUNCTION 'LOCK_TABLE' ...  " 或 SET LOCK OBJECT marc WITH ...
  UPDATE marc SET netpr = @iv_netpr
    WHERE matnr = @iv_matnr AND werks = @iv_werks AND lgort = @iv_lgort.
  lv_subrc = sy-subrc.
  IF lv_subrc <> 0.
    RAISE EXCEPTION sy_subrc_error.
  ENDIF.

  ev_updated = abap_true.
ENDFUNCTION.
```

读 FM 的最小修正：

```abap
FUNCTION z_read_price_rows.
  IMPORTING VALUE(IV_MATNR) TYPE mara-matnr
  EXPORTING VALUE(ET_ROWS) TYPE ty_price_rows
  EXCEPTIONS no_data.

  gv_language = sy-langu.
  gv_user     = sy-uname.
  gv_run_date = sy-datum.

  SELECT matnr werks lgort eina brgew ntgew netpr waers eifn
    FROM marc
    WHERE matnr = @iv_matnr
    ORDER BY werks lgort
    INTO TABLE @et_rows.

  IF et_rows IS INITIAL.
    RAISE EXCEPTION no_data.
  ENDIF.
ENDFUNCTION.
```

（`lt_desc` 要么删掉，要么加进接口作为 `et_texts`，并用 `gv_language` 而不是 `'1'`；`gt_cache` 若不是真被读，就删掉它和 `gv_*` 三个全局变量。）

---

## 7. 横切问题小结

| 类别 | 现状 |
| --- | --- |
| 编译可用性 | `lt_desc` 未声明；主程序未 INCLUDE U01。**函数组大概率根本无法激活。** |
| 异常契约 | `EXCEPTIONS no_data` 与 `RAISE EXCEPTION TYPE cx_sy_no_data` 混用；写 FM 无异常 |
| 死代码 | `gt_cache`（只写）、`gv_user`/`gv_run_date`/`gv_language`（只写不读）、`is_valid_price`（从未调用）、`lv_uom`/`lv_weight`（算完丢弃）、`UPDATE mard ... = mstock`（空操作） |
| 安全 | 无 `AUTHORITY-CHECK`、无 enqueue |
| 审计 | 采集了 user/date 却没用于写库痕迹 |
| 错误可见性 | 全程无 `MESSAGE`、无 `sy-msgid`，失败只能靠 dump 暴露 |
| 域建模 | 想按 EA 定价却只查 `MARC`（没有 EAN→UOM 映射，那在 `MARM`）；重量校验除以 EAN 码；写 `MARC-NETPR` 而非 `EINE` 有效期价格 |
| 版本/接口 | `TABLES` 与新语法混用；FM 是否 remote-enabled 未确认 |

---

## 8. 建议的处置顺序

1. **确认 U01 是否真的被包含**（`SE37` 或看 UXX 源码）。这一步没结论，后面都是空谈。
2. **补声明、让它先能激活**：`lt_desc` 要么删要么加进接口；主程序 INCLUDE 链补齐。
3. **重写写 FM 的库操作**：`SELECT` 指定字段 + 补 `WERKS`/`LGORT` 定位条件 → `UPDATE ... SET netpr` 取代 `MODIFY` → 检查 `sy-subrc` → 加 `EXCEPTIONS` → 删除 `UPDATE mard`。
4. **补校验与授权**：把 `is_valid_price` 真正接进调用路径（净价 > 0、币种一致、单位归一后可比），加 `AUTHORITY-CHECK` 和 enqueue。
5. **币种参数化**：`gc_cap_currency` 从常量改成入参或从价格主数据读取，删掉无条件覆盖。
6. **清理死代码**：`gt_cache` / `gv_*` / `lv_uom` / `lv_weight` —— 要么接上消费方，要么删掉。留着只会让下一个人以为"缓存是有效的"。
7. **业务确认**：这个价格到底是 `MARC-NETPR`（旧式 4.5 视图）还是 `EINE` 采购信息记录（带供应商 + 有效期）？直写 `MARC` 在现代 MM 场景下很可能不参与价格确定——这是需求层面的问题，不是代码能修的。

---

## 9. 需要向业务/开发确认的开放问题

- `lzfg_material_pacuxx` 里到底有没有 `INCLUDE lzfg_material_pacu01.`？（决定函数组是否为空壳）
- `eina` 在这个程序里被当作"分母"使用，是原作者的真实业务含义，还是从别处复制的公式？（从代码看是没有意义的）
- `gc_cap_currency = 'USD'` 是刻意的"统一折成美元"策略，还是临时硬编码？如果是前者，折算逻辑和汇率来源在哪里？（当前代码里没有任何折算）
- 调用方是谁？同系统 dialog/后台 update task，还是 RFC 远程？如果是后者，FM 的 RFC 属性必须补上。
- `MSTOCK` 那条 `UPDATE` 是谁加的、为什么？（看起来是为了"让价格生效"，但机制上不成立）

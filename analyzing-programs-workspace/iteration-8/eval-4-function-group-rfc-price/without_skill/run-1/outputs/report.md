# 函数组 ZFG_MATERIAL_PRICE 代码走读报告

> 分析对象：`ZFG_MATERIAL_PRICE.fg.abap`（主程序 FUNCTION-POOL）、`lzfg_material_pacetop.abap`（TOP）、`lzfg_material_pacu01.abap`（两个 FM 实现）
> 归属（据注释）：MM Purchasing，业务定位「purchasing infos 的价格/重量维护」
> 走读重点：两个 FM 的职责、数据流转、数据库写入逻辑与风险

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 两个 FM 之间**没有**调用关系 | `Z_READ_PRICE_ROWS` 写入的 `gt_cache` 从未被读取；写入 FM 自己重新 `SELECT`，不依赖读 FM |
| 写库逻辑 | **有严重问题**。存在 P0 级：写入目标工厂不确定、货币被硬编码覆盖、只改派生字段不同步主记录、`UPDATE mard SET mstock = mstock` 无意义热写、两个 DB 写非原子、无行锁无 `sy-subrc` 判断、`ev_updated` 恒为真 |
| 能否激活 | **按字面写法无法通过激活**：2 处硬性错误（`lt_desc` 未声明、`normalise_uom` 实参名不匹配），另有 1 处结构疑点（U01 未被主程序 INCLUDE） |
| 整体设计 | 典型的「接口形状决定风险」：写 FM 的 `IMPORTING` 里**没有 `IV_WERKS`**，从签名上就无法定位到正确的 MARC 行，这是所有写入缺陷的根因 |

风险分级约定：**P0** = 会造成生产数据错误/脏数据或必然 dump；**P1** = 结果不可信、无法追溯、审计缺失；**P2** = 可维护性、性能、死代码。

---

## 1. 结构与组件

```
ZFG_MATERIAL_PRICE (FUNCTION-POOL 主程序)
│
├── INCLUDE lzfg_material_pacetop   → 全局类型/变量/常量
├── INCLUDE lzfg_material_pacuxx    → 注释称 "function implementations"（本次未提供）
│
├── CLASS lcl_helper DEFINITION/IMPLEMENTATION
│     ├── normalise_uom  (UOM 归一)
│     └── is_valid_price (价格有效性)
│
└── （FM 实现位于 lzfg_material_pacu01）
      ├── FUNCTION z_read_price_rows
      └── FUNCTION z_update_net_price
```

**结构层面的三个疑点（需要人工核实）**

1. **U01 没有被主程序 INCLUDE。** 主程序只 `INCLUDE` 了 `pacuxx`，而两个 FM 的实现在 `pacu01`。函数组的 FM 实现通常在主程序里被 `INCLUDE`（或直接写在主程序中）才会被编译；若 `LZFG_MATERIAL_PACU01` 确实不在主程序 `INCLUDE` 列表中，这两个 FM 根本不存在。建议在 SE80 展开 `LZFG_MATERIAL_PRICE` 的 include 列表确认真实结构。
2. **include 命名不合 SAP 惯例。** 函数组的标准 include 序列是 `LZG…TOP` + `LZG…U01…U05`（用户自定义区）+ `LZG…F01/F02…`（每个 FM 一个）。FM 实现放在 `U01` 里属手工改造，可能是从程序 `ZM…` 直接搬过来的残留。
3. **把复用逻辑放在函数组里。** `lcl_helper` 是可复用逻辑却挂在函数组主程序下（`PUBLIC SECTION` 实际只是「组内全局」），既不能被别处调用，也不能作为对象单独测试。合理位置是 SE24 全局类或独立 include。

---

## 2. TOP：全局数据结构与常量

```abap
TYPES: BEGIN OF ty_price_row,
         matnr   TYPE mara-matnr,   " 物料号
         werks   TYPE marc-werks,   " 工厂
         lgort   TYPE marc-lgort,   " 库存地点
         eina    TYPE mara-eina,    " 订货单位
         brgew   TYPE mara-brgew,   " 毛重
         ntgew   TYPE mara-ntgew,   " 净重
         netpr   TYPE marc-netpr,   " 采购净价
         waers   TYPE marc-waers,   " 价格货币
         eifn    TYPE marc-eifn,    " 采购信息记录号
       END OF ty_price_row.

TYPES ty_price_rows TYPE STANDARD TABLE OF ty_price_row WITH EMPTY KEY.

DATA: gt_cache    TYPE ty_price_rows,
      gv_run_date TYPE datum,
      gv_user     TYPE sy-uname,
      gv_language TYPE sy-langu.

CONSTANTS gc_weight_tol  TYPE p DECIMALS 4 VALUE '0.5'.
CONSTANTS gc_cap_currency TYPE c LENGTH 3 VALUE 'USD'.
```

**要点**

- **类型是 MARA 与 MARC 的混合切片。** `netpr/waers/eifn/werks/lgort` 是 MARC 字段；`brgew/ntgew/eina` 在结构里显式声明为 `mara-*`，说明作者认为重量和订货单位在 **MARA**。但 U01 的 `SELECT` 只从 **MARC** 取这 9 列。这是一处**内部自相矛盾**：`MARC` 通常不含 `BRGEW/NTGEW`（重量属物料主数据 MARA）。若确实不含，则 `SELECT` 会激活失败；若本地 DDIC 扩展过 MARC，读到的也与重量口径不同。**必须用 SE11 → MARC 字段列表核实这一列是否真实存在**，不要凭字段名推断。
- `WITH EMPTY KEY` 意味着内表**没有主键也没有次键**。后果：不能作为 `MODIFY … FROM TABLE` / `INSERT … FROM TABLE` 的目标（这些语句需要键），也无法用 `WHERE` 定位单条；只能整体追加。目前确实只被整体 `APPEND`，所以还没爆，但这是后续改造时的隐形地雷。
- `gt_cache` 是函数组的会话级全局变量，**只写不读、无上限、无清理**（见 §7.3）。
- `gv_language` 声明后**从未被赋值也从未使用**。
- `gc_weight_tol = 0.5`、`gc_cap_currency = 'USD'` 硬编码在 Z 对象里，客户端无法通过配置调整（`USD` 尤其危险，见 §5.2）。

---

## 3. FM 之一：`Z_READ_PRICE_ROWS` 职责与走读

**接口（据 Local Interface 注释）**

```abap
IMPORTING VALUE(IV_MATNR) TYPE MARA-MATNR
TABLES        IT_ROWS   TYPE ZFG_MATERIAL_PRICE=>TY_PRICE_ROWS
EXCEPTIONS    NO_DATA   1
```

**设计意图**：给定物料号，取出该物料所有工厂/库存地点的采购相关行（MARC）作为内表返回，供调用方展示或计算；并顺手把这次读取缓存到 `gt_cache`、记录运行日期与用户名。

**逐步走读**

```abap
DATA lv_count TYPE i.

SELECT matnr werks lgort eina brgew ntgew netpr waers eifn
  FROM marc
  INTO TABLE it_rows
  WHERE matnr = iv_matnr.                      " ① 只按 MATNR 过滤 → 命中 N 条(每工厂至少 1 条)
```

- 只用 `matnr` 过滤是**正确的**：读接口要的就是全工厂视图。列清单与 `ty_price_row` 严格对齐，字段顺序也一致，这一段是全文件里最规整的部分。
- `INTO TABLE`（未加 `@`）在 Open SQL 新语法下建议写 `INTO TABLE @it_rows`，属风格问题。

```abap
SELECT maktx FROM makt
  INTO TABLE lt_desc                          " ② lt_desc 在整个函数组里没有声明！
  FOR ALL ENTRIES IN it_rows
  WHERE matnr = it_rows-matnr
    AND spras = '1'.                           " ③ 语言写死 '1'，无视 sy-langu
```

- **② `lt_desc` 未声明**：TOP 里没有 `DATA lt_desc`，也没有 `ty_desc` 之类的结构定义。这是一处**必然的编译/激活错误**。按使用意图，它应该是 `makt` 的行类型集合（至少 `matnr/maktx`）。
- **③ 语言写死 `spras = '1'`**：`gv_language` 全局变量就在旁边躺着却不用。中文环境（`spras = '1'`）之外的物料描述永远取不到，功能上是坏的。
- `FOR ALL ENTRIES` 在这里没有意义：`it_rows` 来自单物料的一次性 `SELECT`，根本不在循环里，`WHERE matnr = it_rows-matnr` 与 `WHERE matnr = iv_matnr` 语义等价。`it_rows` 为空时 FAE 会正确跳过 DB 访问（不会 dump），但**这次 DB 读的结果 `lt_desc` 之后从头到尾没被用过**——MAKT 的 `maktx` 没有回填到任何地方（既没有 `DESCRIPTIONS_ADD_TO_SEL`，也没有并入 `it_rows`）。即：**热路径上多打一次库，拿到数据直接扔掉。**

```abap
lv_count = lines( it_rows );
gv_run_date = sy-datum;
gv_user     = sy-uname;

IF lv_count = 0.
  RAISE EXCEPTION TYPE cx_sy_no_data.          " ④ 空结果当异常抛，且是"未声明的异常"
ENDIF.

APPEND LINES OF it_rows TO gt_cache.           " ⑤ 无去重、无上限、只追加
```

- **④ 接口声明的是 `EXCEPTIONS NO_DATA 1`，实现抛的却是 `cx_sy_no_data`。** 这是两件不同的事：函数组外/RFC 的调用方捕获的是 `NO_DATA` 异常（或直接 dump），拿不到一个"没数据"的正常返回路径。`CX_SY_NO_DATA` 没有 RFC 文本，从外部 RFC 调用时通常在调用方侧以未映射异常结束，除非调用方显式 `EXCEPTION cx_sy_no_data = …`。更关键的是**「该物料还没有采购记录」是完全正常的业务态**，不该用异常表达。
- 判定位置偏晚：`lv_count` 在两次 DB 读之后才算，异常在两次读之后才抛。应当在第一次 `SELECT` 之后立刻判断并早退。
- 异常抛出时 `it_rows` 已被清空/填充（`INTO TABLE` 会整体替换），`lv_count = 0` 时调用方的表是空的——这个状态需要文档化。
- **⑤** 见 §7.3。

**`Z_READ_PRICE_ROWS` 评价**：签名与第一段 `SELECT` 是合理的（只读、批量、非破坏性）。但有 1 个编译错误、1 个功能失效（语言写死）、1 个未使用读（MAKT）、1 个异常契约错配（`NO_DATA` vs `CX_SY_NO_DATA`）、1 个内存增长点。**结论：功能半残，不可用。**

---

## 4. FM 之二：`Z_UPDATE_NET_PRICE` 职责与走读

**接口**

```abap
IMPORTING VALUE(IV_MATNR) TYPE MARA-MATNR
          VALUE(IV_NETPR) TYPE MARC-NETPR
EXPORTING VALUE(EV_UPDATED) TYPE ABAP_BOOL
```

**它承诺的职责**：「更新某物料的净价」。

**它实际做的事**（这是问题的核心——**职责范围远超函数名**）：

1. 按 `matnr` 读一条 MARC（工厂不确定，见 §5.1）
2. 调 `lcl_helper` 归一单位（传错了值，见 §6.1）
3. 用毛重/订货单位算一个「重量」，并夹到 `0.5` 上限（**算完丢弃**，见 §5.4）
4. 覆盖 `netpr`，并把货币**硬改成 USD**
5. `MODIFY marc FROM ls_row`（9 列回写）
6. `UPDATE mard SET mstock = mstock`（无意义热写）
7. 无条件返回 `ev_updated = abap_true`

**逐步走读**

```abap
DATA ls_row    TYPE ty_price_row.
DATA lv_uom    TYPE marc-uom.
DATA lv_weight TYPE p DECIMALS 4.

SELECT SINGLE * FROM marc INTO @ls_row
  WHERE matnr = iv_matnr.                      " ① 没有 werks/lgort！MARC 主键是 MATNR+WERKS
```

- **① 根因缺陷。** MARC 的主键是 `MATNR + WERKS`，一个物料通常对应多条工厂记录。`SELECT SINGLE` 在没有 `ORDER BY` 的情况下返回的是**数据库决定的任意一条**（顺序不可控、可随执行计划变化）。后面的 `MODIFY` 就把价格写到了**随机工厂**上。
  同时 FM 的 `IMPORTING` 里**没有 `IV_WERKS`/`IV_LGORT`**，说明不是"漏写 WHERE 条件"，而是**接口从设计上就无法定位目标行**——这是必须改接口的 P0。
- `SELECT SINGLE *` 的目标 `ls_row` 只含 9 个字段，不是 MARC 的工作区。`*` 要求目标是该表的工作区；这种不匹配通常在运行期以转储/异常收场，而不是干净地设 `sy-subrc = 4`。即使本地侥幸通过，正确写法也是显式列清单 + 显式字段目标的结构。

```abap
lv_uom = lcl_helper=>normalise_uom( is_row = ls_row-waers );
                                           " ② 实参名 is_row 属于另一个方法 → 语法错误
                                           "    且传的是货币 waers，方法要的是单位 uom
```

- **② 双重错误**：
  - `normalise_uom` 的形参是 `IMPORTING iv_uom`，调用却写 `is_row = …`。`is_row` 是 `is_valid_price` 的形参名。静态绑定下**实参名不匹配属于语法错误，FM 无法激活**。
  - 即便名字改对，传的也是 `ls_row-waers`（货币），而 `iv_uom TYPE marc-uom` 要的是计量单位。而 MARC 的 `uom` 字段根本没被 `SELECT` 出来，值恒为初始。
  - 所以 `lv_uom` 是一个**恒定无意义**的局部变量（且宏/代码检查器会持续告警）。

```abap
lv_weight = ls_row-brgew / ls_row-eina;       " ③ 除数未判零 → EINA 为 0 时 dump
IF lv_weight > gc_weight_tol.
  lv_weight = gc_weight_tol.
ENDIF.
```

- **③** `ls_row-eina` 未做非零判断。`EINA`（订货单位）在实际数据里经常为空，**一旦为空就是 `CX_SY_ZERODIVIDE` 直接 dump**。这是最容易被真实数据触发的运行时错误。
- 夹到 `0.5` 上限后，`lv_weight` **再也没被使用**：不写回 `ls_row`、不写库、不进 `gt_cache`。函数组头注释宣称的 "weight maintenance" 在代码里**完全没有落地**——算完就丢。

```abap
ls_row-netpr = iv_netpr;
ls_row-waers = gc_cap_currency;               " ④ 硬编码 USD 覆盖原货币

MODIFY marc FROM ls_row;                      " ⑤ 9 列整行回写
UPDATE mard SET mstock = mstock WHERE matnr = iv_matnr;   " ⑥ 无意义热写
ev_updated = abap_true;                       " ⑦ 无条件真
```

- 详见 §5。

**`Z_UPDATE_NET_PRICE` 评价**：这是一个**不能上生产**的写入型 FM。它会在不确定的工厂上、用错误口径的货币、整行覆盖的方式改写采购价，并额外对全部库存地点的库存段做一次无意义更新，且对调用方永远报告"成功"。**结论：必须重写，不是修补。**

---

## 5. 数据库写入专项评估（"写库这块有没有问题"的正面回答）

**有，而且不止一处。**下面按严重度分七类展开。

### 5.1 P0：写入目标行不确定（跨工厂误写）

```abap
SELECT SINGLE * FROM marc INTO @ls_row WHERE matnr = iv_matnr.   " 缺 werks
MODIFY marc FROM ls_row;                                          " 写到"随机"工厂
```

- MARC 主键 `MATNR + WERKS`，`SELECT SINGLE` 无 `ORDER BY` → 结果行不确定。
- 若调用方本意是更新 SAPLIS1 里的那条记录，实际可能写到 SAPLIS2、SAPLIS3……而调用方**无从察觉**（`ev_updated` 恒为真）。
- 修法：接口必须加 `IV_WERKS`（和 `IV_LGORT`），或改为"整批返回 + 调用方指定行"的两段式。改接口是 breaking change，需要先盘调用方。

### 5.2 P0：货币被硬编码覆盖，且无汇率换算

```abap
ls_row-waers = gc_cap_currency.   " 恒为 'USD'
```

- 不管原记录（`IV_NETPR` 来自什么上下文、原 `MARC-WAERS` 是什么币种）一律改成 USD，**`IV_NETPR` 的数字被静默重新解释为美元**。
- 没有 `CURRENCY_CONVERSION`、没有汇率日期、没有汇率类型 → 跨币种场景下是**静默的金额错误**，用户无感、审计无痕。
- 同时也没维护 MARC 的价格口径字段：`PEINH`（价格单位）、`PEINE`（价格单位分母）、`PPRMZ`（价格控制）、`DATRE`（价格有效期至）。只改 `NETPR` 而不同步价格单位/有效期，可能导致：MRP 价格确定不认这条价；或 `DATRE` 已过期的记录被判为无效。
- 修法：要么把币种作为 `IV_WAERS` 传入并做换算，要么在 FM 内按业务规则显式限定只处理 USD 且用 `NO_MESSAGE` 明确声明；同时补 `PEINE/PEINH` 的维护。

### 5.3 P0：只改派生字段，不改主记录（一致性 + 审计缺失）

- 物料采购信息记录（Info record，PR00）里，**价格的主存储是 `EINE-EINE`**；`MARC-NETPR`/`MARC-WAERS` 更接近**为便于读取而冗余的缓存/派生字段**（`MARC-EIFN` 里就是那个信息记录号）。
- 当前代码只改 `MARC-NETPR`：
  - 信息记录本身（`EINE`）价格没变 → 任何走 `EINE` 的价格确定、报表、后续保存都会看到**旧价**；
  - 下一次任何人正常保存该信息记录，`EINE` 的价格会把 `MARC-NETPR` **覆盖回旧值**（看起来"更新丢了"）；
  - `MARC-NETPR` 的变更文档**不会产生**（CD 挂在 `EINE` 上）→ **变更历史断裂，无法追溯谁在什么时候改了价**。
- 这是采购域里最典型的"改了影子没改本体"。正确做法是走 `EINE` 维护（`UPDATE eine SET eine = … WHERE eina = …`）或调用 BAPI（如 `BAPI_INFO_RECORD_UNCHANGES`），顺带拿到标准 CD。

> 需要向开发确认：本项目是否启用了"MARC 上的字段级变更文档/价格确定直读 MARC"。若价格确定链路确实直读 `MARC-NETPR`（非标准配置），第 3 条的"覆盖回旧值"可能不发生，但**审计缺失**依然成立。**建议用真实数据链路验证，不要靠推断下结论。**

### 5.4 P1：`UPDATE mard SET mstock = mstock` —— 教科书级的坏味道

```abap
UPDATE mARD SET mstock = mstock WHERE matnr = iv_matnr;
```

逐条拆解它为什么有害：

1. **语义上空操作**：`mstock = mstock` 不改变任何库存数值，唯一效果是让 DB 层执行一次 UPDATE（获取行锁、更新时间戳/changed 标记）。
2. **锁面被无谓放大**：MARD 主键是 `MATNR+WERKS+LGORT`，只按 `matnr` 过滤 → **一次调用锁住该物料全部工厂、全部库存地点的库存段**。高频调用下这是实打实的生产热点/锁等待来源。
3. **审计噪声**：若 MARD 涉及字段级变更文档或缓存刷新，会写入"内容为空"的时间戳变更，污染变更记录。
4. **与 `NETPR` 毫无关系**：MARD 是库存段，不参与采购价格确定。**如果作者的本意是"让价格重新生效"**：这个手段是错的——SAP 需要失效的是价格确定相关的数据（如带价格确定的 MRP 中间结果/价格确定缓存），不是库存段。
5. **放大非原子性**：把"2 条 DB 语句"变成"两条不同表的语句"，中间任何一点失败/dump 都留下不一致状态（见 §5.5）。
6. **无 `sy-subrc` 判断**：失败时静默。
7. **它还是一个隐藏写**：调用方以为只改了价格，实际上动了库存主数据，授权/审计边界被绕过。

**结论：这行应当直接删除。** 若确实需要触发下游重算，应改用明确的方案（更新 `EINE` 后由 MRP 重跑，或调用相应的重算/FM），而不是"touch 一下库存表"。

### 5.5 P1：两条 DB 写非原子 + 全程无行锁 → 丢失更新

- `MODIFY marc` 与 `UPDATE mard` 是两个独立的 DB 操作，**中间没有 `COMMIT WORK`**，也**没有放在同一个 LUW 语义下**。RFC 上下文里没有隐式提交。中途 dump/断连 → MARC 已改、MARD 未改（或反之）。
- **没有行锁**：`SELECT` 未加 `FOR UPDATE`，也没有 `ENQUEUE_EZMARC`。SELECT 与 MODIFY 之间存在时间差窗口：
  - 并发场景下，别人在窗口内改了同一行的 `brgew/eina/werks/lgort/eifn`，本 FM 的 `MODIFY` 会把**旧值写回**（见 §5.6），形成典型的 **lost update**。
- 修法优先级：**(a) 先把写入收敛成一条显式字段的 `UPDATE marc SET ... WHERE matnr = ? AND werks = ?`**——单语句原子、自动加行锁、字段白名单、一次网络往返，能一次性消掉 5.5/5.6/5.7 三个问题；其次才考虑 `ENQUEUE` + LUW 包装。

### 5.6 P1：`MODIFY marc FROM ls_row` 是"9 列回写"而非"改一列"

```abap
ls_row  TYPE ty_price_row.       " 9 列
MODIFY marc FROM ls_row;         " 写回它在 MARC 中能匹配到的所有列
```

- 开发者意图是"改 `netpr` 和 `waers`"，但实际提交的字段集合是 `ls_row` 里所有能对应到 MARC 的列，包括 `werks/lgort/eina/brgew/ntgew/eifn`。`MODIFY` 写入哪些列取决于 work area 实际包含的字段，这是一条**不透明的隐式契约**（建议在测试系统用 SQL trace 确认实际列集合）。
- 直接后果：把 SELECT 时刻读到的**快照**原样写回，与 §5.5 的时间差窗口叠加 → 覆盖他人并发修改。
- 正确写法（白名单 + 原子）：

```abap
UPDATE marc SET  netpr = @lv_netpr
                waers = @iv_waers
  WHERE matnr = @iv_matnr
    AND werks = @iv_werks.
IF sy-subrc <> 0.
  ev_updated = abap_false.   " 找不到记录，如实返回
  RETURN.
ENDIF.
ev_updated = abap_true.
```

### 5.7 P1：`ev_updated` 恒为 `abap_true`

```abap
ev_updated = abap_true.    " 无条件
```

- 没有 `sy-subrc` 判断（两处 `SELECT` 都没有），没有异常路径，`ev_updated` 只是被"写了个常量"。
- 失败场景举例：物料在该工厂无 MARC 记录 → `ls_row` 保持初始 → 拿初始键去 `MODIFY`（`MATNR/WERKS` 为空）→ **不是干净地返回 false，而是运行期错误/转储**。调用方拿不到可靠的成败信号，只能靠"没 dump"来推断。
- 修法：所有 `SELECT` 后判 `sy-subrc`（或用 `lines( )` / `COUNT( * )`），所有写后判 `sy-subrc`，失败**如实返回 `abap_false` 并写日志/抛消息**。

### 5.8 P1：缺少的机制一览

| 机制 | 现状 | 风险 |
|---|---|---|
| 授权检查 | 两个 FM 都**没有** `AUTHORITY-CHECK`，没有 S_TCODE/工厂/采购组织权限校验 | 任何有程序运行权限的人都能改采购价 |
| 输入校验 | `IV_NETPR` 直接落库，**没调 `lcl_helper=>is_valid_price`**（该方法全组无人调用，死代码） | 0 / 负数 / 超范围价格可写入 |
| 变更文档 | 未走 `EINE`、未调用 CD 相关 FM | 价格变更无痕、不可审计 |
| 日志 | 无 `BAL_LOG_*`、无 `WRITE`、无消息类 | 出问题后无法定位 |
| 锁 | 无 `FOR UPDATE` / 无 `ENQUEUE` | 丢失更新（§5.5） |
| 事务 | 无 LUW/提交策略 | 半写状态（§5.5） |
| RFC 暴露面 | 两个 FM 的接口都是 **RFC 可调用**的（`TABLES`+`EXCEPTIONS`；写 FM 是纯 `IMPORTING/EXPORTING`） | 有副作用、能改 MARC/MARD 的接口挂在 RFC 入口上，等于对所有 RFC 调用方开放，且无调用方身份校验/审计 |

**写库这一块的总结**：写入路径的每一个环节——**定位、字段集合、币种与价格口径、主记录一致性、并发、事务、返回值、授权**——都存在缺陷。**不建议在现有代码上打补丁，应重写写入 FM（收窄为"显式字段的单条 UPDATE + 关键字段入参 + sy-subrc 契约 + 授权检查"），并把 `EINE` 同步与 CD 纳入方案。**

---

## 6. 附：字段级数据流转

### 6.1 血缘

```
MARC (DB)  ──SELECT──▶  it_rows / ls_row  ──▶  调用方内表
  │ matnr werks lgort netpr waers eifn        │   (netpr/waers 供展示或再计算)
  │ (+ eina brgew ntgew ← 声明来自 MARA，存疑)
  │
MAKT (DB)  ──SELECT──▶  lt_desc  ──✗ 丢弃
  │ (spras 写死 '1')

内存全局   gt_cache ◀──APPEND── 每次读取追加（只写不读，无上限）
           gv_run_date / gv_user ◀──赋值── 从不使用
           gv_language        ◀──  从不赋值
常量       gc_weight_tol  ──▶ 夹取 lv_weight ──✗ 丢弃
           gc_cap_currency ──▶ 直接覆盖 ls_row-waers
类方法      normalise_uom ◀── 调用错误（实参名/语义双错）──✗ 结果无意义
           is_valid_price ◀── 无人调用（死代码）
```

### 6.2 写路径流转（问题点标注）

```
调用方 ──IV_MATNR, IV_NETPR──▶ z_update_net_price
   │
   ├─[P0] SELECT SINGLE * marc WHERE matnr   → 工厂不确定
   │        └─[编译] 目标结构非工作区
   ├─[P0] lv_uom ← normalise_uom(is_row=waers) → 语法错 + 语义错
   ├─[P0] lv_weight = brgew / eina            → 除零 dump；结果丢弃
   ├─[P0] ls_row-waers := 'USD'               → 币种被覆盖
   ├─[P1] MODIFY marc FROM ls_row             → 9 列回写 + 丢失更新
   ├─[P1] UPDATE mard SET mstock = mstock     → 无意义热写 + 锁放大
   └─[P1] ev_updated := abap_true             → 恒真
```

### 6.3 读写矩阵

| 对象 | 写 | 读 | 谁写 | 谁读 |
|---|---|---|---|---|
| `MARC` | ✅ UPDATE/MODIFY | ✅ | `z_update_net_price` | `z_read_price_rows`、`z_update_net_price` |
| `MAKT` | — | ✅ | — | `z_read_price_rows`（结果丢弃） |
| `MARD` | ✅（空操作） | — | `z_update_net_price` | — |
| `EINE`（信息记录价格主存储） | ❌ **缺失** | ❌ | — | — |
| `gt_cache` | ✅ | ❌ | `z_read_price_rows` | **无人** |
| `gv_run_date`/`gv_user` | ✅ | ❌ | `z_read_price_rows` | **无人** |
| `gv_language` | ❌ | ❌ | — | — |
| `lv_weight` / `lt_desc` / `lv_uom` | 局部赋值 | ❌ | — | **无人** |

`EINE` 那一行的"❌ 缺失"是整张表里最刺眼的空洞。

---

## 7. 非功能问题

### 7.1 死代码 / 死状态（清理清单）

- `lzfg_material_pacuxx`（本次未提供，主程序 INCLUDE 但内容未知——先确认它是否为空壳）
- `lv_uom`、`lv_weight`、`lv_count`（除异常判定外无其它用途）
- `lt_desc`（DB 读了不用）
- `lcl_helper=>is_valid_price`（全组无调用）
- `gc_weight_tol`（唯一的比较对象 `lv_weight` 被丢弃）
- `gv_run_date`、`gv_user`、`gv_language`
- `gt_cache`（只写不读）

### 7.2 会影响激活的硬错误

1. `lzfg_material_pacu01:26` — `lt_desc` 未声明（且无对应结构类型）。
2. `lzfg_material_pacu01:62` — `normalise_uom( is_row = … )` 实参名不属于该方法，静态绑定语法错误。
3. `lzfg_material_pacu01:20` — 从 MARC 取 `eina/brgew/ntgew`（TOP 中声明为 `mara-*`），需核实 MARC 是否真有这三列。

> 这三条意味着：**以本次提供的源码为基准，这个函数组无法通过激活。** 如果生产系统里它"能跑"，那说明仓库里的源码与激活版本已经漂移（常见原因：FM 直接在 SE37 里改过、或传输后本地手工修过）。**请以 SE38 里的实际激活版本为唯一事实来源重新做一次 diff**，本报告的其余结论仍适用于该版本的结构。

### 7.3 `gt_cache` 内存增长

```abap
APPEND LINES OF it_rows TO gt_cache.   " 无 dedup、无上限、无清理
```

- 函数组是**会话级共享内存**（一个 SAPLU 实例 / 一条 RFC 连接内多轮调用复用同一内存）。反复调用 `z_read_price_rows` 会把同样的行**重复追加**：
  - 既是**内存泄漏**（长会话、批处理反复进入、RFC 服务端长连接下持续增长），也是**语义错误**（叫 cache 却从不命中、永不反映最新数据）。
- 至少修成"去重 + 覆盖"：按 `matnr+werks+lgort` 建次键，读时 `READ TABLE`；或干脆删掉这个伪缓存。

### 7.4 其它

- `TABLES` 参数是**受限表参数**（SEFA 不友好），现代风格应改为非受限形参 `it_rows TYPE ty_price_rows`。
- `TABLES it_rows TYPE ZFG_MATERIAL_PRICE=>TY_PRICE_ROWS` 用组名引用类型不常见，直接写 `TYPE ty_price_rows` 更清晰。
- 接口注释声明 `EXCEPTIONS NO_DATA 1` 与实现抛 `cx_sy_no_data` 不一致（§3）。
- 硬编码常量（`USD`、`0.5`）应可配置。
- 函数组头注释宣称 "price / weight maintenance"，但 **weight 维护根本没有实现**——文档与实现不符，误导接手人。

---

## 8. 改造建议（按优先级）

### P0 — 上线前必须完成

1. **改写 `Z_UPDATE_NET_PRICE` 的接口**：加入 `IV_WERKS`（必要时 `IV_LGORT`），或改成"调用方传行集合/先读后定点写"的两段式。接口变更是 breaking 的，先用 `WHEREUSED`/STAD 盘清调用方。
2. **写入收敛为单条白名单 `UPDATE`**：

```abap
UPDATE marc SET  netpr = @iv_netpr
                waers = @iv_waers
  WHERE matnr = @iv_matnr
    AND werks = @iv_werks.
```

3. **同步 `EINE`**（信息记录价格主存储）或改用 BAPI，让变更文档正常产生。
4. **删除 `UPDATE mard SET mstock = mstock`**。若目标是触发重算，改用明确方案。
5. **补 `sy-subrc` 判断**，`ev_updated` 如实返回；所有失败路径写日志 + 抛消息。
6. **修 3 处硬错误**，并以 SE38 激活版本为基准重新 diff。
7. **`IV_NETPR` 入参校验**（非 0、非负、与币种匹配），把 `is_valid_price` 用起来或改造为更贴切的 `is_valid_input( iv_netpr iv_waers )`。

### P1 — 紧随其后

8. **授权检查**：写 FM 加采购数据/工厂维度的 `AUTHORITY-CHECK`。
9. **币种改为入参** + 需要时 `CURRENCY_CONVERSION`（明确汇率日期与类型）。
10. **异常契约对齐**：要么用 `MESSAGE`/声明异常表达"没数据"（正常态），要么删掉 `cx_sy_no_data`，二选一并写进接口文档。
11. **语言改 `gv_language`（`sy-langu`）**；`lt_desc` 要么回填到结果结构里，要么把 MAKT 读删掉。
12. **`gt_cache` 加键去重/上限，或删除**。
13. **写型 FM 从 RFC 面上摘掉**（迁到 SE24 全局类的方法，或用 `TABLES`/受控参数让它不再 RFC 可调），并补审计出口。

### P2 — 清理与长期

14. 把 `lcl_helper` 迁到 SE24 全局类（可复用、可单测）。
15. 硬编码常量（`USD`、`0.5`）移到配置表。
16. 清理死变量、死全局；把 include 结构规整为 `TOP` + `U01…`（或标准 `F01/F02`）并确认 FM 真的被 INCLUDE。
17. 补 `WITH EMPTY KEY` 不可用于 `MODIFY … FROM TABLE` 的说明，或换成有主键的内表。
18. 补一份函数级文档：参数语义、币种规则、价格单位（`PEINH/PEINE`）口径、异常契约、调用方清单。

---

## 9. 需要向开发/业务确认的问题

1. SE38 里**实际激活**的版本与仓库源码是否一致？（§7.2 判定"仓库版本无法激活"）
2. `LZFG_MATERIAL_PACU01` 是否真的被主程序 INCLUDE？`LZFG_MATERIAL_PACUXX` 里有什么？
3. MARC 是否真有 `EINA/BRGEW/NTGEW` 三列？若没有，重量数据的真实来源表是哪个？
4. 本项目的价格确定链路读的是 `MARC-NETPR` 还是 `EINE-EINE`？是否启用了 MARC 的字段级变更文档？
5. "把价格改成 USD" 是明确业务要求吗？还是历史遗留的调试语句？
6. `UPDATE mard` 那行的原始意图是什么（强制价格重算？刷新缓存？碰缓存）？
7. `Z_UPDATE_NET_PRICE` 的现有调用方有哪些（RFC？同一个 LUW 内的其它程序？批处理？）？它们如何知道写到了哪条记录？

---

## 10. 如何自行验证（本报告结论的可复现检查）

| 想验证什么 | 怎么做 |
|---|---|
| 源码能否激活 | SE38 → `ZFG_MATERIAL_PRICE` → 激活，看 §7.2 三条错误是否复现 |
| 工厂不确定 | 测试系统准备 2+ 工厂的 MARC 记录，ST05/SQL trace 看 `SELECT SINGLE` 实际命中哪条，换 DB/换优化后重试 |
| 实际写哪些列 | ST05 打开 SQL trace，看 `MODIFY marc` 的列清单 |
| MARD 那行到底做了什么 | ST05 观察 `UPDATE mard` 是否真的下发、行锁范围与耗时；对比删掉前后的 DB 负载 |
| 是否丢了变更文档 | 更新价后查 `CDHDR/CDPOS`（EINE 相关），确认是否有记录 |
| 死代码 | Code Inspector（SE80 → 工具 → 代码检查器）/ ATC，把 §7.1 清单逐条对照 |
| 调用方清单 | `WHEREUSED`（FM）/ SE39 全局搜索函数名 / STAD |
| 内存增长 | 在 ST05 之后查 `MEMORY`（ST12/事务 ST12 或 FM `MEMORY`），反复调用 `Z_READ_PRICE_ROWS` 观察 `gt_cache` 占用 |

---

### 一句话总结

这个函数组**读**的那一半（`Z_READ_PRICE_ROWS`）思路对、写法糙（语言写死、多读一张表、内存泄漏、异常契约错配）；**写**的那一半（`Z_UPDATE_NET_PRICE`）则是**设计级缺陷**——接口里没有工厂入参、只写派生字段不改主记录、用一条无意义的库存段空更新充数、并发与事务都没管、返回值恒真——**不应在现有代码上打补丁，应当重写**。当前最高优先级的一件事是：**以 SE38 中实际激活的版本为基准做一次 diff**，因为本次提供的源码按字面是激活不过的。

# 报表程序分析报告：`zreport_bapi_upload`

> 分析对象：`zreport_bapi_upload.abap`（REPORT，126 行）
> 分析重点：BAPI 调用、RFC 复制的正确性；价格计算是否算错
> 结论摘要：**本程序的 BAPI 段因为缺少 `BAPI_TRANSACTION_COMMIT`，在生产中实际上不会落库；而它推给远端系统的却是被算错的价格值；并且 DRY RUN 选项对 RFC 段完全无效。** 三者叠加，是"没改成本地数据，却把错误数据改了远端"的最坏组合。

---

## 一、程序定位与执行流程

程序头注释（`zreport_bapi_upload.abap:3-6`）声明了两件事：

1. 通过 BAPI 上传采购价格变更（Upload purchase price changes via BAPI）
2. 再通过 RFC 把数据复制到远端系统（replicate to a remote system over RFC）

主控流程（`:40-45`）是四个 FORM 的线性串联，没有任何异常分支：

```abap
START-OF-SELECTION.

  PERFORM read_changes.
  PERFORM post_via_bapi.
  PERFORM replicate_remote.
  PERFORM show_log.
```

即：取数 → BAPI 写入 → RFC 推送 → 打印日志。

选择屏幕（`:31-35`）只有三个参数：物料范围 `s_matnr`、RFC 目标 `p_dest`（默认 `ZFIN`）、试运行 `p_dryrun`。工厂 `A100` 和金额换算的取舍逻辑全部硬编码在程序里。

数据模型只有两个结构（`:8-29`）：

| 对象 | 结构 | 关键点 |
|---|---|---|
| `gt_change` | `ty_chg`(matnr/werks/netpr/waers) | 没有 `brgew`，没有价格单位 `priceu` |
| `gt_return` | `ty_rmess`（手工仿写） | 与 BAPI 的 `BAPIRET2` 不一致 |
| `gt_remote` | `TABLE OF ty_chg` | 直接等于 `gt_change` |
| `gr_weight` | `TYPE TABLE OF p` | **声明本身是错的**（见 P1-4） |
| `gs_target` | `rfcdest` | 只填了 `rfcdest`，缺 `bapi_transaction` / `no_put` |

---

## 二、问题清单（按严重度排序）

### P0 — 致命，直接造成生产事故

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| P0-1 | `:83-88` | `BAPI_MATERIAL_MAINTAIN` 是**分组 BAPI（grouped BAPI）**，只把数据写入 LUW 暂存，**绝不会自动 COMMIT**。代码全程没有 `BAPI_TRANSACTION_COMMIT`，也没有 `COMMIT WORK`。 | 本地 MARC **一条数据都改不进去**。程序跑完即回滚。若用户以为"跑成功"并继续下游流程，账实不符。 |
| P0-2 | `:83-88` + `:101-118` | `IF p_dryrun IS INITIAL` **只包住了 BAPI 调用**，`replicate_remote` 在任何情况下都会执行。 | **DRY RUN 形同虚设**。勾选试运行照样把数据推到远端；若远端 FM 自身 COMMIT，生产被真实修改。 |
| P0-3 | `:78` + `:49-58` | 价格算出来后写进的是 `mara-brgew`（**毛重**），并以 `materialdata` 参数传给 BAPI；而 `materialdata` 期望的是 `BAPI_MATMISC`（只有 MATNR + DEL_FLAG），**根本不含 BGRWE 字段**。 | 计算结果与落库字段完全错位：既没改价格，又把重量字段当成垃圾位用，属于典型的"字段误用型数据污染"。 |
| P0-4 | `:107-114` | RFC 调用声明了 `EXCEPTIONS`，但**完全不看 `sy-subrc`**，无条件 `WRITE 'replicated to'`。 | 远端不可达/通信中断时日志仍显示"已复制"。运维失去唯一的失败信号。 |
| P0-5 | `:38` + `:107` | `gs_target` 只填了 `rfcdest`，**没有 `bapi_transaction = 'X'`**，RFC 侧也未在 FM 内 COMMIT，调用后**没有针对 destination 的 `BAPI_TRANSACTION_COMMIT`**。 | 远端系统同样处于"调用结束即回滚"的默认 LUW 语义，**远端也没有真正落库**，只是白跑一趟网络传输。 |

### P1 — 严重，影响正确性与可运维性

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| P1-1 | `:62` | `ls_chg-netpr = ls_chg-netpr * ls_w-brgew` **价格 × 毛重** 没有任何业务依据、无币种换算、无单位换算（`marc-umren/umre z`）、无小数位定标、无溢出保护。 | 详见第四章：价格计算本身是错的，且结果类型不匹配（`p(15,3) × p(13,3)` 写入 `quan(13,3)` 会溢出 DUMP 或丢精度）。 |
| P1-2 | `:49-58` | `mara~brgew` 已经在第一个 JOIN 里查出来了，但结构 `ty_chg` 没有该字段 → **查了丢掉**，然后 `FOR ALL ENTRIES` 再查一次 MARA。 | 一次多余的百万行级全表扫描；`FOR ALL ENTRIES` 在 `gt_change` 有重复物料时还会产生重复键。 |
| P1-3 | `:61` | `READ TABLE gr_weight` **不检查 `sy-subrc`**。 | 查不到时 `brgew` 为 0，净价被静默乘成 0 —— **价格被静默清零**，无任何提示。 |
| P1-4 | `:28` | `DATA gr_weight TYPE TABLE OF p` —— `p` 是 1 位压缩十进制**基本类型**，不是结构。`SELECT matnr brgew ... INTO TABLE gr_weight`（`:55-58`）和 `READ ... WITH KEY matnr`（`:61`）对非结构表都不成立。 | 该行本身是非法的类型/结构声明（编译期即告警或运行失败），说明这一段是复制粘贴后未走 ATC 校验的产物。 |
| P1-5 | `:90-96` | `gt_return` 用**手工仿写的** `ty_rmess`，缺 `msgv3/msgv4` 与行关联字段；调用后**不判 `typeid = 'E'/'A'`**；紧接着 `:94-96` 无条件对所有行打印 `'uploaded'`。 | 批量场景下无法把错误消息对应回具体物料，且**成功日志与失败数据同时出现**，日志本身是误导性的。 |
| P1-6 | `:26` | `gt_return` 是全局表且**调用前未 `CLEAR`**。 | 一旦后续扩展为循环调用（分批/按工厂循环），历史消息会持续累积。 |
| P1-7 | `:113` | 缺 `communication_failure = 2`。RFC 最常见的失败类型正是 `communication_failure`（目标忙、超时、网络断）。 | 真实故障只能落进 `OTHERS`，无法区分网络故障与目标系统不可用。 |
| P1-8 | `:111-114` | `it_price` 在 RFC 中是**引用（CHANGED）参数**，但只声明了输入，没有 `et_error` 之类的返回结构。 | 远端 FM 的业务错误**无法传回**，调用方对"哪一行没写成功"零可见性。 |
| P1-9 | `:105` + `:33` | 一次 RFC 调用传**整张表**，无分批、无 `IN BACKGROUND`、无 RZ 边界控制；`gs_target-no_put` 未置 `'X'`。 | 物料量大时命中 RFC 600s 超时 / 目标系统短时锁，远端内存与参数包双爆。 |
| P1-10 | `:29-35` | 无授权检查（无 ATC / `AUTHORITY-CHECK`），RFC 目标 `ZFIN` 直接由选择屏幕参数决定，无白名单校验。 | 越权改物料主数据 + 任意目标系统外发数据的风险。 |

### P2 — 一般，健壮性与可读性

| # | 位置 | 问题 |
|---|---|---|
| P2-1 | `:49-53` | `netpr` 是**净订购价（按单位/按价格单位）**，不是"变更量"。程序没有与旧值比较，名为"price changes"实为"当前全量价格"。 |
| P2-2 | `:12` | 读了 `waers` 却**全程未使用** —— 多币种数据被混进同一个无币种数值字段。 |
| P2-3 | `:53` | 工厂 `'A100'` 硬编码；`gt_change` 却带着 `werks` 字段，暗示"可多工厂"但实现不支持。 |
| P2-4 | `:52` | 缺 `mara~mstae = 'X'`（未删除物料）、缺 `marc~mhdat` 有效期过滤、缺固定 `marc~matnr` 之外的销售/采购视图有效性判断。 |
| P2-5 | `:33` | 选择屏幕无 `s_matnr` 的必填/合理性检查，用户留空即**全物料全工厂**执行。 |
| P2-6 | `:91,95,116,123-124` | 全篇 `WRITE`。报表应输出结构化日志表 + `MESSAGE` 汇总；`lines( )` 也建议换成 `card` / `lines( )` 之外更直白的写法。 |
| P2-7 | `:103` | `DATA lv_ok TYPE c.` 声明后从未赋值，是死代码。 |
| P2-8 | 全文 | 无锁对象（`ENQUEUE`）、无变更记录（CDHDR）策略、无传输日志表、无可重跑机制 —— 批量改主数据缺可追溯性。 |

---

## 三、专题一：BAPI 调用正确性

### 3.1 调用方式本身

```abap
IF p_dryrun IS INITIAL.
  CALL FUNCTION 'BAPI_MATERIAL_MAINTAIN'
    TABLES
      materialdata  = lt_mara
      return        = gt_return.
ENDIF.
```

三个致命问题叠加：

**① 缺少 COMMIT，分组 BAPI 不落库。** `BAPI_MATERIAL_MAINTAIN` 属于"分组 BAPI"设计：它把数据写入调用者的 LUW，**由调用方负责提交**。标准做法是紧跟 `BAPI_TRANSACTION_COMMIT`，或在 SE37 测试时点"保存并运行（本地）"由测试框架提交。在 REPORT 里没有这两者，数据在 LUW 结束时被丢弃。

**② 参数类型与语义双错。** 真实 FM 签名（节选）：

| 参数 | 期望类型 | 实际传入 | 判定 |
|---|---|---|---|
| `MATERIALDATA` | `BAPI_MATMISC_TAB`（MATNR / DEL_FLAG） | `TABLE OF mara`（200+ 字段） | ❌ 类型不符，且 BGRWE 根本不参与物料主数据维护 |
| `VALUATIONDATA` | `BAPI_MATNR_VK_TAB`（MATNR/WAERS/VPR01/BWSPR…） | 未传 | ❌ 价格**根本没有被提交** |
| `RETURN` | `BAPIRET2_TAB` | `ty_rmess_tab`（手写结构） | ❌ 字段不对齐，msgv3/msgv4 缺失 |

也就是说：**即使把 COMMIT 补上，这次调用改的也是"物料视图标识"，而价格改动压根没进 BAPI。**

**③ 错误处理形同虚设。** `RETURN` 表在 BAPI 中是**逐行业务错误载体**，必须按 `type = 'E'/'A'` 判定，并按消息里的物料号回填到工作表。代码只是 `WRITE` 出来，然后对每一行无条件打印 `'uploaded'`。

### 3.2 正确写法（分组 BAPI + 估值数据 + 逐行判错 + 显式提交）

```abap
FORM post_via_bapi.
  DATA lt_misc   TYPE bapi_matmisc_tab.
  DATA lt_val    TYPE bapi_matnr_vk_tab.
  DATA lt_return TYPE bapiret2_tab.
  DATA lv_err    TYPE i.
  DATA lv_ok_cnt TYPE i.

  LOOP AT gt_change INTO DATA(ls_chg).
    " MARC 级标识：只传 BAPI 认的字段
    APPEND VALUE #( matnr = ls_chg-matnr ) TO lt_misc.

    " 价格必须走 VALUATIONDATA，且带币种与价格单位
    APPEND VALUE #( matnr  = ls_chg-matnr
                    waers  = ls_chg-waers
                    vpr01  = ls_chg-netpr
                    priceu = ls_chg-priceu
                    ) TO lt_val.
  ENDLOOP.

  IF lt_misc IS INITIAL.
    RETURN.
  ENDIF.

  IF p_dryrun = abap_true.
    MESSAGE '试运行：未调用 BAPI。' TYPE 'S'.
    RETURN.                          " ← 必须在 FORM 开头就 RETURN，不能只包住 FM
  ENDIF.

  CALL FUNCTION 'BAPI_MATERIAL_MAINTAIN'
    TABLES
      materialdata  = lt_misc
      valuationdata = lt_val
      return        = lt_return.

  LOOP AT lt_return INTO DATA(ls_ret).
    IF ls_ret-type = 'E' OR ls_ret-type = 'A'.
      lv_err = lv_err + 1.
      " 建议把 ls_ret-msgid/msgno/msgv1..4 与 matnr 一起写入日志表
      APPEND ls_ret TO gt_log.
    ENDIF.
  ENDLOOP.

  " 分组 BAPI 必须显式提交；否则全部回滚
  IF lv_err = 0 AND p_commit = 'X'.
    CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'
      EXPORTING
        work = 'BAPI_MATERIAL_MAINTAIN'.
    MESSAGE 'BAPI 已提交。' TYPE 'S'.
  ELSE.
    CALL FUNCTION 'BAPI_TRANSACTION_ROLLBACK'
      EXPORTING
        work = 'BAPI_MATERIAL_MAINTAIN'.
    MESSAGE lv_err = lv_err
      WITH '存在业务错误，已全部回滚，请查看日志。' TYPE 'E'.
  ENDIF.
ENDOFM.
```

要点：
- `MATERIALDATA` 与 `VALUATIONDATA` **职责分离**，价格永远走 `VALUATIONDATA`（`VPR01` = 无税净订购价，`BWSPR` = 含税，`WAERS`/`PRICEU` 决定价格单位）。
- 失败即整体回滚，避免"部分成功"造成的价格不一致。
- 若业务要求"部分成功"，则必须逐条事务或按成功子集重试，并生成失败清单。

### 3.3 采购价的领域常识（本程序踩了坑）

`MARC-NETPR` 只是**该物料在该工厂的净订购价**，来自 PO 求得的参考价，**不是供应商价格**。真正的供应商价格住在 `EKKAP`（价格确定记录：物料/供应商/工厂/有效期/净价/含税价/币种/数量单位/价格单位）。

因此"上传采购价格变更"如果指供应商价，应改用 **BAPI_PO_GETPRICINGCONDITIONS** 写 `EKKAP`，而不是 BAPI_MATERIAL_MAINTAIN；如果指物料视图的参考净价，那至少要走 `VALUATIONDATA` 并同时维护 `MARC-PRICEU`。这一点建议先与业务确认口径，否则 P1-1 的"算法错误"是**口径错误**，不是代码笔误。

---

## 四、专题二：价格计算正确性

原实现（`:60-64`）：

```abap
LOOP AT gt_change INTO DATA(ls_chg).
  READ TABLE gr_weight INTO DATA(ls_w) WITH KEY matnr = ls_chg-matnr.
  ls_chg-netpr = ls_chg-netpr * ls_w-brgew.
  MODIFY gt_change FROM ls_chg.
ENDLOOP.
```

### 4.1 算式层面的问题

| 编号 | 问题 | 说明 |
|---|---|---|
| C-1 | **量纲不成立** | `NETPR` 是 `CURR(15,3)`，即"每 1 价格单位的货币金额"；`BRGEW` 是 `QUAN(13,3)`，即"毛重"。相乘的物理意义只有在"重量以 kg 计、金额按每 kg 计价"这一特定口径下才成立，而程序**既没换算单位也没换算币种**，属于口径裸奔。 |
| C-2 | **溢出 DUMP 风险** | `p(15,3) × p(13,3)` 最大可达 28 位整数，写回 `MARC-NETPR` 只有 `p(15,3)`；写 `MARA-BRGEW` 只有 `quan(13,3)`（13 位整数）。重物料 × 高单价直接 `CONVT_NO_NUMBER` 短转储。 |
| C-3 | **无舍入** | 结果没有按目标字段小数位 `ROUND`，ABAP 内 `p` 类型赋值虽会截位，但**截断方向不可控**（会计场景通常要求四舍五入，且有 `PRICEUNIT` 相关的舍入表）。 |
| C-4 | **无币种换算** | `waers` 读进来了却没用。若目标系统是单一本位币，需要按汇率表折算；否则必须把币种作为字段一起传过去。 |
| C-5 | **静默清零** | `READ TABLE` 失败时 `brgew` 为 0（`ls_w` 甚至不是合法结构，见 P1-4），净价被乘成 0，**没有 sy-subrc 检查、没有异常消息**。 |
| C-6 | **重复赋值/覆盖语义** | `MODIFY gt_change` 把"净价"原地改写为"金额"，字段含义被污染。随后 `:105` 整表推给远端，远端若按 `NETPR` 语义写入，**错误被复制到另一套系统**。 |
| C-7 | **无变化量** | 程序名为"price changes"，却没有与旧值比较/算差额，等于把当前价全量重刷一遍，无法表达"本次只调了 3 个物料"。 |

### 4.2 建议的取数与算法骨架

```abap
TYPES: BEGIN OF ty_chg,
         matnr  TYPE mara-matnr,
         werks  TYPE marc-werks,
         netpr  TYPE marc-netpr,        " 无税净订购价（保留原语义）
         waers  TYPE marc-waers,
         priceu TYPE marc-priceu,       " 价格单位：每 1 priceu 单位的价格
         brgew  TYPE mara-brgew,        " 毛重（首次 SELECT 就要带出来）
         mgeuw  TYPE mara-einwt,        " 重量单位
         value  TYPE p LENGTH 15 DECIMALS 3,   " 计算结果：金额
       END OF ty_chg.

FORM read_changes.
  " 一次 SELECT 取全，不做 FOR ALL ENTRIES 二次查询
  SELECT marc~matnr marc~werks marc~netpr marc~waers marc~priceu
         mara~brgew mara~einwt mara~mstae
    FROM marc INNER JOIN mara ON mara~matnr = marc~matnr
    INTO TABLE @gt_change
    WHERE marc~matnr IN @s_matnr
      AND marc~werks  = @p_werks
      AND mara~mstae  = @abap_true.
ENDOFM.

FORM calc_values.
  CONSTANTS c_scale TYPE i VALUE 3.
  DATA lv_qty   TYPE p LENGTH 23 DECIMALS 3.   " 宽口径中间变量，防溢出
  DATA lv_price TYPE p LENGTH 23 DECIMALS 3.

  LOOP AT gt_change ASSIGNING FIELD-SYMBOL(<chg>).
    IF <chg>-brgew <= 0 OR <chg>-netpr <= 0.
      <chg>-value = 0.
      CONTINUE.
    ENDIF.

    " 单位换算：价格按 priceu 计价 → 换算到实际重量单位
    lv_qty   = <chg>-brgew * COND #( WHEN <chg>-priceu > 0 THEN <chg>-priceu ELSE 1 ).
    lv_price = <chg>-netpr.

    " 明确的舍入策略，避免截断争议
    <chg>-value = ROUND( iv = lv_price * lv_qty  dec = c_scale
                         mode = abap_decimal_round_half_up ).

    " 目标字段范围校验，防止赋值时 DUMP
    IF <chg>-value > CONVT #( i 999999999999.999 ).
      <chg>-value = 0.
      APPEND VALUE #( matnr = <chg>-matnr
                      type  = 'E'
                      text  = '金额超出目标字段范围' ) TO gt_log.
    ENDIF.
  ENDLOOP.
ENDFORM.
```

> 提示：`netpr * brgew` 若业务上真的需要（例如"吨成本" = 单价 × 每件毛重 × 每箱件数），也**必须**把 `mgeuw`、`priceu`、`umren/umrez` 一并纳入，并把结果写进独立字段（`value`），**不要覆盖 `netpr` 本体**。

---

## 五、专题三：RFC 复制正确性

原实现（`:101-118`）：

```abap
gt_remote = gt_change.

CALL FUNCTION 'Z_FIN_PRICE_PUSH'
  DESTINATION gs_target
  TABLES
    it_price = gt_remote
  EXCEPTIONS
    system_failure = 1
    destination_unavailable = 2
    OTHERS = 3.

WRITE: / 'replicated to', p_dest.
```

### 5.1 问题拆解

1. **事务语义缺失（最致命）**。`DESTINATION` 的 `rfcdest` 属于 **RFC 调用**（`rfcdest` 中 `rfcdestopt-rfcdest = 'D'`，registered destination）。这种调用默认**不共享调用方 LUW**，远端 FM 内的数据在远端 LUW 结束时被回滚，除非：
   - 在 `gs_target-bapi_transaction = 'X'`，或
   - 远端 FM 内部自行 `COMMIT WORK`，或
   - 调用后执行带 `DESTINATION` 的 `BAPI_TRANSACTION_COMMIT`。

   当前代码三条都没有，**远端同样没落库**。

2. **不检查 `sy-subrc`**。`lv_ok` 声明了却没用（`:103`），失败也打印 "replicated to"。

3. **异常清单不完整**。缺 `communication_failure`，这是 RFC 最常见的失败（目标忙 / 超时 / 连接中断）。缺 `no_data`、`not_supported`、`conversion_failure` 等间接失败。

4. **无返回值通道**。远端 FM 业务上"哪条没写成功"必须通过带错误结构（`TYPE`/`ID` 行标识 + 消息）的返回参数传回。`TABLES` 参数在 RFC 下是引用参数，可以在远端被填充并**回传**到本地表 —— 前提是接口定义里声明了这个返回表。

5. **未置 `no_put`**。RFC 表格参数本质是双向的，回传会额外占用带宽与目标端资源。纯推送场景应 `gs_target-no_put = 'X'`。

6. **全量一次性推送**。无分批、无 `IN BACKGROUND`、无超时控制。物料量大时必然踩 600 秒硬超时。

7. **推送的是被污染的数据**。`gt_remote = gt_change` 复制的是 C-6 里已被改写的 `netpr`（金额），远端 FM 若按 `NETPR` 语义落库，远端价格将**全部错乱**。

8. **目标系统无防护**。`p_dest` 由屏幕自由输入，若配置了指向生产或第三方系统的目标，任何用户都能借这个报表外发数据。

### 5.2 正确写法

```abap
FORM replicate_remote.
  DATA lt_err   TYPE zsmm_prc_err_tab.        " 行标识 + 消息（需在 RFC 端也定义）
  DATA lv_rows  TYPE i.
  DATA lv_errs  TYPE i.

  IF p_dryrun = abap_true.
    MESSAGE '试运行：已跳过 RFC 推送。' TYPE 'S'.
    RETURN.                                    " ← DRY RUN 必须在此短路
  ENDIF.

  IF gt_remote IS INITIAL.
    RETURN.
  ENDIF.

  " 目标系统白名单，避免任意外发
  IF NOT line_exists( lt_dest_whitelist[ dest = p_dest ] ).
    MESSAGE '未授权的 RFC 目标系统' TYPE 'E' DISPLAY LIKE 'E'.
  ENDIF.

  gs_target-rfcdest         = p_dest.
  gs_target-no_put          = 'X'.             " 纯推送，不回传表
  gs_target-bapi_transaction = 'X'.            " 远端调用后自动 COMMIT

  " 分批推送：每 500 条一包，避免 RPC 超时
  DATA(lt_chunks) = ...
  LOOP AT gt_remote INTO DATA(ls_row) GROUP BY ( ceil( iv = sy-tabix / 500 ) )
                                SIZE lv_rows.
    CLEAR lt_err.
    CALL FUNCTION 'Z_FIN_PRICE_PUSH'
      DESTINATION gs_target
      TABLES
        it_price = ls_row[]
        et_error = lt_err
      EXCEPTIONS
        communication_failure    = 1
        system_failure           = 2
        destination_unavailable = 3
        no_data                  = 4
        OTHERS                   = 5.
    IF sy-subrc <> 0.
      " 记录批次级失败，必要时不继续后续批次
      lv_errs = lv_errs + lv_rows.
    ELSE.
      APPEND LINES OF lt_err TO gt_log.
    ENDIF.
  ENDLOOP.

  IF lv_errs > 0.
    MESSAGE lv_errs = lv_errs WITH 'RFC 推送存在失败行，详见日志。' TYPE 'W'.
  ENDIF.
ENDOFM.
```

要点补充：
- RFC 目标 FM 的 `it_price` 结构应显式包含 `matnr / werks / waers / priceu / value`，**不要复用语义已变的 `netpr`**。
- 若不能接受"远端自动 COMMIT"，则改为 `BAPI_TRANSACTION_COMMIT DESTINATION gs_target WORK = 'Z_FIN_PRICE_PUSH'`，把提交责任显式收回调用方。
- 建议在 `Z_FIN_PRICE_PUSH` 的异常清单里补上 `message`，直接用 `MESSAGE` 的 v1 传回失败原因。

---

## 六、改进建议汇总

### 立即修复（P0，必须在上线前完成）

1. 在 `post_via_bapi` 末尾补 `BAPI_TRANSACTION_COMMIT` / `ROLLBACK`，并按 `RETURN` 的 `E/A` 级消息决定提交还是回滚。
2. **把 DRY RUN 判断上移到主流程**（或每个 FORM 开头），保证任何写操作都被短路。
3. 价格不再写进 `mara-brg ew`，改走 `BAPI_MATERIAL_MAINTAIN` 的 `VALUATIONDATA`（`VPR01/WAERS/PRICEU`），或按业务口径改用 `EKKAP` 场景。
4. 所有 `EXCEPTIONS` 分支判 `sy-subrc`，补齐 `communication_failure`，失败必须 `MESSAGE ... TYPE 'E'/'W'` 并写日志表。
5. RFC 侧补 `bapi_transaction`（或远端 `COMMIT`），明确"谁提交"的契约。

### 结构性改造（P1）

6. 结构体补齐 `brgew / priceu / mgeuw / einwt / mstae`，并引入独立结果字段 `value`，**禁止覆盖源字段**。
7. 干掉 `FOR ALL ENTRIES` 二次查询，首次 `SELECT` 用结构体直接带出 `brgew`。
8. 所有 `READ TABLE` 后判 `sy-subrc`；`FOR ALL ENTRIES` 前判 `gt_change IS INITIAL`。
9. `gt_return` 改用标准 `bapiret2_tab`，调用前 `CLEAR`；日志落持久化表（`ZPP_PUSH_LOG`），字段：matnr/werks/waers/old_value/new_value/msgid/msgno/msgv1/uuid/timestamp。
10. 引入分批：本地按 500 条提交 BAPI，远端按 500 条一包 RFC。
11. 增加 `AUTHORITY-CHECK`（物料主数据维护 + RFC 目标权限），RFC 目标改为白名单常量。
12. 报表输出从 `WRITE` 改为 ALV / `cl_demo_output` + `MESSAGE` 汇总，并输出"总行数 / 成功 / 失败 / 跳过"四个口径。

### 验证与上线（Definition of Done）

- 在 **测试系统**用 `SE37` 无关、**直接在生产副本**跑 3 条物料，用 `SM30` 确认价格真的落库。
- 勾选 DRY RUN，确认 BAPI 与 RFC **均未**产生任何远端日志/变更记录。
- 断开目标系统（停 RFC 目标或改 `QADM`），确认 `sy-subrc = 1` 且报表报 `E`。
- 找一条 `brgew = 0` 的物料，确认走"跳过"分支而不是被清零。
- 用 ATC（ATC 变式勾选 BAPI/远程调用检查项）跑一遍，消灭"必检项"空结果。
- 配置传输日志（`STMS` → 传输日志）或在 BAPI 前后记录 `CDHDR`，保证可追溯。

---

## 七、一句话总结

`read_changes` 查得**多而冗**（brgew 查了丢、丢了再查）；`post_via_bapi` 因为**缺 COMMIT + 参数类型错**实际**改不了本地价格**；`replicate_remote` 因为**不判 sy-subrc + 无事务提交**既**报假成功**又**推的是被算坏的数据**；而价格计算 `netpr × brgew` 本身**量纲、币种、单位、舍入、溢出五项全缺**。四段各自为政、互不校验，DRY RUN 也拦不住 RFC —— 在补齐提交语义、参数正确性、异常处理与口径定义之前，这个程序不具备在生产执行的条件。

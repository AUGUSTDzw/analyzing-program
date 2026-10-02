# ZREPORT_BAPI_UPLOAD 报表程序分析报告

> 分析对象：`zreport_bapi_upload.abap`（126 行，REPORT 报表）
> 分析重点：BAPI 调用正确性、RFC 复制正确性、价格计算正确性
> 结论一句话：**该程序当前无法通过语法检查，且即使修正编译错误，其价格算法字段语义错误、BAPI 缺少 LUW 提交、dry-run 未拦截远端写入、RFC 异常被完全吞掉这四项都属于生产级高危缺陷，不可投产。**

---

## 1. 程序身份与职责

| 项 | 值 |
|---|---|
| 程序名 | `ZREPORT_BAPI_UPLOAD` |
| 类型 | 经典 ABAP 报表（非 OO、无 ALV） |
| 表头注释意图 | 上传采购价变更（通过 BAPI），随后通过 RFC 复制到远端系统 |
| 输入 | `S_MATNR`（物料范围）、`P_DEST`（RFC 目标，默认 `ZFIN`）、`P_DRYRUN`（试运行勾选） |
| 写操作 | 写 MARA（经 BAPI）、RFC 推送远端 `Z_FIN_PRICE_PUSH` |
| 主流程 | `read_changes` → `post_via_bapi` → `replicate_remote` → `show_log` |
| 风险等级 | 🔴 高危（数据损坏 + 远端误写 + 假成功反馈） |

### 执行流总览

```
START-OF-SELECTION
   │
   ├─ read_changes        SELECT marc⋈mara → gt_change
   │                      SELECT mara FOR ALL ENTRIES → gr_weight
   │                      逐行 netpr = netpr * brgew  ← ⚠ 价格计算（见 §4）
   │
   ├─ post_via_bapi       组装 lt_mara(mara) → BAPI_MATERIAL_MAINTAIN
   │                      ⚠ 无 BAPI_COMMIT / 无错误分级（见 §3）
   │
   ├─ replicate_remote    gt_remote = gt_change → RFC Z_FIN_PRICE_PUSH
   │                      ⚠ dry-run 不生效 / 异常全丢（见 §5）
   │
   └─ show_log            WRITE 统计
```

---

## 2. 阻断性问题：程序存在编译期错误

### 2.1 `gr_weight TYPE TABLE OF p` —— 类型声明根本错误（🔴 致命）

```abap
DATA: gr_weight  TYPE TABLE OF p.          " ← 第 28 行
```

`p` 是 ABAP 的**内部 PACKED 定点数类型**（1–16 位小数定点数），不是"类似 MARA 的行结构"。由此产生三重错误：

```abap
SELECT matnr brgew FROM mara INTO TABLE gr_weight   "第 55–58 行：内部表无组件 matnr/brgew → 语法错误
READ TABLE gr_weight INTO DATA(ls_w) WITH KEY matnr = ls_chg-matnr.   "第 61 行：WITH KEY 引用不存在的组件 → 语法错误
ls_chg-netpr = ls_chg-netpr * ls_w-brgew;          "第 62 行：ls_w 不存在组件 brgew → 语法错误
```

**后果**：程序在激活阶段即报 SYNTAX/SET/字段未找到错误，**根本无法编译、无法传输、无法运行**。这也意味着后面所有"运行期风险"在当前代码状态下还不会发生——但一旦有人为了赶工把 `p` 改成某个看似正确的类型（比如 `mara`），下文的语义错误会立即全部暴露。

**正确写法**：

```abap
TYPES: BEGIN OF ty_bwes,
         matnr TYPE mara-matnr,
         bwes  TYPE mara-bwes,
       END OF ty_bwes.
DATA gt_weight TYPE STANDARD TABLE OF ty_bwes WITH EMPTY KEY.
```

（注：正确组件名为 `BWES`（Weight of Base Unit of Measure，基本计量单位重量），不是 `BRGEW`。见下文 §4.2。）

### 2.2 `FOR ALL ENTRIES` 缺空表守卫（🟠 高）

```abap
SELECT matnr brgew FROM mara
  INTO TABLE gr_weight
  FOR ALL ENTRIES IN gt_change
  WHERE matnr = gt_change-matnr.          "第 55–58 行
```

ABAP 的 `FOR ALL ENTRIES` 有一个众所周知且文档化的语义：**当驱动内表为空时，WHERE 条件被完全忽略，等价于全表 SELECT**。若 `s_matnr` 未命中任何物料（`gt_change` 为空），本语句会把 **整个 MARA 表**（通常数十万行）读入内表。

当前后果有限（后续 `LOOP AT gt_change` 也为空，不会做算术），但在只读场景下这是一次静默的全表扫描；而一旦有人"顺手"改成 `SELECT ... FOR ALL ENTRIES` 之外的分页逻辑、或把 `gr_weight` 挪到别处复用，就会变成 dump 或几分钟的运行时长。

**必须补**：

```abap
IF gt_change IS NOT INITIAL.
  SELECT matnr bwes FROM mara
    INTO TABLE gt_weight
    FOR ALL ENTRIES IN gt_change
    WHERE matnr = gt_change-matnr.
ENDIF.
```

### 2.3 `READ TABLE` 未检查 `sy-subrc`

```abap
READ TABLE gr_weight INTO DATA(ls_w) WITH KEY matnr = ls_chg-matnr.   "第 61 行
ls_chg-netpr = ls_chg-netpr * ls_w-brgew;
```

在 `FOR ALL ENTRIES` 生效的前提下能保证命中，因此不是必然 bug；但一旦去掉 FAE、改成逐条 `SELECT SINGLE`（性能优化时的高频改法），未检查 `sy-subrc` 会让 `ls_w-brgew` 静默取 0 或残值，直接进入价格算式。**未检查的 `READ TABLE` 后面紧跟算术运算，是典型的"静默数据损坏"写法。**

---

## 3. BAPI 调用段正确性分析（`post_via_bapi`，第 69–98 行）

### 3.1 🔴 致命：完全缺少 `BAPI_COMMIT WORK`，LUW 不会提交

```abap
CALL FUNCTION 'BAPI_MATERIAL_MAINTAIN'
  TABLES
    materialdata  = lt_mara
    return        = gt_return.          "第 84–87 行
```

`BAPI_MATERIAL_MAINTAIN` 是**带 LUW（Logical Unit of Work）的 BAPI**。ABAP 报表中调用它之后：

- 若未显式 `BAPI_COMMIT WORK`，修改只存在于**当前 SAP LUW 的暂存态**；
- 报表 `END-OF-SELECTION` 结束、SAPLUW 回收时，**若无显式提交，SAPLUW 的 Update task 仍可能执行提交**——但行为取决于程序类型（后台/对话框）、是否有 `COMMIT WORK`、以及 LUW 是否被标记为 Update 任务。
- 无论是否"侥幸"提交，**报告中没有任何一处检查 `gt_return` 中是否存在 `TYPE = 'E'` 的错误消息就直接进入 RFC 推送**，这是逻辑链条上更致命的一环（见 §5.3）。

**结论**：BAPI 调用段**没有形成"校验 → 提交"的完整闭环**。要么不落库（改了但没生效），要么落库但用户与下游都不知道部分失败。

**必须补**：

```abap
LOOP AT gt_return INTO DATA(ls_ret).
  IF ls_ret-type = 'E' OR ls_ret-type = 'A'.
    lv_error = 1.
  ENDIF.
ENDLOOP.

IF lv_error = 1.
  WRITE: / '*** 存在错误，未提交 ***'.
  MESSAGE ID sy-msgid TYPE 'E' NUMBER sy-msgno
    WITH sy-msgv1 sy-msgv2 sy-msgv3 sy-msgv4.
ELSE.
  BAPI_COMMIT WORK.
ENDIF.
```

### 3.2 🔴 致命：把"价格金额"写进"基本单位数量"字段

```abap
CLEAR ls_mara.
ls_mara-matnr = ls_chg-matnr.
ls_mara-brgew = ls_chg-netpr.        "第 78 行：把价格 × 数量 塞进 BRGEW
APPEND ls_mara TO lt_mara.
```

`MARA-BRGEW` 的真实含义是 **Base Unit of Measure（基本计量单位）**，例如 `PC`、`KG`、`M`。它是一个**物料主数据标识字段**，不是一个数量字段，更不是价格字段。程序把 §4 里算出来的"价格×基本单位"的金额写进去，语义上完全错位：

- 如果 BAPI 接受这个值：MARA 的基本单位会被改成一个数字，后续所有按基本单位的数量换算、MRP、单位换算全部错乱；
- 如果 BAPI 静默忽略该字段：整个上传"什么都没发生"，但报表第 94–96 行照样打印 `'uploaded'`，**用户以为成功了**。

### 3.3 🟠 `BRGEW` 通常不是 BAPI 可写字段，且可能被静默丢弃

`BAPI_MATERIAL_MAINTAIN` 的 `MATERIALDATA` 参数对应 `BAPI_MATM1` 类型（`MARA` 的**部分**字段子集）。用 `TABLES` 传入完整的 `mara` 结构会**绕过编译期类型检查**，于是：

- 若 `BAPI_MATM1` 中不包含 `BRGEW`（或该字段在 BAPI 语义中标记为只读/需经单位换算维护），该赋值被**静默丢弃**，无任何警告；
- 基本单位数量的正确维护路径是走 `UNITCONV`（单位换算表 `MARC-UMREN/UMRES`、`MARA-BWES` 联动），或者直接用 `BAPI_MATERIAL_SAVEMATERIALS` 并在扩展字段中处理，**不是**往 `MARA-BRGEW` 硬塞一个值。

**这是一条维护主数据的红线**：主数据字段写错不会立刻报错，但会污染后续所有单据。

### 3.4 🟠 自造 `ty_rmess` 替代 `BAPIRET1`，丢失关键消息信息

```abap
TYPES: BEGIN OF ty_rmess,
         typeid   TYPE char1,       " ← 字段名不是 BAPIRET1 的 TYPE
         msgid    TYPE msgid,
         msgno    TYPE msgnum,
         msgv1    TYPE char50,
         msgv2    TYPE char50,
       END OF ty_rmess.              " 第 15–21 行
```

`BAPI_MATERIAL_MAINTAIN` 的 `RETURN` 参数是 `BAPIRET1` 的表，其标准结构包含 `TYPE`(C1)、`ID`(CHAR12)、`NUMBER`(NUMC3)、`MESSAGE`(CHAR220)、`LOG_NO`(CHAR20)、`MSGV1`–`MSGV4`(CHAR50)。自造结构的代价：

| 缺失字段 | 后果 |
|---|---|
| `TYPE`（改为 `typeid`） | 无法做 `IF type = 'E'` 的错误分级；`typeid` 这个名字还会让读者误以为是"消息类型 ID" |
| `MESSAGE` | 拿不到完整的可读错误文本，排查时只能看到 msgid/msgno/msgv1–v2 |
| `LOG_NO` | 无日志号，无法查 LUW 短 dump 的详细日志 |
| `MSGV3/VSV4` | 参数不完整，错误信息可能被截断 |

**正确做法**：直接 `DATA gt_return TYPE STANDARD TABLE OF bapiret1 WITH EMPTY KEY.`，不要自造。

### 3.5 🟠 `TABLES` 参数使 BAPI 丧失类型保护

`TABLES materialdata = lt_mara` 是老式无类型参数传递。对 BAPI 而言这是**最不推荐**的用法：结构不匹配不会在编译期报错，只在运行期表现为"字段被忽略"或短 dump。改用 `EXPORTING` / 表类型的正式参数可获得完整的编译期检查。

### 3.6 🟡 `p_dryrun` 判断位置不当

```abap
LOOP AT gt_change INTO DATA(ls_chg).   " 第 74–81 行：先花力气组装 lt_mara
  ...
ENDLOOP.

IF p_dryrun IS INITIAL.                 " 第 83 行：才判断是否 dry run
  CALL FUNCTION 'BAPI_MATERIAL_MAINTAIN' ...
ENDIF.
```

dry-run 分支下 `lt_mara` 被完整构造却从不使用。功能上无害（浪费一次内表构造），但**它暴露了更严重的问题**——见 §5.2：dry-run 的守卫只包住了 BAPI，没有包住 RFC。

### 3.7 🟡 逐行 BAPI，无包络、无失败统计

`gt_change` 每行一个 `BAPI_MATERIAL_MAINTAIN` 调用（虽然 `werks` 被固定为 `'A100'` 使物料维度基本唯一，但按设计仍是一物料一次 FM 调用）。物料数量大时：

- FM 调用次数线性增长，ABAP LUW 中累积大量 BAPI 帧；
- 报表第 90–96 行**没有 error/warning 计数**，只在最后 `WRITE` 两行总数（第 121–125 行），无法自动化判定成败；
- 失败行没有标记，无法只重推失败数据。

---

## 4. 价格计算正确性分析（重点，第 49–64 行）

这是本程序**问题最集中的部分**。按"读什么 → 算什么 → 写什么"三步拆开：

### 4.1 🔴 算式本身没有业务含义

```abap
ls_chg-netpr = ls_chg-netpr * ls_w-brgew;      " 第 62 行
```

`MARC-NETPR` 是**采购净价**（Purchasing Net Price），其含义是"**每一个基本单位**的价格"（价格单位由 `MARC-UMREN/UMRES` 的采购单位换算决定）。既然已经是"每单位价格"，再乘以"基本单位数量"，在业务上不构成任何有意义的量纲：

| 操作 | 量纲 | 是否业务合法 |
|---|---|---|
| `NETPR` | 货币 / 基本单位 | ✅ 合法 |
| `BRGEW` | 无量纲（它是**基本计量单位本身**，如 `PC`/`KG`） | ❌ 不是数量 |
| `NETPR * BRGEW` | 混量纲 | ❌ 无意义 |

如果意图是"折算成每公斤价格"，正确形式应是**除法**：

```abap
ls_chg-netpr = ls_chg-netpr / ls_w-bwes * 1000.   " 假设 BWES 单位为 g，换算成每 kg
```

### 4.2 🔴 取错了字段：`BRGEW` 不是重量，`BWES` 才是

这是本程序最容易被误读、也最致命的一处：

| 字段 | 真实 SAP 含义 | 中文 |
|---|---|---|
| `MARA-BRGEW` | **B**ase **R**eference Unit of **GE**asurement → Base Unit of Measure | **基本计量单位**（如 PC / KG / M） |
| `MARA-BWES` | **B**ase Unit of Measure **W**eight → Weight of Base Unit of Measure | **基本计量单位的重量**（重量类字段） |

程序第 49 行 `SELECT ... mara~brgew`、第 55 行 `SELECT matnr brgew FROM mara`、第 62 行 `ls_w-brgew`——**全程把"基本单位"当作"基本单位重量"来乘**。变量名 `gr_weight`（weight）进一步印证了作者的心智模型是"重量"，但代码取的是"单位"。

**正确字段应为 `BWES`。** 而且 `BWES` 属于重量字段、也只在物料有重量属性时有意义，需要按业务实际选字段（纯计数物料 `BWES` 为 0，见 §4.4）。

### 4.3 🔴 原地覆盖，原始采购价永久丢失

```abap
ls_chg-netpr = ls_chg-netpr * ls_w-brgew;   " 写回同一字段
MODIFY gt_change FROM ls_chg.                " 覆盖原值
```

乘积被写回 `netpr` 自身，`gt_change` 中原有的真实采购净价被销毁。这意味着：

1. **无法回退**：一旦这批数据被推送到远端（§5），本地原始值已无副本；`MARC` 中也未备份。
2. **可重入性被破坏**：程序若再跑一次（或部分行重跑），会**在已被污染的值上再乘一次** —— 结果随执行次数变化，完全不可预测。这是典型的"非幂等"程序，属于生产事故级设计缺陷。
3. **金额字段存了非金额值**：`marc-netpr` 类型为 `CURR 15,3`，而 `mara-brgew` 为 `CURR 13,3`，乘积需要 28 位十进制精度，写回 15,3 会**发生舍入**，大金额场景静默丢精度。

**正确做法**：用独立字段存放计算结果，绝不覆盖源值。

```abap
TYPES: BEGIN OF ty_chg,
         matnr    TYPE mara-matnr,
         werks    TYPE marc-werks,
         netpr    TYPE marc-netpr,     " 原始值，只读
         waers    TYPE marc-waers,
         calpr    TYPE p DECIMALS 6,   " 计算结果另存
       END OF ty_chg.
```

### 4.4 🔴 未处理 `BRGEW`/`BWES` 为空或 0 → 批量把价格清零

第 61–62 行未做任何有效性检查。`BWES`/`BRGEW` 为 initial（0）在以下场景很常见：非重量类物料、无单位换算的物料、新建未维护的物料。

此时 `netpr * 0 = 0`，**该物料的采购价被静默置零**，随后被 BAPI 写回并被 RFC 推送到远端。这是最直接的**批量数据损坏**路径，而且报表第 94–96 行仍然打印 `'uploaded'`。

**必须补守卫**：

```abap
IF ls_w-bwes IS INITIAL OR ls_w-bwes <= 0.
  WRITE: / '跳过：无有效基本单位重量', ls_chg-matnr.
  DELETE gt_change.
  CONTINUE.
ENDIF.
```

### 4.5 🟠 币种 `WAERS` 完全未参与计算

`ty_chg` 读了 `waers`，但：

- 算式中没有任何汇率换算，跨币种（EUR/USD/CNY）数据被混入同一个内表；
- 若下游（远端 `Z_FIN_PRICE_PUSH`）按单一币种汇总，直接得到无意义的总额；
- RFC 传了 `waers` 字段，但远端是否识别未知——如果远端忽略该字段，跨币种数据会**静默按同一币种入账**。

应按 `waers` 分组，或先调用 `CURRENCY_CONVERSION` / `SAP_CONVERT_TO_INTERN_FORMAT` 归一。

### 4.6 🟠 忽略了 `MARC` 的采购单位换算

`NETPR` 的价格单位由 `MARC-UMREN/UMRES` 决定（采购单位 → 基本单位）。真正做"折算"必须把 `UMREN/UMRES` 纳入：

```abap
" 每基本单位价格 = 采购价 × UMREN / UMRES
```

程序只 SELECT 了 `netpr/waers`，**没有读 `umren/umres`**，因此任何"单价 vs 重量"换算都缺少必要的换算基准。

### 4.7 🟡 SELECT 未限定包大小，未做数量上限保护

```abap
SELECT marc~matnr marc~werks marc~netpr marc~waers mara~brgew
  FROM marc INNER JOIN mara ON mara~matnr = marc~matnr
  INTO TABLE gt_change
  WHERE marc~matnr IN s_matnr AND marc~werks = 'A100'.    " 第 49–53 行
```

- `s_matnr` 允许留空 → 无 `low` 下界时走全表 `MARC⋈MARA`；
- 无 `PACKAGE SIZE`，`gt_change` 与 `lt_mara` 一次性全量进内存，随后还有一份 `gt_remote` 拷贝（第 105 行）——**三份数据同驻内存**；
- `WRITE` 输出与 BAPI/RFC 混排（第 91、95、116、123–124 行），无法做后续统计分析，也没有 spool 拆分。

---

## 5. RFC 复制段正确性分析（`replicate_remote`，第 101–118 行）

### 5.1 🔴 致命：`lv_ok` 声明了却从未赋值、从未使用，异常全部被吞

```abap
DATA lv_ok TYPE c.                    " 第 103 行

CALL FUNCTION 'Z_FIN_PRICE_PUSH'
  DESTINATION gs_target
  TABLES it_price = gt_remote
  EXCEPTIONS
    system_failure = 1
    destination_unavailable = 2
    OTHERS = 3.                       " 第 107–114 行

WRITE: / 'replicated to', p_dest.     " 第 116 行：无条件打印
```

这是全程序**最危险的一行**：

- `lv_ok` 从未被赋任何值 → 三个 EXCEPTIONS 编号 `1/2/3` 被**完全丢弃**；
- 第 116 行 `WRITE` **不在任何条件判断内** → 无论 `SYST-SUBRC` 是 0 还是 1/2/3，都打印"replicated to ZFIN"；
- 因此 `show_log`（第 121–125 行）会输出"total N, messages M"，**看起来像一次完全成功的运行**。

**故障场景**：远端系统宕机 / RFC 链路断 / 目标程序在远端不存在（RFC 4xx）→ `destination_unavailable` → 报表照样报"replicated to ZFIN"，运维据此认为远端已同步，**数据在远端缺失且无人知晓**。这是典型的"假成功"（silent failure）缺陷，属于必须上生产前清零的问题。

**必须补**：

```abap
CASE sy-subrc.
  WHEN 0.
    WRITE: / 'replicated to', p_dest.
  WHEN 1.
    MESSAGE '目标系统通信失败（system_failure）' TYPE 'E'.
  WHEN 2.
    MESSAGE '目标系统不可用（destination_unavailable）' TYPE 'E'.
  WHEN OTHERS.
    MESSAGE 'RFC 调用失败' TYPE 'E'.
ENDCASE.
```

### 5.2 🔴 致命：`P_DRYRUN` 完全没有覆盖 RFC —— "试运行"照样写远端

```abap
IF p_dryrun IS INITIAL.      " 第 83 行：只包住 BAPI
  CALL FUNCTION 'BAPI_MATERIAL_MAINTAIN' ...
ENDIF.
...
PERFORM replicate_remote.    " 第 44 行：主流程无条件调用
```

主流程第 42–45 行：

```abap
PERFORM read_changes.
PERFORM post_via_bapi.
PERFORM replicate_remote.    " ← 不看 p_dryrun
PERFORM show_log.
```

`replicate_remote` 内部**没有任何 `p_dryrun` 判断**。所以用户在选择屏幕上勾选了"试运行"，期望"只看不动"，实际结果是：

- BAPI 被跳过 ✅（符合预期）
- **RFC 被执行，真实数据被推送到远端系统** ❌（完全违背预期）

这是**dry-run 语义被绕过**的严重缺陷。运维人员用 dry run 验证参数时的标准动作，恰恰会污染远端生产系统。**必须补**：

```abap
FORM replicate_remote.
  IF p_dryrun = 'X'.
    WRITE: / '*** DRY RUN: 跳过 RFC 推送，目标 =', p_dest.
    WRITE: / '*** 将推送', lines( gt_remote ), '行'.
    EXIT.
  ENDIF.
  ...
ENDFORM.
```

### 5.3 🔴 致命：推送的是"想写"的值，不是"已生效"的值

```abap
gt_remote = gt_change.     " 第 105 行：直接复制内存内计算结果
```

- `gt_change` 来自**读取时的**内存值，与 BAPI 的执行结果**没有任何回读校验**；
- BAPI 部分失败（`gt_return` 中有 `'E'`）的行**照样被推送到远端**（第 90–96 行的 `LOOP` 只是 `WRITE`，没有任何过滤/标记逻辑）；
- BAPI 未 `COMMIT`（§3.1），远端如果通过反向调用回读本地 DB，读到的是**未提交/不一致**状态；
- 本地与远端会形成**长期数据分叉**，且没有任何对账机制。

**正确做法**：先 commit，再**重读数据库确认生效值**，只推送真正成功的行：

```abap
" 1) BAPI + 错误分级 + BAPI_COMMIT
" 2) 失败行从 gt_change 中 DELETE（或置标记 'status' = 'E'）
" 3) 重新 SELECT netpr/waers FROM marc 读取实际生效值
" 4) 用重读值构造 gt_remote 再推送
```

### 5.4 🔴 致命：`P_DEST` 可为空，空 `DESTINATION` 会在**本地系统**执行 RFC

```abap
PARAMETERS p_dest TYPE rfcdest DEFAULT 'ZFIN'.   " 第 33 行
INITIALIZATION.
  gs_target-rfcdest = p_dest.                    " 第 37–38 行
```

`p_dest` 是**非必填**的 `PARAMETERS`，用户可以清空。此时 `gs_target-rfcdest` 为空，而 ABAP 中：

> `CALL FUNCTION ... DESTINATION` 传入**空值**时，被调用的函数模块在**本地系统**执行。

后果：`Z_FIN_PRICE_PUSH` 会在**本地系统**被调用。如果该程序只在远端存在，本地会 short dump；如果本地恰好也有同名程序（不同逻辑），则**静默在本地执行了本应属于远端的写操作**。

**必须补**：

```abap
START-OF-SELECTION.
  IF p_dest IS INITIAL.
    MESSAGE '请指定 RFC 目标系统（P_DEST）' TYPE 'E'.
  ENDIF.
```

并且生产上建议改用 F4 从 `TRFC_NPLU` 维护目标系统（当前 `TYPE rfcdest` 的普通输入框**无值校验、无候选列表**，输入 `ZFNN` 这种手误会得到 `destination_unavailable`——而 §5.1 已证明这个错误现在是被吞掉的）。

### 5.5 🟠 RFC 接口类型 `ty_chg` 不是字典类型 → 目标 FM 无法建接口

`tRFC` 的接口在 SE37 中定义，**参数类型必须是数据字典类型**（结构、表、元素）。`ty_chg` 是本 REPORT 内联定义的**局部类型**：

```abap
TYPES: BEGIN OF ty_chg, ... END OF ty_chg.   " 第 8–13 行
```

`Z_FIN_PRICE_PUSH` 无法以 `ty_chg` 为参数类型建立有效的 tRFC 接口。若强行在 SE37 用一个不兼容的自定义结构接收，RFC 传输时会因**结构不兼容**触发 short dump（如 `CONVT_NO_NUMBER` / 字段长度不符），而且——**这个错误发生在远端，本地 `SYST-SUBRC` 可能仍为 0**，再次落进 §5.1 的"假成功"陷阱。

**必须**把 `ty_chg` 提升为独立的字典结构（如 `ZFPRICE_CHG`，或直接复用字典结构 `ZFIN_PRICE_LINE`），并在 SE37 中基于它建接口。

### 5.6 🟡 未提交数据即跨系统传输 / 无分包

- RFC 传输的数据属于**调用方 LUW 的未提交状态**。若远端逻辑在同一事务内反向查本地，会读到不一致视图；
- `gt_remote` 一次性全量传给 `it_price`，物料数很大时会超出 RFC 单次数据量限制（且无 PACKAGE 分包）；
- RFC 调用**不做 LUW 边界隔离**，远端若耗时较长会长时间占用调用方的连接与 LUW。

### 5.7 🟡 缺少 MESSAGE 化的错误提示

BAPI/RFC 失败对用户只应体现为 `MESSAGE ... TYPE 'E'/'W'`，本程序全部用裸 `WRITE` 输出到列表，交互场景下用户必须翻到列表末尾才能发现问题。

---

## 6. 问题清单（按严重度汇总）

### 🔴 阻断级（不修复禁止投产）

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| 1 | L28, L55–62 | `gr_weight TYPE TABLE OF p` 类型错误 | **程序无法编译/激活** |
| 2 | L62 | `netpr * brgew`：算式无业务含义（价格已是每单位价） | 价格数据错误 |
| 3 | L49/55/61/62 | 用 `BRGEW`（基本单位）当重量，实际应为 `BWES` | 字段语义误用 |
| 4 | L62 | 原地覆盖 `netpr`，原始采购价不可恢复 | 不可逆数据损失、程序非幂等 |
| 5 | L62 | 未校验分母/因子为 0 | **批量把采购价置零** |
| 6 | L78 | 把价格金额写入 `MARA-BRGEW`（基本单位字段） | 主数据污染 |
| 7 | L84–87 | 缺 `BAPI_COMMIT WORK` | 改动不落库或状态不明 |
| 8 | L90–96 | 未按 BAPI 返回消息分级即宣告 `uploaded` | 失败被当成功 |
| 9 | L103/107–116 | `lv_ok` 未赋值未使用，RFC 异常全吞 | **假成功**，远端未同步却报成功 |
| 10 | L44, L101 | `P_DRYRUN` 不覆盖 RFC | **试运行仍真实写远端** |
| 11 | L105 | 推送未经 BAPI 校验的内存值 | 本地/远端数据分叉 |
| 12 | L33, L38 | `P_DEST` 可为空 → 空 `DESTINATION` 在本地执行 | 本地误执行/short dump |
| 13 | L8–13, L110 | `ty_chg` 为局部类型，非字典类型 | tRFC 接口不可用/远端 short dump |
| 14 | L55–58 | `FOR ALL ENTRIES` 无空表守卫 | 空结果时全表 MARA 扫描 |

### 🟠 高危

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| 15 | L11, L78 | `MARA-BRGEW` 很可能不是 `BAPI_MATM1` 可写字段 | 写入被静默丢弃，"什么都没发生" |
| 16 | L15–21 | 自造 `ty_rmess` 替代 `BAPIRET1`，缺 `TYPE`/`MESSAGE`/`LOG_NO` | 无法做错误分级，排查困难 |
| 17 | L86 | `TABLES` 无类型参数传 BAPI | 丧失编译期类型保护 |
| 18 | L61 | `READ TABLE` 未检查 `sy-subrc` | 后续重构易引入静默 0 值 |
| 19 | L12, L62 | `waers` 参与不完整，无汇率换算 | 跨币种金额混算 |
| 20 | L49–53 | 未读 `MARC-UMREN/UMRES` | 缺换算基准，换算不可靠 |
| 21 | L49–53 | 无 `PACKAGE SIZE`，`s_matnr` 可留空 | 全表读，三份内数组同驻内存 |

### 🟡 改进项

| # | 位置 | 问题 |
|---|---|---|
| 22 | L74–83 | dry-run 判断在构造 `lt_mara` 之后，逻辑顺序倒置 |
| 23 | L74 | 逐条 BAPI，无包络、无错误统计 |
| 24 | L91/95/116/123 | 裸 `WRITE` 混排，无 ALV、无 spool、无法二次处理 |
| 25 | L33 | `TYPE rfcdest` 无 F4/无校验，建议从 `TRFC_NPLU` 维护 |
| 26 | L42–45 | 空结果未提前 return，仍会调 BAPI 与 RFC |
| 27 | — | 无一致性对账、无 `WAERS` 分组、无失败行可重推标记 |

---

## 7. 改进建议

### 7.1 立即修复（上线阻断）

1. **修正类型声明**：`gr_weight` 改为真正含 `matnr`/`bwes` 的行结构，解除编译错误。
2. **重写价格计算**：分母取 `MARA-BWES`（基本单位重量），0 值直接 `DELETE` 该行并输出跳过日志；结果**写入新字段**，绝不覆盖 `netpr`。
3. **写入正确的 BAPI 字段**：BAPI 阶段应更新**价格字段**（如 `MARC-NETPR`，且需确认目标 BAPI 的物料视图/价格视图参数），**绝不写 `MARA-BRGEW`**。
4. **补 `BAPI_COMMIT WORK` + 错误分级**：先扫 `gt_return` 找 `'E'`/`'A'`，有错则 `MESSAGE ... TYPE 'E'` 终止；无错才 commit。
5. **`REPLICATE_REMOTE` 开头加 dry-run 短路**，`EXIT` 前打印"将推送 N 行"。
6. **补 RFC 异常处理**：`CASE sy-subrc` 四个分支分别处理，至少要 `MESSAGE ... TYPE 'E'`，绝不能让"replicated to"无条件打印。
7. **`P_DEST` 必填校验**：`IF p_dest IS INITIAL. MESSAGE ... TYPE 'E'.`

### 7.2 结构性改进

8. **接口类型字典化**：把 `ty_chg` 提升为 `ZFIN_PRICE_LINE` 字典结构，RFC 目标 FM 基于它建接口；同时把 `ty_rmess` 换成 `BAPIRET1`。
9. **BAPI → commit → 重读 → 推送的正确顺序**：

```abap
START-OF-SELECTION.
  PERFORM read_changes.
  PERFORM calc_price.          " 原始值与计算值分列存储
  PERFORM post_via_bapi.       " 分级 + BAPI_COMMIT
  PERFORM reread_effective.    " 从 DB 重读实际生效值
  PERFORM replicate_remote.    " dry-run 守卫 + RFC 异常处理
  PERFORM show_log.
```

10. **BAPI 参数改用正式类型化接口**（不用 `TABLES`），把 `mara` 全结构传参改为只填必要字段的显式结构。
11. **主数据与价格分离**：程序应只改价格，**绝不触碰物料主数据标识字段**（`BRGEW`/`BWES`/`MEINS` 等）。若业务真要改主单位重量，那是独立的主数据变更流程。
12. **大结果集处理**：`SELECT` 加 `PACKAGE SIZE`，`s_matnr` 设为必填，RFC 推送按包分批。
13. **输出改造**：用 ALV 或结构化日志（ALIVEL 日志表）替代裸 `WRITE`，至少记录：行数、错误数、警告数、跳过数、提交时间、目标系统。
14. **增加对账**：复制完成后在远端回读行数做比对，或在远端记录推送流水以便反查。

---

## 8. 建议的验证步骤（修完后）

1. `SE38` 激活，确认无 SYNTAX/SET 错误（当前因 `TABLE OF p` 必失败）。
2. **纯 dry-run + 小范围**：`S_MATNR = 单个已知物料` + `P_DRYRUN = X`，确认：远端**无任何写入痕迹**（这是当前版本会失败的关键验证点）。
3. **静态比对**：dry-run 输出的计算值 vs 手工在 Excel 里用 `NETPR / BWES` 算的值，逐物料核对。
4. **`BRGEW`/`BWES = 0` 的物料**：挑一个非重量类物料，确认被**跳过并有日志**，而不是被写 0。
5. **可回滚验证**：在测试系统对单个物料跑真实上传，commit 后立即用 `SELECT` 从 `MARC` 读回，确认值确实是想要的值且 BAPI 没有静默忽略。
6. **RFC 故障注入**：故意填一个不存在的目标系统名，确认报表**报红并终止**，而不是打印 "replicated to"（这是当前版本的确定性失败点）。
7. **重入验证**：同一批物料连续跑两次，确认第二次结果与第一次**完全一致**（幂等性）。当前版本因原地覆盖，第 2 次结果会是第 1 次的平方倍。
8. **币种验证**：跨 `WAERS` 跑一次，确认远端入账未混币。

---

## 9. 总评

| 维度 | 评价 |
|---|---|
| 结构可读性 | 尚可：四段式 PERFORM 分工清楚，命名基本达意 |
| 编译可用性 | ❌ **无法编译**（`TABLE OF p`） |
| 取数 | ⚠️ 字段语义误用（`BRGEW` vs `BWES`）、缺 `UMREN/UMRES`、无 `PACKAGE SIZE` |
| 价格计算 | ❌ **量纲错误 + 原地覆盖 + 零值未守卫**，具备批量数据损坏能力 |
| BAPI 调用 | ❌ 缺 commit、无错误分级、写入非 BAPI 字段、自造 return 结构、`TABLES` 传参 |
| RFC 复制 | ❌ **dry-run 形同虚设**、异常全吞导致假成功、空 destination 落本地、接口类型不可用、未校验结果即推送 |
| 错误处理 | ❌ 唯一错误处理路径是 `WRITE`，无 `MESSAGE`、无 `sy-subrc` 消费 |
| 综合结论 | **高危、不可投产**。属于典型的"看起来能跑、实际每一步都在制造不一致"的报表程序：三个关键阶段（计算 / 提交 / 复制）各有一处会导致数据错误或错误反馈被掩盖的缺陷，且缺少任何失败可见性机制。 |

**建议处置**：不做局部修补，按 §7.2 的"计算值与原值分离 → BAPI 分级提交 → 重读生效值 → 推送带守卫"四段式重构；在此之前至少先修 §7.1 的 7 项阻断问题，并在测试系统完成 §8 的 8 项验证。

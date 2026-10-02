# ZORDER_DIALOG 走读报告 —— 订单录入对话程序

> 被分析文件：`evals/zorder_dialog.abap`（128 行，`REPORT zorder_dialog.`）
> 关注重点：选择屏幕事件块、屏幕 0100 的 PBO/PAI 模块、保存（`save_order`）逻辑的风险

---

## 0. 一句话结论

这个程序**当前状态下无法正常工作**：屏幕 0100 从未被填充数据（所以点保存必然被 `MESSAGE ... 'E'` 拦下）、`SAVE` 功能码在 `user_command_0100` 里只做了 `SET SCREEN 0100` 而**根本没调用 `save_order`**、而 `save_order` 本身的写法是**把刚刚从 VBAK 读出来的行再 INSERT 回 VBAK**，属于"必然重复键 + 直接写标准表 + 无条件 COMMIT"的三重高危组合。下面逐段拆解。

---

## 1. 整体结构与执行流

### 1.1 对象一览

| 类别 | 名称 | 备注 |
|---|---|---|
| 全局类型 | `ty_order` / `ty_order_tab` | 6 字段：VBELN KUNNR WAERK NETWR MENGE |
| 全局数据 | `gt_order`、`gs_order`、`gv_user`、`gv_datum`、`gv_init` | `gv_init` 从未被使用（死变量） |
| 选择屏幕 | BLOCK `b1`：`s_vbeln`、`p_waerk` | 标题 `TEXT-001` |
| 事件块 | `INITIALIZATION`、`AT SELECTION-SCREEN OUTPUT`、`AT SELECTION-SCREEN ON VALUE-REQUEST`、`START-OF-SELECTION` | |
| Dynpro | `0100`（由 `CALL SCREEN 0100` 调用） | PF-STATUS `S0100`，标题栏 `T0100` |
| PBO 模块 | `status_0100 OUTPUT` | |
| PAI 模块 | `user_command_0100 INPUT`、`save_order INPUT`、`back INPUT` | |

### 1.2 事件时间线（标准执行顺序）

```text
1  INITIALIZATION                       gv_datum / gv_user 赋值（后续没人用）
2  AT SELECTION-SCREEN OUTPUT            P_WAERK 设高亮
3  (用户交互)  AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln   ← F4
4  START-OF-SELECTION                    SELECT VBAK → gt_order；CALL SCREEN 0100
5  0100 PBO   → status_0100              PF-STATUS / TITLEBAR / P_WAERK 只读
6  0100 PAI   → user_command_0100        SAVE→0100、BACK/EXIT/CANC→0000
7  (未被调用) save_order / back
```

### 1.3 屏幕流（Screen Flow）

```text
START-OF-SELECTION ──CALL SCREEN 0100──▶ 0100
                                        │ user_command: SAVE ─▶ SET SCREEN 0100（原地打转）
                                        │ user_command: BACK/EXIT/CANC ─▶ SET SCREEN 0000
                                        └─ 0000 并不是一个真实 dynpro，
                                           SET SCREEN 0000 之后没有 LEAVE / CALL TRANSACTION 收尾
```

**结论：屏幕流是断的。** 退出路径上有三种写法（`SET SCREEN 0000`、`SET SCREEN 0000 + LEAVE PROGRAM`、`SET SCREEN 0000`）互相不一致；`save_order` 和 `back` 两个 PAI 模块**没有任何地方引用**——它们既不在 `user_command_0100` 的 `CASE` 里被调用，也不在 0100 的屏幕流逻辑里（Flow Logic）出现（该 .screen 文件不在交付范围内，见第 8 节）。

---

## 2. 选择屏幕分析

### 2.1 定义

```abap
SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
  SELECT-OPTIONS s_vbeln FOR gs_order-vbeln.   "← 挂在业务结构的一个组件上
  PARAMETERS p_waerk TYPE waerk DEFAULT 'EUR'.
SELECTION-SCREEN END OF BLOCK b1.
```

**问题 1：`s_vbeln` 的数据参照对象是 `gs_order-vbeln`，即"业务记录"和"选择范围"复用了同一块内存。**
`gs_order` 在本程序里被当成"当前订单行"使用（`save_order` 就是这么用的），而 `s_vbeln` 把它当选择屏的参照字段。两者语义互斥：只要有人往 `gs_order` 里写数据，选择屏的 `VBELN` 范围值就被改写。

**问题 2：F4 帮助会把用户输入的值清空。**

```abap
AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln.
  READ TABLE gt_order INTO gs_order INDEX 1.    "gs_order 被整体覆盖
  MESSAGE 'No order data loaded yet' TYPE 'S'.
```

- 这个事件块在 `START-OF-SELECTION` **之前**执行，而 `gt_order` 只有在 `START-OF-SELECTION` 里才被 `SELECT ... INTO TABLE` 填充 → **`gt_order` 必然为空**，这条消息是"永远为真"的死逻辑。
- `READ TABLE ... INDEX 1` 在空表上不抛异常（`sy-subrc = 4`），但会把 `gs_order` **清空**；而 `gs_order` 是 `s_vbeln` 的参照对象 → 用户之前输入/选择的 VBELN 被静默抹掉。
- 而且 `MESSAGE ... TYPE 'S'` 只是弹个成功条，不会终止 F4，用户按了 F4 之后既没值也没下拉，**只能看到一个"没数据"的提示**，形成一个死胡同。
- F4 挂在 **SELECT-OPTIONS** 上本身就是非典型用法（SELECT-OPTIONS 的 F4 只能设单值），标准做法是挂搜索帮助（`AT SELECTION-SCREEN ON HELP-REQUEST` / `SEARCH HELP`）或改成 `PARAMETERS`。
- 完全没有 `sy-subrc` 判断。

### 2.2 `AT SELECTION-SCREEN OUTPUT`

```abap
LOOP AT SCREEN.
  IF SCREEN-NAME = 'P_WAERK'.
    SCREEN-INTENSIFIED = '1'.
    MODIFY SCREEN.
  ENDIF.
ENDLOOP.
```

- 逻辑正确（OUTPUT 事件里 `MODIFY SCREEN` 的合法用法），只是 `SCREEN-NAME` 硬编码字符串。
- 没有 `AT SELECTION-SCREEN` / `AT SELECTION-SCREEN ON HELP-REQUEST` 里的**权限预检**（SAP 标准做法是在 START-OF-SELECTION 前就 `DCL` 校验），所以未授权用户会先白读一次数据。

### 2.3 `START-OF-SELECTION`

```abap
SELECT vbeln kunnr waerk netwr menge
  FROM vbak INTO TABLE gt_order
  WHERE vbeln IN s_vbeln
    AND waerk = p_waerk.
```

| 风险 | 说明 |
|---|---|
| **未判 `s_vbeln` 非空** | `IN` 的范围为空（初始值）时条件不生效 → 变成"该币种的全部订单"全表捞。无 `UP TO n ROWS`、无分段取数，大结果集可能 dump / 吃掉工作目录。至少要 `IF s_vbeln[] IS INITIAL` 校验 + `UP TO 500 ROWS`。 |
| **`MENGE` 字段可能不属于 VBAK** | 订单数量 `MENGE` 通常在**明细表 VBAP** 上，表头 VBAK 没有该字段。若确实没有，这句 SELECT 在激活或运行时会直接报错。请用 SE11 确认后再定；确认存在也建议把数量从 VBAP 单独取。 |
| **选币种无校验** | `p_waerk` 只有 DEFAULT 'EUR'，没有 `CHECK TABLE OF waerk` / 值域校验，用户可以随便敲 `XXX`。 |
| **无权限检查** | 直接读客户订单头，属于最小权限原则的破口。 |
| `CALL SCREEN 0100` 直接跟在 `START-OF-SELECTION` 后 | 合法（这是 7.40 前的经典写法），但意味着程序是"选择屏 → 直接跳 Dynpro"，**没有列表页**，`SET SCREEN 0000` 之后无处可回；标准的 7.40+ 做法是列表用 `WRITE`/ALV + `AT LINE-SELECTION`，或直接 `CALL SCREEN` 后用 `CALL TRANSACTION` 收尾。 |

---

## 3. 屏幕 0100 的 PBO：`status_0100 OUTPUT`

```abap
SET PF-STATUS 'S0100'.
SET TITLEBAR 'T0100'.

LOOP AT SCREEN.
  IF SCREEN-NAME = 'P_WAERK'.
    SCREEN-DISPLAY-MODE = '1'.
    MODIFY SCREEN.
  ENDIF.
ENDLOOP.
```

**这是整个程序最关键的"缺失点"。**

1. **没有任何一次性初始化逻辑。** 程序声明了 `gv_init TYPE abap_bool`，显然原意是"PBO 首次进入时把 `gt_order` 的第一行搬到屏幕字段上"，但 `gv_init` 从未被赋值/判断，`gs_order` 也从未被 `gt_order` 填充。后果：0100 屏幕上一片空白 → 用户点保存 → `save_order` 第一句 `IF gs_order-vbeln IS INITIAL` 成立 → 必然弹 `'Sales order number is mandatory'`。**这个程序在正常路径下永远走不到保存。**
2. **`SET PF-STATUS 'S0100'` 无异常保护。** 如果状态 `S0100` 没建好（很常见），在 PBO 里会直接 **short dump**（`SET PF-STATUS` 不会像某些 FM 那样给你 `sy-subrc`）。稳妥写法是先用 `PF-STATUS` 表查询存在性，或把状态建进事务里。
3. **字段名假设未经验证。** PBO 里假设 0100 上有个叫 `P_WAERK` 的字段——但 0100 的字段名是 Screen Painter 定的，交付物里**没有 .screen 文件**（第 8 节）。如果实际叫别的名字，`MODIFY SCREEN` 静默不生效，币种仍可被修改。
4. **复用了选择屏变量名做 Dynpro 字段名**，语义混乱。0100 上应该用独立命名的字段（如 `gv_waerk`）并配套 `MODULE ... INPUT`。
5. `SCREEN-DISPLAY-MODE = '1'` 是只读，但**没有把订单号、行项目、金额等字段设为输出模式**（`OUTPUT`），可编辑的输入字段与"修改订单"的语义可能相反。
6. 每次 PBO 都 `SET PF-STATUS` / `SET TITLEBAR`（无害，但 PBO 会在每个 AT-SELECTION-SCREEN 之后被反复触发，标准做法可以接受）。
7. **没有 `MODULE ... INPUT` 配套的字段初始化**、没有 `SCREEN-DISPLAY-MODE = 'L'`（可选）等细节，也没有把 `gt_order` 的行号/选中行传给屏幕（没有 `sy-ucomm` 级别的行选择处理）。

---

## 4. PAI：`user_command_0100`

```abap
DATA lv_ok_code TYPE sy-ucomm.
lv_ok_code = ok_code.
CLEAR ok_code.

CASE lv_ok_code.
  WHEN 'SAVE'.       SET SCREEN 0100.
  WHEN 'BACK' OR 'EXIT'.  SET SCREEN 0000.
  WHEN 'CANC'.       SET SCREEN 0000.
ENDCASE.
```

问题：

1. **SAVE 根本不触发保存。** `SET SCREEN 0100` 只是"留在当前屏"，`save_order` 从未被调用 → 用户点保存**毫无反应**（只在原地重走一次 PBO）。要触发模块，得在 0100 的屏幕流逻辑里把 `SAVE` 映射到 `MODULE save_order`，或者在 `CASE` 里用 `ok_code` 派发（`SET OK-CODE` + `CALL SCREEN`，或直接调方法）。这是**功能性断链**，不是风格问题。
2. **`ok_code` 未声明。** 对话程序必须有 `DATA ok_code TYPE sy-ucomm`（或用生成 include 里的同名变量），本程序里没有声明 → 按现状**激活就会报语法错误**。
3. **`'EXIT'` 复用了标准 OK-Code 语义。** `EXIT` 在 SAP 里是"退出程序"的标准码，跟"返回"混用会跟系统/ALV 的标准命令打架；返回一般用 `BACK` / `ENDE`。
4. **无 `ELSE` 分支。** 未知 F-code 被静默吞掉（`F1`/`F4`/`F12` 等），用户会以为程序没反应。
5. **退出路径只有 `SET SCREEN 0000`，没有 `LEAVE PROGRAM` / `CALL TRANSACTION` / `SUBMIT ...`**。而 `back` 模块里又写了 `SET SCREEN 0000 + LEAVE PROGRAM`——两种风格并存，且 `back` 没人调用。`SET SCREEN 0000` 在"从 START-OF-SELECTION 调进来的 Dynpro"场景下**不会显示任何屏幕**，通常导致进程空转或直接结束（回到选择屏），用户体感是"闪一下就没了"。
6. 缺少 `AT USER-COMMAND` 层面的统一处理（例如把标准 `BACK`/`ENDE` 归一化）。

---

## 5. 【重点】保存逻辑 `save_order` 的风险

```abap
DATA lv_check TYPE c LENGTH 1.          " ← 声明后从未使用（死代码）
DATA ls_order TYPE ty_order.

IF gs_order-vbeln IS INITIAL.
  MESSAGE 'Sales order number is mandatory' TYPE 'E'.
ENDIF.

SELECT SINGLE * FROM vbak INTO ls_order
  WHERE vbeln = gs_order-vbeln.

CALL FUNCTION 'AUTHORITY-CHECK'
  EXPORTING OBJECT   = 'V_VBAK_VKO'
            TCD      = 'VBA1'
            ACTIVITY = '01'
  EXCEPTIONS NOT_AUTHORIZED = 1
              OTHERS         = 2.

IF sy-subrc = 1.
  MESSAGE 'Not authorized for sales orders' TYPE 'E'.
ENDIF.

INSERT INTO vbak VALUES ls_order.

COMMIT WORK.

MESSAGE 'Order saved' TYPE 'S'.
SET SCREEN 0000.
LEAVE PROGRAM.
```

下面按严重度逐条列。**这 7 条里有 5 条是"数据正确性/生产事故"级别。**

### 🔴 R1 —— `INSERT INTO vbak` 把刚读出来的行再写回去（必然重复键）

`ls_order` 是用 `SELECT SINGLE ... FROM vbak` 从**同一张表**读出来的完整行，紧接着无条件 `INSERT INTO vbak`。原行已存在、主键 `MANDT + VBELN` 冲突 → 数据库返回重复键错误（SAP 典型 `DUPLICATE_KEY` / SQL 155）；由于这里**既没有 `EXCEPTIONS DUPREC` 也没有 `sy-subrc` 检查，程序会带着未处理的 DB 错误继续往下走**，`COMMIT WORK` 依旧执行，界面还会弹 `'Order saved'`。也就是说：**用户看到"保存成功"，数据库里什么都没有，而且没人知道失败过。** 这是最典型的"静默数据丢失"形态。

> 这段代码的意图和实现完全矛盾：注释说"change order"，代码却做的是"新增一行自己刚读出来的数据"。**如果真的要改订单，应该是 UPDATE + 前后值对比，或者走 BAPI。**

### 🔴 R2 —— `SELECT SINGLE *` 写入只有 6 个字段的结构 → 字段错位/半截数据

```abap
SELECT SINGLE * FROM vbak INTO ls_order   "ls_order : ty_order (6 字段)
```

`ty_order` 只有 6 个组件，`*` 在**平面结构**里会被展开成"该结构的 6 个字段"，然后按 **VBAK 的物理字段顺序**位置对应，而不是按名字对应：

- `VBAK` 的字段顺序是 `VBELN, VBELN_TV, VBELN_FF, VBELN_REF, ..., KUNNR, ..., WAERK, ..., NETWR, ...`
- 结构里的第 1 位对上 `VBELN`（碰巧对），第 2/3 位对上 `VBELN_TV/VBELN_FF`（**不是 KUNNR**），第 4 位对上 `VBELN_REF`（**不是 WAERK**）……

结论：`ls_order` 里除了 `VBELN` 之外基本是**错位或空的**。这样的行拿去 `INSERT`（R1）即使不撞主键，也会写入一条 `KUNNR/WAErk/NETWR` 全空的垃圾订单头。**绝对不能对平面结构用 `SELECT *`**，必须显式列字段：

```abap
SELECT SINGLE vbeln kunnr waerk netwr      "只取需要的字段
  FROM vbak INTO ls_order
  WHERE vbeln = gs_order-vbeln.
```

### 🔴 R3 —— 直接 `INSERT` 标准表 `VBAK`，绕过所有一致性机制

- `VBAK` 是 **SAP 标准表**。业务代码严禁直接写标准表：会绕过编号范围（`VBAK` 的单号由 `VB_BELEG_CREATE`/FIM 维护）、订单类型/组织/销售范围的完整性校验、伙伴函数、定价、文本、状态、后台号段锁、变更日志。
- 合规/审计红线：客户订单的创建有 `VBAK` 的表维护事件、变更指针（`VBAP`/`CDHDR`）、`CDPOS`、QM 通知、FI 凭证预览等一系列下游，漏掉就是数据不一致。
- 正确做法：改订单用 **`BAPI_SALESORDER_CHANGE`**（或 `SALESORDER_CHANGEFROMDATA` / `VB_UPDATE` 系列 FM），建订单用 **`BAPI_SALESORDER_SIMULATE` + `BAPI_SALESORDER_CREATEFROMDATA`**，并检查 `BAPI_TRANSACTION_COMMIT` / `RETURN` 里的错误。

### 🔴 R4 —— 无条件 `COMMIT WORK` + 零错误处理

```abap
INSERT INTO vbak VALUES ls_order.
COMMIT WORK.
```

- `COMMIT WORK` 会提交**整个 LUW**，包括本对话框之前所有未提交的修改（不止这次 INSERT）。对话框里最忌讳裸 `COMMIT WORK`，它让"部分成功 + 部分失败"变得不可回滚。
- 前面**没有任何 `sy-subrc` / `DUPREC` 判断**：`SELECT SINGLE` 没找到行（`sy-subrc = 4`）时 `ls_order` 全空 → 照样 INSERT（大概率 dump）→ 照样 COMMIT。
- 如果 BAPI 化，应当在对话框里用 `CALL FUNCTION ... IN UPDATE TASK` 或 BAPI 事务，并在 `ENDLCM`/错误处理里决定是否提交。

### 🟠 R5 —— 权限检查被架空：`IF sy-subrc = 1` 放过了 `OTHERS = 2`

```abap
EXCEPTIONS NOT_AUTHORIZED = 1
            OTHERS         = 2.
IF sy-subrc = 1.  "← 只判 1
  MESSAGE 'Not authorized ...' TYPE 'E'.
ENDIF.
```

- `AUTHORITY-CHECK` 的 `OTHERS` 会在 **对象不存在于 `TACT01` / 对象名拼错 / 权限 profile 未激活 / 内部错误** 时置 `sy-subrc = 2`。此时代码直接放行 → **保存照做不误**。必须写成 `IF sy-subrc <> 0`。
- 而且 `V_VBAK_VKO` 是变式订单类 SAP 对象（VKO 变式），`TCD = 'VBA1' + ACTIVITY = '01'` 这个组合在客户系统里**很可能是错的**（保存变更应该用变式活动 02/03，对应的 TCD 也不是 VBA1）。TCD/活动配错 → 检查永远返回"通过"。
- 更根本的问题：这里查的是"程序内部 TCD-Activity"，而代码走的是裸 `INSERT`（没有文档头 TCD），**这个检查与实际动作毫无绑定关系**，纯装饰。
- 位置也不对：权限检查在读数据（`SELECT SINGLE`）**之后**、而且只在保存时才做 → 未授权用户已能看到/读到数据。标准做法是在 `AT SELECTION-SCREEN` / `START-OF-SELECTION` 用 `AUTHORITY-CHECK OBJECT ... DCL 01`（或 ABAP CDS DCL）做**早期拒绝**。

### 🟠 R6 —— 退出流程自相矛盾，消息很可能丢失

```abap
MESSAGE 'Order saved' TYPE 'S'.
SET SCREEN 0000.
LEAVE PROGRAM.
```

- `SET SCREEN 0000` 在这个流程里**是废语句**：`LEAVE PROGRAM` 紧接着就终止了本次 ABAP 运行（回到选择屏/结束事务），`SET SCREEN` 的效果不会发生。三行里有一行是噪音。
- `LEAVE PROGRAM` 会让 `'Order saved'` 这条成功消息在很多返回路径下**被丢弃或显示在已关闭的屏幕上**，用户不知道自己保存没保存。标准做法：把消息挂到返回的事务/列表上（`MESSAGE ... TYPE 'S'` 后 `LEAVE LIST-PROCESSING` / `SUBMIT <report>` / `CALL TRANSACTION`），或者用 `'S'` + `SET TITLEBAR`/`POPUP` 明确提示。
- 逻辑上"保存"应该重新回到 0100 或刷新列表，而不是直接退程序。

### 🟡 R7 —— 保存没有留痕、屏幕与后端状态不一致

- `INITIALIZATION` 里已经准备好了 `gv_user` / `gv_datum`，但**保存时完全没用**——`ERDAT/ERNAM/EDAT` 之类"谁在什么时候改的"信息没有落库，订单变更无法审计。注释掉的意图存在，代码没实现。
- 成功后既不刷新 `gt_order`，也不更新 `gs_order`，屏幕上的值与数据库可能已经不一致（下次进 PBO 也没有重新读取）。

### 🟡 R8 —— 杂项

| 项 | 位置 | 问题 |
|---|---|---|
| 死变量 | `DATA lv_check TYPE c LENGTH 1.` | 声明后从未使用；`TYPE c` 已过时，应为 `abap_bool` / `flag` |
| 死变量 | `gv_init` | 声明为"一次性初始化"标志，从未使用（见第 3 节，这是 PBO 缺逻辑的证据） |
| `DATA` 类型与源表不符 | `ty_order` | `TYPE STANDARD TABLE ... WITH EMPTY KEY` 对可排序业务表不合适（不能用 `SORT`/二分查找），且 `menge` 归属存疑（第 2.3 节） |
| 消息风格不统一 | 多处 | 硬编码英文 `MESSAGE 'xxx' TYPE 'E'`，没用消息类（`MESSAGE-ID`）也没用 `TEXT-xxx`，而选择屏标题用了 `TEXT-001` |
| 无 `NO-TEXT` | 报表头 | 激活时会出现"文本符号未使用"提示，噪音 |

---

## 6. 风险汇总表

| # | 位置 | 风险 | 等级 | 现象 / 影响 |
|---|---|---|---|---|
| R1 | `save_order:95` | 读出的行再 INSERT 回同表 | 🔴 致命 | 主键重复错误被静默吞掉，界面仍提示"Order saved" |
| R2 | `save_order:79-80` | `SELECT SINGLE *` 写入 6 字段平面结构 | 🔴 致命 | 字段按物理顺序错位，`KUNNR/WAErk/NETWR` 变空 |
| R3 | `save_order:95` | 直接 `INSERT` 标准表 VBAK | 🔴 致命 | 绕过编号范围/一致性校验/日志，审计违规 |
| R4 | `save_order:95-97` | 无条件 `COMMIT WORK` + 零 `sy-subrc` 检查 | 🔴 致命 | 提交整个 LUW，部分失败不可回滚 |
| R5 | `save_order:82-93` | 权限检查只判 `sy-subrc = 1` | 🟠 高 | `OTHERS = 2`（对象未维护/拼错）直接放行；TCD/活动组合存疑 |
| R6 | `save_order:99-101` | `SET SCREEN 0000` + `LEAVE PROGRAM` 混用 | 🟠 高 | `SET SCREEN` 失效、成功消息丢失、流程不可预测 |
| R7 | `user_command_0100:120-121` | `SAVE` 只 `SET SCREEN 0100` | 🟠 高 | 保存功能**完全没接通**，点按钮无反应 |
| R8 | `status_0100:55-67` | PBO 无一次性初始化 | 🟠 高 | 0100 空白 → `gs_order` 初值 → 保存必报 E，永远走不通 |
| R9 | `save_order:75-77` | 前置校验依赖没人填充的 `gs_order` | 🟠 高 | 唯一的入口校验恒为真，等于没有校验 |
| R10 | `START-OF-SELECTION:46-50` | `s_vbeln` 未判非空 + 无行数上限 | 🟠 中高 | 全表捞，可能 dump / 内存与工作目录溢出 |
| R11 | `AT ... VALUE-REQUEST:41-43` | F4 读空表 + 覆盖 `gs_order` | 🟠 中高 | 用户输入的 VBELN 被清空；提示文案恒定；F4 无用 |
| R12 | `START-OF-SELECTION:47` | `MENGE FROM vbak` 字段可能不存在 | 🟠 中高 | 激活/运行期报错（请 SE11 确认） |
| R13 | `user_command_0100:112-128` | `ok_code` 未声明 / 无 `ELSE` / 复用 `EXIT` | 🟡 中 | 语法错误 / 未知 F 码无响应 / 与标准命令冲突 |
| R14 | `status_0100:57` | `SET PF-STATUS` 无存在性保护 | 🟡 中 | 状态缺失即 short dump |
| R15 | 全局 | `SELECT-OPTIONS FOR gs_order-vbeln` 语义复用 | 🟡 中 | 业务结构与选择范围共用内存，隐性耦合 |
| R16 | `status_0100:60-65` | 0100 字段名硬编码 `P_WAERK` | 🟡 中 | 字段名不符则 `MODIFY SCREEN` 静默失效 |
| R17 | `save_order:72` / `INITIALIZATION` | 死变量、无变更留痕 | 🟢 低 | `lv_check` 未用；`gv_user/gv_datum` 未落库 |
| R18 | 全局 | 硬编码英文消息、缺消息类 | 🟢 低 | 可维护性 / 本地化 |

---

## 7. 建议的修复路线

**第 1 步：先把流程接通（不做任何数据库写入）**

```abap
DATA ok_code TYPE sy-ucomm.          " ① 补上声明

AT SELECTION-SCREEN.                " ② 早期权限拒绝
  IF NOT auth_check_vko( sy-subrc ).
    MESSAGE 'Not authorized for sales orders' TYPE 'E'.
  ENDIF.

AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln.   " ③ F4 改搜索帮助
  DATA ls_help TYPE ty_order.
  SELECT vbeln kunnr waerk netwr FROM vbak INTO ls_help
    WHERE vbeln LIKE s_vbeln-low% AND waerk = p_waerk.
  " 用 ALV 弹窗或 SET PARAMETER 回填，绝不覆盖 gs_order

START-OF-SELECTION.
  IF s_vbeln[] IS INITIAL.
    MESSAGE 'Please enter order number' TYPE 'E'.
  ENDIF.
  SELECT ... FROM vbak INTO TABLE gt_order
    WHERE vbeln IN s_vbeln AND waerk = p_waerk
    UP TO 500 ROWS.                 " ④ 限量

MODULE status_0100 OUTPUT.
  SET PF-STATUS 'S0100'.  SET TITLEBAR 'T0100'.
  IF gv_init IS INITIAL.            " ⑤ 一次性初始化
    gv_init = abap_true.
    READ TABLE gt_order INTO gs_order INDEX 1.
    WRITE : gs_order-vbeln, gs_order-kunnr, gs_order-waerk, gs_order-netwr.
    LOOP AT SCREEN.
      IF SCREEN-NAME = 'P_WAERK' OR SCREEN-NAME = 'NETWR'.
        SCREEN-DISPLAY-MODE = '1'.  MODIFY SCREEN.
      ENDIF.
    ENDLOOP.
  ENDIF.
ENDMODULE.
```

`user_command_0100` 里把 SAVE 真正派发出去，并统一退出码：

```abap
CASE lv_ok_code.
  WHEN 'SAVE'.       SET OK-CODE 'SAVED'.  " 由屏幕流逻辑调用 save_order
  WHEN 'BACK' OR 'ENDE'.  LEAVE PROGRAM.
  WHEN 'CANC' OR 'EXIT'.  LEAVE PROGRAM.
  WHEN OTHERS.                     " 未知码不要静默
    RETURN.
ENDCASE.
```

**第 2 步：把保存改成标准业务 API，并做完整错误处理**

```abap
DATA: ls_xvbap TYPE vbap,            " 变更结构
      lv_vbeln TYPE vbeln_va,
      lt_ret   TYPE bapiret2_tab.

MOVE lv_order TO ls_xvbap.           " 只允许改白名单字段
" 只读字段必须从 DB 读回来填充，否则 BAPI 会拒绝或清空
SELECT SINGLE vbeln kunnr waerk netwr FROM vbak
  INTO ls_order WHERE vbeln = gs_order-vbeln.   " 显式字段，禁用 *

CALL FUNCTION 'BAPI_SALESORDER_CHANGE'
  EXPORTING SALESORDER    = gs_order-vbeln
            SALESORDER_ORG = sy-subrc
  TABLES   ORDERITEMS    = lt_xvbap
  CHANGING  ERROR         = lv_error
  EXCEPTIONS OTHERS       = 1.

" 检查 BAPIRETURN（尤其 EXTENDEDERROR）
LOOP AT lt_ret INTO ls_ret WHERE type = 'E' OR type = 'A'.
  MESSAGE ls_ret-message TYPE 'E'.
ENDLOOP.

CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'
  EXPORTING WORKREQUEST = 'X'.      " 或在 update task 中处理
```

要点：
- **删掉 `INSERT INTO vbak` 和裸 `COMMIT WORK`。**
- `AUTHORITY-CHECK` 改成 `IF sy-subrc <> 0`；并在选择屏阶段就用 `DCL 01` 早拒绝。
- 保存时把 `gv_user`/`gv_datum` 记入自己的日志表（**不写标准表的 `ERNAM/EDAT`**，那是 BAPI 的职责）。
- 消息走消息类（`MESSAGE-ID`），中文可维护。

**第 3 步：边界与稳健性**

- 0100 字段全部设为 `OUTPUT`（只读展示）+ 需要编辑的字段单独 `MODULE ... INPUT` + 字段级 `DCL` 检查。
- `SELECTION-SCREEN` 上加 `CHECK TABLE OF waerk`，`p_waerk` 加值域。
- 检查 `vbeln` 的数字范围、订单类型、已存在性，给出具体中文错误消息（而不是"Save failed"）。
- 退出统一为 `LEAVE PROGRAM` / `CALL TRANSACTION` 单一路径，删掉所有 `SET SCREEN 0000`。

---

## 8. 缺失资产 / 待确认清单

| 项 | 说明 |
|---|---|
| **dynpro 0100 的屏幕流逻辑（.screen）** | 不在交付物中。`save_order` / `back` 是否被它以 `MODULE` 方式挂上，**必须看这个文件才能定论**。若没挂，R7 就是硬缺陷。 |
| **PF-STATUS `S0100`** | 需确认已创建（否则 R14 会 dump）。 |
| **TITLEBAR `T0100`** | 需确认已创建。 |
| **0100 的实际字段名** | PBO 硬编码了 `P_WAERK`；需与 Screen Painter 逐字段比对（R16）。 |
| **`VBAK` 是否有 `MENGE`** | 需 SE11 确认；若无，`START-OF-SELECTION` 的 SELECT 无效（R12）。 |
| **`V_VBAK_VKO` / `TCD 'VBA1'` / `ACTIVITY '01'`** | 需查 `TACT01` 与客户侧权限 profile；"修改订单"的活动码大概率不是 `01`（R5）。 |
| **`s_vbeln` 挂在 `gs_order-vbeln` 上** | 建议改为 `DATA s_vbeln TYPE vbeln_va`（或 `TYPE vbeln_va_tab`）+ `SELECT-OPTIONS ... FOR s_vbeln`，彻底切断与业务结构的耦合（R15）。 |
| **`ok_code` 声明** | 程序内无声明，激活即语法错误（R13）。 |

---

## 9. 修复优先级

```text
P0  阻断上线：R1 R2 R3 R4（禁止 INSERT VBAK + 裸 COMMIT + SELECT *）
P0  功能不通：R7（SAVE 未派发）R8/PBO 无初始化 R9（恒真校验）
P1  安全合规：R5（sy-subrc <> 0 + DCL 早拒绝）R6（退出流程统一）
P1  稳定性：   R10（限量+非空校验）R11（F4 修正）R12（字段确认）
P2  可维护性： R13 R14 R16 R17 R18
```

**一句话给开发同事：** 在把 `INSERT INTO vbak VALUES ls_order.` 换成 `BAPI_SALESORDER_CHANGE`（并把 `SELECT SINGLE *` 改成显式字段列表、把 `COMMIT WORK` 换成受控的 BAPI 事务提交）之前，这个程序既不能通过生产环境的代码审查，也过不了自己的功能测试——因为它连屏幕数据都还没填上。

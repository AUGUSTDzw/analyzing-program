# ZORDER_DIALOG 交互式订单录入程序 — 源码走读报告

> 分析对象：`evals/zorder_dialog.abap`（128 行，REPORT 报表程序 + 经典对话框 dynpro 100）
> 关注重点：选择屏幕事件块、屏幕流、100 屏 PBO/PAI 模块、保存逻辑风险

---

## 一、程序概览

| 项 | 内容 |
| --- | --- |
| 程序名 | `ZORDER_DIALOG`（REPORT，非函数模块、非 OO） |
| 类型 | 报表程序 + 一步式对话框（`CALL SCREEN 0100`） |
| 选择条件 | 销售订单号 `S_VBELN`（select-option）、币种 `P_WAERK`（parameter，默认 EUR） |
| 主数据源 | `VBAK`（销售订单抬头） |
| 写操作 | `INSERT INTO VBAK`（直接写数据库表，绕过 BAPI） |
| 屏幕模块 | `status_0100`(OUTPUT) / `user_command_0100`(INPUT) / `back`(INPUT) / `save_order`(INPUT) |
| 错误处理 | **几乎没有**：全局无 sy-subrc 检查、无消息类、无异常处理 |

一句话概括程序意图：用户输入订单号区间与币种 → 程序从 VBAK 读订单抬头 → 弹出 100 屏让用户"修改并保存" → `save_order` 做必填校验、权限检查后把数据写回 VBAK 并提交。

实际代码与这个意图之间存在多处**严重偏差**，尤其是"保存"部分（详见第六节）。

---

## 二、全局数据结构与内存模型

```abap
TYPES: BEGIN OF ty_order,
         vbeln TYPE vbeln_va,
         kunnr TYPE kunnr,
         waerk TYPE waerk,
         netwr TYPE netwr,
         menge TYPE menge,
       END OF ty_order.

TYPES ty_order_tab TYPE STANDARD TABLE OF ty_order WITH EMPTY KEY.

DATA gt_order TYPE ty_order_tab.   "内表：从 VBAK 读出
DATA gs_order TYPE ty_order.      "单行：既是选择屏幕 s_vbeln 的绑定对象，又是 F4 的目标
DATA gv_user  TYPE sy-uname.      " 赋值后从未使用
DATA gv_datum TYPE sy-datum.      " 赋值后从未使用
DATA gv_init  TYPE abap_bool.     " 从未使用
```

三点需要注意：

1. **`gs_order` 承担双重身份**。`SELECT-OPTIONS s_vbeln FOR gs_order-vbeln` 把选择屏幕字段直接绑定到全局结构体的 `vbeln` 上，因此 `gs_order` 既是"选择屏幕传参结构"，又是"业务数据结构"。任何一处往 `gs_order` 写值（包括 F4 里的 `READ TABLE ... INTO gs_order`）都会连带污染其它 4 个字段。
2. `ty_order_tab` 用 `WITH EMPTY KEY`，主键为空（无排序），对 `LOOP AT` 遍历没问题，但 `gt_order` 无任何唯一性保障；配合 `netwr TYPE netwr`（15,2 小数位数量）后续做金额汇总时要留意精度。
3. `gv_user` / `gv_datum` / `gv_init` 是死代码，没有任何读取点（`gv_datum`/`gv_user` 在 `INITIALIZATION` 里赋值后即被遗忘），典型的"打算做审计但没做完"的痕迹。

---

## 三、选择屏幕事件块走读

事件块执行顺序（用户执行 F8 后的标准链）：
`INITIALIZATION` → `AT SELECTION-SCREEN OUTPUT`（可多次）→ [F4/检查事件] → `START-OF-SELECTION` → `CALL SCREEN 0100` → 100 屏 PBO/PAI 循环 → 返回

### 3.1 选择屏幕定义

```abap
SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
  SELECT-OPTIONS s_vbeln FOR gs_order-vbeln.
  PARAMETERS p_waerk TYPE waerk DEFAULT 'EUR'.
SELECTION-SCREEN END OF BLOCK b1.
```

* select-option 会展开成 4 个内部字段：`S_VBELN-SIGN`、`S_VBELN-OPTION`、`S_VBELN-LOW`、`S_VBELN-HIGH`，屏幕上有 6 行输入行（区间/单值/多值）。
* 缺少 `AT SELECTION-SCREEN ON CHECK`（P_WAERK 的有效性校验）、`AT SELECTION-SCREEN ON HELP-REQUEST`、`NO-DISPLAY` / `NO-EXTENSION`。
* 缺少 `AT SELECTION-SCREEN BEGIN-OF-SELECTION` 里的任何必填校验，因此用户可以完全不输入订单号直接执行，程序照样进入 100 屏（见 3.4）。

### 3.2 INITIALIZATION

```abap
gv_datum = sy-datum.
gv_user  = sy-uname.
```

只赋值了两个从未被使用的全局变量。**没有**做任何权限/角色预检查、没有 `sy-msgid` 相关初始化、没有为 F4 准备数据（见 3.3 的连锁问题）。

### 3.3 AT SELECTION-SCREEN OUTPUT

```abap
AT SELECTION-SCREEN OUTPUT.
  LOOP AT SCREEN.
    IF SCREEN-NAME = 'P_WAERK'.
      SCREEN-INTENSIFIED = '1'.
      MODIFY SCREEN.
    ENDIF.
  ENDLOOP.
```

* 这里**是有效的**：`P_WAERK` 确实是选择屏幕上的字段名，硬编码名能匹配上，功能意图（币种字段高亮，提示"这是关键参数"）能达成。
* 写法可优化：`LOOP AT SCREEN` 后没有 `CONTINUE`/`EXIT`，如果将来有第二个匹配项仍会继续处理；且应配合 `ENDIF` + `CONTINUE` 或直接用 `MODIFY SCREEN` 后 `EXIT`。
* 逻辑重复：与 100 屏 PBO 里的那段几乎一样的循环（见 4.2），说明作者想"把币种设为只读"这个意图写了两遍，但两遍都作用在不同屏幕上，只有一处真正生效。

### 3.4 AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln（F4 事件）

```abap
AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln.
  READ TABLE gt_order INTO gs_order INDEX 1.
  MESSAGE 'No order data loaded yet' TYPE 'S'.
```

这是本程序里**最典型的 ABAP 反模式**，有四层问题：

1. **事件声明本身不对。** F4 对 select-option 触发的字段名是 `S_VBELN-LOW` / `S_VBELN-HIGH`，正确写法必须分别声明：
   ```abap
   AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln-low.
   ...
   AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln-high.
   ```
   写成 `FOR s_vbeln` 后，F4 不会进入这个事件块（激活时可能就报语法错），整段逻辑等价于**死代码**。
2. **F4 里读内表在时序上必然读空。** `gt_order` 在 `START-OF-SELECTION` 才填充，而 F4 事件发生在 `START-OF-SELECTION` **之前**。首次执行时 `gt_order` 恒为空 → `READ TABLE ... INDEX 1` 的 `sy-subrc = 4`，`gs_order` 保持原值，然后必然弹出"No order data loaded yet"。返回 100 屏退出后再回来执行，第二次 F4 才"可能"读到数据 —— **同一段代码的行为取决于用户是否已经进过 100 屏**，这是典型的时序依赖型缺陷。
3. **没有检查 `sy-subrc`。** `READ TABLE` 失败时 `gs_order` 保留旧值（也就是选择屏幕里用户刚输入的值），静默通过，用户毫无察觉。
4. **F4 应该直接查库，而不是查内存内表。** 正确做法是在 F4 里 `SELECT ... WHERE vbeln LIKE s_vbeln-low%`，把查询结果做成 F4 结果列表（`TABLE OF vbeln` 传参）。把展示用的内表当 F4 数据源，本身就是设计错误。
5. 目标结构是 `gs_order`（见第二节第 1 点）：即使哪天 `READ TABLE` 成功，它会一次性覆盖 `kunnr/waerk/netwr/menge`，这些字段对选择屏幕毫无意义，却把业务数据一起改了。
6. `MESSAGE ... TYPE 'S'` 在 F4 事件里用一个成功类消息报告失败，语义错误（应为 `'E'` 或 `'W'`），且成功消息在选择屏幕流程里常会被重复显示一次。

**结论**：F4 校验/帮助功能实质不可用。

### 3.5 START-OF-SELECTION

```abap
START-OF-SELECTION.
  SELECT vbeln kunnr waerk netwr menge
    FROM vbak
    INTO TABLE gt_order
    WHERE vbeln IN s_vbeln
      AND waerk = p_waerk.

  CALL SCREEN 0100.
```

* **未检查 `sy-subrc`。** 查询无结果（订单号不存在 / 币种不匹配）时没有任何提示，直接进 100 屏显示一个空清单；用户看到的是"程序坏了"而不是"没查到数据"。应至少 `IF sy-subrc = 0. ... ELSE. MESSAGE ... TYPE 'S'/'A' / 'E'. ENDIF.`
* 无 `WHERE` 空值保护，`s_vbeln` 全空时 `vbeln IN (' '..)`，实际取全表 VBAK 按币种过滤 → **一次拖垮全表的选择**，生产系统上是典型的性能事故源。
* 币种条件只作用于读取，`p_waerk` 与 100 屏上用户实际看到的字段之间**没有任何关联**，读出来的 `waerk` 也没有在 PBO 里赋给屏幕字段。
* `CALL SCREEN 0100` 无条件执行，没有 `STARTING NEW LINE`、没有 `CALL TRANSACTION`、也没有 `LEAVE PROGRAM` 之外的返回策略。
* 语句风格可用新语法：`INTO TABLE @gt_order`、`WHERE vbeln IN @s_vbeln`（7.40+）。

---

## 四、屏幕流与 100 屏 PBO

### 4.1 屏幕流无法从源码中验证（重要风险）

源码里只有 `MODULE ... OUTPUT` / `MODULE ... INPUT` 声明，**没有** `PROCESS BEFORE FLOW LOGICAL` / `SCREEN 100 BEGIN OF BLOCK` 之类的流程定义。也就是说：模块的调用顺序、字段与模块的绑定关系，全部保存在屏幕绘制器（Screen Painter，dynpro 100）里，源码不包含它们。

直接后果：

* 无法判断 `save_order` 是挂在 `PROCESS AFTER FLOW`（**每次 PAI 都会跑**）还是挂在某个命令字段上 —— 这直接决定了它是被"只在点 SAVE 时执行"还是"点任何按钮都执行"。
* 无法判断 100 屏上是否存在 `Vbeln` 字段、表格控件（Table Control）及其命名 —— 这直接决定了保存模块读到的是不是用户输入的数据。
* 该程序**无法在本地独立复现/测试**，新人接手必须先拿到屏图与模块流，这是交接与变更的主要隐性成本。

### 4.2 status_0100（PBO）

```abap
MODULE status_0100 OUTPUT.
  SET PF-STATUS 'S0100'.
  SET TITLEBAR 'T0100'.
  LOOP AT SCREEN.
    IF SCREEN-NAME = 'P_WAERK'.
      SCREEN-DISPLAY-MODE = '1'.
      MODIFY SCREEN.
    ENDIF.
  ENDLOOP.
ENDMODULE.
```

* `SET PF-STATUS` / `SET TITLEBAR` 写在 PBO 里**每次进屏都执行**，虽然可用但属于规范问题：通常应放在 `INITIALIZATION` 或只设置一次。
* **`P_WAERK` 是选择屏幕的参数名，不是 100 屏字段名。** 100 屏上除非确实存在一个恰好叫 `P_WAERK` 的字段，否则这个 `IF` 永不成立 → 又一段死代码。作者的真实意图（把币种置为只读，`DISPLAY-MODE = '1'` 表示 output/protected）在此处**没有落地**。
* PBO **没有任何数据下发逻辑**：没有把 `gt_order` 灌进表格控件、没有把 `gs_order-waerks/kunnr` 赋给屏幕字段。也就是说 100 屏目前是"无数据绑定"的空壳，屏幕上要么空白、要么显示陈旧值（ABAP 中 `gt_order` 不会自动显示）。
* PBO 里没有屏幕编号校验、没有 `SCREEN-NAME` 的 `EXIT`/`CONTINUE`，风格与 3.3 重复。

---

## 五、PAI 模块：user_command_0100 与 back

### 5.1 user_command_0100（OK_CODE 分发）

```abap
MODULE user_command_0100 INPUT.
  DATA lv_ok_code TYPE sy-ucomm.
  lv_ok_code = ok_code.
  CLEAR ok_code.
  CASE lv_ok_code.
    WHEN 'SAVE'.
      SET SCREEN 0100.
    WHEN 'BACK' OR 'EXIT' OR 'CANC'.
      SET SCREEN 0000.
  ENDCASE.
ENDMODULE.
```

写法本身（先取到局部变量、再 `CLEAR ok_code`、再处理）是标准的正确姿势，`CLEAR ok_code` 在这里**不是**问题。但逻辑上有硬伤：

1. **`SAVE` 没有连接任何保存动作。** 处理 `SAVE` 唯一的语句是 `SET SCREEN 0100`，即"留在原屏、重画一次"。保存逻辑 `save_order` 在这里根本没有被调用。用户点保存 → 屏幕闪一下 → 什么都没发生。
2. **未处理的 OK_CODE 会让屏幕"死掉"。** `CASE` 没有 `WHEN OTHERS`；只要用户的操作产生的 `OK_CODE` 不在这三个值里（工具栏按钮、回车、PF-STATUS 上任何自定义功能键、`F3`/`F4`、Backspace 修改字段产生的空 OK_CODE 等），`ok_code` 已被清空却什么都不执行 → **屏幕无任何反应，用户既不能前进也不能后退，只能杀会话**。这是经典症状，必须修。
3. `BACK`/`EXIT`/`CANC` 三者被合并成同一个行为，语义完全丢失：取消（放弃输入）与退出结果一致，且没有任何"是否放弃修改"的确认。
4. `SET SCREEN 0000` 与 `LEAVE PROGRAM` 在其他模块里同时出现（见 5.2），屏幕流语义混乱：`SET SCREEN` 只是**延迟**换屏，紧跟的 `LEAVE PROGRAM` 直接终止流程，前一句完全失效。

### 5.2 back

```abap
MODULE back INPUT.
  CALL SCREEN 0000.
  LEAVE PROGRAM.
ENDMODULE.
```

`CALL SCREEN 0000` + `LEAVE PROGRAM` 同时存在，只有 `LEAVE PROGRAM` 生效；且离开前无任何确认（用户已录入的内容会静默丢弃）。另外 `back` 与 `user_command_0100` 的 `BACK` 分支重复，两者都挂在同一屏上时存在重复处理的可能。

---

## 六、保存逻辑 `save_order` 深度风险清单（本节为用户关注重点）

```abap
MODULE save_order INPUT.
  DATA lv_check TYPE c LENGTH 1.
  DATA ls_order TYPE ty_order.

  IF gs_order-vbeln IS INITIAL.
    MESSAGE 'Sales order number is mandatory' TYPE 'E'.
  ENDIF.

  SELECT SINGLE * FROM vbak INTO ls_order
    WHERE vbeln = gs_order-vbeln.

  CALL FUNCTION 'AUTHORITY-CHECK'
    EXPORTING OBJECT = 'V_VBAK_VKO' TCD = 'VBA1' ACTIVITY = '01'
    EXCEPTIONS NOT_AUTHORIZED = 1 OTHERS = 2.

  IF sy-subrc = 1.
    MESSAGE 'Not authorized for sales orders' TYPE 'E'.
  ENDIF.

  INSERT INTO vbak VALUES ls_order.
  COMMIT WORK.
  MESSAGE 'Order saved' TYPE 'S'.
  SET SCREEN 0000.
  LEAVE PROGRAM.
ENDMODULE.
```

按严重程度排列：

### 🔴 R1（阻断级）`SELECT SINGLE * FROM vbak INTO ls_order` 结构性不匹配 —— 运行必短时 dump

`ls_order` 只有 5 个字段，而 `VBAK` 有数百个字段（`SELECT SINGLE *` 取整表结构）。把整表结构传进只有 5 个字段的工作区，是结构不匹配错误，运行到这句直接 dump。同样的问题也存在于下一句：

```abap
INSERT INTO vbak VALUES ls_order.   " 同样按 5 字段写整表 → 结构不匹配
```

**这一段代码从未被成功执行过。** 修法是显式列出字段：

```abap
SELECT SINGLE vbeln kunnr waerk netwr menge
  FROM vbak INTO ls_order
  WHERE vbeln = @gs_order-vbeln.
```

### 🔴 R2（阻断级）保存的是"数据库读回来的旧值"，不是"用户改的值"

即使修好 R1，`ls_order` 的数据来源仍是 `SELECT SINGLE ... FROM vbak`，即**库里的原始行**。用户从 100 屏上做的所有修改（金额、数量、客户、币种）根本没有参与写操作。语义上这根本不是"保存"，而是"把老数据再插一次"。

### 🔴 R3（阻断级）主键冲突 / 空值插入

* 若 `vbeln` 已存在 → `INSERT INTO vbak` 触发主键冲突（VBAK 键为 `MANDT + VBELN`）。程序**不检查 `sy-subrc`**，随后直接 `COMMIT WORK`，最终要么 dump、要么**打印一条"Order saved"的假成功消息**。
* 若 `vbeln` 不存在 → `SELECT SINGLE` 无结果（`sy-subrc = 4`，未检查），`ls_order` 全初始 → 插入一条 **VBELN 为空的订单抬头**：没有编号范围分配（未调用 `NUMBER_GET_INTVAL` / 未走 BAPI 的 `VBAK-NR`）、没有 `VBTYP/VKORG/SALESORG`、没有抬头以外的任何字段。这种数据一旦提交就是**无法用正常业务事务修复的脏数据**（ABAP 层无法 delete 掉正确的数据），并且 `VBAK` 有抬头而没有 `VAPO/VBAP` 项目数据，订单在业务上完全不可用。

### 🔴 R4（阻断级）在对话框里 `COMMIT WORK`

* `COMMIT WORK` **立即结束 SAP LUW，之后无法回滚**。这里提交的是一个业务上不完整的对象（无项目、无编号、无变更凭证、无订单类型），把中间态永久落库。
* 一旦 `COMMIT` 之后的语句（`MESSAGE` / `SET SCREEN` / `LEAVE PROGRAM`）出错，数据已提交、无法通过对话框回滚或重新执行修正。
* 对话框程序中不该手工 `COMMIT`，应交给 SAP LUW 在对话框结束时统一提交，异常路径自动 `ROLLBACK`。
* 直接写 `VBAK` 绕过 `BAPI_SALESORDER_CREATE` / `BAPI_SALESORDER_SAVE`，同时绕过：编号范围、订单类型校验、定价条件、交货计划、输出、变更凭证对象（`CDHDR`）、统计更新。正确做法是走 BAPI，`COMMIT WORK` 由 BAPI 的 `BAPI_TRANSACTION_COMMIT`（且必须配套 `bapi_revert`）控制。

### 🟠 R5（高）权限检查不完整，存在放行路径

```abap
    EXCEPTIONS NOT_AUTHORIZED = 1 OTHERS = 2.
  IF sy-subrc = 1.
```

* **`OTHERS = 2` 完全没有处理**：一旦权限对象缺失、权限档案异常、或内部错误被转成 `OTHERS`，`sy-subrc = 2` 时程序继续往下走执行 `INSERT` + `COMMIT` → **未授权也能写库**。这是安全缺陷，必须 `WHEN OTHERS` 分支也 MESSAGE 'E' 并终止。
* `OBJECT = 'V_VBAK_VKO'` + `TCD = 'VBA1'` + `ACTIVITY = '01'` 的字段组合可疑：TCD 通常用于 T-code 级权限，`ACTIVITY` 更常见的用法是 `ACTVT`；这种混搭很可能导致权限检查退化为"几乎恒通过"或语义不清。需要用 `SU53` 在真实权限档案上验证检查结果，而不是假设它生效。
* 权限检查在 `SELECT` **之后**、且没有任何行级/字段级（`V_VBAK_VKO` 常含金额字段级权限）处理；读取阶段完全没有权限控制。
* 没有数据库层的 `WHERE` 保护、没有行级（"销售组织/客户范围"）限制，任何能执行该程序的用户都可以改任意订单号。

### 🟠 R6（高）必填校验作用在错误的内存上，用户无法自救

```abap
IF gs_order-vbeln IS INITIAL.
  MESSAGE 'Sales order number is mandatory' TYPE 'E'.
ENDIF.
```

* `gs_order-vbeln` 是**选择屏幕**结构体的字段。100 屏上如果订单号字段不是这个名字（或者虽有同名字段但未与结构体绑定），这段校验读到的就是选择屏幕里的旧值，与用户当前在 100 屏上的输入无关。
* `MESSAGE ... TYPE 'E'` 会终止 PAI 并弹错误框，但 100 屏上**没有任何地方能让用户输入订单号** → 用户只能反复点 SAVE、反复报错，**死循环**。这是最可能被用户报障的现象。

### 🟠 R7（高）与 OK_CODE 处理脱节，可能"每次点任何按钮都在尝试 INSERT"

结合 4.1 的不确定性：若屏图把 `save_order` 放在 `PROCESS AFTER FLOW`（ABAP 中 PAI 的 AFTER FLOW 模块**每个 PAI 都会执行**），那么 `user_command_0100` 处理 `BACK`/`CANC` 之后，紧接着 `save_order` 照样执行 → **点击"取消"也会去写库**。而 `user_command_0100` 的 `SAVE` 分支又根本不调用它。这就是"保存逻辑最危险"的组合：**触发时机与用户意图完全脱钩**。

修复前提是先拿到屏图确认模块流；在此之前，应主动给 `save_order` 加入口守卫：

```abap
MODULE save_order INPUT.
  CHECK ok_code = 'SAVE'.   " 或用独立的命令字段/按钮，不放在 AFTER FLOW
```

### 🟡 R8（中）没有输入校验

* `waerk`：未校验币种是否存在于 `TCURC`、未校验与订单的客户/销售组织是否匹配。
* `netwr` / `menge`：未做金额上限、数量>0、精度/数量单位校验。
* `kunnr`：未校验是否存在、是否为有效且未冻结的销售伙伴（未查 `KNA1`/`XDPA`），可写入无主客户。
* `vbeln`：未校验是否允许修改（很多单据类型下达单后不允许改抬头）、未校验所属销售组织。

### 🟡 R9（中）成功消息不可见 + 状态陈旧

* `MESSAGE 'Order saved' TYPE 'S'` 紧跟 `SET SCREEN 0000` + `LEAVE PROGRAM`，`LEAVE PROGRAM` 会销毁屏幕流程，成功消息很可能**根本不显示**。正确做法是先 `MESSAGE` 再正常导航（或只保留 `LEAVE PROGRAM`）。
* `gt_order` 在 `START-OF-SELECTION` 只读一次，保存后/返回后再进 100 屏看到的是**旧数据**，没有任何刷新（没有重新 SELECT、没有 `READ ... TRANSPORTING` 增量更新）。

### 🟡 R10（低）消息与代码规范

* 全部消息是硬编码英文字符串，没有消息类（`MESSAGE '...' 'ZSORDER' 001`），无法翻译、无法统一维护。
* `DATA lv_check TYPE c LENGTH 1.` 声明后**从未使用**（死变量）。
* 全程序零注释（仅 3 行头注释），关键业务规则（为什么只查该币种、SAVE 按钮挂在哪里）没有任何说明。
* 新语法未使用：`sy-subrc` 检查缺失、`INTO TABLE` 未加 `@`、未用内表表达式（`gt_order[ 1 ]`）。

---

## 七、屏幕流全链路（当前实际行为推断）

```
用户 F8
  ├─ INITIALIZATION            → gv_datum / gv_user（无效赋值）
  ├─ AT SELECTION-SCREEN OUTPUT → P_WAERK 高亮（唯一有效的选择屏幕事件）
  ├─ [F4 on S_VBELN]           → 事件块无效/读空内表；提示 "No order data loaded yet"
  ├─ START-OF-SELECTION        → 读 VBAK（无结果不提示）→ CALL SCREEN 0100
  │    ├─ PBO status_0100      → PF-STATUS/TITLEBAR；P_WAERK 保护逻辑在 100 屏上不生效；无数据下发
  │    ├─ 用户点 SAVE
  │    │    ├─ user_command_0100 → SET SCREEN 0100（仅重画，不保存）
  │    │    └─ save_order        → 取决于屏图模块流；若有非法 OK_CODE 则屏幕无反应
  │    ├─ 若 save_order 真被调用  → 结构不匹配 dump / 主键冲突 / 空抬头脏数据 / COMMIT WORK
  │    ├─ 用户点 BACK/EXIT/CANC → SET SCREEN 0000（+ LEAVE PROGRAM 冗余），无确认
  └─ 回到选择屏幕（gt_order 陈旧，无刷新）
```

---

## 八、结论与修复优先级

**整体判定：该程序不具备生产可用性。** 保存模块（`save_order`）在当前状态下几乎必然在运行时 dump（R1），即使修复了语法层面的结构问题，也仍然是"用数据库旧值回写 + 不检查 sy-subrc + 对话框内 COMMIT WORK"的组合，属于会造成不可逆脏数据与授权放行的实现方式。

| 优先级 | 问题 | 位置 | 建议动作 |
| --- | --- | --- | --- |
| P0 | `SELECT SINGLE *` / `INSERT ... VALUES` 结构不匹配 | 第 79-80、95 行 | 显式列出 5 个字段 |
| P0 | 写库前未校验数据来自用户输入 | 第 73、79、95 行 | 从屏幕字段读入 `ls_order`，禁止用 DB 回读值 |
| P0 | `sy-subrc`（SELECT/INSERT/READ）全部未检查 | 第 42、46、79、95 行 | 每条 DB 语句后立即判断 |
| P0 | 对话框内 `COMMIT WORK` + 直写 VBAK | 第 95-97 行 | 改用 `BAPI_SALESORDER_CREATE` + `BAPI_TRANSACTION_COMMIT/REVERT` |
| P0 | 权限检查 `OTHERS = 2` 未处理导致放行 | 第 82-93 行 | 增加 `WHEN OTHERS` 报错；用 SU53 验证权限对象字段 |
| P1 | `SAVE` 未与 `save_order` 建立连接 | 第 120-121 行 | OK_CODE 分发里显式调用保存入口 |
| P1 | 未处理 OK_CODE 导致屏幕无响应 | 第 119-126 行 | 增加 `WHEN OTHERS`，提示"无效操作" |
| P1 | 必填校验读错内存 + 用户无法输入 | 第 75-77 行 | 校验屏幕字段；把校验字段真正放到 100 屏并绑到独立结构 |
| P1 | `save_order` 可能挂在 AFTER FLOW 造成误触发 | 屏图（源码外） | 取屏图确认；给模块加 `CHECK ok_code = 'SAVE'` |
| P1 | F4 事件声明错误 + 查内存内表 | 第 41-43 行 | 拆成 `-low`/`-high`，改为现场查库 |
| P2 | 选择结果为空无提示 / 全表风险 | 第 46-52 行 | 检查 `sy-subrc`；`s_vbeln` 必填校验 |
| P2 | PBO 无数据下发、`P_WAERK` 保护失效 | 第 55-67 行 | 100 屏加表格控件并 `LOOP AT SCREEN` 绑定 `gt_order`；保护字段用真实屏字段名 |
| P2 | 硬编码英文消息、死变量、死代码 | 全程序 | 建消息类；删除 `lv_check`/`gv_init`/`gv_datum`/`gv_user` |
| P3 | 无注释、无版本控制痕迹 | 全程序 | 补业务注释，屏幕模块流与屏图纳入版本管理 |

**给接手者的一句话**：在拿到 dynpro 100 的屏图与模块流之前，不要相信源码里的 MODULE 声明能反映实际执行顺序；保存相关的所有行为都依赖那份不在这份源码里的信息。
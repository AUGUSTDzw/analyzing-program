# ZSALES_SYNCH 源码分析报告

> 分析对象：`zsales_synch.abap`（146 行）+ `zi_vbak_open.asddls`（22 行）
> 业务链路：CDS 视图取数 → 手工拼 JSON → HTTP POST 外部 REST 服务
> 关注重点：CDS 取数条件、JSON 拼装、HTTP 调用与错误处理

---

## 一、结论速览

整体结构（FORM 分解、变量命名、全局变量使用）是典型报表程序风格，意图清晰，但**在"看起来能跑"和"实际可靠"之间差距很大**。核心问题集中在三处：

| # | 严重度 | 位置 | 问题 |
|---|--------|------|------|
| 1 | **P0 阻塞** | `zsales_synch.abap:34-39, 86-137` | `p_dryrun` 只在 `log_result` 里用于控制打印，**HTTP 调用无条件执行**。"空跑"开关是假的，默认 `'X'` 下依然会把数据推到外部系统 |
| 2 | **P0 阻塞** | `:112-129` | `send` / `receive` 的 `sy-subrc` **完全没有检查**，且 `lv_status` 初始为 0。远端 500、超时、连接失败时，程序打印 `posted to ...` 后**以绿灯正常结束** |
| 3 | **P0 阻塞** | `:94-96, 121` | `cl_http_client=>create_by_url` 会在创建客户端后**立即以 GET 发送请求**，代码未 `set_method( if_http_client=>method_post )`。实际发出的是一次"空 GET + 一次无业务方法的 POST"，且 URL 上根本不是 POST 语义 |
| 4 | **P0 安全** | `:26, 94-96` | URL 为选择屏幕自由文本 + **无任何认证头**。任何有 S_TCODE 权限的用户可把"2024 年以来全部 USD 订单"POST 到任意 http 地址，数据外泄通道 |
| 5 | **P1** | `:94-96` | URL 未校验 scheme（明文 http 可用）、未限定 host 白名单、无超时参数化（`timeout = 3` 秒对公网接口过激） |
| 6 | **P1** | `:50-52` | `SELECT ... INTO TABLE` 之后判断 `sy-subrc <> 0` 是**死代码**（`SELECT INTO TABLE` 不设置 sy-subrc，该分支永不进入），"无数据"的实际表现是继续拼出 `[]` 并推送 |
| 7 | **P1** | `:131-135` | 只判 `>= 400`：**3xx 重定向被当成成功**；HTTP 200 + 错误 body 的服务无法识别。`MESSAGE ... TYPE 'S'` 会**终止当前 FORM，导致 `lo_client->close( )` 被跳过**（HTTP 连接泄漏） |
| 8 | **P1** | `:63-81` | 手工字符串拼 JSON：**无转义**、`sy-tabix` 隐式依赖、反复 `gv_json && lv_row` 触发 O(n²) 拷贝、日期输出 `YYYYMMDD` 非 ISO、金额小数位不受控、空表发 `[]` |
| 9 | **P1** | `zi_vbak_open.asddls:20-22` + `:47-48` | 业务过滤条件（`USD` / `>= 20240101`）**写死在 CDS 视图里**，报表再次重复同一条件（第二份真值来源）；"daily summary" 实际推送 2024 年至今**全量订单头**，无聚合、无上限 |
| 10 | **P1** | `zi_vbak_open.asddls:2` | `@AccessControl.authorizationCheck: #NOT_REQUIRED`：客户号 + 金额属于敏感业务数据，视图对所有人开放，无 DCL、无 PFCG |
| 11 | **P2** | `:44-48` | `INTO TABLE gt_orders` 缺 `@`，结构靠人工同步；视图字段增删/改名时**运行期直接 dump**，没有编译期保护 |
| 12 | **P2** | `:140-146` | `log_result` 只有 `WRITE`，无应用日志；失败与成功都无留痕，后台定时运行时无法追溯 |

---

## 二、执行流程

```text
INITIALIZATION
   └─ gv_base_url = p_url (选择屏幕自由输入)

START-OF-SELECTION
   ├─ read_from_cds    SELECT * FROM z_i_vbak_open WHERE waerk='USD' AND wrdat>=20240101
   ├─ build_payload    手工拼 [ {...}, {...} ]
   ├─ push_to_service  ← 不看 p_dryrun，直接走 HTTP
   └─ log_result       仅在 p_dryrun 为空时 WRITE 'posted to ...'
```

耦合点：`push_to_service` 里三个致命缺陷都在同一段 50 行内，且**错误信息在最外层完全不可见**（列表报告中 `MESSAGE TYPE 'S'` 只在屏幕上飘一行，不写日志、不置消息类、不影响退出码）。

---

## 三、CDS 视图 `ZI_VBAK_OPEN`

### 3.1 取数条件

```abap
where
  wrdat >= '20240101'
  and waerk  = 'USD'
```

这是本程序最值得质疑的设计：

1. **过滤逻辑本该属于报表/应用层，不该固化在视图定义里。** 视图一旦被固化 USD + 2024，别的场景（查 EUR、查历史、查今天）**必须改 CDS 视图**，而 CDS 视图是跨程序共享对象，改动会触发所有消费者的传输/激活回归——典型的 change impact 陷阱。
2. **`WHERE` 里的日期是硬编码字面量**，没有参数化。正确做法是视图不带业务过滤（或只带"结构性过滤"），日期/币种通过 `WITH PARAMETERS` 或直接由报表 `WHERE` 传下去。
3. 报表侧 `zsales_synch.abap:47-48` 又写了一遍完全相同的条件。因为 CDS 优化（视图里的 WHERE 必然向下传递），报表侧的 `WHERE` 是**纯冗余**，却制造了"两处配置"的错觉——将来只改一处，不会有人发现逻辑已经跑偏。

### 3.2 视图本身的问题

- **`@AccessCatalog...: #NOT_REQUIRED`**：DCL 缺失，`kunnr` / `netwr` 对所有授权用户开放。若这是标准 SAP 交付的订单视图，应改为 `#REQUIRED` 并挂 PFCG（订单数据域至少 `F_BKPF_BUK`/组织级对象），或至少建 DCL 排除掉非业务范围客户。
- **`cast( sy-datum as abap.dats ) as run_date`**：`sy-datum` 本身就是 `abap.dats`，这个 `cast` 是空操作；同时把 **`sy-` 系统字段塞进视图定义**，属于"非确定性 / 与运行上下文绑定"的建模方式，会带来缓存、后台任务、测试可复现性的困扰。更合理的是由 ABAP 侧传入 `sy-datum`。而且报表**根本没有消费 `run_date`**——白白付了建模成本。
- **`association [0..1] to ZI_KNA1_NAME`**：客户名被暴露为 `_Customer` 关联，但报表没有 join 取名。要么用上（推送 payload 里有客户名才是业务价值点），要么删掉。注意基数声明为 `[0..1]`：若 `ZI_KNA1_NAME` 对 `kunnr` 可能返回多行或 0 行，日后有人加 join 会踩坑（去重 / sy-subrc）。
- **字段冗余**：`netwr` 与 `net_amount` 同一来源各暴露一次（`netwr` 原始 + `netwr as net_amount` 带 currencyCode 语义），报表选的是 `netwr`，**白白丢弃了 `@Semantics.amount.currencyCode` 带来的金额语义**，下游拿到一个裸 number，无法自证币种。
- **命名与内容不符**：视图名叫 `..._OPEN`（未结订单），但过滤条件里**没有任何"未结"判据**（没有对 `VBSTATUS` / `LVKON` / `WBKLS` 之类完成标志的过滤）。`ZI_` 前缀在很多团队的规范里表示"接口/集成"，与 `EndUserText` 里写的 "batch pricing review" 也对不上。名字会骗人，注释不会——这类不一致最容易在需求变更时演变成缺陷。
- **待确认**：`menge` 字段被当作"订单数量"使用。若 `MENGE` 语义与业务期望（明细行数量合计 vs 表头冗余值）不一致，或者该字段在当前 SAP 版本/表头层含义不同，需要与业务确认口径。报告把它放在 payload 之外（没有推送），所以当前无直接影响，但一旦加入推送就是口径错误。

---

## 四、SELECT 取数（`read_from_cds`）

```abap
SELECT vbeln kunnr waerk netwr menge wrdat
  FROM z_i_vbak_open
  INTO TABLE gt_orders
  WHERE waerk = 'USD'
    AND wrdat >= '20240101'.

IF sy-subrc <> 0.
  MESSAGE 'CDS view returned no rows' TYPE 'S'.
ENDIF.
```

问题清单：

- **`IF sy-subrc <> 0` 是死代码**。`SELECT ... INTO TABLE` 不会把 sy-subrc 置为非 0（无结果时也是 0，sy-tabix 为 0）。"无数据"的真实路径是：空表 → `build_payload` 产出 `[]` → 推送一个空数组 → 对方服务很可能返回 400 → 报"Remote service rejected the payload"，**排查时会被彻底带偏**。正确判空用 `IF gt_orders IS INITIAL` 或 `lines( gt_orders ) = 0`。
- **缺 `@`**：未使用 host variable 语法，`gt_orders` 与视图字段的类型/名称靠人手保持一致。视图改字段（改名、长度变化）→ 激活通过、报表激活也通过、**运行时 conversion dump**。这是报表程序最常见的线上事故来源。
- **无 `PACKAGE SIZE`**：全量结果一次进内存。2024 年至今的订单头在生产环境轻易几十万行，内部表 + 随后拼出的 `gv_json` 字符串 + `xstring` 副本，内存占用是**三份**。应当在循环中做聚合。
- **聚合口径缺失**：文件头注释写 "pushes a **daily summary**"，代码却是一行订单一行 JSON，且日期下界是 2024-01-01。`run_date` 没用上、`sy-datum` 没用上、"daily" 这个词**在代码里没有任何对应实现**。要么改注释，要么改实现——这是需求与实现的口径漂移，必须与业务对齐后再改。
- `WRITE: / 'orders', lines( gt_orders )` 放在取数后立刻打印，把行数暴露在屏幕上（生产环境属于信息泄露面），建议并入 `log_result`。

---

## 五、JSON 拼装（`build_payload`）

```abap
gv_json = '['.
LOOP AT gt_orders INTO DATA(ls_order).
  lv_row = |{ |"vbeln": "{ ls_order-vbeln }",| &
            |"customer": "{ ls_order-kunnr }",| &
            |"amount": { ls_order-netwr },| &
            |"currency": "{ ls_order-waerk }",| &
            |"date": "{ ls_order-wrdat CONDENSE SPACE }" }|.
  IF sy-tabix > 1.
    gv_json = gv_json && |,|.
  ENDIF.
  gv_json = gv_json && lv_row.
ENDLOOP.
gv_json = gv_json && ']'.
```

| 缺陷 | 说明 | 后果 |
|------|------|------|
| **无转义** | `vbeln` / `kunnr` / `waerk` 直接插值 | 当前字段是纯数字/字母，侥幸安全；一旦按"业务价值点"把 `ZI_KNA1_NAME` 的客户名塞进 payload（客户名必含空格、`"`、`\`、`&`），**产出的就是非法 JSON**，远端 400，且本地毫无提示。`escape( ... format = ... )` 是 HTML/XML 语义，不能用来做 JSON 转义，必须自己处理 `\` 与 `"` |
| **`sy-tabix` 隐式依赖** | 用循环计数器决定是否加逗号 | 目前逻辑等价于"第一行不加逗号"，能跑对；但 `sy-tabix` 是全局的隐式状态，**任何人在这两行之间插入一次内表操作**（排序、READ、另一个 LOOP）就会静默产出 `,,` 或缺逗号 → 非法 JSON。这类 bug 只在特定数据量下偶发，极难定位。改用显式首行标志或 `concat_lines_of` |
| **O(n²) 字符串拼接** | `gv_json = gv_json && lv_row` 每行复制整个累积串 | 十万行时是数十亿次字符拷贝，ABAP 字符串扩容 + GC 直接把工作台拖死。正确做法是拼进行表后一次 `concat_lines_of( )` |
| **日期格式** | `wrdat` 是 `DATS`，`CONDENSE SPACE` 对 8 位定长数字日期**毫无作用**，输出 `20240615` | 绝大多数 REST 端点要求 ISO 8601 `2024-06-15`。这是一个"看起来处理过、其实没处理"的假动作，评审极易放过。应使用 `|{ ls_order-wrdat DATE = ISO }|` |
| **金额无格式契约** | `\|{ ls_order-netwr }\|`，`NETWR` 为 `CURR(23,2)` | 小数位数由类型隐式决定，没有显式 rounding 契约；若该字段在后续被改成 `CHAR` 型的带千分位/本地化格式值，将产出 `"amount": 1.234,50` —— **非法 JSON**。且 JSON number 无币种语义，币种靠旁边字段"自证" |
| **空表** | 无数据仍产出 `[]` 并推送 | 语义上"今天没有订单"应跳过推送或发带 `count: 0` 的信封，而不是让远端来判 400 |
| **无信封/元数据** | 裸数组 | 缺少 `run_date`、数据源、行数、schema 版本。对端无法幂等去重，重推一次就重复入账 |
| **初始值** | `kunnr` 初始 → `"customer": ""` | 业务上空值应是 `null`，空串通常会被对端校验拒绝 |

---

## 六、HTTP 调用（`push_to_service`）

### 6.1 `create_by_url` 用错

```abap
cl_http_client=>create_by_url(
  EXPORTING url = gv_base_url
  IMPORTING client = lo_client
  EXCEPTIONS argument_not_found = 1 plugin_not_active = 2 OTHERS = 3 ).
```

`CREATE_BY_URL` 是**"创建 + 立即发送 + 接收"的一体化快捷方法**（面向 GET 场景）。因此本程序的实际行为是：

1. 第一次请求：**空的 GET**，打到 URL 上，此时还没有任何业务 body、也没有业务方法；
2. 然后代码又 `set_cdata` + `send` 发第二次，但**从未调用 `set_method( )`**，方法仍停留在默认；
3. 两次请求的响应被互相覆盖，`lv_status` 反映的是哪一次取决于对象内部状态——**不可预期**。

正确写法是 `cl_http_client=>create( )` + 显式 `set_method( if_http_client=>method_post )`。

### 6.2 异常与状态处理是"看起来处理了"

```abap
lo_client->send( EXCEPTIONS http_communication_failure = 1 ... OTHERS = 4 ).
lo_client->receive( EXCEPTIONS ... ).
IF sy-subrc = 0.
  lv_status = lo_client->response->get_status( ).
ENDIF.
IF lv_status >= 400.
  MESSAGE 'Remote service rejected the payload' TYPE 'S'.
ENDIF.
lo_client->close( ).
```

- `send` 的 `sy-subrc` **完全未判**：失败后仍然调 `receive`（多半再抛 `http_invalid_state`），而 `receive` 的失败**只会让 `lv_status` 保持 0**。
- `lv_status` 初值 0 → **`0 >= 400` 为假 → 一路绿灯走到 `log_result` 打印 `posted to ...`**。这就是最恶劣的失败模式：**数据没送出去，但报告显示成功**。定时任务每天跑一次，问题要等到对方对账发现缺数时才暴露。
- `MESSAGE '...' TYPE 'S'` **会终止当前 FORM**，因此 `lo_client->close( )` **不会执行** → HTTP 连接不归还，长跑任务下 ICM 连接池耗尽。
- `MESSAGE` 未指定消息类（`MESSAGE-ID`），文本硬编码不可翻译，且**后台运行时 TYPE 'S' 消息基本被丢弃**，等于什么都没记。
- 状态判定只覆盖 `>= 400`：**3xx（重定向）视为成功**，401/403 与 400 混为一谈；HTTP 200 但 body 里是 `{"error": ...}` 的接口无法识别。
- **没有任何认证**：`Authorization` 头、API Key、OAuth 全部缺失。凭证缺失说明要么服务不需要认证（生产系统几乎不可能），要么**调用方式本身就没跑通过**——建议向对接方确认接口契约。
- `timeout = 3` 秒硬编码：公网 + 大 payload 下必然大量 `http_communication_failure`，而且失败被静默（见上）。
- `CREATE XSTRING LV_XSTRING DATA GV_JSON` **未显式 `CODEPAGE = 'UTF-8'`**，依赖系统默认代码页；一旦 payload 含非 ASCII（客户名、中文备注）就有乱码风险。
- 无 **重试 / 幂等键**：重复运行或人工重跑会重复推送；也没有"推送内容指纹"，无法回答"昨天到底发了哪一版"。

### 6.3 清理路径不完整

| 出口 | `close( )` 是否执行 |
|------|--------------------|
| `create_by_url` 失败 → `RETURN` | 无需（客户端未创建） |
| `send` / `receive` 失败 | 否（`sy-subrc` 未拦，继续往下） |
| `lv_status >= 400` → `MESSAGE` | **否**（MESSAGE 终止 FORM） |
| 正常 | 是 |

---

## 七、错误处理与可观测性总评

当前程序的"错误处理"实际形态是：三处 `WRITE`、两处 `MESSAGE TYPE 'S'`、若干 `sy-subrc` 检查（其中关键的两个被跳过）。它满足的是"代码里有 IF 语句"，不满足"失败可被观测"：

- **没有消息类** → 无法做 message class 级的监控；
- **没有应用日志** → 后台运行时无痕迹；
- **没有失败退出码** → 定时任务 job 永远绿灯；
- **没有 dry-run 语义隔离** → 最危险的一点：想"先看看不真发"，实际上已经发出去了；
- **无法单元测试** → 逻辑锁在 FORM 里，JSON 构造和 HTTP 调用没有可替换的接缝。

---

## 八、修复建议（按优先级）

### P0-1 让 dry-run 真正生效

```abap
FORM push_to_service.
  IF p_dryrun = 'X'.
    WRITE: / 'DRY RUN - skipped HTTP, payload size:',
           byte_length( gv_json ), 'bytes, rows:', lines( gt_orders ).
    RETURN.
  ENDIF.
  " ... 真实调用
ENDFORM.
```

同时把 `log_result` 的语义改成"结果上报"，不要再用 checkbox 控制"是否打印成功"。

### P0-2 正确的 POST 调用骨架

```abap
FORM push_to_service USING iv_url TYPE string.

  DATA lo_client TYPE REF TO if_http_client.
  DATA lv_xstring TYPE xstring.
  DATA lv_status  TYPE i VALUE 999.
  DATA lv_body    TYPE string.

  CREATE XSTRING lv_xstring DATA gv_json CODEPAGE = 'UTF-8'.

  cl_http_client=>create(
    EXPORTING
      url        = iv_url
    IMPORTING
      client     = lo_client
    EXCEPTIONS
      argument_not_found = 1
      plugin_not_active  = 2
      OTHERS             = 3 ).

  IF sy-subrc <> 0.
    " 记录日志 + MESSAGE e 终止；此处 lo_client 未创建，不需 close
    ...
    RETURN.
  ENDIF.

  lo_client->request->set_method( if_http_client=>method_post ).
  lo_client->request->set_cdata( lv_xstring ).
  lo_client->request->set_content_type( 'application/json' ).
  lo_client->request->set_request_header( name = 'Accept'
                                           value = 'application/json' ).
  " 如对端要求鉴权：
  " lo_client->request->set_request_header( name = 'Authorization'
  "                                        value = |Bearer { lv_token }| ).

  TRY.
      lo_client->send(
        EXPORTING timeout = lv_timeout
        EXCEPTIONS http_communication_failure = 1
                    http_invalid_state         = 2
                    http_processing_failed     = 3
                    OTHERS                     = 4 ).
      IF sy-subrc <> 0.
        " 发送失败：记录 sy-subrc，必须在此终止，不得继续 receive
      ENDIF.

      lo_client->receive(
        EXCEPTIONS http_communication_failure = 1
                    http_invalid_state         = 2
                    OTHERS                     = 3 ).
      IF sy-subrc = 0.
        lv_status = lo_client->response->get_status( ).
        lv_body   = lo_client->response->get_data( ).
      ENDIF.
    CATCH cx_static_check.
      " 兜底异常同样必须走统一失败出口
  ENDTRY.

  " 统一出口：先关连接，再上报错误，避免 MESSAGE 打断 close
  lo_client->close( ).

  IF lv_status < 200 OR lv_status >= 300.
    " 3xx 也当作失败/待人工确认；把响应 body 落日志便于对账
  ENDIF.

ENDFORM.                       "push_to_service
```

关键改动：`method_post` 显式设置、`sy-subrc` 逐段拦截、`close( )` 提到错误上报之前、状态码区间判定、响应 body 留痕。

### P0-3 补鉴权与 URL 约束

```abap
* 进入前校验 scheme + host 白名单
IF iv_url NOT MATCH '^https://api\.example\.com(/.*)?$'
   OR iv_url CA '?& '.
  MESSAGE e000(zsales_synch) WITH 'URL 不合法'.
ENDIF.
```

并为报告配置 PFCG 授权对象；`p_dryrun = 'X'` 时限制在 `SY-TCODE` 白名单内。

### P1-1 取数条件参数化，CDS 视图不再固化业务条件

```abap
" CDS 视图：只保留结构性条件，参数由调用方传入
define view entity ZI_VBAK_OPEN
  as select from vbak
  association [0..1] to ZI_KNA1_NAME as _Customer
    on $projection.kunnr = _Customer.kunnr
{
  key vbeln,
      kunnr,
      waerk,
      @Semantics.amount.currencyCode: 'waerk'
      netwr as net_amount,
      wrdat
}
```

```abap
" 报表侧：参数化 + 宿主变量 + 显式结构
SELECT vbeln, kunnr, waerk, netwr AS net_amount, wrdat
  FROM z_i_vbak_open
  INTO TABLE @gt_orders
  WHERE waerk = @p_waerk
    AND wrdat BETWEEN @p_since AND @p_until.
```

选择屏幕增加 `p_waerk`（默认 USD）、`p_since`、`p_until`（默认 `sy-datum - 1`，落实 "daily" 语义），并把 `sy-datum` 从视图里挪到 ABAP 侧。

### P1-2 真正的 JSON 构造（先聚合、再序列化）

```abap
FORM build_payload.
  DATA lt_rows TYPE ty_string_tab.
  DATA lv_row  TYPE string.

  IF gt_orders IS INITIAL.
    gv_json = '[]'.
    RETURN.
  ENDIF.

  LOOP AT gt_orders INTO DATA(ls_order).
    lv_row = |{ "vbeln"   : "{ escape_json( ls_order-vbeln ) }"|
          |, "customer": "{ escape_json( ls_order-kunnr ) }"|
          |, "amount"  : { ls_order-netwr DECIMALS = 2 }|
          |, "currency": "{ ls_order-waerk }"|
          |, "date"    : "{ |{ ls_order-wrdat DATE = ISO }| }" }|.
    APPEND lv_row TO lt_rows.
  ENDLOOP.

  gv_json = |[{"run_date": "{ |{ sy-datum DATE = ISO }| }"|
        |, "rows": [ { concat_lines_of( table = lt_rows sep = ',' ) } ] }]|.

ENDFORM.

FORM escape_json USING iv_val TYPE any RETURNING VALUE(rv_out) TYPE string.
  DATA lv_tmp TYPE string.
  lv_tmp = |{ iv_val }|.
  REPLACE ALL OCCURRENCES OF '\' IN lv_tmp WITH '\\'.
  REPLACE ALL OCCURRENCES OF '"' IN lv_tmp WITH '\"'.
  REPLACE ALL OCCURRENCES OF |{ cl_abap_char_utilities=>newline }| IN lv_tmp WITH '\n'.
  rv_out = lv_tmp.
ENDFORM.
```

若项目里有可用的 JSON 序列化类（如 `/ui2/cl_json` 之类），直接用它替代手写模板，键顺序、空值、数字格式都由库保证，收益远大于自己维护模板。

### P1-3 可观测性

- 增加消息类 `ZSALES_SYNCH`，所有失败路径 `MESSAGE ... TYPE 'E'/'A'` 并指定 `ID`；
- 统一写应用日志（`BAL_LOG_CREATE` 或自建日志类）：行数、payload 长度、`SY-UNAME`、状态码、响应 body 摘要、payload 指纹（`SHSTRING2` / `HASH`）；
- `lv_status` 初值改为 999，保证"未知"永远不等于"成功"；
- 推送成功后输出可对账的批次号（`run_date + 行数`），便于与对端核对。

### P2 结构性改进

- 把 FORM 逻辑迁到**本地类**（`lcl_synch`）+ 依赖接口（`zif_http_sender`），JSON 与 HTTP 可单元测试、HTTP 可打桩；
- `WITH EMPTY KEY`（`:18`）写法是对的，保留；补上 `@` 宿主变量语法；
- 选择屏幕加字段标签、`NO-DISPLAY` 版本参数（`P_TEST`）、`p_urllen` 限制；
- 若确需全量推送，加 `PACKAGE SIZE` + 哈希表聚合，或改为分批推送 + 批次号。

---

## 九、验证与测试建议

修复后至少覆盖以下用例（这是当前程序完全缺失的部分）：

| 用例 | 期望 |
|------|------|
| CDS 返回 0 行 | 不发 HTTP（或发 `count:0` 信封），job **不报成功** |
| CDS 返回 1 行 | JSON 为 `[{...}]`，**无前导逗号** |
| CDS 返回 N 行 | 数组合法，`json_valid` 可校验 |
| `kunnr` 含 `引号` / `反斜杠` / 中文 | 转义正确，远端不 400 |
| `netwr` 含大额与负数 | `amount` 为合法 JSON number，无千分位、本地化逗号 |
| `wrdat` | 输出 ISO `YYYY-MM-DD` |
| 远端 200 | 记录日志，job 绿灯 |
| 远端 400 / 401 / 500 | 日志含响应 body，job 红灯，连接已 `close` |
| 远端 302 | 判为失败（按业务约定） |
| 连接超时 / 目标不可达 | `send` 的 `sy-subrc` 被拦截，不打印 `posted to` |
| `p_dryrun = 'X'` | **零 HTTP 请求** |

---

## 十、遗留待确认项

1. 接口契约未知：HTTP 方法、鉴权方式、请求/响应 schema、分页要求、超时约定——需向对接方索取。**当前代码的实现细节与任何一种常见 REST 契约都不匹配**，这是最优先要澄清的事。
2. `MENGE`（`ZI_VBAK_OPEN`）的业务口径：订单头数量是否等于明细汇总？是否需要下推到 payload？
3. "daily summary" 的准确定义：是"每天推昨天新增订单"，还是"每天推全量快照"？目前实现两者都不是（推 2024 至今全量，且逐条而非汇总）。
4. `ZI_KNA1_NAME` 的存在性与基数：若后续要 join 取客户名，需确认 `kunnr` 唯一。
5. 该报表是否已在生产运行？若已运行，需检查历史执行日志确认推送量与频率，据此评估回滚方案。

---

## 附：一句话总结

这个程序"能编译、能跑完、不 dump"，但**在业务语义上（dry-run 形同虚设、全量冒充日报、过滤条件写在共享视图里）、在可靠性上（异常被静默吞掉、失败被报成成功）、在安全性上（无鉴权、URL 自由输入、无转义）三个层面都不具备生产可用性**。优先级最高的改动只有两处：让 `p_dryrun` 真正短路 HTTP 调用，以及把 `send`/`receive` 的 `sy-subrc` 和 `lv_status` 老实检查掉——这两点决定了它是"日报工具"还是"静默丢数据的小程序"。
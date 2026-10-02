# ZSALES_SYNCH 分析报告

> 分析对象：`zsales_synch.abap`（146 行，报表程序）+ `zi_vbak_open.asddls`（22 行，CDS View Entity）
> 分析重点：CDS 取数条件 / JSON 拼装 / HTTP 调用的错误处理

---

## 0. 一句话结论

**当前状态下这个程序既不能正确取数，也不能正确推送，而且会在"默认勾选 dry run"的情况下真的把数据发出去，同时把所有失败都报成成功。** 共有 3 个必须立刻修复的阻断级缺陷（缺 `set_method`、dry-run 开关失效、失败被吞成成功），以及 1 个数据泄露隐患（URL 自由输入 + 默认指向外部域名 + 无鉴权）。

| 等级 | 数量 | 代表问题 |
|---|---|---|
| 阻断 P0 | 3 | 未设置 HTTP method（默认 GET）、`p_dryrun` 完全未参与发送逻辑、失败状态被判定为成功 |
| 高危 P1 | 7 | `sy-tabix` 当逗号分隔符、金额小数点变逗号、CDS 硬编码业务过滤、`#NOT_REQUIRED` 无授权、URL 无校验、明文外发客户数据、金额语义（表头价）未确认 |
| 中危 P2 | 8 | `sy-subrc` 误用、CDS 与 ABAP 双重过滤、`sy-datum` 写进视图、超时不对称、无响应体日志、全量扫描无分页、`netwr`/`net_amount` 双暴露、"daily summary" 名不副实 |
| 低危 P3 | 5 | JSON 手工拼接 O(n²)、`CONDENSE SPACE` 空操作、`gv_user` 字段命名、`WRITE` 在后台作业无效、未用 CDS DDIC 类型 |

---

## 1. 程序骨架与实际执行流

```abap
REPORT zsales_synch.

INITIALIZATION.
  gv_base_url = p_url.
  gv_user     = sy-unime.

START-OF-SELECTION.
  PERFORM read_from_cds.     " 1 取数
  PERFORM build_payload.     " 2 拼 JSON
  PERFORM push_to_service.    " 3 发送（无条件）
  PERFORM log_result.        " 4 打印
```

四个 FORM 线性串联、无异常统一出口、无返回码传递。`p_url` / `p_dryrun` 两个输入参数中，只有 `p_url` 被真正使用，而 `p_dryrun` 只影响最后一行 `WRITE`——这是全文最危险的设计（见 §6.2）。

数据流（AS-IS）：

```
VBAK ──> ZI_VBAK_OPEN (硬编码 USD + wrdat>=20240101)
      ──> gt_orders (全量载入内存, EMPTY KEY)
      ──> gv_json (手工字符串拼接)
      ──> xstring (按系统码页转换)
      ──> cl_http_client (GET, 无鉴权, 任意 URL)
```

---

## 2. CDS 视图 `ZI_VBAK_OPEN`

```abap
@AbapCatalog.sqlViewName: 'ZVBAKOPEN'
@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZI_VBAK_OPEN
  as select from vbak
  association [0..1] to ZI_KNA1_NAME as _Customer
    on $projection.kunnr = _Customer.kunnr
{ ... }
where
  wrdat >= '20240101'
  and waerk  = 'USD'
```

### 2.1 「取数条件」的问题（本节是重点）

**① 业务过滤条件被写死在 DDL 里，且无法覆盖**
`wrdat >= '20240101'` 和 `waerk = 'USD'` 是硬编码常量，不是参数。后果：
- 想取 EUR 单据、想换时间窗、想按销售组织过滤的调用方**无法覆盖**，只能得到空结果；
- 没有 `@Consumption` / `WITH PARAMETERS` 之类的参数化出口，所以"换条件"唯一的办法就是改视图，而视图是被多个程序共用的；
- 2024-01-01 这个起点在视图里和程序里各写了一遍（见 §3.2），两处会随时间漂移。

**② `cast( sy-datum as abap.dats ) as run_date` 让视图变成非确定性对象**
把会话变量 `sy-datum` 塞进 SELECT 列表是 DDL 层的反模式：
- 结果依赖调用时点，不可缓存、不可复用；
- 该表达式通常会阻止谓词下推（pushdown），让 `WHERE wrdat >= ...` 无法完全下推到 DB；
- 任何二次加工（CDS 消费模型、MDM 抽取、跨系统同步）复用这个视图都会得到"运行当天"这个伪业务字段。
应该改成由调用程序传入，或干脆删掉。

**③ 视图名叫「Open」，但没有任何状态过滤**
`vbak` 里含已完成、已取消、已作废的订单头（文档类别、订单状态 `trstatus`/`rbstat` 都没过滤）。视图标签写的是 "Open sales order headers for batch pricing review"，语义与实际内容不符，报表把"2024 年以来所有 USD 销售订单头"全部推给外部系统。

**④ `netwr` 与 `net_amount` 双重暴露**
同一个字段出现了两次，只有 `net_amount` 带 `@Semantics.amount.currencyCode: 'waerk'`，`netwr` 裸奔。下游随手选 `netwr` 就丢掉币种语义。同时这也说明视图是"边写边加"的产物，没有做过清理。

**⑤ `association` 是死元数据**
`ZI_KNA1_NAME` 没有 join、也没有被任何消费方 select，运行时零开销，但它让视图多了一个激活期依赖。若该 CDS 不存在/未激活，视图无法激活。另一个待确认点：若 `ZI_KNA1_NAME` 带语言字段（`spras`），`[0..1]` 的基数声明就是错的，应为 `[0..*]`。

**⑥ `@AccessControl.authorizationCheck: #NOT_REQUIRED` + 无 DCL**
任何能执行 `ZSALES_SYNCH` 的用户，都会拿到**全量**客户号（`kunnr`）和订单金额，且没有行级/对象级授权控制。客户主数据 + 销售金额属于受管控数据，这一项建议按合规问题上报。

**⑦ 全表扫描**
`vbak` 是超大表，条件打在非键字段 `waerk`/`wrdat` 上，且 `wrdat` 没有上界。视图没有任何范围收敛手段，2024 年之后的数据量会随时间线性增长。

---

## 3. 取数阶段 `read_from_cds`

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

### 3.1 `sy-subrc` 语义误用：这段错误处理永远不会按预期触发

`SELECT ... INTO TABLE` 返回 0 行时 `sy-subrc = 0`（只有数据库错误、类型转换错误、授权失败等才会非 0）。所以：

- **"返回 0 行"这个分支根本走不到** → 视图查不到数据时，程序会带着 `'[]'` 继续往下走，正常推送一个空数组；
- 反过来，当 `sy-subrc` 真的非 0 时（DB 断连、字段转换失败），报出来的信息却是"没有数据"——**故障原因被彻底掩盖**。

正确写法是把"空结果"和"失败"分开判断：

```abap
  IF sy-subrc <> 0.
    MESSAGE 'CDS read failed: internal error' TYPE 'E'.
  ENDIF.

  IF lines( gt_orders ) = 0.
    MESSAGE 'No matching sales orders in selection' TYPE 'S'.
    RETURN.
  ENDIF.
```

### 3.2 过滤条件在 CDS 和 ABAP 里重复了

视图已经过滤了 `waerk = 'USD'` 和 `wrdat >= '20240101'`，ABAP 的 `WHERE` 再写一遍：
- 对结果**没有任何影响**（下推后 CDS 先过滤）；
- 却制造了"两处规则"的错觉 —— 有人把 ABAP 侧改成 `waerk <> 'USD'` 时，永远得到 0 行，而且因为 §3.1 的 bug 连提示都不会有，排查成本极高。

过滤条件应该**只在 CDS 里定义一次**（并且参数化），报表只负责传选择条件。

### 3.3 全量装载、无分页、无上界

`INTO TABLE` 一次性把所有命中行读进内表，没有 `PACKAGE SIZE`，没有日期上界，没有 ALPHA 转换。而 `ty_order_tab` 是 `WITH EMPTY KEY`：

```abap
TYPES ty_order_tab TYPE STANDARD TABLE OF ty_order WITH EMPTY KEY.
```

`EMPTY KEY` 正好触发了 §5.2 里 `sy-tabix` 的坑；同时它也意味着这份数据只能顺序遍历，无法做任何基于键的聚合/去重。

### 3.4 自己声明结构体，而不是用 CDS 生成的类型

程序自己定义了 `ty_order`，而不是用 CDS 实体对应的 DDIC 类型（`ZI_VBAK_OPEN` / `ZVBAKOPEN` 的结构）。代价：视图加字段、改字段名、改类型，编译期毫无感知，运行期才炸；同时视图新增的 `net_amount`、`run_date` 两个字段完全用不上。

---

## 4. `lv_status` 与 `sy-tabix` 两个隐性 bug 的共同点

这两个 bug 有同一个成因：**用"上一条语句留下的"系统变量去推断当前循环/调用的状态**。`sy-subrc`、`sy-tabix` 在语句之间随时可能被覆盖，ABAP 里唯一可靠的"上一次操作结果"就是紧跟其后的 `sy-subrc`。

---

## 5. JSON 拼装 `build_payload`

```abap
    lv_row = |{ |"vbeln": "{ ls_order-vbeln }",| &
              |"customer": "{ ls_order-kunnr }",| &
              |"amount": { ls_order-netwr },| &
              |"currency": "{ ls_order-waerk }",| &
              |"date": "{ ls_order-wrdat CONDENSE SPACE }" }|.

    IF sy-tabix > 1.
      gv_json = gv_json && |,|.
    ENDIF.
```

### 5.1 没有任何转义

整段靠 `| |` 把 `{`、`"` 硬转义出来手写 JSON。只要任一字段出现 `"`、`\`、换行或控制字符，产出的就是语法错误的 JSON，而且没有任何机制能发现。
`vbeln`/`kunnr` 是纯数字字符，暂时安全；一旦按第 2 节说的把客户名称（`ZI_KNA1_NAME`）接进来，中文/引号立刻炸。
这是"手写 JSON"最经典的缺陷，正确解法是让 ABAP 序列化：

```abap
TYPES: BEGIN OF ty_payload,
         vbeln   TYPE string,
         customer TYPE string,
         amount  TYPE string,
         currency TYPE string,
         date     TYPE string,
       END OF ty_payload.

" amount 先转成规范的 '1234.56' 文本，再交给序列化器加引号/转义
lv_amount = ls_order-netwr.
REPLACE ALL OCCURRENCES OF ',' IN lv_amount WITH '.'.
APPEND VALUE #( vbeln = |{ ls_order-vbeln }|
                customer = |{ ls_order-kunnr }|
                amount = lv_amount
                currency = |{ ls_order-waerk }|
                date = |{ ls_order-wrdat }| ) TO lt_payload.

gv_json = /ui2/cl_json=>serialize( data = lt_payload ).
```

### 5.2 `sy-tabix` 当逗号分隔符 —— 非法 JSON（P0/P1）

`ty_order_tab` 是 `WITH EMPTY KEY`。按 ABAP 语义，**`LOOP AT` 只有在内表有（非空）键时才维护 `sy-tabix`**；空键表的 `LOOP AT` 不设置 `sy-tabix`。于是循环里的 `sy-tabix` 保留的是上一条数据库语句留下的值——对前面的 `SELECT ... INTO TABLE`，那是**取到的行数**。

结果：
- 0 行：不进循环 → `'[]'`，碰巧合法；
- 1 行：`sy-tabix = 1`，不加逗号 → 碰巧合法；
- **≥2 行：`sy-tabix` 是行数（>1）且循环中恒定 → 每一行前面都插逗号 → `[,{...},{...}]`，非法 JSON，首字符是 `,`，任何标准 JSON 解析器都会直接报错。**

也就是说，**只要查到 2 条以上数据，100% 发出非法报文**。而且即使给内表加键让 `sy-tabix` 生效，用系统计数器做"是不是第一行"的判断也是脆弱写法。正确做法是显式状态标志：

```abap
  DATA lv_first TYPE abap_true.
  gv_json = '['.
  LOOP AT gt_orders INTO DATA(ls_order).
    IF lv_first = abap_false.
      gv_json = gv_json && ','.
    ENDIF.
    gv_json = gv_json && lv_row.
    lv_first = abap_false.
  ENDLOOP.
  gv_json = gv_json && ']'.
```

### 5.3 金额数值格式

`"amount": { ls_order-netwr }` —— `netwr` 是 `CURR` 类型，模板转换为 `string` 时小数分隔符**跟随系统设置，绝大多数系统是逗号**，产出 `"amount": 1234,56`，这是非法 JSON（RFC 8259 数值不允许逗号）。即使是句点，也可能带前导 `+`、尾随小数点或千分位。
金额必须显式归一化成 `1234.56`，或者干脆以字符串传输并在契约里声明。相关地，`netwr` 是**表头净价**，未过账的订单可能是 0 或陈旧值——"批量价格复核"场景下这个字段是否就是要推送的业务量，需要业务确认（见 §10）。

### 5.4 `CONDENSE SPACE` 是空操作

```abap
|   "date": "{ ls_order-wrdat CONDENSE SPACE }"|
```

`wrdat` 是 `DATS`（CHAR8，`YYYYMMDD`），根本不含空格，`CONDENSE SPACE` 什么也没做。这是一段防御性代码留下的痕迹，暗示作者曾经担心过脏数据，但没解决真正的问题（格式/转义）。

### 5.5 日期与契约

推送的是 `"date": "20240115"`，而不是 ISO 8601 的 `2024-01-15`。字段名叫 `date` 却用 ABAP 内部格式，跨系统对接时是个典型的隐性契约冲突，需要和接口方对齐。

### 5.6 字段/口径问题

- `menge` 取了但**从未进报文**——白读一个字段，白占传输量；
- 报文头注释说"pushes a **daily summary**"，但代码既没有按日期聚合，也没有做任何汇总，只是把每条订单头原样推出去。**注释与实现不符**；
- 视图暴露的 `net_amount`/`run_date` 没用，报文里的 key（`customer`/`amount`）和 CDS 字段名（`kunnr`/`netwr`）也不一致，映射关系只存在于这 5 行模板里，无文档。

### 5.7 字符串拼接是 O(n²)

```abap
gv_json = gv_json && lv_row.
```

循环里不断把整条报文复制一份。行数上万时 CPU 和临时内存都会被这条语句吃掉，报文本身可能只有几十 MB，但峰值分配是它的平方级。应该先 `APPEND` 到 `string` 行内表，最后一次性 `CONCATENATE ... INTO gv_json`（或直接用 §5.1 的序列化器）。

---

## 6. HTTP 调用 `push_to_service`

```abap
  CREATE XSTRING LV_XSTRING DATA GV_JSON.

  cl_http_client=>create_by_url(
    EXPORTING url = gv_base_url
    IMPORTING client = lo_client
    EXCEPTIONS argument_not_found = 1 plugin_not_active = 2 OTHERS = 3 ).

  IF sy-subrc <> 0.
    WRITE: / 'client creation failed', sy-subrc.
    RETURN.
  ENDIF.

  lo_client->request->set_cdata( lv_xstring ).
  lo_client->request->set_content_type( 'application/json' ).

  lo_client->send( EXPORTING timeout = 3 EXCEPTIONS ... OTHERS = 4 ).

  lo_client->receive( EXCEPTIONS ... OTHERS = 3 ).

  IF sy-subrc = 0.
    lv_status = lo_client->response->get_status( ).
  ENDIF.

  IF lv_status >= 400.
    MESSAGE 'Remote service rejected the payload' TYPE 'S'.
  ENDIF.

  lo_client->close( ).
```

### 6.1 【P0】从头到尾没有设置 HTTP method —— 这是 GET 请求

`if_http_client` 的请求方法**默认为 `GET`**，代码里只有 `set_cdata` 和 `set_content_type`，没有任何 `set_method`。也就是说：一个带 JSON body 的 **GET** 请求被发给了外部 REST 服务。绝大多数服务端会返回 `405 Method Not Allowed`，或者干脆忽略 body 直接按 GET 处理。更危险的是：GET 的 URL/参数会被中间代理记录，而这里 body 里装的是客户号和金额。

```abap
  lo_client->request->set_method( if_http_request=>meth_post ).
```

### 6.2 【P0】`p_dryrun` 是个假开关

```abap
  PARAMETERS p_dryrun AS CHECKBOX DEFAULT 'X'.   " 默认勾选 = 默认"试运行"
...
  IF p_dryrun IS INITIAL.
    WRITE: / 'posted to', gv_base_url, 'by', gv_user.
  ENDIF.
```

`p_dryrun` **只出现在 `log_result` 里，决定要不要打印那行提示**。`push_to_service` 完全不看它。也就是说：

- 默认勾选（试运行）→ **照样真的发送**；
- 取消勾选（真要发）→ 只是多打一行日志。

从"默认勾选 dry run"这个默认值可以确定作者的主观意图是"默认安全"，而实现把这条保证完全架空了。任何人（包括定时任务）第一次跑这个程序就会真发。这是全篇最需要立刻改的一处：

```abap
  IF p_dryrun = abap_true.
    WRITE: / 'DRY RUN - payload not sent:', lines( gt_orders ), 'rows,',
            strlen( gv_json ), 'bytes'.
    WRITE: / gv_json.
    RETURN.
  ENDIF.
```

### 6.3 【P0】所有失败都被报成成功

三个问题叠加，形成一条完整的"失败伪装成成功"链路：

1. `send` 的 `sy-subrc` **完全没有检查**，发送失败被静默吞掉，紧接着仍然调用 `receive`；
2. `DATA lv_status TYPE i.` 初始为 `0`，只在 `receive` 成功后才赋值。`receive` 失败 → `lv_status` 保持 `0` → `IF lv_status >= 400` 为假 → **不发任何消息**；
3. 即便拿到了 `400/500`，用的是 `MESSAGE ... TYPE 'S'`（**成功**类型），在报表里只是往状态行写一行字，**不中断 `FORM`**，于是继续往下走到 `lo_client->close( )` 和 `log_result`，后者打印 `posted to https://... by XXX`。

净效果：网络不通、超时、证书错误、服务端 500、参数被拒 —— **屏幕上都会显示"posted to ..."**。运维看到绿色的一行字就以为同步成功了。

```abap
  DATA lv_status TYPE i.
  DATA lv_body   TYPE string.

  lo_client->request->set_method( if_http_request=>meth_post ).

  lo_client->send( EXPORTING timeout = 10
                   EXCEPTIONS http_communication_failure = 1
                              http_invalid_state         = 2
                              http_processing_failed     = 3
                              OTHERS                     = 4 ).
  IF sy-subrc <> 0.
    MESSAGE |Send failed (rc={ sy-subrc }): { lo_client->response->get_status( ) }| TYPE 'E'.
  ENDIF.

  lo_client->receive( EXCEPTIONS http_communication_failure = 1
                                http_invalid_state         = 2
                                OTHERS                     = 3 ).
  IF sy-subrc <> 0.
    MESSAGE |Receive failed (rc={ sy-subrc })| TYPE 'E'.
  ENDIF.

  lv_status = lo_client->response->get_status( ).
  lv_body   = lo_client->response->get_data( ).

  IF lv_status NOT BETWEEN 200 AND 299.
    MESSAGE |Service rejected payload: HTTP { lv_status } { lv_body }| TYPE 'E'.
  ENDIF.
```

注意上面用的是 `BETWEEN 200 AND 299` 而不是 `>= 400`：原逻辑把 `3xx` 重定向当成功（本程序不跟随重定向，一个跳到登录页的 302 会被误判为成功）。

### 6.4 客户端资源没有可靠释放

`close( )` 写在最后一行，前面任何一条 `MESSAGE ... TYPE 'A'`、或 `response->get_data( )` 抛异常，都会跳过它 → HTTP 连接泄漏。建议 `close` 紧跟处理逻辑，或用 `TRY/CATCH` + `FINALLY` 保证释放。

### 6.5 响应体从不读取

没有 `lo_client->response->get_data( )`。对方返回的错误码 + 错误描述（字段校验失败原因、重复单号、限流提示）全部丢弃，出了问题只能靠猜。任何对接类程序，**响应体落日志是最低要求**。

### 6.6 编码：按系统码页转 xstring

```abap
  CREATE XSTRING LV_XSTRING DATA GV_JSON.
```

`CREATE XSTRING` 用的是**系统码页**，不是 UTF-8。当前字段恰好是纯 ASCII 数字所以没暴露；一旦接入客户名称等非 ASCII 字段，body 就是乱码或非法 UTF-8，服务端解析必然失败。应当用 UTF-8 明确转换，并在 Content-Type 里带上 charset。

### 6.7 超时不对称、不可重试

`send` 给了 3 秒，`receive` **完全没给**（走默认值）。大报文 + 慢服务 = 3 秒必失败；小报文超时 = 挂到默认超时。3 秒本身对外部网络也偏激进。也没有任何重试/退避，而外部 REST 的 5xx 和网络抖动恰恰是最常见的可重试场景。

### 6.8 没有任何鉴权

`create_by_url` 之后直接设 body，**没有** `lo_client->authenticate`、没有 Basic/Bearer token、没有 `if_http_client` 的 OAuth 插件、没有客户端证书。对着一个真实的外部接口，这等于匿名推送客户数据。同时也没有消费 HTTPS 证书校验策略（`ssl_hostname_verification_failed` 也没有单独捕获，被 `OTHERS` 吞掉）。

### 6.9 【安全】URL 自由输入 + 默认值指向外部域名

```abap
  PARAMETERS p_url TYPE string LOWER CASE DEFAULT 'https://api.example.com'.
```

- 任何执行者都可以把 `p_url` 改成**任意地址**（内网地址、`http://` 明文地址、别的租户），程序会把全量客户号和金额发过去。`LOWER CASE` 无关紧要，`VALUE CHECK`、协议校验、主机白名单一个都没有；
- 默认值 `api.example.com` 是一个**占位域名**。真实环境里如果没人改它就直接跑，业务数据会流向一个并非本企业控制的地址；域名抢注 / DNS 劫持场景下这是典型的数据外泄通道；
- `gv_base_url` 还被原样打印到列表和日志里。

建议：默认值留空，程序启动时校验 URL（必须 `https://` + 主机在白名单内），否则 `MESSAGE TYPE 'E' ABORT`；凭据从后端配置读取，不在源码和选择屏幕上。

---

## 7. 可观测性

```abap
  WRITE: / 'orders', lines( gt_orders ).
  WRITE: / 'posted to', gv_base_url, 'by', gv_user.
```

- 全部用 `WRITE` 写基本列表，**没有消息类、没有 `BAL_LOG`/`APPL_LOG`/日志表**。作为"每日推送"程序，日志应当能被 SM21 / 作业日志 / 自建日志表采集；
- 在后台作业里 `WRITE` 的输出通常直接被丢弃，等于**零日志**；
- `gv_user TYPE sy-unime` 在定时作业里就是系统用户名，"谁推的"这个信息毫无区分度。应该记录作业名、运行时间、批次号、报文摘要（行数 + 字节数 + 哈希）；
- 没有幂等键、没有"本次推了什么"的明细，重跑就是重复推送；没有分包、没有失败重投队列、没有死信处理。

---

## 8. 重构后的骨架（供参考）

```abap
FORM push_to_service.

  DATA lo_client  TYPE REF TO if_http_client.
  DATA lv_xstring TYPE xstring.
  DATA lv_status  TYPE i.
  DATA lv_body    TYPE string.

  IF lines( gt_orders ) = 0.
    MESSAGE 'Nothing to send' TYPE 'S'.
    RETURN.
  ENDIF.

  IF p_dryrun = abap_true.
    WRITE: / 'DRY RUN:', lines( gt_orders ), 'rows /', strlen( gv_json ), 'bytes'.
    RETURN.
  ENDIF.

  TRY.
      cl_http_client=>create_by_url(
        EXPORTING  url  = gv_base_url
                   i_ssl = if_ssl=>ssl2
        IMPORTING  client = lo_client ).

      lo_client->request->set_method( if_http_request=>meth_post ).
      lv_xstring = cl_abap_conv=>convert_to_xstring( gv_json ).
      lo_client->request->set_cdata( lv_xstring ).
      lo_client->request->set_content_type( 'application/json; charset=utf-8' ).
      lo_client->authenticate( lo_client->request ).  " 凭据来自后端配置

      lo_client->send( EXPORTING timeout = 10 ).
      lo_client->receive( EXPORTING timeout = 30 ).

      lv_status = lo_client->response->get_status( ).
      lv_body   = lo_client->response->get_data( ).

      IF lv_status NOT BETWEEN 200 AND 299.
        MESSAGE |HTTP { lv_status }: { lv_body }| TYPE 'E'.
      ENDIF.
    CATCH cx_root INTO DATA(lx_err).
      MESSAGE |Sync failed: { lx_err->get_text( ) }| TYPE 'E'.
    ENDTRY.

  lo_client->close( ).

ENDFORM.
```

配合把 `log_result` 换成 `bal_log_add` / 写日志表，并把 CDS 改成参数化视图（`@Consumption.filter` 或 `WITH PARAMETERS`），过滤条件下沉到视图、报表只传参数。

---

## 9. 复核清单

想在测试环境里快速证伪/证实，按这个顺序验：

| # | 验证动作 | 预期暴露 |
|---|---|---|
| 1 | 在 `push_to_service` 前 `BREAK-POINT`，看 `gv_json` 前 10 个字符 | ≥2 行时以 `[,` 开头 → §5.2 确认 |
| 2 | 找一条 `netwr` 有小数的记录，看 `"amount"` 片段 | `1234,56` → §5.3 确认 |
| 3 | 用 Postman/curl 手动 `POST` 该 URL，对比程序行为 | 程序发的是 GET → §6.1 确认 |
| 4 | 保持 `p_dryrun = 'X'` 运行，抓包看是否有出站请求 | 有请求发出 → §6.2 确认 |
| 5 | 把 URL 改成不可达地址，看屏幕输出 | 仍显示 `posted to ...` → §6.3 确认 |
| 6 | 选一个只有 1 条单据的时间窗，再选 ≥2 条对比 | 单条正常、多条非法 → §5.2 |

---

## 10. 需要向业务/DBA 确认的遗留问题

1. `netwr` 是订单**表头**净价（未过账时可能为 0 或陈旧），是否就是"价格复核"要推送的量？还是应该取项目/行项目层的 `netwr`？
2. 接口契约：报文 key（`customer`/`amount`/`date`）由谁定义？日期要 `YYYYMMDD` 还是 ISO 8601？金额是数字还是字符串？
3. "daily summary" 是笔误还是漏实现了聚合逻辑？若是后者，按天/按客户/按币种怎么汇总？
4. `ZI_KNA1_NAME` 是否存在、是否带语言字段（影响 association 基数声明）？客户名称是否要进报文？
5. 谁有权限执行本程序？`#NOT_REQUIRED` 是否需要改为 `#REQUIRED` + DCL？
6. 目标服务的认证方式、限流配额、超时 SLA、幂等要求？

---

## 11. 修复优先级

**立即（上线前必须）**
1. 加 `set_method( if_http_request=>meth_post )`
2. 让 `p_dryrun` 真正拦截 `push_to_service`
3. 修 `lv_status` 未初始化 / `send` 未检查 / `MESSAGE TYPE 'S'` → 失败必须 `E` 或 `A`
4. `p_url` 默认值置空 + 强制 `https` + 主机白名单校验
5. 修 `sy-tabix` 逗号分隔符
6. 金额小数点归一化

**短期（1–2 周）**
7. `sy-subrc` 与 `lines( )` 分开判断；空结果直接 `RETURN`
8. 改用 `json_serialize`（或 `/ui2/cl_json`）生成报文 + UTF-8 编码
9. 超时对称化 + 一次有限重试 + 响应体落日志
10. 日志改为消息类 / 日志表，去掉裸 `WRITE`
11. `read_from_cds` 加日期上界 + `PACKAGE SIZE`，避免全量装载

**中期**
12. CDS 参数化，去掉硬编码 `USD` / `20240101` / `sy-datum`
13. 补 DCL 与程序内授权检查
14. 视图字段去重（`netwr` vs `net_amount`），补状态过滤让它名副其实
15. 引入幂等键、分包、失败重投

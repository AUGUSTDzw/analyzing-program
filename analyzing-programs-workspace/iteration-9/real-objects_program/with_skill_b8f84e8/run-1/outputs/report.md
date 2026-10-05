# 程序分析报告：ZCL_ABAPGIT_OBJECTS_PROGRAM

> 分析对象：`ZCL_ABAPGIT_OBJECTS_PROGRAM`（CLAS 类，继承自 `ZCL_ABAPGIT_OBJECTS_SUPER`）
> 来源仓库：abapGit / abapGit —— SAP ABAP 对象的版本控制工具（Git 化 ABAP 开发库）

---

## 一、程序定位与业务背景

abapGit 要让 SAP 系统里的 ABAP 对象能被 Git 追踪：把"对象"导出成一组纯文本文件（`.abap` 源码 + `.xml` 元数据），再把这组文件导入到另一个系统，得到语义等价的对象副本。

而 ABAP 报表程序（TADIR 对象类型 `REPS`）在 SAP 内部是所有对象里结构最杂的一批——一个"程序"在数据库里并不只有一张表：

- `PROGD/PROGS`：程序目录元数据（类型、UC、包、标题）
- `REPOSRC/REPOSRCV`：源码（活动态 + 非活动态各一份）
- `TEXTPOOL`：标题与多语言描述（含 SPLIT 类长文本的特殊拼接形态）
- `D020S/D021S/D021T`：屏幕（DYNPRO）的结构、字段、文本
- 屏幕流逻辑（Flow Logic）：一段可独立保存的 ABAP 代码
- `CUAD` 子对象：命令区域（状态、菜单、消息、功能码、按钮、功能键……）
- `VARID/VARIT`：选择变式，其中系统独立变式（`SAP&*`/`CUS&*`）存放在客户端 `000`

任何一个环节漏掉，导入后对象就"少了半边身子"；任何一个环节多写，Git 上就会冒出无意义的假差异（generator 时间戳、自动派生的屏幕文本、NUMC 空值……）。这个类就是把这件事收口的地方。

**整体设计范式一句话**：一对"导出/导入"的镜像方法组，用**清洗导出 + 修复导入**的双向对称策略消除假差异，用**版本探测式重试**兼容跨 release 的 FM 形参差异，用**激活入队**把多张底表的分散写入收敛成一次原子激活。

---

## 二、程序执行流程总览

```mermaid
flowchart TD
    subgraph EXP["导出路径（serialize）"]
        A["serialize_program（导出总编排）"]
        A --> A1["RPY_PROGRAM_READ（取源码与文本池）"]
        A --> A2["serialize_dynpros（屏幕与流逻辑）"]
        A --> A3["serialize_cua（命令区域）"]
        A --> A4["serialize_varis（选择变式）"]
        A --> A5["add_tpool（文本池编码）"]
        A --> A6["strip_generation_comments（去生成头）"]
        A4 --> A4a["get_varis_for_report"]
        A4 --> A4b["get_vari_data"]
        A4 --> A4c["get_vari_screens"]
    end

    subgraph IMP["导入路径（deserialize）"]
        B["deserialize_program（导入总编排）"]
        B --> B1["is_exit_include（退出包含分流）"]
        B --> B2["get_program_title（取标题并修工作区）"]
        B --> B3["insert_program（新建）"]
        B --> B4["update_program（覆盖）"]
        B --> B5["deserialize_textpool（文本池）"]
        B --> B6["deserialize_cua（命令区域）"]
        B --> B7["deserialize_dynpros（屏幕）"]
        B --> B8["deserialize_varis（选择变式）"]
        B7 --> B7a["uncondense_flow（还原流逻辑缩进）"]
        B6 --> B6a["auto_correct_cua_adm（ADM 兜底重建）"]
        B8 --> B8a["create_vari / delete_vari / set_vari_protection"]
    end

    subgraph LCK["锁预检（导入前由父类调用）"]
        C["is_any_dynpro_locked"]
        D["is_cua_locked"]
        E["is_text_locked"]
    end

    A6 --> F["io_files 落盘（XML 与 ABAP 文件）"]
    B --> G["zcl_abapgit_objects_activation 入队（REPS/REPT/CUAD/DYNP）"]
```

### 责任链表

| 子程序 | 调用者 | 职责 |
|---|---|---|
| `serialize_program` | 父类序列化管线（或 GUI） | 导出总编排：取数、分发子对象、装配 XML、落盘 |
| `serialize_dynpros` | `serialize_program`（仅 SUBC='1'/'M'） | 读全量屏幕，清洗后写 XML，流逻辑外置为独立 `.abap` |
| `serialize_cua` | `serialize_program`（仅 SUBC='1'/'M'） | `RS_CUA_INTERNAL_FETCH` 读命令区域 12 张表 |
| `serialize_varis` | `serialize_program`（仅 SUBC='1'/'M'） | 汇总系统独立变式为一个 `ty_vari_tt` |
| `get_varis_for_report` | `serialize_varis`、`deserialize_varis` | 列出该程序的 `SAP&*`/`CUS&*` 系统独立变式 |
| `get_vari_data` | `serialize_varis` | 读单个变式的技术数据、值、对象、文本 |
| `get_vari_screens` | `serialize_varis` | 读单个变式绑定的屏幕号 |
| `add_tpool` | `serialize_program` | 文本池编码：S 类条目把 ENTRY 拆成 SPLIT+ENTRY |
| `strip_generation_comments` | `serialize_program` | 删除 FUGR 自动生成头里的时间戳/版本行 |
| `deserialize_program` | 父类反序列化管线 | 导入总编排：分流退出包含、登记 CTS、写入源码与 PROGDIR |
| `deserialize_exit_include` | `deserialize_program` | 退出包含专用写入（只允许活动态） |
| `get_program_title` | `deserialize_program`、`deserialize_exit_include` | 从 TPOOL 取标题，并清空 `SAPLSIFP` 的 `TTAB` 修长度继承 bug |
| `insert_program` | `deserialize_program`、`deserialize_exit_include` | 新建程序（含低版本参数降级、`name_not_allowed` 双写回退） |
| `update_program` | `deserialize_program`、`deserialize_exit_include` | 覆盖已有程序，特化 `EU510`/`EU522` 错误语义 |
| `deserialize_textpool` | 父类反序列化管线 | 文本池写入与删除，主语言走非活动态待激活 |
| `deserialize_cua` | 父类反序列化管线 | 组装 TRKEY、ADM 兜底、写回 CUAD、入队激活 |
| `auto_correct_cua_adm` | `deserialize_cua` | 旧 XML 无 ADM 时从 ACT/MEN/PFK 反查回填（issue #1807） |
| `deserialize_dynpros` | 父类反序列化管线 | 屏幕写入、遗留屏幕删除、字段属性修复、原生屏分流 |
| `uncondense_flow` | `deserialize_dynpros` | 按 `spaces` 表还原流逻辑原始缩进（#3680 兼容） |
| `deserialize_varis` | 父类反序列化管线 | 变式差异同步：重建远端存在的、删除本地多余的 |
| `create_vari` / `delete_vari` | `deserialize_varis` | 变式写入与删除（`delete_vari` 含低版本重试） |
| `set_vari_protection` | `deserialize_varis` | 以 `SELECT FOR UPDATE` 暂解/恢复变式保护 |
| `is_any_dynpro_locked` | 父类导入前检查 | 逐个屏幕查 `ESCRP` 锁 |
| `is_cua_locked` | 父类导入前检查 | 查 `ESCUAPAINT` 锁 |
| `is_text_locked` | 父类导入前检查 | 查 `EABAPTEXTE` 锁 |
| `read_tpool` | 父类反序列化管线（XML → 内表） | `add_tpool` 的逆操作：SPLIT+ENTRY 拼回 ENTRY |

下面按这条流程，逐个子程序展开。

---

## 三、分组分析（按程序流程 / 子程序）

---

### 3.1 类定义段：`ZCL_ABAPGIT_OBJECTS_PROGRAM` 的骨架

```abap
CLASS zcl_abapgit_objects_program DEFINITION
  PUBLIC
  INHERITING FROM zcl_abapgit_objects_super
  CREATE PUBLIC .
```

**做什么** — 声明一个继承自 `ZCL_ABAPGIT_OBJECTS_SUPER` 的公开类，作为 `REPS` 对象的处理器；PUBLIC/PROTECTED/PRIVATE 三段把"面向父类的接口"和"实现细节"物理隔开。

**为什么** — 父类定义了一套对象处理器的模板（`serialize_*` / `deserialize_*` 的调用契约、`ms_item`/`mv_language`/`mo_files`/`mo_i18n_params` 等共享成员），子类只需填空。这样 TADIR 里的每种对象类型（类、函数组、程序、表……）都能挂到同一条导入导出管线上，新增对象类型时不碰管线代码。

**风险与改进** — 本类的"导入顺序"完全由父类约定，类内部看不到全貌。`deserialize_program` 里只写了源码和 PROGDIR，屏幕/命令区域/文本池/变式都在别处被父类调用，读源码的人容易误以为"导入就这几步"。建议在类注释或 `README` 中显式写出父类约定的调用顺序。

---

### 3.2 常量与类型：`ty_cua` / `ty_dynpro` / `ty_vari` / `c_state` / `c_sysvari_*`

```abap
TYPES:
  BEGIN OF ty_cua,
    adm TYPE rsmpe_adm,
    sta TYPE STANDARD TABLE OF rsmpe_stat WITH DEFAULT KEY,
    ...
    biv TYPE STANDARD TABLE OF rsmpe_buts WITH DEFAULT KEY,
  END OF ty_cua.

CONSTANTS:
  BEGIN OF c_state,
    active   TYPE r3state VALUE 'A',
    inactive TYPE r3state VALUE 'I',
    off      TYPE r3state VALUE '',
  END OF c_state.

CONSTANTS c_sysvari_clnt        TYPE mandt      VALUE '000'.
CONSTANTS c_sysvari_pattern_sap TYPE c LENGTH 5 VALUE 'SAP&*'.
CONSTANTS c_sysvari_pattern_cus TYPE c LENGTH 5 VALUE 'CUS&*'.
```

**做什么** — 用**结构体常量 `c_state`** 命名活动态/非活动态/空态三个取值；用 `ty_cua` 把 CUAD 子对象的 12 张底表（ADM + STA/FUN/MEN/MTX/ACT/BUT/PFK/SET/DOC/TIT/BIV）打成一个可序列化结构；用 `ty_dynpro` 把屏幕的两种存储形态（常规 `header/containers/fields` 与原生 `nat_header/nat_fields/nat_texts`）放进同一行；用 `c_sysvari_clnt = '000'` 与两个模式串固定"系统独立变式"的判定口径。

**为什么** — 把 SAP 内部零散表结构收拢成"一个导出单元一个结构"，序列化器才能直接 `XML->add`；`c_state` 用结构化常量而非散落的字面量 `'A'`/`'I'`，避免 `"ACTIVE"`/`'A'` 混用；`c_sysvari_pattern_sap`/`cus` 把"哪些变式算系统独立"提成常量，导出与导入共用同一口径，不会出现"导出时按一套、导入时按另一套"的错位。

**风险与改进** — `ty_dynpro` 把两种互斥形态（常规 vs 原生屏）塞进同一个结构体，靠 `type CA c_native_dynpro` 运行时判断走哪一支，类型系统给不了保护，导入侧写错字段组合不会在编译期暴露。可以拆成两个结构 + 运行时选择，或用 `CASE` 提前定型。

---

### 3.3 方法 `serialize_program`（导出总编排）

这是整个类的导出入口，分六步。

#### ① 解析对象名并切换语言上下文

```abap
IF iv_program IS INITIAL.
  lv_program_name = is_item-obj_name.
ELSE.
  lv_program_name = iv_program.
ENDIF.

zcl_abapgit_language=>set_current_language( mv_language ).
```

**做什么** — 优先取调用方显式传入的 `iv_program`，否则回退到 `is_item-obj_name`；随后把当前语言上下文切换成用户配置的 `mv_language`。

**为什么** — 一个对象处理器实例可能被复用来导多个对象（`iv_program` 参数就是为此），必须容忍"未指定即自取"。语言上下文必须先切，因为下一步 `RPY_PROGRAM_READ` 会按 `sy-langu` 去读文本池，不切就读到登录语言的描述。

**风险与改进** — `iv_program` 与 `is_item-obj_name` 同时给出但**不一致**时静默采信前者，不告警。若上游参数错配（比如批量导出时循环变量串了），对象会被以错误名字取数，直到 FM 返回 `not_found` 才暴露。建议加一行 `ASSERT is_item-obj_name IS INITIAL OR is_item-obj_name = iv_program.` 做防御。

#### ② 读取源码与文本池

```abap
CALL FUNCTION 'RPY_PROGRAM_READ'
  EXPORTING
    program_name     = lv_program_name
    with_includelist = abap_false
    with_lowercase   = abap_true
  TABLES
    source_extended  = lt_source
    textelements     = lt_tpool
  EXCEPTIONS
    cancelled        = 1
    not_found        = 2
    permission_error = 3
    OTHERS           = 4.

IF sy-subrc = 2.
  zcl_abapgit_language=>restore_login_language( ).
  RETURN.
ELSEIF sy-subrc <> 0.
  zcl_abapgit_language=>restore_login_language( ).
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

zcl_abapgit_language=>restore_login_language( ).
```

**做什么** — 一次 FM 调用同时取回源码（`source_extended`，255 宽度）和文本池（`textelements`）；`not_found` 时**静默返回**（不报错），其余错误码抛异常。`with_lowercase = abap_true` 保留小写源码形式。三条退出路径都保证语言上下文被还原。

**为什么** — "对象不存在"不是错误而是正常状态（删除后的对象、被过滤掉的对象），所以必须返回而非抛异常；但语言上下文切换是有副作用的操作，任何退出路径都必须 `restore_login_language`，否则会污染同会话后续的对象导出。用 `with_lowercase` 是因为 ABAP 允许源码含小写（如 `SELECT ... FROM` 写法、字符串字面量），丢掉大小写会改动对象。

**风险与改进** — 三条分支里 `restore_login_language` 被写了三次，靠人肉重复而非 `CLEANUP`/`TRY..CLEANUP` 结构保证。这里没有异常抛出点，所以暂时安全，但一旦中间加一段会抛异常的代码（比如后面就真的有），漏写就必然泄漏语言上下文。建议改成 `TRY. ... ENDTRY. CLEANUP. zcl_abapgit_language=>restore_login_language( ). ENDTRY.` 的形态。

#### ③ 区分活动态与非活动态版本

```abap
li_report = zcl_abapgit_factory=>get_sap_report( ).

TRY.
    " Raises exception if inactive version does not exist
    ls_progdir = li_report->read_progdir(
      iv_name  = lv_program_name
      iv_state = c_state-inactive ).

    " Explicitly request active source code
    lt_source = li_report->read_report(
      iv_name  = lv_program_name
      iv_state = c_state-active ).
  CATCH zcx_abapgit_exception ##NO_HANDLER.
ENDTRY.

ls_progdir = li_report->read_progdir(
  iv_name  = lv_program_name
  iv_state = c_state-active ).
```

**做什么** — 先尝试读**非活动态** PROGDIR；若成功（说明存在未激活的版本），再显式用活动态读回源码，覆盖掉步骤 ② 里读到的（可能是非活动的）源码；若失败（无非活动版本），沿用步骤 ② 的结果。最后无条件再读一次活动态 PROGDIR 作为最终输出。

**为什么** — `RPY_PROGRAM_READ` 在对象存在非活动版本时，返回的源码**不是活动版本**，导致导出的源码与对象实际运行代码不一致（Git 上看到的是没激活的草稿）。这里用一次探测 + 一次显式覆写来纠正。最终 PROGDIR 固定取活动态，因为元数据以已生效版本为准。

**风险与改进** — `##NO_HANDLER` 的空捕获是这段代码最脆弱的地方：它假设"抛异常 ⟺ 非活动版本不存在"，但 `read_progdir` 也可能因其他原因抛 `zcx_abapgit_exception`（表被锁、TADIR 缺失、包不存在），这些真实错误会被一并吞掉，然后走到活动态读取拿到一份与源码不同步的元数据，导出的 `.xml` 与 `.abap` 就悄悄错配了。建议捕获后检查异常原因或子码，只对"对象不存在"这一类放行。

#### ④ 清空 ABAP 语言版本并装配 XML

```abap
clear_abap_language_version( CHANGING cv_abap_language_version = ls_progdir-uccheck ).

IF io_xml IS BOUND.
  li_xml = io_xml.
ELSE.
  CREATE OBJECT li_xml TYPE zcl_abapgit_xml_output.
ENDIF.

li_xml->add( iv_name = 'PROGDIR'
             ig_data = ls_progdir ).

IF ls_progdir-subc = '1' OR ls_progdir-subc = 'M'.
  lt_dynpros = serialize_dynpros( lv_program_name ).
  li_xml->add( iv_name = 'DYNPROS'
               ig_data = lt_dynpros ).

  ls_cua = serialize_cua( lv_program_name ).
  li_xml->add( iv_name = 'CUA'
               ig_data = ls_cua ).

  lt_varis = serialize_varis( lv_program_name ).
  li_xml->add( iv_name = 'VARIS'
               ig_data = lt_varis ).
ENDIF.
```

**做什么** — 清掉 PROGDIR 里的 ABAP 语言版本标记（`UCCHECK`），避免升级 ABAP 版本后同一份源码被 Git 判为"有变化"；`io_xml` 可选注入，未注入则自建；先写 PROGDIR，再按程序类型 SUBC 判断是否附带 DYNPROS/CUA/VARIS。

**为什么** — `1`（报表）和 `M`（模块池/屏幕程序）才可能有屏幕与命令区域；`5`（函数组）、`M`以外的类型导出这些子对象是浪费甚至报错。语言版本清理是纯"差异消除"：版本升级会改写 `UCCHECK`，但源码一行未变，不处理会让全库产生噪音 diff。`io_xml` 可注入支持"多个对象共享一个 XML 文件"的场景（父类做嵌套对象导出时会传进来）。

**风险与改进** — SUBC 判断用字面量 `'1'`/`'M'` 而非具名常量，`SUBC` 合法值远不止这两个，新增类型时这里是个隐形分支点。建议提成常量并加注释说明"未覆盖的 SUBC 值不导出屏幕/命令区域/变式"。

#### ⑤ 文本池清洗与编码

```abap
READ TABLE lt_tpool WITH KEY id = 'R' INTO ls_tpool.
IF sy-subrc = 0 AND ls_tpool-key = '' AND ls_tpool-length = 0.
  DELETE lt_tpool INDEX sy-tabix.
ENDIF.

li_xml->add( iv_name = 'TPOOL'
             ig_data = add_tpool( lt_tpool ) ).
```

**做什么** — 若标题类条目（`id='R'`）的 `key` 与 `length` 都是空（即这是一条无内容的空壳标题行），删掉它；再把清洗后的文本池经 `add_tpool` 编码后写入 XML。

**为什么** — 无标题的程序在 TPOOL 里仍会留一条空 `R` 条目，把它当有效内容导出去，导入侧就会重建一条不存在的空条目，形成"空对空"的假差异。删除属于把存储层的"保底占位行"还原成语义层的"没有标题"。

**风险与改进** — 判定条件是 `key = '' AND length = 0`，但若某程序有标题而 `length` 恰好被工作区 bug 清成 0（见 3.14 的 `SAPLSIFP` 问题），这里会**误删有效标题**。两处 workaround 之间没有交叉校验，属于潜在的正确性盲区。建议在删除前再比对 `ls_tpool-entry` 是否也空。

#### ⑥ 去生成注释并落盘

```abap
strip_generation_comments( CHANGING ct_source = lt_source ).

io_files->add_xml( iv_extra = iv_extra
                   ii_xml   = li_xml ) "仅在 io_xml 未注入时
io_files->add_abap( iv_extra = iv_extra
                    it_abap  = lt_source ).
```

**做什么** — 先剥离源码里的生成器时间戳行（仅函数组），再把 XML 交给 `io_files` 落盘（若 XML 是注入的则不落 XML，只返回给调用方），最后落 ABAP 源码。

**为什么** — 生成头里的日期/版本每次重新生成都会变，不剥离则"重新生成一次"就会在 Git 上产生 diff。XML 是否落盘由注入与否决定，是为了让父类能对嵌套对象做"合并到一个文件"的控制。

**风险与改进** — `add_xml` 的调用被包在 `IF NOT io_xml IS BOUND` 里（源码第 1408-1411 行），但 `strip_generation_comments` 与 `add_abap` 无条件执行。也就是说当 XML 被注入时源码仍会落盘而 XML 不会，两个产物的可见性不对称——依赖调用方清楚这一约定，否则容易误以为"注入 XML 就不产出任何文件"。建议把条件对称化或加注释。

---

### 3.4 方法 `serialize_dynpros`（屏幕序列化，导出侧最复杂的一段）

分五步。

#### ① 列举屏幕并过滤生成屏

```abap
CALL FUNCTION 'RS_SCREEN_LIST'
  EXPORTING
    dynnr     = ''
    progname  = iv_program_name
  TABLES
    dynpros   = lt_d020s
  EXCEPTIONS
    not_found = 1
    OTHERS    = 2.
IF sy-subrc = 2.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

SORT lt_d020s BY dnum ASCENDING.

LOOP AT lt_d020s ASSIGNING <ls_d020s>
    WHERE type <> 'S' AND type <> 'W' AND type <> 'J'
    AND NOT dnum IS INITIAL.
```

**做什么** — 列出程序下的全部屏幕并**按屏幕号升序排序**；循环时跳过三种系统生成屏（`S` 选择屏、`W` 状态屏、`J` 菜单屏）以及无屏幕号的条目。

**为什么** — 选择屏/状态屏/菜单屏是系统按选择参数、状态、菜单结构**自动派生**的，它们的结构由程序源码和 CUA 决定，导出它们既无用又会引入每次重新生成都变化的噪音。排序是保证导出结果**可重现**的前提（否则同一份对象的 XML 顺序不稳定，Git 上永远有 diff）。

**风险与改进** — 无。这是标准的"导出白名单 + 稳定排序"写法。

#### ② 读取屏幕结构与原生格式

```abap
CALL FUNCTION 'RPY_DYNPRO_READ'
  EXPORTING
    progname = iv_program_name
    dynnr    = <ls_d020s>-dnum
  IMPORTING
    header   = ls_header
  TABLES
    containers           = lt_containers
    fields_to_containers = lt_fields_to_containers
    flow_logic           = lt_flow_logic
  EXCEPTIONS
    cancelled        = 1
    not_found        = 2
    permission_error = 3
    OTHERS           = 4.

FREE lt_fieldlist_int.

CALL FUNCTION 'RPY_DYNPRO_READ_NATIVE'
  EXPORTING
    progname = iv_program_name
    dynnr    = <ls_d020s>-dnum
  TABLES
    fieldlist  = lt_fieldlist_int
    fieldtexts = lt_texts.
```

**做什么** — 每个屏幕调两次 FM：一次取**外部展示格式**（容器、字段到容器的绑定、流逻辑），一次取**内部底层格式**（`d021s` 字段表与文本）。每次循环前 `FREE lt_fieldlist_int` 避免上一屏的字段残留。

**为什么** — 两次调用是必要的：外部格式决定"怎么导出成 XML"，内部格式（带 `flg1`/`flg3` 位掩码）决定"哪些字段真的需要 foreign key"。SAP 自己给外部格式里的 `FOREIGNKEY` 字段填的值并不总是准确的（issue #2746），必须用内部标志位重算。`FREE` 是防串屏的关键——FM 不保证清空传入的内表。

**风险与改进** — `RPY_DYNPRO_READ` 检查了返回码，但 `RPY_DYNPRO_READ_NATIVE` **没有检查 `sy-subrc`**。若原生读取失败（权限、屏不存在），后续用一份空的 `lt_fieldlist_int` 去做 foreignkey 重算与原生屏判定，结果可能静默写错。建议补上返回码判断。

#### ③ 规范化字段属性（消除假差异的核心）

```abap
CONSTANTS: lc_flg1ddf TYPE x VALUE '20',
           lc_flg3fku TYPE x VALUE '08',
           lc_flg3for TYPE x VALUE '04',
           lc_flg3fdu TYPE x VALUE '02'.

LOOP AT lt_fields_to_containers ASSIGNING <ls_field>.
  ASSIGN COMPONENT 'OUTPUTSTYLE' OF STRUCTURE <ls_field> TO <lv_outputstyle>.
  IF sy-subrc = 0 AND <lv_outputstyle> = '  '.
    CLEAR <lv_outputstyle>.
  ENDIF.

  UNASSIGN <ls_field_int>.
  READ TABLE lt_fieldlist_int ASSIGNING <ls_field_int> WITH KEY fnam = <ls_field>-name.
  IF <ls_field_int> IS ASSIGNED.
    IF <ls_field_int>-flg1 O lc_flg1ddf AND
        <ls_field_int>-flg3 O lc_flg3for AND
        <ls_field_int>-flg3 Z lc_flg3fdu AND
        <ls_field_int>-flg3 Z lc_flg3fku.
      <ls_field>-foreignkey = 'X'.
    ELSE.
      CLEAR <ls_field>-foreignkey.
    ENDIF.
  ENDIF.

  IF <ls_field>-from_dict = abap_true AND
     <ls_field>-modific   <> 'F' AND
     <ls_field>-modific   <> 'X'.
    CLEAR <ls_field>-text.
  ENDIF.
ENDLOOP
```

**做什么** — 对每个屏幕字段做三件清洗：
- `OUTPUTSTYLE`（NUMC 字段）若为 `'  '` 全空格，清空成 INITIAL，否则 XML 转换会因为 NUMC 非法值失败；
- 用内部 `d021s` 的位标志位**重算** `FOREIGNKEY`：仅当 `flg1` 含 DDF 标志、且 `flg3` 含 FOR、不含 FDU、不含 FKU 时才置 `'X'`；
- 若字段是 `from_dict`（文本来自 DDIC）且修改标志既不是 `F`（固定文本）也不是 `X`（总是从字典取），清空自定义 `text`。

**为什么** — 这三条全是"存储层有值、语义层没意义"的典型：NUMC 空值以空格存储，XML 编码会炸；`FOREIGNKEY` 在屏幕被反复打开/保存后可能被 FM 写成脏值，而真正的判定依据在内部标志位里；`from_dict` 字段的文本本来就是字典派生的，存一份副本只会因为字典翻译更新而产生无意义 diff。这是**差异消除**策略在字段级的具体落地。

**风险与改进** — `flg1`/`flg3` 的位掩码常量取自"include MSEUSBIT"（注释里写明 `#2746`），但位含义**没有被任何类型系统保护**：`'20'`/`'08'`/`'04'`/`'02'` 是十六进制字面量，未来 SAP 调整标志位定义时这里会静默失效。建议以命名常量注释出位含义（如"位 5 = DDF 派生"），或改为调用 SAP 提供的判定 API（如果有）。另外 `ASSIGN COMPONENT 'OUTPUTSTYLE'` 用字符串定位字段，字段不存在时靠 `sy-subrc` 兜住——这是为了兼容不同 release（该字段并非所有版本都有），属合理的版本容错，但字符串定位本身就易错。

#### ④ 规范化容器最小尺寸并外置流逻辑

```abap
LOOP AT lt_containers ASSIGNING <ls_container>.
  IF <ls_container>-c_resize_v = abap_false.
    CLEAR <ls_container>-c_line_min.
  ENDIF.
  IF <ls_container>-c_resize_h = abap_false.
    CLEAR <ls_container>-c_coln_min.
  ENDIF.
ENDLOOP.

APPEND INITIAL LINE TO rt_dynpro ASSIGNING <ls_dynpro>.
<ls_dynpro>-header = ls_header.

" Store flow logic as separate ABAP files instead of XML
mo_files->add_abap(
  iv_extra = 'screen_' && ls_header-screen
  it_abap  = lt_flow_logic ).
```

**做什么** — 不可纵向/横向缩放的容器，其最小行数/列数在存储层可能残留旧值，语义上无效，清空。然后把屏幕流逻辑作为**独立 ABAP 文件**（文件后缀标识 `screen_0001` 之类）落盘，而不是塞进 XML。

**为什么** — 流逻辑是纯 ABAP 文本，放 XML 里要么转义麻烦、要么编码成不可读的二进制形态；外置成 `screen_XXXX.abap` 之后，用户可以用 Git diff 直接看到"哪个屏幕的哪一行流逻辑变了"，且能与主源码一起走 lint。这是把**数据形态匹配内容的真实性质**的设计选择。

**风险与改进** — 文件名用 `'screen_' && ls_header-screen` 拼接，`screen` 是 4 位屏幕号，`&&` 拼接若屏幕号被 pad 规则影响可能产生 `screen_0001` 之外的形态。导入侧对应靠 `mo_files->read_abap( iv_extra = 'screen_' && ... )` 取回（见 3.20 ②），两侧约定必须严格一致，目前靠两条字面量字符串对齐，没有共享常量。建议提成常量。

#### ⑤ 原生屏分流存储

```abap
READ TABLE lt_fieldlist_int TRANSPORTING NO FIELDS WITH KEY fill = 'X'.
IF ls_header-type CA c_native_dynpro AND sy-subrc = 0.
  " In particular for dynpros with splitter
  <ls_dynpro>-nat_header = <ls_d020s>.
  CLEAR: <ls_dynpro>-nat_header-dgen, <ls_dynpro>-nat_header-tgen.
  <ls_dynpro>-nat_fields = lt_fieldlist_int.
  <ls_dynpro>-nat_texts  = lt_texts.
ELSE.
  <ls_dynpro>-containers = lt_containers.
  <ls_dynpro>-fields     = lt_fields_to_containers.
ENDIF.
```

**做什么** — 判断这个屏幕是否为"原生屏"（`header-type` 含 `'IN'`，且内部字段表里有 `FILL = 'X'` 的字段，典型如带 splitter 的屏幕）。是则走原生分支：存 `nat_header`（拷贝自 `d020s`）、`nat_fields`、`nat_texts`；否则存常规的容器与字段。`nat_header` 的 `dgen`/`tgen`（生成日期/时间）被显式清空。

**为什么** — 原生屏（尤其含 splitter 的屏幕）如果按常规格式导出，导入时会丢失 splitter 布局，变成普通容器屏。所以必须保留原始 `d020s` 头与 `d021s` 字段表。**清 `dgen`/`tgen` 又是差异消除**：生成时间是每次写屏都会变的噪音。

**风险与改进** — 判定条件是"两者都满足"（`type CA 'IN'` **且** 有 `FILL='X'`），这个"且"意味着一个 `type='IN'` 但字段表里没有 `FILL` 的屏幕会被当作常规屏导出，导入时走 `RPY_DYNPRO_INSERT` 而非 `RPY_DYNPRO_INSERT_NATIVE`，可能生成错形态的对象。这条判定来自经验归纳（注释只说"In particular for dynpros with splitter"），没有对照 SAP 文档做穷举验证。建议补一个"原生屏被降级导出"的检测告警。

---

### 3.5 方法 `serialize_cua`（命令区域序列化）

```abap
CALL FUNCTION 'RS_CUA_INTERNAL_FETCH'
  EXPORTING
    program  = iv_program_name
    language = mv_language
    state    = c_state-active
  IMPORTING
    adm = rs_cua-adm
  TABLES
    sta = rs_cua-sta
    fun = rs_cua-fun
    men = rs_cua-men
    mtx = rs_cua-mtx
    act = rs_cua-act
    but = rs_cua-but
    pfk = rs_cua-pfk
    set = rs_cua-set
    doc = rs_cua-doc
    tit = rs_cua-tit
    biv = rs_cua-biv
  EXCEPTIONS
    not_found       = 1
    unknown_version = 2
    OTHERS          = 3.
IF sy-subrc > 1.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.
```

**做什么** — 一次 FM 调用把 CUAD 子对象的 ADM 主表 + 11 张明细表全部取回，装入 `ty_cua` 返回。语言用 `mv_language` 显式指定，状态固定活动态。

**为什么** — CUA 是"1 主表 + 11 明细表"的家族结构，用 FM 一把取比自己 12 次 SELECT 更可靠（FM 会处理语言合并、多版本回退）。**固定读活动态**是因为命令区域不像源码有"草稿"概念需要区分，读活动态保证导出的就是运行时的命令区域。

**风险与改进** — 返回码判定用 `sy-subrc > 1`，即 `not_found(1)` 与 `unknown_version(2)` 都**不算错误**：前者是"程序没有 CUA"（正常），后者是"版本未知"（FM 内部兼容态，可能带部分数据）。这样宽松是对的，但 `unknown_version` 意味着拿到的数据可能是**不完整的**且无任何告警——导入侧（3.18）会因为"所有表都空"而直接 RETURN，等于**静默丢失 CUA**。建议至少在 `unknown_version` 时记录一条警告。另外 `TABLES` 参数有 11 个且类型各异，属同构样板，此处完整列出是为了让读者看清 CUA 的全貌。

---

### 3.6 方法 `serialize_varis`（选择变式序列化）

```abap
lt_varis = get_varis_for_report( iv_program_name ).

LOOP AT lt_varis ASSIGNING <ls_varikey>.
  CLEAR: ls_vari, ls_varid.

  get_vari_data( EXPORTING is_vari    = <ls_varikey>
                 IMPORTING es_varid   = ls_varid
                           et_values  = ls_vari-values
                           et_objects = ls_vari-objects
                           et_texts   = ls_vari-texts ).

  MOVE-CORRESPONDING ls_varid TO ls_vari.

  " Clear texts - they will be provided in TEXTPOOL section
  LOOP AT ls_vari-objects ASSIGNING <ls_object>.
    CLEAR <ls_object>-text.
  ENDLOOP.

  ls_vari-variscreens = get_vari_screens( <ls_varikey> ).

  INSERT ls_vari INTO TABLE rt_varis.
ENDLOOP.
```

**做什么** — 先取变式清单，然后逐个变式：读技术数据/值/对象/文本，用 `MOVE-CORRESPONDING` 把 `varid` 的技术字段（`transport`/`environmnt`/`protected`/`xflag1`/`xflag2`）搬进 `ty_vari`，**清空对象里的 `text`**，再取该变式绑定的屏幕号，最后插入结果表。

**为什么** — 对象里的 `text` 是**变式对象的描述文本**，这部分内容由 TEXTPOOL 段落统一承载（避免同一份文本在 XML 里出现两处，产生双写冲突和假差异）。`MOVE-CORRESPONDING` 而非手写逐字段赋值，是为了让 `varid` 未来新增技术字段时自动带过来——但代价是字段语义对齐完全依赖同名匹配。

**风险与改进** — `MOVE-CORRESPONDING ls_varid TO ls_vari` 是这段唯一一处"靠同名自动对齐"的映射，而 `ty_vari` 的字段是手写选出来的（`variant`/`flag1`/`flag2`/`transport`/`environmnt`/`protected`/`secu`/`xflag1`/`xflag2`）。如果 `varid` 结构未来改名或加一个同名不同义的字段，这里会静默错配。建议改为显式赋值并注释"仅搬运技术字段，业务字段单独处理"。

---

### 3.7 方法 `get_varis_for_report`（列出系统独立变式）

```abap
CALL FUNCTION 'RS_ALL_VARIANTS_4_1_REPORT'
  EXPORTING
    program = iv_repid
  IMPORTING
    cat     = ls_catalog
  EXCEPTIONS
    OTHERS  = 1.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

ls_vari-report = iv_repid.
LOOP AT ls_catalog-cat ASSIGNING <ls_cat>
     WHERE variant CP c_sysvari_pattern_sap
     OR variant CP c_sysvari_pattern_cus.
  ls_vari-variant = <ls_cat>-variant.
  INSERT ls_vari INTO TABLE rt_varis.
ENDLOOP.

SORT rt_varis.
```

**做什么** — 用 SAP 提供的变式目录 FM 取该程序的全部变式，然后用模式串 `SAP&*` 与 `CUS&*` 过滤出**系统独立变式**（客户端无关、存放在客户端 000 的那一类），最后按变式名排序。

**为什么** — 选择变式有两个世界：个人变式（存用户自己的客户端，属于用户私有配置）和系统独立变式（`SAP&*`/`CUS&*` 前缀，存客户端 000，属于程序资产）。只有后者应该被版本控制。这个过滤口径被提成常量（`c_sysvari_pattern_sap`/`cus`），导出与导入共用，保证两侧一致。

**风险与改进** — 依赖 SAP 用 `SAP&*`/`CUS&*` 作为系统独立变式的命名约定，这是**约定而非接口**。若某系统自定义了别的系统级变式前缀（有些老系统用 `ZSYS*`），这类变式会被静默忽略、不进入版本控制。这个边界应该在文档里明确告知使用者，而不是埋在过滤逻辑里。

---

### 3.8 方法 `get_vari_data`（读单个变式的全部数据）

#### ① 取技术数据（附带一次被丢弃的结果）

```abap
CLEAR: es_varid, et_values, et_objects, et_texts.

CALL FUNCTION 'RS_VARIANT_VALUES_TECH_DAT_255'
  EXPORTING
    report  = is_vari-report
    variant = is_vari-variant
    sorted  = abap_true
  IMPORTING
    techn_data     = es_varid
  TABLES
    variant_values = et_values " is ignored
  EXCEPTIONS
    OTHERS         = 1.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

" Use variant values from CONTENTS call
" both calls have this parameter as non-optional
CLEAR et_values.
```

**做什么** — 调用技术数据 FM，只取 `techn_data`（变式的 `varid` 头），把 `variant_values` 表格直接清掉。

**为什么** — 注释写得很清楚：**这两个 FM 的 `variant_values` 形参都不是可选的**，不传就会报"必填参数缺失"。所以只能传一个进去再扔掉，真正的值稍后用 `RS_VARIANT_CONTENTS_255` 取。这是被 FM 设计逼出来的写法。

**风险与改进** — 一次完整的变式内容读取被完全丢弃，属纯浪费；更关键的是这个 FM 会**真正执行/读取变式的值数据**，在大量变式的程序上这是可测量的开销。目前无解（FM 形参不可选），但可以记录在性能评估中。`CLEAR et_values` 之后立刻被下面的 `RS_VARIANT_CONTENTS_255` 覆写，这个 CLEAR 主要是为了防"FM 未执行时残留上一次循环的旧数据"——在循环场景下这是必要的防御。

#### ② 语言过滤与多语言文本读取

```abap
IF mo_i18n_params->ms_params-main_language_only <> abap_true.
  lt_language_filter = mo_i18n_params->build_language_filter( ).
ENDIF.
ls_language_filter-sign   = 'I'.
ls_language_filter-option = 'EQ'.
ls_language_filter-low    = mv_language.
CLEAR ls_language_filter-high.
INSERT ls_language_filter INTO TABLE lt_language_filter.

" SELECT because RS_VARIANT_TEXT and related FMs cannot list available languages
SELECT langu vtext FROM varit CLIENT SPECIFIED
  INTO CORRESPONDING FIELDS OF TABLE et_texts
  WHERE mandt = c_sysvari_clnt
    AND report = is_vari-report
    AND variant = is_vari-variant
    AND langu IN lt_language_filter
  ORDER BY langu.
```

**做什么** — 组一个语言筛选区间：非"仅主语言"模式下取用户配置的翻译语言集，并**总是追加主语言** `mv_language`（区间 sign=`I`、option=`EQ`、high 清空）。然后直接 `SELECT ... FROM varit CLIENT SPECIFIED` 按语言集取文本。

**为什么** — 注释点明了动因：`RS_VARIANT_TEXT` 系列 FM **不能列出变式实际存在哪些语言**，所以只能自己 SELECT 底表。主语言必须强制包含，否则主语言描述会丢。`CLIENT SPECIFIED` 配合 `mandt = '000'` 是访问系统独立变式文本的正确姿势（默认客户端读不到）。

**风险与改进** — 直接用 SQL 读 `VARIT` 底表绕过了 FM 层，意味着**放弃了 FM 提供的语言合并/派生逻辑**（比如某语言没有文本时是否回退到主语言）。当前实现是"有哪些取哪些"，这正好符合 Git 化的诉求（导出什么就存什么，不做派生），是合理的。但要注意 `langu IN lt_language_filter` 里混了 `I/EQ` 区间，若 `build_language_filter` 返回空表再插入主语言，最终只查一个语言——这个空表路径没有显式判断，属隐式依赖。

#### ③ 取内容与对象，并排序

```abap
CALL FUNCTION 'RS_VARIANT_CONTENTS_255'
  EXPORTING
    report         = is_vari-report
    variant        = is_vari-variant
    execute_direct = abap_true
  TABLES
    valutab        = et_values
    objects        = et_objects
  EXCEPTIONS
    OTHERS         = 1.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

" reproducible order
SORT et_values.
SORT et_objects.
SORT et_texts.
```

**做什么** — 用内容 FM 取真正的变式值（`valutab`）与对象清单（`objects`），`execute_direct = abap_true` 表示不触发执行确认。最后对三张结果表做排序，注释标明目的是"可重现的顺序"。

**为什么** — `execute_direct` 是为避免 FM 弹出确认/执行变式带来的交互与副作用（变式里的选择条件不该在导出时被真正执行）。三处 `SORT` 是**导出确定性的最后保证**——底表读取顺序不保证稳定，不排序则同一变式每次导出都可能得到不同顺序的 XML，Git diff 会持续噪音。

**风险与改进** — `SORT et_values` 是对 `rsparamsl_255` 行的排序，若该结构没有稳定的全字段键（比如有未填充的客户端/用户字段），排序结果可能仍有残余不确定性。属低风险，但值得用一次双次导出对比来实证。

---

### 3.9 方法 `get_vari_screens`（取变式绑定的屏幕）

```abap
DATA lt_dynnr LIKE rt_vari_screens ##NEEDED.

CALL FUNCTION 'RS_GET_SCREENS_4_1_VARIANT'
  EXPORTING
    program = is_vari-report
    variant = is_vari-variant
  TABLES
    dynnr       = lt_dynnr
    variscreens = rt_vari_screens
  EXCEPTIONS
    OTHERS      = 1.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

SORT rt_vari_screens.
```

**做什么** — 用 FM 取变式绑定的屏幕清单；`lt_dynnr` 是一个**从未使用**的中间表，用 `##NEEDED` 抑制警告；最后排序。

**为什么** — 这个 FM 的 `dynnr` 表格形参同样不是可选的，必须传一个（注释未写但与前一个 FM 同型，是同一种"被 FM 逼出来的写法"）。排序同样是为可重现性。

**风险与改进** — `##NEEDED` 是对"我传了一个不用的参数"的显式承认，可读性差；如果这里的必填性未来放宽，这行会变成一个永久噪音。建议改成把 `rt_vari_screens` 直接传给 FM 的两个形参不可行（类型不同），那就用一个带注释的空局部变量：`DATA lt_dynnr_dummy TYPE ... "FM 形参非可选，此处仅为满足签名"`。

---

### 3.10 方法 `add_tpool` 与 `read_tpool`（文本池的编解码对）

```abap
METHOD add_tpool.
  LOOP AT it_tpool ASSIGNING <ls_tpool_in>.
    APPEND INITIAL LINE TO rt_tpool ASSIGNING <ls_tpool_out>.
    MOVE-CORRESPONDING <ls_tpool_in> TO <ls_tpool_out>.
    IF <ls_tpool_out>-id = 'S'.
      <ls_tpool_out>-split = <ls_tpool_out>-entry.
      <ls_tpool_out>-entry = <ls_tpool_out>-entry+8.
    ENDIF.
  ENDLOOP.
ENDMETHOD.

METHOD read_tpool.
  LOOP AT it_tpool ASSIGNING <ls_tpool_in>.
    APPEND INITIAL LINE TO rt_tpool ASSIGNING <ls_tpool_out>.
    MOVE-CORRESPONDING <ls_tpool_in> TO <ls_tpool_out>.
    IF <ls_tpool_out>-id = 'S'.
      CONCATENATE <ls_tpool_in>-split <ls_tpool_in>-entry
        INTO <ls_tpool_out>-entry
        RESPECTING BLANKS.
    ENDIF.
  ENDLOOP.
ENDMETHOD.
```

**做什么** — 一对互为逆操作的方法：`add_tpool`（导出）对 `id='S'`（分类型长文本）的条目，把 `ENTRY` 的前 8 个字符搬到 `SPLIT`，`ENTRY` 保留第 8 位之后的部分；`read_tpool`（导入）把 `SPLIT` 与 `ENTRY` 按**保留空格**的语义拼回 `ENTRY`。

**为什么** — `TEXTPOOL` 的 S 类条目在底表里是"分行长文本"形态，一个逻辑串被切成 `SPLIT` + `ENTRY` 两段存放；而 abapGit 自己用于 XML 序列化的文本池类型（`zif_abapgit_lang_definitions=>ty_tpool_tt`）对这两段的承载方式与底表不同。把 `ENTRY` 的前 8 个字符显式搬到 `SPLIT` 字段，等于**借已有的字段承载会被压平的那一段信息**，让长描述能完整往返。`CONCATENATE ... RESPECTING BLANKS` 是逆操作的必需——否则前后段的空格边界会在拼接时被吃掉，长文本内容错位。8 这个数字对应 `TEXTPOOL-SPLIT` 的 `CHAR8` 长度。**注意**：这里"SAP 读取路径丢掉了哪一段"的具体成因仅能从代码行为反推，未在注释中说明，建议核对 `RPY_PROGRAM_READ` 对 S 类条目的实际返回形态后再定稿注释。

**风险与改进** — `entry+8` 的偏移量 8 是硬编码魔术数字，与 `SPLIT` 字段的实际长度耦合；一旦底层结构变更（历史上 SAP 确实调整过 TEXTPOOL 的字段布局），这里会静默错切，且**导出与导入两侧会同时错**，往返自洽地"看起来没问题"，只有与 SAP GUI 里的原文比对才能发现。建议提成常量并注释来源字段（如 `CONSTANTS lc_split_len TYPE i VALUE 8. "TEXTPOOL-SPLIT 的 CHAR8 长度"`），或改用 `SPLIT` 的实际长度取值而非字面量。

---

### 3.11 方法 `strip_generation_comments`（剥离函数组生成头）

```abap
IF ms_item-obj_type <> 'FUGR'.
  RETURN.
ENDIF.

" Case 1: MV FM main prog and TOPs
READ TABLE ct_source INDEX 1 ASSIGNING <lv_line>.
IF sy-subrc = 0 AND <lv_line> CP '#**regenerated at *'.
  DELETE ct_source INDEX 1.
  RETURN.
ENDIF.

" Case 2: MV FM includes
IF lines( ct_source ) < 5. " Generation header length
  RETURN.
ENDIF.

READ TABLE ct_source INDEX 1 ASSIGNING <lv_line>.
ASSERT sy-subrc = 0.
IF NOT <lv_line> CP '#*---*'.
  RETURN.
ENDIF.

" 第 2~5 行逐行校验（'**'、'generation date:'、'generator version:'、'---*'）
" ...校验全部通过后：
DELETE ct_source INDEX 4.
DELETE ct_source INDEX 3.
```

**做什么** — 仅对函数组（`FUGR`）生效。情形 1：若第 1 行是 `#**regenerated at *`（MV 函数模块主程序或 TOPS 的重新生成标记），删除第 1 行。情形 2：若第 1~5 行完整匹配生成器头的五段结构（`---*` / `**` / `generation date:` / `generator version:` / `---*`），删除第 3 行（生成日期）与第 4 行（生成器版本），保留头框架。

**为什么** — 生成头里的日期与版本每次重新生成都变，是全库最大的 diff 噪音源之一。删掉这两行后，"重新生成一次但逻辑未变"就不会在 Git 上留下痕迹。保留头框架（第 1、2、5 行）是因为**它们标记了这段源码是系统生成的**——去掉框架会让用户误以为这是手写代码而手改，反而危险。删除顺序是 4 然后 3（倒序），避免索引下移导致的错位删除。

**风险与改进** — 这是导出路径上唯一使用 `ASSERT` 的地方。`ASSERT sy-subrc = 0` 在 `READ TABLE INDEX n` 失败时会**直接 dump**，而这里的前提是 `lines < 5` 已提前 RETURN，所以理论上安全——但"前提被满足"依赖源码长度而非源码内容，遇到长度够但结构被改动的畸形生成头（比如人工编辑过的函数组包含），`ASSERT` 就会把一次导出变成一次系统崩溃。而情形 1 用的是 `IF ... CP ... RETURN` 的柔和路径，两种情形风格不一致。建议情形 2 的守卫也统一为 `IF NOT ( ... ) RETURN.` 形态，与导出的"容错优先"基调一致。

---

### 3.12 方法 `deserialize_program`（导入总编排）

#### ① 退出包含分流

```abap
IF is_exit_include( is_progdir-name ) = abap_true.
  deserialize_exit_include(
    is_progdir = is_progdir
    it_source  = it_source
    it_tpool   = it_tpool
    iv_package = iv_package ).
  RETURN.
ENDIF.
```

**做什么** — 先用命名模式判断是否为退出包含（`LX*` / `SAPLX*` 及 `/LX*` / `/SAPLX*` 的偏移形态），是则走专用导入路径并**立即返回**，不再执行后续任何步骤。

**为什么** — 退出包含（exit include）受 SAP 保护，`RS_INSERT_INTO_WORKING_AREA` 会校验其状态；普通导入流程里带的 CTS 登记、PROGDIR 更新对退出包含不适用甚至报错。所以必须先分流。

**风险与改进** — 分流的判断完全基于**程序命名约定**（`is_exit_include` 只是模式匹配，见 3.25），不看 TADIR/PROGD 里的实际类型。一个恰好以 `LX` 开头但不是退出包含的自定义程序会被错误地送进"只允许活动态"的写入路径。命名约定作为控制流依据是脆弱的一环。

#### ② 登记 CTS 对象并解析标题

```abap
zcl_abapgit_factory=>get_cts_api( )->insert_transport_object(
  iv_object   = 'ABAP'
  iv_obj_name = is_progdir-name
  iv_package  = iv_package
  iv_language = mv_language ).

lv_title = get_program_title( it_tpool ).
```

**做什么** — 先把对象登记进 CTS（变更与传输系统）的传输队列，再从文本池解析出标题。

**为什么** — 顺序不能反：CTS 登记必须在源码写入之前，否则写入产生的更改不会被任何传输请求捕获（对象"消失"在版本控制之外）。标题解析也必须在写入之前完成，因为写入需要标题字符串。

**风险与改进** — `insert_transport_object` 没有返回码检查；若登记失败（对象已存在于另一个请求、传输请求已标记为释放），后面的写入照常进行，产生一个"改了但没被登记"的对象。这是导入静默失配的入口。建议至少检查返回状态。

#### ③ 探测活动态版本并分支写入

```abap
SELECT SINGLE progname FROM reposrc INTO lv_progname
  WHERE progname = is_progdir-name
  AND r3state = c_state-active.

IF sy-subrc = 0.
  update_program( is_progdir = is_progdir it_source = it_source iv_title = lv_title ).
ELSE.
  insert_program( is_progdir = is_progdir it_source = it_source iv_title = lv_title iv_package = iv_package ).
ENDIF.
```

**做什么** — 到 `REPOSRC` 底表查是否存在**活动态**版本。存在则覆盖（`update_program`），不存在则新建（`insert_program`）。

**为什么** — 这是导入的核心分支：已有对象要覆盖、新对象要创建。用 `REPOSRC` 而不是 `PROGD` 判断，是因为 `REPOSRC` 直接反映"有没有可覆盖的源码"；查活动态（而非非活动态）是为了避免"存在一个未激活草稿"的场景被误判为覆盖。

**风险与改进** — 只查活动态意味着：若目标系统只有**非活动态草稿**而没有活动版本，这里会走 `insert_program`，很可能撞上 `already_exists`（因为非活动版本占用同名）。此时 `insert_program` 里的 `name_not_allowed` 回退分支（见 3.15 ③）会被触发，最终可能产生"活动+非活动双写"的结果，与预期不完全一致。这个边界场景建议显式处理（先探测非活动态并决定是否覆盖）。另外 `SELECT ... reposrc` 直查底表而非用 FM，放弃了 FM 层的多版本/权限处理，属可接受的取舍但要意识到。

#### ④ 更新 PROGDIR 元数据并入队激活

```abap
zcl_abapgit_factory=>get_sap_report( )->update_progdir(
  is_progdir = is_progdir
  iv_package = iv_package ).

zcl_abapgit_objects_activation=>add(
  iv_type = 'REPS'
  iv_name = is_progdir-name ).
```

**做什么** — 源码写入后，用 PROGDIR 结构（类型 `SUBC`、`UCCHECK`、作者、语言版本等）更新程序目录元数据，然后把 `REPS` 对象加入激活队列。

**为什么** — `RPY_PROGRAM_INSERT`/`RPY_INCLUDE_UPDATE` 只处理源码与标题，PROGDIR 里的其他元数据（程序类型、版本控制标记等）需要单独一步。激活统一入队而非就地激活，是因为屏幕、命令区域、文本池、变式都要写入，分散激活会中间态失败（比如源码激活了但屏幕还没写）。**把所有写入都设为非活动态、最后一次性激活**，是这个类保证一致性的核心手法。

**风险与改进** — 若前面 `insert_program`/`update_program` 已部分成功（源码写入成功但 PROGDIR 更新失败），激活队列里已经有 `REPS`，会去激活一个元数据不完整的状态。没有事务包裹（这是 ABAP 的常见限制，跨 FM 无法做事务回滚），只能靠"非活动态 + 延迟激活"降低爆炸半径。这是设计取舍，建议在注释里写明"本方法不具备事务原子性，失败时靠非活动态保持可恢复"。

---

### 3.13 方法 `deserialize_exit_include`（退出包含专用导入）

```abap
lv_title = get_program_title( it_tpool ).

SELECT SINGLE progname FROM reposrc INTO lv_progname
  WHERE progname = is_progdir-name
  AND r3state = c_state-active.

IF sy-subrc = 0.
  update_program(
    is_progdir = is_progdir
    it_source  = it_source
    iv_title   = lv_title
    iv_state   = c_state-off ).
ELSE.
  insert_program(
    is_progdir = is_progdir
    it_source  = it_source
    iv_title   = lv_title
    iv_package = iv_package ).
ENDIF.
```

**做什么** — 与 `deserialize_program` 的 ③④ 结构相同，但覆盖时传的 `iv_state` 是 `c_state-off`（空字符串），且不做 CTS 登记、不更新 PROGDIR、不入激活队列。

**为什么** — 方法头的注释给出原因："Includes in SAP exit function groups must be processed in active state only (check in RS_INSERT_INTO_WORKING_AREA)"——退出包含的写入校验要求活动态，所以不能用"先写非活动态再激活"的常规手法，只能直接写活动态。空字符串 `c_state-off` 在 `RPY_INCLUDE_UPDATE` 的 `save_inactive` 形参上表达的是"不按非活动态保存"，即直接落到活动态。

**风险与改进** — `c_state-off` 的语义**依赖 `RPY_INCLUDE_UPDATE` 对空值的隐含解释**，这个含义没有在方法注释中说明，只说了"必须活动态"。空字符串作为状态值是典型的"三态枚举漏掉第三态文档化"的隐患：若 SAP 未来改变对空值的解释，这里会静默改变写入行为。建议用显式布尔或命名常量（如 `c_state-active` 配合另一个形参）来表达意图，或在注释中明确写出"空值在此 FM 中等价于直接保存活动态"。

---

### 3.14 方法 `get_program_title`（取标题 + 修工作区 bug）

```abap
READ TABLE it_tpool INTO ls_tpool WITH KEY id = 'R'.
IF sy-subrc = 0.
  " there is a bug in RPY_PROGRAM_UPDATE, the header line of TTAB is not
  " cleared, so the title length might be inherited from a different program.
  ASSIGN ('(SAPLSIFP)TTAB') TO <lg_any>.
  IF sy-subrc = 0.
    CLEAR <lg_any>.
  ENDIF.

  rv_title = ls_tpool-entry.
ENDIF.
```

**做什么** — 从文本池中找 `id='R'`（标题）的条目取值。若找到，先用 `ASSIGN ('(SAPLSIFP)TTAB')` 动态定位到 include `SAPLSIFP` 的私有全局内表 `TTAB` 并清空它，然后再返回标题。

**为什么** — 注释讲清了背景：`RPY_PROGRAM_UPDATE` 有个 bug，`TTAB`（该 FM 内部用来缓存标题元数据的工作区表）的头部行不会被清空，导致**标题长度会从上一个程序继承过来**，把短标题写成带旧长度标记的形式（结果对象标题显示异常或长度错误）。这里通过反射式访问把缓存清掉，是"在调用方修 SAP 标准 bug"的典型 workaround。

**风险与改进** — 这是整份代码里最脆弱的一处：`ASSIGN ('(SAPLSIFP)TTAB')` 依赖三个隐含前提——(1) include `SAPLSIFP` 已被加载进当前程序空间；(2) 全局变量名 `TTAB` 在所有 release 中不变；(3) 它确实是导致该 bug 的表。任一前提失效时 `sy-subrc <> 0`，代码**静默跳过**清理，bug 原样复现（不报错、不告警）。建议：(a) 至少记录一条 `DEBUG` 级别的调试输出表明清理未生效；(b) 加注释标注"此 workaround 依赖的 SAP bug 编号/Note 号"以便追踪；(c) 长期方案是推动 SAP 修复或改用不经过 `RPY_PROGRAM_UPDATE` 的写入路径。

---

### 3.15 方法 `insert_program`（新建程序）

#### ① 标准插入（含 `uccheck` 形参）

```abap
CALL FUNCTION 'RPY_PROGRAM_INSERT'
  EXPORTING
    development_class = iv_package
    program_name      = is_progdir-name
    program_type      = is_progdir-subc
    title_string      = iv_title
    save_inactive     = iv_state
    suppress_dialog   = abap_true
    uccheck           = is_progdir-uccheck " does not exist on lower releases
  TABLES
    source_extended   = it_source
  EXCEPTIONS
    already_exists    = 1
    cancelled         = 2
    name_not_allowed  = 3
    permission_error  = 4
    OTHERS            = 5 ##FM_SUBRC_OK.
```

**做什么** — 用标准 FM 新建程序，带上开发类、程序类型、标题、保存状态（默认非活动态）、以及版本控制标记 `uccheck`；`suppress_dialog` 关闭交互确认。

**为什么** — `suppress_dialog` 是批量导入的必需，否则每个对象都弹确认框。`uccheck` 是较新版本才有的形参，用于传递 ABAP 版本控制标记，缺了会导致导入后的对象版本标记与源系统不一致。

**风险与改进** — `OTHERS = 5 ##FM_SUBRC_OK` 用抑制警告代替了真正的错误处理：任何未列举的失败都会落到 `OTHERS`，而 `##FM_SUBRC_OK` 只是告诉静态检查"我知道这个 FM 的 OTHERS 可能成功"。后面靠 `IF sy-subrc = 3 ... ELSEIF sy-subrc > 0` 兜住，但 `sy-subrc = 5` 与 `1`/`2`/`4` 都会走 `raise_t100`，语义上是对的，只是"OTHERS 可能成功"的警告被压掉了而非被分析掉。建议对 OTHERS 单独记录 `sy-msgno` 以便定位真实失败原因。

#### ② 低版本参数降级重试

```abap
CATCH cx_sy_dyn_call_param_not_found.
  CALL FUNCTION 'RPY_PROGRAM_INSERT'
    EXPORTING
      development_class = iv_package
      program_name      = is_progdir-name
      program_type      = is_progdir-subc
      title_string      = iv_title
      save_inactive     = iv_state
      suppress_dialog   = abap_true
    TABLES
      source_extended   = it_source
    EXCEPTIONS
      ...
ENDTRY.
```

**做什么** — 用动态调用捕获 `cx_sy_dyn_call_param_not_found`（`uccheck` 形参在低版本不存在），去掉该形参后重试一次。

**为什么** — abapGit 要跑在从 NetWeaver 7.0 到 S/4 的各个版本上，`uccheck` 是较新才加入的形参。"先试完整版，失败则降级"比"探测版本再分支"简单得多，且不需要维护版本清单。

**风险与改进** — 这个模式在文件里出现了**三次**（`insert_program`、`delete_vari`，以及同类场景），每次都完整复制一遍 FM 调用，任何一处修正都需同步三处。建议提成一个小工具方法（如 `call_fm_fallback`），或在注释里交叉引用"另见 delete_vari 同款降级模式"以便维护。另外 `cx_sy_dyn_call_param_not_found` 只保证"某个参数不存在"，理论上不保证是 `uccheck`；若未来又新增一个可选形参且低版本也没有，这里会误把该失败当成 `uccheck` 问题再重试一次，第二次仍失败才落到 `raise_t100`——路径正确但有一次无谓的失败调用。

#### ③ `name_not_allowed` 的双写回退

```abap
IF sy-subrc = 3.

  " For cases that standard function does not handle (like FUGR),
  " we save active and inactive version of source with the given PROGRAM TYPE.
  " Without the active version, the code will not be visible in case of activation errors.
  zcl_abapgit_factory=>get_sap_report( )->insert_report(
    iv_name         = is_progdir-name
    iv_package      = iv_package
    it_source       = it_source
    iv_state        = c_state-active
    iv_version      = is_progdir-uccheck
    iv_program_type = is_progdir-subc ).

  zcl_abapgit_factory=>get_sap_report( )->insert_report(
    iv_name         = is_progdir-name
    iv_package      = iv_package
    it_source       = it_source
    iv_state        = c_state-inactive
    iv_version      = is_progdir-uccheck
    iv_program_type = is_progdir-subc ).

ELSEIF sy-subrc > 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.
```

**做什么** — 若 FM 返回 `name_not_allowed`（`sy-subrc = 3`，标准 FM 拒绝这个"名称/类型组合"，典型如函数组），则绕过 FM，用工厂方法 `insert_report` 直接写底表，**同一份源码分别写活动态与非活动态**。

**为什么** — 注释讲得很清楚：标准 FM 不处理函数组这类对象，必须自己写。而"活动态版本"是必需的——若只写非活动态，一旦激活失败，SE38 里就**看不到任何代码**（因为没有活动版本可显示），用户面对一个"空对象"无从排错。写活动态版本等于给排错留一条可见路径。

**风险与改进** — 直接写底表意味着绕过了 FM 的所有校验（名称合法性、版本控制、锁）。这里之所以安全，是因为只有 FM 明确拒绝（`name_not_allowed`）时才走到这，等于"SAP 说这是它管不了的对象，那我手动写"。但两次 `insert_report` 之间没有事务保护：若活动态写入成功、非活动态写入失败，对象会处于"只有活动态"的半状态。建议在两次调用之间加异常捕获并尽量补写/清理。另外这里 `iv_version` 传 `is_progdir-uccheck` 与 `insert_program` 里 `uccheck` 的传递保持一致，是好的一致性。

---

### 3.16 方法 `update_program`（覆盖已有程序）

```abap
zcl_abapgit_language=>set_current_language( mv_language ).

CALL FUNCTION 'RPY_INCLUDE_UPDATE'
  EXPORTING
    include_name    = is_progdir-name
    title_string    = iv_title
    save_inactive   = iv_state
  TABLES
    source_extended = it_source
  EXCEPTIONS
    not_found        = 1
    cancelled        = 2
    permission_error = 3
    OTHERS           = 4.

IF sy-subrc <> 0.
  zcl_abapgit_language=>restore_login_language( ).

  IF sy-msgid = 'EU' AND sy-msgno = '510'.
    zcx_abapgit_exception=>raise( 'User is currently editing program' ).
  ELSEIF sy-msgid = 'EU' AND sy-msgno = '522'.
    " for generated table maintenance function groups, the author is set to SAP* instead of
    " the user which generates the function group. This hits some standard checks, pulling new
    " code again sets the author to the current user which avoids the check
    IF is_exit_include( is_progdir-name ) = abap_false.
      zcx_abapgit_exception=>raise( |Delete function group and pull again, { is_progdir-name } (EU522)| ).
    ENDIF.
  ELSE.
    zcx_abapgit_exception=>raise_t100( ).
  ENDIF.
ENDIF.

zcl_abapgit_language=>restore_login_language( ).
```

**做什么** — 切换语言上下文后调用 `RPY_INCLUDE_UPDATE` 覆盖源码与标题；失败时按消息号分流：`EU510`（有用户在编辑该程序）给出人类可读提示；`EU522`（作者校验失败，多见于系统生成的表维护函数组，因为作者是 `SAP*` 而非当前用户）提示"删除后重新拉取"，但**退出包含场景下静默放过**；其余走 `raise_t100`。语言上下文在任何退出路径都被还原。

**为什么** — 覆盖操作和新建不同，会撞上"有人在编辑"的锁校验与"作者不匹配"的版本控制校验。把 `EU510`/`EU522` 单独识别，是把 SAP 的模糊错误码翻译成用户可执行的行动指引（"删了重拉"比看 `EU 522` 有用得多）。退出包含对 `EU522` 放行，是因为退出包含的作者校验在目标系统里本就无法满足（它是 SAP 退出），硬报错只会让所有退出包含导入都失败。

**风险与改进** — `raise_t100` 依赖 `sy-t100key` 是否被 FM 正确设置；若 FM 未设，用户看到的是空消息。另外 EU522 对退出包含的"静默放行"意味着**导入实际未成功但方法未报错**——后续激活步骤会发现源码没变，但错误已经不可见。建议至少在放行路径记录一条警告消息，让操作者知道这个对象需要人工确认。

---

### 3.17 方法 `deserialize_textpool`（文本池导入）

#### ① 语言与状态决策

```abap
IF iv_language IS INITIAL.
  lv_language = mv_language.
ELSE.
  lv_language = iv_language.
ENDIF.

IF lv_language = mv_language.
  lv_state = c_state-inactive. "Textpool in main language needs to be activated
ELSE.
  lv_state = c_state-active. "Translations are always active
ENDIF.
```

**做什么** — 语言参数缺省时用主语言。若目标语言等于主语言，写入状态取**非活动态**（待激活）；否则取**活动态**（翻译即时生效）。

**为什么** — 主语言文本池的写入必须走激活流程（`REPT` 是独立可激活的对象），而翻译文本是即插即用的。这个分叉是整个方法后续所有分支的开关。

**风险与改进** — "目标语言 = 主语言"的比较用字符串相等，跨语言的等价场景（比如主语言 `EN` 而传入 `en`）不会命中。语言标识的规范化建议集中到语言服务类，而不是在每个对象处理器里各自比较。

#### ② 空文本池的两种处理

```abap
IF it_tpool IS INITIAL.
  IF iv_is_include = abap_false OR lv_state = c_state-active.
    DELETE TEXTPOOL iv_program
      LANGUAGE lv_language
      STATE lv_state.

    lv_delete = abap_true.
  ELSE.
    INSERT TEXTPOOL iv_program
      FROM it_tpool
      LANGUAGE lv_language
      STATE lv_state.
  ENDIF.
ELSE.
  INSERT TEXTPOOL iv_program
    FROM it_tpool
    LANGUAGE lv_language
    STATE lv_state.
  IF sy-subrc <> 0.
    zcx_abapgit_exception=>raise( 'error from INSERT TEXTPOOL' ).
  ENDIF.
ENDIF.
```

**做什么** — 文本池为空时有两条路径：**非包含**（`iv_is_include = abap_false`）或**翻译态**（`lv_state = 活动`）→ 直接 `DELETE TEXTPOOL`，并把 `lv_delete` 置真；**包含的主语言**（`iv_is_include = abap_true` 且状态为非活动）→ 执行一次 `INSERT TEXTPOOL FROM it_tpool`（此时 `it_tpool` 仍为空，等于插入空文本池）。文本池非空时正常插入。

**为什么** — 注释解释得很到位：对包含（include）而言，主语言文本池的删除无法激活，因为**激活文本池删除会连带激活主程序的文本池删除**，这是 SAP 的保护设计。所以当包含的主语言文本池为空时，不能删（会触发不想要的连锁激活），只能"插入一个空文本池"来表达"这里没有文本"。这是绕开 SAP 激活级联的唯一可行手法。

**风险与改进** — `INSERT TEXTPOOL ... FROM it_tpool` 在 `it_tpool` 为空时执行，这个"用空表插入来表达删除意图"的语义非常反直觉，且**没有返回码检查**（`DELETE TEXTPOOL` 分支也没有）。若插入失败，方法静默结束，对象处于"该有文本池却没有"的状态。建议对两个分支都加返回码检查。另外 `iv_is_include` 的判定来源是父类（按对象名模式），与 `is_exit_include` 的命名判定是两套不同的包含判定口径，需要保证语义一致。

#### ③ 主语言激活入队

```abap
IF lv_state = c_state-inactive AND iv_program NP 'SAPLX*'.
  zcl_abapgit_objects_activation=>add(
    iv_type   = 'REPT'
    iv_name   = iv_program
    iv_delete = lv_delete ).
ENDIF.
```

**做什么** — 仅当写入的是主语言非活动态、且程序名不匹配 `SAPLX*`（函数组包含）时，把 `REPT`（文本池）对象加入激活队列，并把"本次是删除操作"这一事实通过 `iv_delete` 传给激活器。

**为什么** — 函数组包含（`SAPL*`）的文本池激活归属在函数组主对象上，包含本身不应单独激活（否则与 ② 的"删除无法激活"约束冲突）。`iv_delete` 参数让激活器能区分"新增/修改"与"删除"，走不同的激活调用。

**风险与改进** — `NP 'SAPLX*'` 是硬编码的命名排除，与 3.25 的 `is_exit_include` 模式判定是第三套命名规则。全类里"这是不是特殊程序"的判断分散在三处（`SUBC`、`LX*`/`SAPLX*`、`SAPL*`），维护者必须同时记住三者。建议收敛成一个"程序角色判定"方法，各处统一调用。

---

### 3.18 方法 `deserialize_cua`（命令区域导入）

#### ① 全空短路

```abap
IF lines( is_cua-sta ) = 0
    AND lines( is_cua-fun ) = 0
    AND lines( is_cua-men ) = 0
    AND lines( is_cua-mtx ) = 0
    AND lines( is_cua-act ) = 0
    AND lines( is_cua-but ) = 0
    AND lines( is_cua-pfk ) = 0
    AND lines( is_cua-set ) = 0
    AND lines( is_cua-doc ) = 0
    AND lines( is_cua-tit ) = 0
    AND lines( is_cua-biv ) = 0.
  RETURN.
ENDIF.
```

**做什么** — 若 11 张明细表全部为空，直接返回，不执行写入。

**为什么** — 程序没有 CUA 是常态，向 SAP 写一个空 CUA 没有意义且可能触发不必要的激活/锁。这是导入侧的对称短路（导出侧 `serialize_cua` 对 `not_found` 也是直接返回）。

**风险与改进** — 这个短路**不检查 `is_cua-adm`**。若 ADM 主表有内容而所有明细表为空（这在 issue #1807 的旧数据里恰恰出现过），会直接被短路跳过，ADM 永远写不回去。虽然 3.19 的 `auto_correct_cua_adm` 就是为了补 ADM，但补完之后的结果仍然被这个 `RETURN` 挡在门外。建议把 ADM 非空也纳入条件（ADM 有值时不短路）。

#### ② 组装传输键

```abap
SELECT SINGLE devclass INTO ls_tr_key-devclass
  FROM tadir
  WHERE pgmid = 'R3TR'
  AND object = ms_item-obj_type
  AND obj_name = ms_item-obj_name.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise( 'not found in tadir' ).
ENDIF.

ls_tr_key-obj_type = ms_item-obj_type.
ls_tr_key-obj_name = ms_item-obj_name.
ls_tr_key-sub_type = 'CUAD'.
ls_tr_key-sub_name = iv_program_name.
```

**做什么** — 从 `TADIR` 取该对象的开发类填入传输键，再补齐 `obj_type`/`obj_name` 与 `sub_type='CUAD'`、`sub_name=程序名`。

**为什么** — 写 CUA 必须带传输键（TRS 体系要求），而程序本身的包信息不在这一步的入参里，只能回查 `TADIR`。`sub_type='CUAD'` 表明这是程序的一个子对象，与主对象 `REPS` 分开传输。

**风险与改进** — `TADIR` 缺失即抛异常（`raise 'not found in tadir'`），这是合理的硬失败——没有包信息就无法创建传输请求。但异常消息是硬编码英文小写字符串，与其他地方用 `raise_t100` 或中文/本地化提示的风格不一致；另外 `pgmid = 'R3TR'` 硬编码，对于非 ABAP 仓库（本例都是 ABAP）不适用，属可接受的假设。

#### ③ ADM 兜底、`sy-tcode` hack 与写回

```abap
ls_adm = is_cua-adm.
auto_correct_cua_adm( EXPORTING is_cua = is_cua CHANGING cs_adm = ls_adm ).

sy-tcode = 'SE41' ##WRITE_OK. " evil hack, workaround to handle fixes in note 2159455
CALL FUNCTION 'RS_CUA_INTERNAL_WRITE'
  EXPORTING
    program = iv_program_name
    language = mv_language
    tr_key  = ls_tr_key
    adm     = ls_adm
    state   = c_state-inactive
  TABLES
    sta = is_cua-sta
    ...
    biv = is_cua-biv
  EXCEPTIONS
    not_found = 1
    OTHERS    = 2.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

zcl_abapgit_objects_activation=>add(
  iv_type = 'CUAD'
  iv_name = iv_program_name ).
```

**做什么** — 先复制 ADM 并通过 `auto_correct_cua_adm` 兜底补全；然后**手工设置 `sy-tcode = 'SE41'`**（作者自己标注为 `evil hack`，针对 SAP Note 2159455）；调用写回 FM（状态固定非活动态）；成功后把 `CUAD` 子对象加入激活队列。

**为什么** — SAP 在某些版本里修了一个 bug（Note 2159455），修复逻辑依赖 `sy-tcode` 判断当前事务码，而在 abapGit 这种非 GUI 会话里 `sy-tcode` 不会被设置成期望值，导致 FM 走错分支（可能写错状态或跳过校验）。手动把 `sy-tcode` 设为 `SE41`（命令区域维护事务）让 FM 走"正常的事务内路径"。作者自己也承认这是 hack，用 `##WRITE_OK` 抑制了"不应写 sy-tcode"的静态警告。

**风险与改进** — **这是本类中风险最高的单行代码**，问题不在它是否有效，而在于它的副作用范围：
1. `sy-tcode` 是**会话级全局变量**，设置后**永远不会被恢复**，同一次导入请求里后续所有 FM 调用（屏幕写入、变式创建、文本池激活……）都会看到 `sy-tcode = 'SE41'`，可能触发其他基于事务码的分支逻辑。
2. 修复一个 SAP bug 的手段本身可能**再次成为 bug 来源**（Note 2159455 的后续修正若改变了对 `sy-tcode` 的判定，这里就会反向出错）。
3. 它把"环境状态"当成"参数"传递，破坏了 FM 的纯函数假设，使得该方法在并发/批量场景下难以推理。

改进方向：(a) 至少在方法末尾记录 `sy-tcode` 的原值并恢复（即使 SAP 文档说不要改，恢复也比泄漏好）；(b) 给这行加一条明确的"适用版本范围 + Note 追踪"注释，便于未来移除；(c) 中期方案是改为直接写 CUA 底表（`CUAD` 结构对应的表），绕开这个 FM，彻底摆脱对 `sy-tcode` 的依赖。

---

### 3.19 方法 `auto_correct_cua_adm`（ADM 兜底重建）

```abap
" issue #1807 automatic correction of CUA interfaces saved incorrectly in the past (ADM was not saved in the XML)

CONSTANTS:
  lc_num_n_space TYPE string VALUE ' 0123456789',
  lc_num_only    TYPE string VALUE '0123456789'.

IF cs_adm IS NOT INITIAL
    AND cs_adm-actcode CO lc_num_n_space
    AND cs_adm-mencode CO lc_num_n_space
    AND cs_adm-pfkcode CO lc_num_n_space. "Check performed in form check_adm of include LSMPIF03
  RETURN.
ENDIF.

LOOP AT is_cua-act ASSIGNING <ls_act>.
  IF <ls_act>-code+6(14) IS INITIAL AND <ls_act>-code(6) CO lc_num_only.
    cs_adm-actcode = <ls_act>-code.
  ENDIF.
ENDLOOP.

LOOP AT is_cua-men ASSIGNING <ls_men>.
  IF <ls_men>-code+6(14) IS INITIAL AND <ls_men>-code(6) CO lc_num_only.
    cs_adm-mencode = <ls_men>-code.
  ENDIF.
ENDLOOP.

LOOP AT is_cua-pfk ASSIGNING <ls_pfk>.
  IF <ls_pfk>-code+6(14) IS INITIAL AND <ls_pfk>-code(6) CO lc_num_only.
    cs_adm-pfkcode = <ls_pfk>-code.
  ENDIF.
ENDLOOP.
```

**做什么** — 这是**导入侧的迁移性修复**。先检查 ADM 是否已完整（三个 code 字段都非空且符合数字模式）——是则直接返回；否则分别从 `act`、`men`、`pfk` 三张表里找"主代码"（`code` 的前 6 位是数字、后 14 位为空，代表该表的主条目而非子条目），回填到 ADM 对应的 `actcode`/`mencode`/`pfkcode`。

**为什么** — 早期版本的 abapGit 导出 XML 时**没有保存 ADM 主表**（issue #1807），导致旧仓库里的 CUA 数据一导入就缺 ADM，而 SAP 的 `RS_CUA_INTERNAL_WRITE` 需要 ADM 来定位状态/菜单/功能键。这里根据明细表反推出 ADM 应该是什么值，让旧数据能继续用。注释引用的 `check_adm`（include `LSMPIF03` 里的同名校验）说明校验规则是与 SAP 内部一致的。

**风险与改进** — "主代码"的判定规则（前 6 位数字、后 14 位空）是从 SAP 的 `CUAD` 编码约定归纳的，注释里没写明依据。若某 CUA 有多个主条目，循环会**用最后一个覆盖前面的**（没有 `EXIT` 或"仅当 ADM 为空才写"的守卫）。这在"旧数据只有一个主条目"的场景下没问题，但对多状态程序可能选错。建议在条件里加 `IF cs_adm-actcode IS INITIAL` 之类的"只填一次"守卫，避免后写覆盖先写。另外这个方法被设计成 `CHANGING` 传入 `ls_adm` 而非 `RETURNING`，与类里其他"读入+返回"的风格略不一致，但用 `CHANGING` 表达"就地修正"语义也算合理。

---

### 3.20 方法 `deserialize_dynpros`（屏幕导入，导入侧最复杂的一段）

分五步。

#### ① 构建待删除屏幕清单

```abap
CALL FUNCTION 'RS_SCREEN_LIST'
  EXPORTING
    dynnr    = ''
    progname = ms_item-obj_name
  TABLES
    dynpros  = lt_d020s_to_delete
  EXCEPTIONS
    not_found = 1
    OTHERS    = 2.
IF sy-subrc = 2.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

SORT lt_d020s_to_delete BY dnum ASCENDING.
```

**做什么** — 先列出**目标系统现有的全部屏幕**，作为"待删除集合"，并按屏幕号升序排序。

**为什么** — 导入是"用远端定义替换本地定义"，所以先取本地现状做基线。后面每处理一个远端屏幕，就从集合里删掉对应项；循环结束后集合里剩下的就是"远端没有、本地有"的屏幕，需要删除。这是**差异集合算法**的标准起手式。

**风险与改进** — 这里排序**不是可有可无的**：下面用了 `BINARY SEARCH`，它要求表已按 `dnum` 排序。排序与后续的二分查找形成隐式耦合，中间若有人删掉排序语句，二分查找会静默返回"未找到"（`sy-subrc <> 0`），待删除集合永远清不掉，本地屏幕永远删不掉，而整个过程**不报任何错**。建议在二分查找前加一行断言或注释说明依赖。

#### ② 逐屏处理：从待删集合移除 + 还原流逻辑

```abap
" ls_dynpro is changed by the function module, a field-symbol will cause
" the program to dump since it_dynpros cannot be changed
LOOP AT it_dynpros INTO ls_dynpro.

  READ TABLE lt_d020s_to_delete WITH KEY dnum = ls_dynpro-header-screen
    TRANSPORTING NO FIELDS
    BINARY SEARCH.
  IF sy-subrc = 0.
    DELETE lt_d020s_to_delete INDEX sy-tabix.
  ENDIF.

  " todo: kept for compatibility, remove after grace period #3680
  ls_dynpro-flow_logic = uncondense_flow(
    it_flow   = ls_dynpro-flow_logic
    it_spaces = ls_dynpro-spaces ).

  IF ls_dynpro-flow_logic IS INITIAL.
    ls_dynpro-flow_logic = mo_files->read_abap( iv_extra = 'screen_' && ls_dynpro-header-screen ).
  ENDIF.
```

**做什么** — 用 `LOOP INTO`（按值复制）而非 `ASSIGNING`（字段符号）遍历远端屏幕，因为后续 FM 会修改这个结构体，而字段符号指向的 `it_dynpros` 是不可变的。对每个屏幕：若它在待删除集合里，删掉；然后**先尝试还原流逻辑缩进**，若还原后仍为空（说明这份导出没有流逻辑内联数据），从外置的 `screen_XXXX.abap` 文件读回流逻辑。

**为什么** — `LOOP INTO` 的注释是这段代码最有教学价值的一行：它显式记录了"字段符号 + FM 修改 + 只读表 = dump"这个 ABAP 陷阱。流逻辑的双重来源（先还原、后读文件）是版本迁移的产物：新版本把流逻辑写成独立 `.abap` 文件（可读性好），旧版本把它内联在 XML 里并用 `spaces` 表压缩了缩进。两个来源都要支持，否则旧仓库无法导入。

**风险与改进** — `DELETE lt_d020s_to_delete INDEX sy-tabix` 依赖"刚做完二分查找的 `sy-tabix`"，这段逻辑正确但极其脆弱（任何插入的中间语句都会破坏它）。更稳妥的写法是用 `DELETE ... WHERE dnum = ...` 或直接 `DELETE lt_d020s_to_delete WITH KEY dnum = ...`，一次性表达意图且消除对 `sy-tabix` 时序的依赖。另外 `#3680` 的 TODO 明确标注"保留兼容，宽限期后移除"，属**已知负债**——建议标注目标移除版本/里程碑，否则这类兼容分支会永久留存。

#### ③ 字段属性的导入侧修复

```abap
LOOP AT ls_dynpro-fields ASSIGNING <ls_field>.
  " if the DDIC element has a PARAMETER_ID and the flag "from_dict" is active
  " the import will enable the SET-/GET_PARAM flag. In this case: "force off"
  IF <ls_field>-param_id IS NOT INITIAL
      AND <ls_field>-from_dict = abap_true.
    IF <ls_field>-set_param IS INITIAL.
      <ls_field>-set_param = lc_rpyty_force_off.
    ENDIF.
    IF <ls_field>-get_param IS INITIAL.
      <ls_field>-get_param = lc_rpyty_force_off.
    ENDIF.
  ENDIF.

  " If the previous conditions are met the value 'F' will be taken over
  " during de-serialization potentially overlapping other fields in the screen,
  " we set the tag to the correct value 'X'
  IF <ls_field>-type = 'CHECK'
      AND <ls_field>-from_dict = abap_true
      AND <ls_field>-text IS INITIAL
      AND <ls_field>-modific IS INITIAL.
    <ls_field>-modific = 'X'.
  ENDIF.

  "fix for issue #2747:
  IF <ls_field>-foreignkey IS INITIAL.
    <ls_field>-foreignkey = lc_rpyty_force_off.
  ENDIF.
ENDLOOP
```

**做什么** — 对导入的每个字段做三处"反向修复"：
- 有 `PARAMETER_ID` 且 `from_dict` 的字段，导入时会错误地启用 SET/GET 参数标志，用 `'/'`（`lc_rpyty_force_off`）强制关闭；
- 无文本、无修改标志的 `CHECK` 类型字段，SAP 导入会默认成 `'F'`（固定文本），而 `'F'` 在屏幕上会遮挡其他字段，所以改回 `'X'`（文本来自字典）；
- `FOREIGNKEY` 为空的字段填 `'/'`（issue #2747）。

**为什么** — 这是导出侧"清洗"（3.4 ③）的**对称镜像**。导出时把语义上无效的值清空成空串（为了 diff 干净），导入时又必须把这些空值翻译成 SAP 能接受的显式取值——因为 `'/'`（force off）才是 SAP 里表示"明确关闭"的合法值，而空串会被 SAP 当成"沿用默认"，触发那些错误的默认行为。所以一个空串在导出侧是"干净"，在导入侧必须变成 `'/'` 才是"干净"。这种**双向不透明的语义映射**是这个类最精妙也最容易出错的地方。

**风险与改进** — 三处修复都是"若为空则填 X"的模式，但它们各自的触发条件各不相同（有的带 `param_id`+`from_dict` 双条件，有的带 `type='CHECK'`，有的无条件）。`<ls_field>-foreignkey` 那条是**无条件的**：任何 `FOREIGNKEY` 为空的字段都会被填 `'/'`。这在导出侧是被"重算后清空"的字段（3.4 ③ 里 `ELSE CLEAR <ls_field>-foreignkey`），语义上正确；但如果某字段的 `FOREIGNKEY` 本来就该保持空（不启用外键），这个 `'/'` 是否等价于"不启用"需要确认——注释只说"fix for issue #2747"，没有说明 `'/'` 与空串的语义区别。**建议为这三处修复各写一条一句话的语义说明**，而不是只留 issue 编号，否则半年后没人记得为什么。另外这些修复都写死在循环里，没有集中的"导入修复策略"层，新增一条时容易漏掉导出侧的对称处理。

#### ④ 原生屏 / 常规屏双路径插入

```abap
IF ls_dynpro-header-type CA c_native_dynpro AND ls_dynpro-nat_header IS NOT INITIAL.
  DELETE FROM d021t WHERE prog = ls_dynpro-header-program AND dynr = ls_dynpro-header-screen ##SUBRC_OK.
  INSERT d021t FROM TABLE ls_dynpro-nat_texts ##SUBRC_OK.

  ls_dynpro-nat_header-dgen = sy-datum.
  ls_dynpro-nat_header-tgen = sy-uzeit.

  CALL FUNCTION 'RPY_DYNPRO_INSERT_NATIVE'
    EXPORTING
      header       = ls_dynpro-nat_header
      dynprotext   = ls_dynpro-header-descript
    TABLES
      fieldlist    = ls_dynpro-nat_fields
      flowlogic    = ls_dynpro-flow_logic
      params       = lt_params
    EXCEPTIONS
      cancelled          = 1
      already_exists     = 2
      program_not_exists = 3
      not_executed       = 4
      OTHERS             = 5.
ELSE.
  CALL FUNCTION 'RPY_DYNPRO_INSERT'
    EXPORTING
      header                 = ls_dynpro-header
      suppress_exist_checks  = abap_true
      suppress_generate      = ls_dynpro-header-no_execute
    TABLES
      containers             = ls_dynpro-containers
      fields_to_containers   = ls_dynpro-fields
      flow_logic             = ls_dynpro-flow_logic
    EXCEPTIONS
      ... (cancelled / already_exists / program_not_exists / not_executed /
           missing_required_field / illegal_field_value / field_not_allowed /
           not_generated / illegal_field_position / OTHERS，共 10 个分支已省略)
ENDIF.
IF sy-subrc <> 2 AND sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.
```

**做什么** — 原生屏路径：先**删除并重新插入 `d021t`（屏幕文本表）**（因为文本可能已存在，需要覆盖），然后**重写 `nat_header` 的生成日期与时间为当前时间**，再调 `RPY_DYNPRO_INSERT_NATIVE`。常规屏路径：调 `RPY_DYNPRO_INSERT`，其中 `suppress_exist_checks = abap_true` 关闭存在性校验，`suppress_generate` 用远端保存的 `no_execute` 标志。最后**把 `sy-subrc = 2`（`already_exists`）当作成功**。

**为什么** — 重插 `d021t` 是因为原生屏文本表在已存在对象上不会被 FM 自动覆盖，不手动清就会残留旧文本（导出与导入的文本不一致）。重写 `dgen`/`tgen` 是因为这两字段在导出时被清空了（3.4 ⑤，为了 diff 干净），而 FM 要求它们非空。`suppress_exist_checks` 是因为导入场景下屏幕本来就可能存在（覆盖导入），不关掉会误报 `already_exists` 之外的错误。把 `sy-subrc = 2` 视为成功是**幂等性设计**：重复导入同一份数据不应该失败。

**风险与改进** — `DELETE FROM d021t ... ##SUBRC_OK` 与 `INSERT d021t ... ##SUBRC_OK` 都**忽略了返回码**：删除失败（文本未存在，正常）与插入失败（结构不匹配、锁冲突，异常）无法区分。插入失败意味着屏幕文本没写进去但对象结构已插入，产生"有结构无文本"的屏幕。建议至少对 `INSERT` 检查返回码。另外 `sy-subrc = 2` 被放行意味着"已存在的屏幕没被真正覆盖"也可能静默通过——在"本地屏幕已损坏、远端屏幕正常"的场景下，导入会报告成功但对象仍是坏的。这个放行是基于幂等性假设的合理取舍，但建议在注释中写明"已存在且内容不同的情况无法检测"。

#### ⑤ 屏幕激活入队与遗留屏幕删除

```abap
CONCATENATE ls_dynpro-header-program ls_dynpro-header-screen
  INTO lv_name RESPECTING BLANKS.
ASSERT NOT lv_name IS INITIAL.

zcl_abapgit_objects_activation=>add(
  iv_type = 'DYNP'
  iv_name = lv_name ).

ENDLOOP.

" Delete obsolete screens
LOOP AT lt_d020s_to_delete INTO ls_d020s.
  CALL FUNCTION 'RS_SCRP_DELETE'
    EXPORTING
      dynnr       = ls_d020s-dnum
      progname    = ms_item-obj_name
      with_popup  = abap_false
    EXCEPTIONS
      enqueued_by_user       = 1
      enqueue_system_failure = 2
      not_executed           = 3
      not_exists             = 4
      no_modify_permission   = 5
      popup_canceled         = 6.
  IF sy-subrc <> 0.
    zcx_abapgit_exception=>raise_t100( ).
  ENDIF.
ENDLOOP
```

**做什么** — 每个成功插入的屏幕，用"程序名 + 屏幕号"拼接成激活名（`RESPECTING BLANKS` 保留屏幕号前导空格），入队激活。整个循环结束后，遍历剩余待删除集合，逐个删除本地存在但远端已不存在的屏幕。

**为什么** — `RESPECTING BLANKS` 是关键细节：屏幕号是 `NUMC` 类型，`CONCATENATE` 默认会吃掉前导空格，而 SAP 内部标识屏幕时依赖这个带空格的形态，不保留会导致激活名不匹配。`with_popup = abap_false` 是批量删除必需。删除放在**插入循环结束之后**，避免"先删后插"在部分失败时留下无屏幕的程序。

**风险与改进** — `ASSERT NOT lv_name IS INITIAL` 又是导出/导入路径里为数不多的硬断言：若 `header-program` 与 `header-screen` 都为空（理论上不可能，但数据损坏时可能），直接 dump 整个导入。更严重的是 `RS_SCRP_DELETE` **任何非零返回码都抛异常**——包括 `enqueued_by_user`（被其他用户锁定）。这意味着**只要目标系统里有人正开着某个要删的屏幕，整个对象导入就失败**，且此时前面的屏幕已经插入成功了（不可回滚）。这就是 3.25 里那些锁预检方法存在的意义——预检是为了在导入前把这种情况挡掉。建议把"被锁定"这一码单独识别并给出可执行提示，而不是走通用 `raise_t100`。

---

### 3.21 方法 `uncondense_flow`（还原流逻辑缩进）

```abap
LOOP AT it_flow ASSIGNING <ls_flow>.
  APPEND INITIAL LINE TO rt_flow ASSIGNING <ls_output>.
  <ls_output>-line = <ls_flow>-line.

  READ TABLE it_spaces INDEX sy-tabix INTO lv_spaces.
  IF sy-subrc = 0.
    SHIFT <ls_output>-line RIGHT BY lv_spaces PLACES IN CHARACTER MODE.
  ENDIF.
ENDLOOP
```

**做什么** — 逐行遍历被压缩的流逻辑，按 `it_spaces`（一个整数表，与流逻辑行一一对应）中记录的偏移量把每行**右移**，还原原始缩进。

**为什么** — 流逻辑的缩进在旧版导出时被"压缩"了（去掉行首空格以减小 XML 体积），并另存一份"每行原始缩进量"的整数表。导入时按表还原。这是一个**无损压缩**方案：缩进量本身是数据，不是格式，所以可以分离存储。

**风险与改进** — `READ TABLE it_spaces INDEX sy-tabix` 用主键索引对齐两个表，若两表长度不一致，多出的流逻辑行会保持未缩进（`sy-subrc <> 0` 时不移动），造成导入的流逻辑缩进错误但**不报错**。建议在方法末尾加一行长度断言（`ASSERT lines( it_flow) = lines( it_spaces )`）以让长度错位立刻暴露。此外如 3.20 ② 所述，这个方法本身已被标注为兼容用，未来移除时是整段可删的负债。

---

### 3.22 方法 `deserialize_varis`（选择变式的差异同步）

#### ① 建立本地基线

```abap
lt_local_varis = get_varis_for_report( iv_program_name ).

ls_varikey-report = iv_program_name.
```

**做什么** — 取本地现有的系统独立变式清单作为基线；`ls_varikey-report` 只设置一次，循环内复用。

**为什么** — 与屏幕导入同一套差异集合思路：先拿本地现状，逐条与远端比对，剩下的就是要删的。

**风险与改进** — 无。这是标准的起手式。

#### ② 逐远端变式重建

```abap
LOOP AT it_varis ASSIGNING <ls_vari>.
  CLEAR: lt_vari_text, ls_varid, lv_recreate, lv_was_protected, lv_exists_locally.

  ls_varikey-variant = <ls_vari>-variant.

  DELETE lt_local_varis WHERE variant = <ls_vari>-variant.
  lv_exists_locally = boolc( sy-subrc = 0 ).

  lv_was_protected = set_vari_protection( is_vari    = ls_varikey
                                          iv_protect = abap_false ).

  TRY.
      IF lv_exists_locally = abap_true.
        delete_vari( ls_varikey ).
      ENDIF.

      MOVE-CORRESPONDING <ls_vari> TO ls_varid.
      ls_varid-mandt  = c_sysvari_clnt.
      ls_varid-report = iv_program_name.

      " Assemble text table
      LOOP AT <ls_vari>-texts ASSIGNING <ls_vari_text_remote>.
        ls_vari_text_create-mandt   = c_sysvari_clnt.
        ls_vari_text_create-report  = iv_program_name
        ls_vari_text_create-variant = <ls_vari>-variant.
        ls_vari_text_create-langu   = <ls_vari_text_remote>-langu.
        ls_vari_text_create-vtext   = <ls_vari_text_remote>-vtext.
        INSERT ls_vari_text_create INTO TABLE lt_vari_text.
      ENDLOOP.

      create_vari( is_varid   = ls_varid
                   it_values  = <ls_vari>-values
                   it_texts   = lt_vari_text
                   it_screens = <ls_vari>-variscreens
                   it_objects = <ls_vari>-objects ).

      set_vari_protection( is_vari    = ls_varikey
                           iv_protect = ls_varid-protected ).

    CLEANUP.
      set_vari_protection( is_vari    = ls_varikey
                           iv_protect = lv_was_protected ).
  ENDTRY.
ENDLOOP.
```

**做什么** — 对每个远端变式：先记录它是否在本地存在，然后**暂解保护 → 若本地存在则先删除 → 重建 varid（客户端强制为 `000`、报表名为当前程序）→ 组装多语言文本表 → 创建变式 → 恢复应有保护**。整个"删+建"包在 `TRY...CLEANUP` 里，失败时 `CLEANUP` 把保护状态还原成进入前的值。

**为什么** — SAP 的受保护变式不允许被程序修改，所以任何写操作前必须临时解除保护，写完再恢复。用 `CLEANUP` 而非手动在成功/失败两条路径都调用恢复，是**确保"无论如何都恢复保护"的唯一可靠写法**——变式保护是安全属性，导入失败却留下"保护被永久解除"的变式是最糟糕的失败模式。`mandt = c_sysvari_clnt`（`000`）与 `report = iv_program_name` 是必要的覆写：XML 里存的客户端/报表名不能直接采信，必须以目标系统为准，否则变式会被写到错误的客户端。

**风险与改进** — `CLEANUP` 里**没有 `TRY`** 包裹恢复调用，意味着若恢复保护本身抛异常，会覆盖掉原始的导入异常，操作者看到的是"恢复保护失败"而不是"变式创建失败"。这是 `CLEANUP` 的固有局限，建议把恢复逻辑也包一层 `TRY` 并吞掉其异常（恢复失败时无法做的更好，但至少不掩盖原始错误）。另外 `lv_recreate` 变量被声明并每次 `CLEAR`，但**方法体中从未使用**，属死变量。

#### ③ 清理本地多余变式

```abap
" remaining variants have been deleted on remote
" => delete
LOOP AT lt_local_varis INTO ls_varikey.
  CLEAR lv_was_protected.

  lv_was_protected = set_vari_protection( is_vari    = ls_varikey
                                          iv_protect = abap_false ).

  TRY.
      delete_vari( ls_varikey ).
    CLEANUP.
      set_vari_protection( is_vari    = ls_varikey
                           iv_protect = lv_was_protected ).
  ENDTRY.
ENDLOOP
```

**做什么** — 遍历差异集合的剩余项（本地有、远端没有），逐个暂解保护并删除，`CLEANUP` 恢复保护。

**为什么** — 这就是差异同步的第二半：远端删掉的变式，本地也要删。用"逐条删除"而非"整体清空"，是为了保留那些**不在 `SAP&*`/`CUS&*` 命名范围内**的变式（个人变式、其他系统级变式）不被误删。

**风险与改进** — 与 ② 相同的 `CLEANUP` 无保护问题。另外这里**没有检查 `delete_vari` 之后的返回状态**（`delete_vari` 内部对非零返回码抛异常，所以实际上是被 `TRY` 接住的），路径是通的，但依赖子方法的异常约定而非返回码检查，属隐式耦合。

---

### 3.23 方法 `create_vari`（变式创建）

```abap
CALL FUNCTION 'RS_CREATE_VARIANT_255'
  EXPORTING
    curr_report   = is_varid-report
    curr_variant  = is_varid-variant
    vari_desc     = is_varid
  TABLES
    vari_contents = it_values
    vari_text     = it_texts
    vscreens      = it_screens
  EXCEPTIONS
    variant_exists = 0
    OTHERS         = 1.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.

CALL FUNCTION 'RS_CHANGE_CREATED_VARIANT_255'
  EXPORTING
    curr_report   = is_varid-report
    curr_variant  = is_varid-variant
    vari_desc     = is_varid
  TABLES
    vari_contents = it_values
    vari_text     = it_texts
    objects       = it_objects
  EXCEPTIONS
    OTHERS        = 1.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.
```

**做什么** — 分两步：先调 `RS_CREATE_VARIANT_255` 创建变式（不含对象清单），再调 `RS_CHANGE_CREATED_VARIANT_255` 补充对象清单（`objects`）。两步都用同一份 `vari_contents` 与 `vari_text`。

**为什么** — `RS_CREATE_VARIANT_255` 的表格形参**不支持 `objects`**（创建 FM 与修改 FM 的形参集不同），所以必须"创建后立刻修改一次"来补上对象清单。第一步把 `variant_exists = 0` 声明为成功码，是因为调用方已在 3.22 ② 里保证变式已被删除，若还报"已存在"说明删除没生效。

**风险与改进** — 两步之间不是事务的：若创建成功而修改失败，会留下一个**没有对象清单的半变式**。调用方（3.22）的 `TRY` 会捕获异常，但此时"已删除旧变式 + 已创建空变式"的状态无法回滚，下次导入会看到"本地已存在该变式"并再次删除重建，属于自愈路径但会留下一次失败。建议在异常消息里带上"变式已部分创建，请手动删除后重试"的指引。另外这里 `sy-subrc = 0` 时（`variant_exists`）被当作成功——与 `RPY_DYNPRO_INSERT` 的"已存在即成功"是同一幂等性思路，一致性好。

---

### 3.24 方法 `delete_vari`（变式删除）

```abap
TRY.
    CALL FUNCTION 'RS_VARIANT_DELETE'
      EXPORTING
        report                = is_vari-report
        variant               = is_vari-variant
        flag_confirmscreen    = abap_true " true = No confirm screen
        " suppress parameters do not exist in older releases
        suppress_message      = abap_true
        suppress_input_dialog = abap_true
      EXCEPTIONS
        OTHERS                = 1 ##FM_SUBRC_OK.
  CATCH cx_sy_dyn_call_param_not_found.
    CALL FUNCTION 'RS_VARIANT_DELETE'
      EXPORTING
        report             = is_vari-report
        variant            = is_vari-variant
        flag_confirmscreen = abap_true " true = No confirm screen
      EXCEPTIONS
        OTHERS             = 1 ##FM_SUBRC_OK.
ENDTRY.
IF sy-subrc <> 0.
  zcx_abapgit_exception=>raise_t100( ).
ENDIF.
```

**做什么** — 调用 `RS_VARIANT_DELETE` 删除变式，带两个"抑制弹窗"形参；若低版本没有这两个形参（`cx_sy_dyn_call_param_not_found`），降级为只带 `flag_confirmscreen` 再试一次。

**为什么** — 同 3.15 ② 的版本降级模式：`suppress_message`/`suppress_input_dialog` 是新版本才有的形参，用于彻底静默删除（连消息都抑制），老版本只能做到"不弹确认框"。

**风险与改进** — 与 `insert_program` 完全同构的降级重试，是第三处重复。另外 `flag_confirmscreen = abap_true` 的注释写的是"true = No confirm screen"，这个语义反直觉（true 表示"不确认"而非"要确认"），值得在注释中点明这是 SAP 的反向命名，避免后来者误改成 `abap_false`。

---

### 3.25 方法 `set_vari_protection`（变式保护的暂解/恢复）

```abap
SELECT SINGLE FOR UPDATE protected
  FROM varid CLIENT SPECIFIED
  INTO rv_was_protected
  WHERE mandt   = c_sysvari_clnt
    AND report  = is_vari-report
    AND variant = is_vari-variant
    AND flag1   = space
    AND flag2   = space.

IF sy-subrc <> 0 OR rv_was_protected = iv_protect.
  RETURN.
ENDIF.

UPDATE varid CLIENT SPECIFIED
  SET protected = iv_protect
  WHERE mandt   = c_sysvari_clnt
    AND report  = is_vari-report
    AND variant = is_vari-variant
    AND flag1   = space
    AND flag2   = space.
```

**做什么** — 用 `SELECT SINGLE FOR UPDATE` 读出变式的当前保护标志并**行级加锁**；若行不存在（不是系统独立变式）或当前值已等于目标值，直接返回不做更新；否则 `UPDATE` 改保护标志。返回原值供调用方在 `CLEANUP` 里恢复。

**为什么** — `FOR UPDATE` 是关键：变式保护是并发敏感状态，两个导入进程同时"暂解 → 重建 → 恢复"会互相覆盖对方的保护状态。加行锁把这段窗口串行化。`flag1 = space AND flag2 = space` 是 SAP 用来标记"该变式未被传输/未激活"的条件，只有满足这个条件的行才是可被 abapGit 管理的变式——避免误改正在传输中的变式。返回值而非状态码，是为了让调用方能精确恢复原状。

**风险与改进** — `SELECT FOR UPDATE` 在 `READ COMMITTED`（SAP 默认隔离级别）下**锁在 UPDATE 执行时释放**，因此锁只保护了 SELECT 到 UPDATE 之间的窄窗口，并不能覆盖整个"暂解 → 删除/创建 → 恢复"的大流程。也就是说，两个导入进程的暂解动作会被串行化，但它们的重建动作可能交错——A 暂解后 B 才能暂解，A 恢复后 B 才恢复，中间 A 的重建与 B 的重建若作用于同一变式就会冲突。当前代码靠"每个变式独立处理"降低了这种概率，但并未真正互斥。若要严谨，需要在外层用应用级锁（`ENQUEUE`）包住整个变式重建流程。另外本方法对 `UPDATE` 的返回码没有检查：若 UPDATE 影响 0 行（行在 SELECT 后被并发删掉），方法静默返回，调用方会以为保护已被暂解。建议加 `IF sy-dbcnt = 0` 的判断并抛异常。

---

### 3.26 方法 `is_any_dynpro_locked` / `is_cua_locked` / `is_text_locked`（导入前锁预检）

```abap
" is_any_dynpro_locked
lt_dynpros = serialize_dynpros( iv_program ).
LOOP AT lt_dynpros ASSIGNING <ls_dynpro>.
  lv_object = |{ <ls_dynpro>-header-screen }{ <ls_dynpro>-header-program }|.
  IF exists_a_lock_entry_for( iv_lock_object = 'ESCRP'
                              iv_argument    = lv_object ) = abap_true.
    rv_is_any_dynpro_locked = abap_true.
    EXIT.
  ENDIF.
ENDLOOP.

" is_cua_locked
lv_object = |CU{ iv_program }|.
OVERLAY lv_object WITH '                                          '.
lv_object = lv_object && '*'.
rv_is_cua_locked = exists_a_lock_entry_for( iv_lock_object = 'ESCUAPAINT'
                                            iv_argument    = lv_object ).

" is_text_locked
lv_object = |*{ iv_program }|.
rv_is_text_locked = exists_a_lock_entry_for( iv_lock_object = 'EABAPTEXTE'
                                             iv_argument    = lv_object ).
```

**做什么** — 三个方法分别在导入前检查屏幕、命令区域、文本池是否被他人锁定，作为导入的**前置守卫**。屏幕是逐个屏幕号检查（锁对象 `ESCRP`，参数为"屏幕号 + 程序名"）；命令区域用 `CU` + 程序名 + 星号通配（锁对象 `ESCUAPAINT`）；文本池用星号 + 程序名（锁对象 `EABAPTEXTE`）。任一被锁定即返回真，调用方应中止导入并提示用户。

**为什么** — 3.20 ⑤ 已经说明：删除屏幕遇到 `enqueued_by_user` 会让整个导入失败，且此时部分屏幕已写入，不可回滚。与其让导入在跑到一半时失败，不如**在开始前就把锁冲突挡掉**，给用户一个明确的"请等那个人关掉"的提示。这是"尽早失败 + 可操作提示"的工程实践，比依赖 SAP 的模糊错误码好得多。

**风险与改进** —
- `is_any_dynpro_locked` **调用 `serialize_dynpros` 做锁检查**，代价等于一次完整导出（读全量屏幕、清洗字段、外置流逻辑）。锁检查只需用 `RS_SCREEN_LIST` 拿屏幕号清单即可，用全量序列化是明显的过度实现。**建议改成只取屏幕清单**。
- `is_cua_locked` 里的 `OVERLAY lv_object WITH '                                          '` 用一串硬编码空格把对象参数 pad 到固定长度再加通配星号——`eqegraarg` 的固定长度决定了这个 pad 长度，但 42 个空格没有任何注释说明来源，是**典型的魔术字面量**，一次 `eqegraarg` 长度调整就会静默失效。建议用 `REPEAT` 或按目标长度计算（如 `lv_object && |{ space_replicate( length ) }|`）。
- `is_text_locked` 用 `*` + 程序名做通配，含义是"该程序及所有包含的文本锁"，这个通配方向的语义没有注释，读者容易误解为"以程序名结尾的对象"。

---

## 四、执行流程全景图（数据视角）

```mermaid
sequenceDiagram
    participant ORC as 父类编排器
    participant SER as serialize_program
    participant FMD as 屏幕FM
    participant FMC as 命令区域FM
    participant FMT as 文本池操作
    participant FMV as 变式FM
    participant DES as deserialize_program
    participant ACT as 激活队列

    Note over ORC,SER: 导出阶段
    ORC->>SER: 触发序列化
    SER->>SER: 切换语言上下文
    SER->>FMD: RPY_PROGRAM_READ 取源码与文本池
    FMD-->>SER: source_extended + textelements
    SER->>SER: 探测非活动态并覆写活动态源码
    SER->>FMD: RS_SCREEN_LIST + RPY_DYNPRO_READ 逐屏读取
    FMD-->>SER: 屏幕结构与内部字段表
    SER-->>ORC: XML(PROGDIR/DYNPROS/CUA/VARIS/TPOOL) + screen_XXXX.abap
    SER-->>ORC: 去生成头后的源码 .abap

    Note over ORC,ACT: 导入阶段
    ORC->>DES: 触发反序列化
    DES->>DES: CTS 登记 ABAP 对象
    DES->>FMC: RPY_INCLUDE_UPDATE 或 RPY_PROGRAM_INSERT
    DES->>ACT: 入队 REPS
    ORC->>FMD: RS_SCREEN_LIST 取本地基线
    ORC->>FMD: RPY_DYNPRO_INSERT 逐屏写入并删除遗留屏幕
    ORC->>ACT: 入队 DYNP
    ORC->>FMC: RS_CUA_INTERNAL_WRITE 写 CUAD
    ORC->>ACT: 入队 CUAD
    ORC->>FMT: INSERT 或 DELETE TEXTPOOL
    ORC->>ACT: 入队 REPT 主语言非活动态时
    ORC->>FMV: 差异同步变式 删除本地多余并重建远端变式
    Note over ACT: 统一激活 REPS REPT CUAD DYNP
```

---

## 五、问题清单与改进建议（按优先级）

### 🔴 P0 业务正确性

**1. `deserialize_cua` 里 `sy-tcode = 'SE41'` 属会话级全局污染且从不恢复**（方法 `deserialize_cua`）
这是全类唯一手工改写会话级全局变量的地方。它不仅服务当前 FM 调用，还会被同一次导入请求里后续的屏幕写入、变式创建、文本池激活等所有 FM 看到。修复一个 SAP bug 的手段本身可能成为下一个 bug 的来源。**改进**：记录原值并在方法末尾恢复；给这行加"适用版本范围 + Note 追踪"注释；中期方案是改为直接写 CUA 底表，彻底摆脱对 `sy-tcode` 的依赖。

**2. `deserialize_cua` 的全空短路不检查 `adm`，与 `auto_correct_cua_adm` 的修复意图冲突**（方法 `deserialize_cua`、`auto_correct_cua_adm`）
短路条件只看 11 张明细表，不看 ADM。而 issue #1807 的旧数据恰恰是"ADM 缺失、明细表完整"——但反过来，若某数据的形态是"ADM 有值、明细表全空"，`auto_correct_cua_adm` 补出来的 ADM 会被这个 `RETURN` 直接挡掉，永远写不回去。**改进**：把 `is_cua-adm IS INITIAL` 纳入短路条件。

### 🟠 P1 健壮性

**3. `serialize_program` 的空捕获会吞掉非"版本不存在"类的真实错误**（方法 `serialize_program`）
`##NO_HANDLER` 假设"抛异常 ⟺ 非活动版本不存在"，但读 PROGDIR 也可能因锁、TADIR 缺失、包不存在而抛同类异常。结果是一份元数据与源码不同步的 XML 被静默导出。**改进**：捕获后检查异常子码或消息，只对"对象不存在"放行。

**4. `deserialize_program` 不检查 `insert_transport_object` 的返回状态**（方法 `deserialize_program`）
CTS 登记失败（对象已在另一请求中、请求已释放）后写入照常进行，产生"改了但没被登记"的对象。**改进**：检查返回状态并在失败时中止。

**5. 屏幕写入与删除路径的返回码检查缺失**（方法 `deserialize_dynpros`）
`DELETE FROM d021t ##SUBRC_OK` 与 `INSERT d021t ##SUBRC_OK` 都忽略返回码，插入失败会产生"有结构无文本"的屏幕；`RS_SCRP_DELETE` 的任何非零返回码（含 `enqueued_by_user`）都走通用 `raise_t100`，而此时代价是不可回滚的部分成功状态。**改进**：对 `INSERT d021t` 检查返回码；对 `enqueued_by_user` 单独识别并给出可操作提示（"请关闭占用该屏幕的会话后重试"）。

**6. `deserialize_textpool` 对 `DELETE TEXTPOOL` 与"空插入"分支无返回码检查**（方法 `deserialize_textpool`）
插入空文本池这个反直觉手法一旦失败，方法静默结束，对象处于"该有文本池却没有"的状态。**改进**：两个分支都补返回码检查。

**7. `ASSIGN ('(SAPLSIFP)TTAB')` 的失败路径静默跳过清理**（方法 `get_program_title`）
前提失效时（include 未加载、变量名漂移、表不存在）bug 原样复现且无任何告警。**改进**：至少记录调试输出表明清理未生效；加注释标注该 workaround 依赖的 SAP bug/Note 编号以便追踪与后续移除。

**8. 二分查找与 `sy-tabix` 的时序耦合**（方法 `deserialize_dynpros`）
`DELETE lt_d020s_to_delete INDEX sy-tabix` 依赖"紧接在 `BINARY SEARCH` 之后的 `sy-tabix`"，任何插入的中间语句都会破坏它；而"已排序"这一前提又只在上方 20 行之外。建议改用 `DELETE ... WHERE dnum = ...` 直接表达意图，并同时消除对排序前提的隐式依赖。

### 🟡 P2 性能与规范

**9. 锁预检代价过高**（方法 `is_any_dynpro_locked`）
为查锁而完整执行 `serialize_dynpros`（读全量屏幕、清洗字段、外置流逻辑），代价等于一次导出。锁检查只需要屏幕号清单。**改进**：改用 `RS_SCREEN_LIST` 取清单。

**10. `get_vari_data` 里一次完整的变式值读取被完全丢弃**（方法 `get_vari_data`）
`RS_VARIANT_VALUES_TECH_DAT_255` 的 `variant_values` 形参非可选，被迫传入再清空。在大变式数程序上是可测量开销。属 FM 设计限制，无解，但值得记录在性能评估中。

**11. `cx_sy_dyn_call_param_not_found` 降级重试模式重复三处**（方法 `insert_program`、`delete_vari` 等）
每次完整复制 FM 调用，任何修正需同步三处。**改进**：提成工具方法或在注释中交叉引用。

**12. `eqegraarg` 的 pad 长度与 TEXTPOOL 的偏移量 8 都是无来源说明的魔术字面量**（方法 `is_cua_locked`、`add_tpool`、`read_tpool`）
`OVERLAY ... WITH '                                          '`（42 空格）与 `entry+8` 分别依赖 `eqegraarg` 的固定长度与 `TEXTPOOL-SPLIT` 的 `CHAR8` 长度，两处都没有注释说明来源，一次结构调整就会静默失效（且导出导入同时失效，往返自洽地"看起来没问题"）。**改进**：提成常量并注释来源字段。

**13. `ASSERT` 与 `IF/RETURN` 风格混用**（方法 `strip_generation_comments`、`deserialize_dynpros`）
`strip_generation_comments` 里情形 1 用柔和的 `IF ... RETURN`，情形 2 却用 `ASSERT`；`deserialize_dynpros` 里 `ASSERT NOT lv_name IS INITIAL` 在数据损坏时会直接 dump 整个导入。导出/导入路径的基调应是"容错优先"。**改进**：统一为 `IF NOT ( ... ) RETURN.` 形态。

**14. "这是不是特殊程序"的判定分散在三处且口径不同**（方法 `deserialize_program`、`deserialize_textpool`、`is_exit_include`、`update_program`）
`SUBC = '1'/'M'`、`CP 'LX*'/'SAPLX*'`、`NP 'SAPLX*'` 三套规则并存，维护者需同时记住三者。**改进**：收敛成一个"程序角色判定"方法，各处统一调用。

**15. 局部变量用底表字段类型而非语义类型**（方法 `deserialize_program`、`deserialize_exit_include`）
`DATA lv_progname TYPE reposrc-progname`、`lv_title TYPE rglif-title` 可读性差，且语义上就是 `syrepid` 与 `repti`。**改进**：改为语义类型，便于 IDE 提示与跨模块理解。

**16. 语言上下文的还原靠人肉重复而非 `CLEANUP`**（方法 `serialize_program`、`update_program`）
三处 `restore_login_language` 是手写的，当前没有异常抛出点所以安全，但一旦中间加代码就必然泄漏。**改进**：改成 `TRY..CLEANUP` 结构保证还原。

### 🟢 P3 可扩展性

**17. `uncondense_flow` 是标注了"宽限期后移除"的兼容负债**（方法 `deserialize_dynpros`、`uncondense_flow`）
`#3680` 的 TODO 没有目标移除版本/里程碑，这类兼容分支极易永久留存。**改进**：标注移除目标版本，并在下次大版本升级时删除整段（含 `ty_dynpro-spaces` 字段）。

**18. 导出侧"清洗"与导入侧"修复"成对出现但无映射表**（方法 `serialize_dynpros` 与 `deserialize_dynpros`）
四处成对规则（`OUTPUTSTYLE` 清空 ↔ 无、`foreignkey` 重算 ↔ 填 `'/'`、`text` 清空 ↔ `modific = 'X'`、容器 min 清空 ↔ 无）分散在两处循环中，新增一条时极易漏掉对称侧。建议增加一处集中注释或表格，列出"导出侧动作 ↔ 导入侧动作"的完整对应关系。

**19. `MOVE-CORRESPONDING` 承担字段语义映射**（方法 `serialize_varis`、`deserialize_varis`）
`MOVE-CORRESPONDING ls_varid TO ls_vari` 与 `MOVE-CORRESPONDING <ls_vari> TO ls_varid` 靠同名自动对齐，字段改名或新增同名不同义字段时会静默错配。**改进**：改显式赋值并注释"仅搬运技术字段"。

**20. `deserialize_exit_include` 用 `c_state-off` 表达"写活动态"，语义依赖 FM 对空值的隐含解释**（方法 `deserialize_exit_include`）
空字符串作为状态值是"三态枚举漏文档化"的典型隐患。**改进**：在注释中明确写出"空值在此 FM 中等价于直接保存活动态"，或改用显式参数表达意图。

**21. `deserialize_varis` 中的死变量与 `is_exit_include` 的疑似冗余分支**（方法 `deserialize_varis`、`is_exit_include`）
`lv_recreate` 被声明并每次 `CLEAR` 但从未使用；`is_exit_include` 里的 `iv_program+1 CP '/LX*'` 与前面的 `CP 'LX*'` 覆盖范围关系不明确（`CP` 是通配匹配而非前缀比较，`'LX*'` 已能匹配 `'LXFOO'`，而 `iv_program+1 CP '/LX*'` 匹配的是"首字符后紧跟 /LX 开头"的形态）。建议核对后删除死变量，并给 `+1` 分支补一条说明它覆盖的具体命名形态。

---

## 六、整体评价与启发

**优点**

- **差异消除（diff hygiene）意识极强**。这是这份代码最可贵的东西：清 `UCCHECK`、清 `OUTPUTSTYLE` 空格、清 `dgen`/`tgen` 生成时间、清空标题的空壳条目、剥离函数组生成日期、清容器最小尺寸、清空 `from_dict` 字段的派生文本……几乎每一个"存储层有值但语义层无意义"的字段都被识别并处理了。没有这套意识，abapGit 的 Git diff 会全是噪音，工具就失去了存在价值。
- **双向对称的设计思维**。导出侧清洗与导入侧修复成对出现（`'/'` force off 是最精彩的例子：空串在导出侧是"干净"，在导入侧必须变成 `'/'` 才干净），说明作者理解"序列化"不是单向映射而是一个需要往返自洽的协议。
- **对 SAP 标准 FM 缺陷的处理方式诚实且可追踪**。`SAPLSIFP` 的 `TTAB` bug、`RS_CUA_INTERNAL_WRITE` 的 `sy-tcode` 依赖、`RPY_PROGRAM_READ` 不返回活动源码、`RS_VARIANT_VALUES_TECH_DAT_255` 的非可选形参——每一个都有注释说明原因，甚至标注了 issue 编号与 SAP Note 号。作者用 `evil hack` 自我标注那种最脆弱的代码，这种坦诚比掩盖更有价值。
- **失败模式设计到位**。导入前锁预检（尽早失败 + 可操作提示）、`EU510`/`EU522` 翻译成人话、变式保护的 `CLEANUP` 必恢复、`name_not_allowed` 时保留活动态版本以便排错、所有写入先落非活动态再统一激活——这些都是从真实事故里长出来的设计。

**短板**

- **全局环境状态被当作参数传递**（`sy-tcode = 'SE41'` 从不恢复），这是全类唯一的会话级泄漏点，也是最高优先级问题。
- **隐式耦合密集**：`BINARY SEARCH` 依赖 20 行外的 `SORT`、`DELETE INDEX sy-tabix` 依赖紧邻的上一次查找、`uncondense_flow` 依赖两个表长度相等、`OVERLAY` 的 pad 长度依赖 `eqegraarg` 的编译期长度。每一处单看都正确，但都不自解释，重构时极易被踩断。
- **降级重试与"忽略返回码"两个模式的复用程度不足**。`cx_sy_dyn_call_param_not_found` 降级出现三处，`##SUBRC_OK`/`##FM_SUBRC_OK` 抑制警告出现多处，都是"能抽出来却复制粘贴"的形态。

**可学到的设计经验**

1. **"清洗导出 + 修复导入"是应对不完美存储层的通用解法**。当上游存储把语义信息编码成噪音（空值填空格、生成时间戳、派生字段副本）时，不要在读取时容错，而在写出时清洗、读入时修复——两阶段各自的规则可以很简单，因为每阶段只面对一个问题。
2. **对 FM 返回的"看似有效"字段要保持怀疑，必要时用内部标志位重算**。`FOREIGNKEY` 就是典型：FM 给的值不可信，真正依据在 `d021s` 的位掩码里。这个思路可以推广到任何"存储值 ≠ 语义值"的字段。
3. **版本兼容用"先试完整版、失败则降级重试"比"维护版本清单分支"更稳**。代价是一次失败的动态调用，收益是不用跟踪 release 矩阵，且未来新增形参时行为自动正确。
4. **对不可回滚的多步写入，用"全部写非活动态 + 统一入队激活"来收窄爆炸半径**。ABAP 无法在跨 FM 写入上做事务回滚，那么就把"不可回滚"的范围压到最小——只让最后一次激活成为真正的状态提交点。这个模式在涉及多张底表、无法用事务保护的对象写入场景里普遍适用。

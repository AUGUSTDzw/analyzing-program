# ZABAPGIT_PASSWORD_DIALOG 源码分析报告

> 分析对象：`abapGit__abapGit__zabapgit_password_dialog.prog.abap`（MIT 开源项目 abapGit）
> 程序类型：**Include（被上层程序 `INCLUDE` 的对话框子程序）**，不是可独立执行的报表。
> 核心机制：动态选择屏 `1002` + PBO/PAI 回调注入 + 一个局部类作为状态机。
> 说明：本文件**不含任何 ALV**（无 `CL_GUI_ALV_GRID`、无 `FIELD-SYMBOL`、无 grid 事件回调），
> 它是一套纯 `CALL SELECTION-SCREEN` 的模态密码输入框实现。以下分析严格以源码实际内容为准。

---

## 一、程序定位与业务背景

### 1.1 它要解决什么问题

abapGit 的核心业务是把远端 Git 仓库的代码同步进 SAP（clone / pull / fetch）。绝大多数 Git 托管平台走 HTTPS + 认证，于是必然有一个绕不开的问题：

**"请提供这个仓库的账号与密码（或 Access Token）"**

而这句话必须在一个非常受限的环境里问出来：

- 它运行在 SAPGUI 批处理式的经典屏幕里，没有浏览器、没有 JS、不能弹 HTML 输入框；
- 它必须支持多仓库 —— 用户一次会话里可能先后要访问 `github.com`、内网 `gitlab.corp`、Azure DevOps，绝不能把上一家仓库的凭据悄悄复用给下一家；
- 它必须做到**密码永不明文显示、永不落日志、永不进消息文本**（SAP 里 `MESSAGE` 和 `POPUP` 的内容都可能进 `S_ALT` 审计或被中间件抓取）。

### 1.2 为什么不能直接用现成的对话框

| 候选方案 | 卡在哪里 |
|---------|---------|
| `POPUP_GET_VALUES` / `POPUP` | 是消息弹窗而非输入控件，密码会作为消息文本出现；不能做密码掩码；不能逐字段校验 |
| 自己画 Screen Painter 屏幕 | 要自己实现焦点、Tab 顺序、F4、`sy-ucomm` 分发、屏幕重绘、`MESSAGE E` 后重入 PBO —— 几十行纯 UI 胶水代码，且几乎没人愿意长期维护 |
| `CALL TRANSFORMATION` 到 HTML 页 | 走的是 Web 服务器链路，会引入浏览器弹窗被拦截、HTTP 调试代理抓包（凭据裸奔）等风险，与密码场景直接冲突 |
| 让用户把 Token 写进配置表 | 密码落在数据库明文，abapGit 全项目的红线就是不做这件事 |

### 1.3 它的设计范式（一句话定性）

**用 SAP 内核免费提供的"动态选择屏 = 模态对话框"机制，把交互层整体外包，只在 PBO/PAI 回调里做差异化注入（置灰、密码隐藏、状态栏、光标、校验），对外只暴露一个 `popup` 静态方法。**

这是一个非常典型的 **"薄壳 + 策略回调"** 设计：屏幕的"骨架"由 `SELECTION-SCREEN` 声明式地给出，"行为"由三个回调方法注入，"状态"由一个 `CLASS-DATA` 布尔量承载。整份代码只回答两个问题：**用户在对话框里按了什么**，以及**用户到底确认还是取消**。

### 1.4 业务边界（它不做什么）

值得强调的是这个组件的克制：它不鉴权、不保存凭据、不重试、不做 URL 合法性校验的完整语义。它只负责"问一次 + 判断确认与否"。凭据的落盘由 abapGit 的 persistence/secret 层负责，失败处理由调用方负责。这种"每层只做一件事"的边界感，是这个文件最值得学的地方。

---

## 二、程序执行流程总览

```mermaid
flowchart TD
  A["上层程序调用 FORM password_popup：传入仓库 URL 与凭据引用"] --> B["类方法 popup：复位全局参数、清空旧密码、登记仓库 URL"]
  B --> C["类方法 enrich_title_by_hostname：正则抽主机名写入 sc_title"]
  C --> D["类方法 popup 计算中心坐标并 CALL SELECTION-SCREEN 1002：进入模态对话框"]
  D --> E["方法 on_screen_init：PBO 初始化阶段写入屏幕注释文本与标题"]
  E --> F["方法 on_screen_output：每次 PBO 置灰 URL 与提示、隐藏密码、设 DETL 状态栏、设光标"]
  F --> G["方法 on_screen_event：PAI 收到 sy-ucomm 分派 Enter / F1 / 其他"]
  G -->|"校验失败 MESSAGE E，对话框保持打开"| F
  G -->|"用户确认 gv_confirm 置真"| H["方法 on_screen_event 执行 LEAVE TO SCREEN 0"]
  G -->|"其他动作 gv_confirm 置假"| H
  H --> I["方法 popup 收尾：确认则回填 cv_user 与 cv_pass，取消则清空二者，再清空全局参数"]
  I --> J["返回 FORM password_popup，再返回上层程序"]
```

**做什么** — 一条从"外部调用"到"拿到凭据"的完整闭环：预填 → 加标题 → 动态屏进入 → PBO 布置界面 → PAI 收用户动作 → 依据确认标志回填或清空 → 清空痕迹。
**为什么** — 这张图刻意画出了 `MESSAGE E` 之后回到 `on_screen_output` 的那条回边：**错误校验不是"退出循环"，而是"重画一次屏幕"**。这是理解整个对话框能"留在原地让用户改正"的关键。
**风险与改进** — 图中 `on_screen_init` / `on_screen_output` / `on_screen_event` 三个节点是虚线依赖：**驱动它们的 PBO/PAI 分发代码不在本 include 内**（见 3.2 与 P0 问题），因此流程图的前半段可静态确认，后半段依赖框架契约，图上没有体现这个断裂点。

### 责任链表（按执行先后）

| 子程序 | 调用者 | 职责 |
|--------|--------|------|
| 全局声明区 `选择屏 1002` 定义 | 编译器（屏幕生成器） | 声明对话框的字段集合、行布局与注释文本变量 |
| 全局声明区 `类 lcl_password_dialog 定义段` | 编译器 | 声明对外契约、屏幕号常量、静态确认标志 |
| `FORM password_popup` | 上层程序（abapGit 的 UI/仓库对象逻辑） | 对外门面：把仓库 URL 传入、把凭据引用传出 |
| 方法 `popup` | `FORM password_popup` | 预填与复位、注入标题、定位并调用动态屏、收尾回填或清空 |
| 方法 `enrich_title_by_hostname` | `popup` | 从仓库 URL 中抽出主机名并写入窗口标题 |
| 方法 `on_screen_init` | GUI 框架的屏幕初始化阶段（本 include 内无驱动） | 写入 `sc_title` 与四个注释文本 `sc_url/sc_user/sc_pass/sc_cmnt` |
| 方法 `on_screen_output` | GUI 框架的 PBO（每次重绘，含报错后重绘） | 置灰 URL 与提示字段、隐藏密码、设状态栏、按需设光标 |
| 方法 `on_screen_event` | GUI 框架的 PAI（每次用户动作） | 分派 Enter 校验确认 / F1 打开帮助 / 其他动作视为取消 |
| 全局声明区 `类 lcl_password_dialog 实现段` | 编译器 | 局部类的作用域声明，保证不泄漏到上层程序命名空间 |

下面按这条流程，逐个子程序展开。

---

## 三、分组分析（按程序流程 / 子程序）

### 3.1 全局声明区 `选择屏 1002 定义`

这一步分四步：① 屏幕骨架与行布局 ② 仓库 URL 与用户名参数 ③ 密码参数 ④ 提示参数。

#### ① 屏幕骨架与行布局

```abap
SELECTION-SCREEN BEGIN OF SCREEN 1002 TITLE sc_title.
SELECTION-SCREEN SKIP.
SELECTION-SCREEN BEGIN OF LINE.
SELECTION-SCREEN COMMENT 1(18) sc_url FOR FIELD p_url.
PARAMETERS: p_url TYPE string LOWER CASE VISIBLE LENGTH 60 ##SEL_WRONG.
SELECTION-SCREEN END OF LINE.
SELECTION-SCREEN SKIP.
```

**做什么** — 声明屏幕 `1002`，标题取自文本变量 `sc_title`；用 `BEGIN OF LINE` / `END OF LINE` 把注释与输入框锁在同一行，用 `SKIP` 插入空行做视觉分组，最后把 `P_URL` 这一行（标签占第 1–18 列 + 60 字符宽的输入框）钉在屏幕上。

**为什么** — 这是整套设计的地基。选择屏是 SAP 自带的标准屏幕类型：它**免费提供**了模态语义（`CALL SELECTION-SCREEN` 后原程序被挂起，直到动态屏退出）、`PBO`/`PAI` 触发、`sy-ucomm` 分发、`MESSAGE E` 后自动重绘、Tab 键顺序与 `SET CURSOR`。用声明式语法把这些"白送的能力"拿来当对话框，比自己用 `WRITE` + `AT USER-COMMAND` 拼屏幕健壮一个量级。`SKIP` 的存在纯粹是"对话框需要呼吸感"，这在报表里是不必要的，在 7 行的弹窗里却直接影响可用性。

**风险与改进** — 三个小问题：① 单个 `PARAMETERS` 用了冒号（`: p_url ...`），合法但与后续 `p_user`/`p_pass`/`p_cmnt` 的逗号风格不一致，属于风格瑕疵；② `TITLE sc_title` 与 `COMMENT ... sc_x` 隐式声明的文本变量长度有限，`sc_title` 要装下 `Login:` + 主机名，这正是后面静默截断风险的来源；③ 屏幕号 `1002` 在此只能是字面量（`SELECTION-SCREEN` 语法不接受常量），因此类里不得不额外定义 `c_dynnr` 来避免"魔法数字"，这是合理妥协，但要注意**两处定义之间没有任何编译期一致性检查**。

#### ② 仓库 URL 与用户名参数

```abap
SELECTION-SCREEN BEGIN OF LINE.
SELECTION-SCREEN COMMENT 1(18) sc_user FOR FIELD p_user.
PARAMETERS p_user TYPE string LOWER CASE VISIBLE LENGTH 60 ##SEL_WRONG.
SELECTION-SCREEN END OF LINE.
```

**做什么** — 与 `P_URL` 同构地声明 `P_USER`，同样占第 1–18 列的标签位加 60 字符宽的输入框，类型为 `string`，并保留大小写。

**为什么** — 两个参数用同一套模板声明（1(18) 注释 + 60 宽输入框），说明作者把这个对话框的视觉规格当成了稳定的约定，后续加字段直接照抄。`TYPE string` 而不是定长字符，是为了容纳长度不定的用户标识（企业 AD 账号可能几十个字符）。`LOWER CASE` 则是**这个程序里最容易踩坑、也最容易被后人误删的一行**：SAP 标准屏幕默认把输入转成大写，而 Git 托管平台的 URL 路径与用户名**大小写敏感**，删掉 `LOWER CASE` 会直接导致 URL 打不开、Token 认证失败。

**风险与改进** — `TYPE string` 出现在 `PARAMETERS` 上本身是"违规"用法，靠 `##SEL_WRONG` 显式承认。**关键前提是：这个屏幕永远只通过 `CALL SELECTION-SCREEN` 动态调用**——动态屏不回传 `SSCPARAM`，程序直接读同一份全局内存，所以不需要走标准屏的值传递通道。一旦有人把这些参数搬到屏幕 `1000`，`##SEL_WRONG` 就会从一个"合理的确认"变成"掩盖真实取值缺陷的帮凶"，参数值将静默为空且极难排查。建议在旁边补一行注释说明这个前提，并把 pragma 的使用范围限制在本文件。

#### ③ 密码参数

```abap
SELECTION-SCREEN BEGIN OF LINE.
SELECTION-SCREEN COMMENT 1(18) sc_pass FOR FIELD p_pass.
PARAMETERS p_pass TYPE c LENGTH 255 LOWER CASE VISIBLE LENGTH 60 ##SEL_WRONG.
SELECTION-SCREEN END OF LINE.
```

**做什么** — 声明第三个输入字段 `P_PASS`，标签为"Password or Token"，内部类型是 `TYPE c LENGTH 255`，显示宽度 60，保留大小写。

**为什么** — 它的作用在 PBO 阶段被彻底改写：`on_screen_output` 里把 `P_PASS` 的 `screen-invisible` 置为 `'1'`，用户在界面上看到的是一个**标签 + 一个被隐藏的输入框**，但 `sy-ucomm` 与 `PBO` 完全正常，因此可以正常接收键盘输入、`MESSAGE E` 后正常带回错误。这就是"用一个可见输入框占位、再把它藏起来"的经典做法——因为标准屏幕没有原生密码控件可挂靠。定长 255 而非更短，是为了容纳较长的 Personal Access Token（GitHub 的 classic PAT 是 40 位字符，某些平台的自定义 Token 更长）。

**风险与改进** — 这是本文件里类型语义最值得质疑的一处：前两个参数用 `TYPE string`，唯独密码用 `TYPE c LENGTH 255`。`c` 类型带空白填充语义，与 `string` 的比较、拼接、`IS INITIAL` 判定都存在微妙差异（赋值给 `string` 时尾部空白被截掉，密码若以空格结尾会丢失；`c` 字段在内存快照里也不像 `string` 那样易被整体擦除）。三处一致用 `TYPE string` 更符合本文件的整体风格，也避免这类陷阱。次要点：`c LENGTH 255` 的选择屏字段宽度远超 `VISIBLE LENGTH 60` 的显示宽度，实际是"看得见 60 字、能输 255 字"，这在密码字段上体验良好（长 Token 可滚动），但没有任何提示告知用户上限。

#### ④ 提示参数

```abap
SELECTION-SCREEN BEGIN OF LINE.
SELECTION-SCREEN COMMENT 1(18) sc_cmnt FOR FIELD p_cmnt.
PARAMETERS p_cmnt TYPE c LENGTH 255 LOWER CASE VISIBLE LENGTH 60 ##SEL_WRONG.
SELECTION-SCREEN END OF LINE.
SELECTION-SCREEN END OF SCREEN 1002.
```

**做什么** — 声明第四个字段 `P_CMNT`（标签 "Note"），与前三个一样是**可输入的参数**而不是只读注释；随后闭合屏幕 `1002`。`popup` 会在运行时给它预填 `'Press F1 for Help'`。

**为什么** — 作者显然想让这条提示"可以由代码动态改写"（比如不同场景写不同的操作指引），这是与 `SELECTION-SCREEN COMMENT ... '字面量'` 相比多出来的一点灵活性——注释写法其实也支持文本符号，所以这个"灵活性"代价大于收益。

**风险与改进** — 用 `PARAMETERS` 承载一段**纯提示文本**是明显的类型误用，代价有三处：① 它需要额外挂 `##SEL_WRONG`；② 它在 PBO 里必须走"先整体置灰、再单独把 `P_CMNT` 激活"的两段重叠判断（见 3.5），一个只读提示引发了全部的复杂度；③ 它落在输入区而非文本元素里，无法通过文本符号做多语言翻译，而 `'Note'`、`'Repo URL'`、`'Press F1 for Help'` 这些文案目前全部硬编码英文。正确做法是 `SELECTION-SCREEN COMMENT 1(18) TEXT-xxx FOR FIELD p_cmnt.`，既天然只读又可翻译。

---

### 3.2 全局声明区 `类 lcl_password_dialog 定义段`

```abap
CLASS lcl_password_dialog DEFINITION FINAL.
**************
* This class will remain local in the report
**************
  PUBLIC SECTION.
    CONSTANTS c_dynnr TYPE c LENGTH 4 VALUE '1002'.
    CLASS-METHODS popup
      IMPORTING
        iv_repo_url TYPE string
      CHANGING
        cv_user     TYPE string
        cv_pass     TYPE string.
    CLASS-METHODS on_screen_init.
    CLASS-METHODS on_screen_output.
    CLASS-METHODS on_screen_event
      IMPORTING
        iv_ucomm TYPE sy-ucomm.
  PRIVATE SECTION.
    CLASS-DATA gv_confirm TYPE abap_bool.
    CLASS-METHODS enrich_title_by_hostname
      IMPORTING
        iv_repo_url TYPE string.
ENDCLASS.
```

**做什么** — 定义一个 `FINAL` 局部类：`c_dynnr` 固定屏幕号 `1002`；`popup` 以 `IMPORTING` 收仓库 URL、以 `CHANGING` 出入凭据；三个 `on_screen_*` 是给 GUI 框架回调的钩子，其中 `on_screen_event` 接收 `sy-ucomm`；`gv_confirm` 是 `CLASS-DATA` 的确认标志；`enrich_title_by_hostname` 私有。

**为什么** — 三个设计点都值得称道：① **`FINAL`** 明确禁止继承，杜绝了"派生类偷偷改掉掩码逻辑"的可能，这类只有一份实现、靠约定维系的 UI 类不应开放继承点；② **全静态方法**——对话框没有"实例身份"，它是一个纯粹的过程，实例化只会增加心智负担；③ **`gv_confirm` 是这个设计的灵魂**：`CALL SELECTION-SCREEN` 是一条语句而不是函数调用，**没有返回值通道**，唯一能把 PAI 里发生的"用户按了确认"告诉 `popup` 的办法就是借助一个在两次 PBO 之间存活的静态变量，这是 ABAP 标准屏编程里绕不开的机制。

**风险与改进** — 两点。① **契约不在本文件内**：按 abapGit 的 GUI 约定，`on_screen_init` / `on_screen_output` / `on_screen_event` 这三个名字必须由外层 GUI 框架按名字约定派发，而**这个 include 里既没有 PBO/PAI 驱动，也没有注册代码**。也就是说，这份代码的正确性依赖一个文件之外、且编译器看不见的约定：一旦上层漏了注册，对话框会显示成一个"Enter 无反应、Esc 也无反应"的死屏。文件头的注释只说明了"This class will remain local in the report"，却没说清这个派发契约 —— 这恰恰是最该写进注释的信息。② **`CLASS-DATA gv_confirm` 是进程级静态状态**，不可重入、不可单元测试；由于 `popup` 入口会把它复位成 `abap_false`，实际串味风险被控制住了（这是 fail-safe 的默认值，值得肯定），但把它做成实例属性 + 由驱动层持有实例会更干净。

---

### 3.3 方法 `popup`（对话框生命周期主控）

这一步分四步：① 复位与预填 ② 注入标题并计算弹窗位置 ③ 调用动态选择屏 ④ 收尾回填或清空。

#### ① 复位与预填

```abap
  METHOD popup.

    DATA ls_position TYPE zif_abapgit_popups=>ty_popup_position.

    CLEAR p_pass.
    p_url      = iv_repo_url.
    p_user     = cv_user.
    gv_confirm = abap_false.

    p_cmnt = 'Press F1 for Help'.
```

**做什么** — 进入时先无条件 `CLEAR p_pass`（确保上一次的密码不会因为内存残留而被显示出来），再把调用方传入的仓库 URL 写入 `p_url`、把可能已有的用户名写入 `p_user`，把确认标志复位为假，最后给提示字段预填"F1 查看帮助"。

**为什么** — 这是**凭据卫生（credential hygiene）**的标准动作，值得单独强调：`p_pass` 是全局变量（上层程序的全局变量，因为这是 include），它的上一轮内容在内存里原封不动地躺着。**任何"进入即清空"的习惯都是对的方向**，因为密码这类数据一旦在内存里活得比必要时间长，泄露面就从"用户眼前的输入框"扩大到"STXD 屏幕录像、内存快照、调试器 dump、RFC 跟踪"。把 `CLEAR` 放在**函数第一行**而不是收尾，是有讲究的——入口清空是防御性的，不依赖上一次调用是否正常结束。

同时注意 `p_url` 被**回填成调用方给的 URL**：用户不能在这个框里改成别的仓库。这是一条重要的业务护栏——它让"对话框显示的 URL"和"凭据将发往的 URL"永远是同一个，杜绝了用户误把 A 仓库的密码填到 B 仓库的框里。

**风险与改进** — ① `'Press F1 for Help'` 硬编码英文，与其余注释文案一样不可翻译（见 P2 问题）；② `p_cmnt` 每次都被覆盖，这个字段从设计上就不接受调用方传入的内容，如果将来想按场景定制提示，这里是唯一改点；③ `p_url` 从头到尾**没有任何格式校验**——用户在界面上一眼看不出自己粘贴的是不是一个合法 URL，而它决定了凭据最终发往哪里，这类"发往地址"却不做校验，是安全边界上的一处留白。

#### ② 注入标题并计算弹窗位置

```abap
    enrich_title_by_hostname( iv_repo_url ).

    ls_position = zcl_abapgit_popups=>center(
      iv_width  = 65
      iv_height = 7 ).
```

**做什么** — 先让 `enrich_title_by_hostname` 把窗口标题改成 `Login: <主机名>`，再调用 abapGit 公共弹窗工具 `zcl_abapgit_popups=>center`，传入宽 65、高 7，算出对话框在屏幕上居中的起止行列，写入结构 `zif_abapgit_popups=>ty_popup_position`。

**为什么** — **标题注入是这个组件最有价值的一处 UX 设计**，很多人会忽略：用户在弹出的瞬间最需要确认的不是"我的密码是什么"，而是"我正在给哪个站点输密码"。因为 `p_url` 已被置灰不可编辑，用户无法靠改 URL 来纠正点错的仓库，此时唯一的信息通道就是标题。abapGit 还把它复用到标题栏之外（`sc_title` 同时是选择屏标题），一次赋值两处生效。

至于"居中定位"为什么要借 `zcl_abapgit_popups=>center`：自己写居中就是 `sy-screen-height`/`sy-screen-width` 的一半加减一行列的算术，而这是 abapGit 全项目共用的工具方法。**复用公共工具而不是就地实现**，在多弹窗的项目里价值非常实在——它保证了所有弹窗的视觉位置一致。

**风险与改进** — **尺寸与内容不匹配**：注释标签占 1–18 列，`VISIBLE LENGTH 60` 的输入框从第 19 列开始，内容横跨约 **78 列**；而行数是 4 行字段加 3 个 `SKIP` 加首尾行，约 **8 行**。按 `center` 的 width/height 即对话框总宽高的语义，这里声明的 65×7 **小于实际所需**，右侧 URL/Token 的尾部与提示行很可能被裁掉。建议把宽高按内容重算，或缩短 `VISIBLE LENGTH` 与注释列宽，让声明值与内容一致——这类"魔法数字"最容易被后续加字段时无声破坏。

#### ③ 调用动态选择屏

```abap
    CALL SELECTION-SCREEN c_dynnr
      STARTING AT ls_position-start_column ls_position-start_row
      ENDING AT ls_position-end_column ls_position-end_row.
```

**做什么** — 调用动态选择屏 `1002`，以 `center` 算出的行列作为对话框的四至。语句执行后原程序在此挂起，SAP 接管屏幕，循环触发 PBO/PAI 直到对话框关闭，控制权才回到这条语句的下一行。

**为什么** — `CALL SELECTION-SCREEN` 是这段代码存在的**唯一理由**。它是 ABAP 里少数几个能把"标准选择屏"变成"模态子程序"的语句：调用后程序栈停在原地，但屏幕独立出来接收输入，且 `MESSAGE E` 会让控制流回到同一个对话框继续交互——这正是 `on_screen_event` 里能"报错但不退出"的前提。相比之下 `CALL TRANSACTION` 会切换 LUW 上下文、提交/回滚行为复杂得多，而这里只需要一个纯输入的界面，动态屏是最轻的载体。

**风险与改进** — ① 该语句没有返回值，"用户是否确认"只能靠 `gv_confirm` 这一条腿；② `c_dynnr` 与 `SELECTION-SCREEN BEGIN OF SCREEN 1002` 两处屏幕号之间无编译期约束，改一处忘另一处会在运行时报"屏幕不存在"；③ 语句本身不带 `SUPPRESS DIALOG`，若对话框内部再去调别的弹窗，嵌套行为需要上游保证（本文件未做保护）。

#### ④ 收尾回填与痕迹清理

```abap
    IF gv_confirm = abap_true.
      cv_user = p_user.
      cv_pass = p_pass.
    ELSE.
      CLEAR: cv_user, cv_pass.
    ENDIF.

    CLEAR: p_url, p_user, p_pass.

  ENDMETHOD.
```

**做什么** — 控制权回来后读 `gv_confirm`：为真表示用户按了 Enter 且通过了校验，把 `p_user` / `p_pass` 回填给调用方的 `CHANGING` 参数；否则（Esc、Back、Exit，或根本没走到确认分支）**清空调用方的两个凭据**。无论哪条分支，最后统一 `CLEAR` 三个全局参数。

**为什么** — 取消分支的 `CLEAR: cv_user, cv_pass` 是这段代码里最容易被漏掉、但最重要的防御动作：如果只写确认分支的赋值，`cv_pass` 会**保留调用方之前传进来的旧值**，而调用方看到"popup 返回了"就会以为拿到了新凭据——于是一次"用户取消"会静默变成"使用旧密码重试"，形成一个极难察觉的无限重试或认证失败循环。**"失败路径必须显式清空返回缓冲区"** 是所有带输出参数的对话框的通用铁律，这里做得很到位。末尾的 `CLEAR` 则与入口的 `CLEAR p_pass` 形成呼应：进来清一次、出去清一次，把密码在全局内存中的驻留时间压到最短。

**风险与改进** — ① 凭据仍然以全局参数的形式驻留在**上层程序**的内存中直到本方法返回，之后屏幕缓冲区里也还留着已输入的密码（在可见性方面可以接受，因为已隐藏）。彻底的做法是不用全局参数传递，而是把值保存在类实例或 ABAP memory 之外的结构中，代价是复杂度上升——对 abapGit 而言这是可接受的权衡，但应当被明确记录成"已知残余风险"而非默认安全。② `IF gv_confirm = abap_true` 可以简写为 `IF gv_confirm`，abap 项目规约里前者更常见，属风格问题。③ 这里没有对"确认成功但密码为空"再做兜底——当前靠 `on_screen_event` 里强制非空来保证，属于跨方法的隐式契约，值得加注释固化。

---

### 3.4 方法 `on_screen_init`

```abap
  METHOD on_screen_init.
    sc_title = 'Login'.
    sc_url   = 'Repo URL'.
    sc_user  = 'User'.
    sc_pass  = 'Password or Token'.
    sc_cmnt  = 'Note'.
  ENDMETHOD.
```

**做什么** — 在屏幕初始化阶段一次性写入窗口标题默认值 `'Login'` 以及四个注释文本：仓库 URL、用户、密码或令牌、提示。

**为什么** — 两个细节体现了作者的经验：① **`'Password or Token'` 这个标签是有业务含义的**——abapGit 支持 Token 认证，明确告诉用户"这里可以填 Token"能显著提高 Token 认证的采用率，比干巴巴的 "Password" 友好；它把一个技术选项暴露在了最该出现的地方。② **文案集中在 `init` 而不是散落到 `output`**：`on_screen_output` 每次 PBO 都会跑，如果在那里写 `sc_*` 文本，一旦将来混入对 `p_*` 的赋值，就会把用户已经输入的内容冲掉。这里严格把"框架文本"（`sc_*`）与"用户数据"（`p_*`）分开，避免了这类极其常见的坑。

**风险与改进** — 五条文案全部硬编码英文，与 abapGit 的其他界面一样依赖外部翻译机制或英语用户群；对多语言系统（SAP 标准做法）而言这些文本不可翻译。另外 `'Login'` 只是**默认值**——`enrich_title_by_hostname` 会在 `popup` 里尝试覆盖它，所以"没有主机名可抽"的场景下用户看到的就是这个朴素的 `Login`，此时用户将失去"这是哪个站点"的唯一线索（因为 URL 被置灰不可读地修改），这是文案设计的一个隐性盲区。

---

### 3.5 方法 `on_screen_output`（PBO：界面行为注入）

这一步分三步：① 遍历 SCREEN 做差异化置灰与隐藏 ② 设置状态栏 ③ 设置光标。

#### ① 遍历 SCREEN 做差异化置灰与隐藏

```abap
  METHOD on_screen_output.

    DATA lt_ucomm TYPE TABLE OF sy-ucomm.

    ASSERT sy-dynnr = c_dynnr.

    LOOP AT SCREEN.
      IF screen-name = 'P_URL' OR screen-name = 'P_CMNT'.
        screen-input       = '0'.
        screen-intensified = '1'.
        screen-display_3d  = '0'.
        MODIFY SCREEN.
      ENDIF.
      IF screen-name = 'P_CMNT' OR screen-name = 'SC_CMNT'.
        screen-active    = '1'.
        screen-invisible = '0'.
        MODIFY SCREEN.
      ENDIF.
      IF screen-name = 'P_PASS'.
        screen-invisible = '1'.
        MODIFY SCREEN.
      ENDIF.
    ENDLOOP.
```

**做什么** — 断言当前屏幕号是 `1002`，然后遍历该屏的所有屏幕行：把 `P_URL` 和 `P_CMNT` 设为不可输入、取消三维边框、高亮显示（视觉上像只读文本）；紧接着又对 `P_CMNT` 与它对应的注释文本行 `SC_CMNT` 单独设为"激活且可见"（把上一步刚置灰的提示字段救回来）；最后把 `P_PASS` 设为不可见。

**为什么** — `LOOP AT SCREEN` + `MODIFY SCREEN` 是 ABAP 里**唯一**能在不重画屏幕的前提下改变某个屏幕行外观的官方手段，也是"把标准选择屏改造成对话框"的核心技巧。三个 `screen-*` 属性的组合拳也很讲究：`input = '0'` 管交互，`display_3d = '0'` + `intensified = '1'` 管视觉——很多程序只设了前者，结果用户看到的是一个**看起来能点、点了没反应**的输入框，这才是真正糟糕的 UX。

第三段的 `screen-invisible = '1'` 则是密码处理的正解：它只隐藏显示，输入能力保留，所以键盘输入、PBO/PAI、错误重绘全都照常工作，而**密码不会以明文出现在屏幕上、不会被肩窥、不会进 STXD 截图**。

**风险与改进** — 这一段集中了本文件**最危险的三处代码**：

① **字段名硬编码为字面量，且没有任何编译期保护**。`screen-name = 'P_PASS'` 与声明处的 `p_pass` 之间是纯字符串关联。**一旦有人把参数改名为 `p_password`（这在 abapGit 里很常见，命名规范常要求更明确），这段代码不会报错、不会警告，密码掩码会静默失效，密码将以明文显示在屏幕上。** 这是"重构一次、泄露一次"的典型陷阱。同理 `P_URL`、`P_CMNT`、`SC_CMNT` 也一样。改进方向：把屏幕行名收敛为类常量（集中一处），并在注释中标注"改名时必须同步此处"；更进一步的做法是让 `on_screen_output` 只处理一个"需要隐藏的字段列表"，把映射关系放到唯一可维护的地方。

② **`P_CMNT` 走的是"先关再开"**。第一段把它置为不可输入，第二段又把它和 `SC_CMNT` 重新激活。两个 `IF` 条件在 `P_CMNT` 上**重叠**，正确性完全依赖"判断顺序"。这在阅读时非常反直觉，也让"改其中一个条件"的维护成本升高。应改为一个 `CASE screen-name`，每个字段一次判定到底。

③ **`ASSERT sy-dynnr = c_dynnr` 用得不合规**。`ASSERT` 在**生产系统上不生效**，也就是说它的保护在生产环境等于不存在；而且即便开发态断言失败，ABAP 的行为是终止程序而不是返回，调试体验也不好。它在这里的真实价值只是"提示我以为自己知道自己在干嘛"，不足以承担校验职责。正确做法是 `IF sy-dynnr <> c_dynnr. RETURN. ENDIF.`。

#### ② 设置状态栏

```abap
    APPEND 'PICK' TO lt_ucomm.

    CALL FUNCTION 'RS_SET_SELSCREEN_STATUS'
      EXPORTING
        p_status  = 'DETL'
        p_program = 'RSPFPAR'
      TABLES
        p_exclude = lt_ucomm.

    ASSERT sy-dynnr = c_dynnr.
```

**做什么** — 构造一个只含 `'PICK'` 的排除表，调用 `RS_SET_SELSCREEN_STATUS`，指定状态栏为 `'DETL'`、来源程序为 `'RSPFPAR'`，把该状态栏套到当前动态选择屏上，并排除 `PICK` 这个命令。

**为什么** — `CALL SELECTION-SCREEN` 默认会带一套**报表**的状态栏（执行、选择、变式、保存……），对密码框来说既不相关又会误导用户。所以作者借用了 SAP 标准的 **详情页状态栏 `DETL`**（Enter/绿勾、F1 帮助、返回、取消、退出）——这是与"确认/取消"语义最贴合的一套按键。`p_program = 'RSPFPAR'` 是关键技巧：`RSPFPAR` 是 SAP 为选择屏生成的标准程序模板，用它作"借用来源"就能拿到这套状态栏而无需自建。

`p_exclude` 的作用是屏蔽不该出现的功能键，避免用户按下某个键后 `sy-ucomm` 落进 `on_screen_event` 的 `WHEN OTHERS` 而被当成"取消"。

**风险与改进** — ① **状态栏是全局副作用**：`RS_SET_SELSCREEN_STATUS` 设定的是当前会话的屏幕状态，`popup` 返回后并不会自动撤销，后续同程序内再调用其他动态选择屏时可能继承到这套状态。② `p_program = 'RSPFPAR'` 依赖 SAP 标准生成程序模板的稳定存在，属于**跨版本升级时的脆弱点**。③ 该函数在**每次 PBO 都被调用**（包括每次 `MESSAGE E` 后的重绘），而它的效果是幂等的全局设置，重复调用纯属浪费，且放大了第 ① 点的副作用范围。建议在初始化阶段设置一次即可。④ 排除表里只有 `PICK` 一个动作码，而真正应该被审慎对待的是 `BACK`、`EXIT`、`%_...` 等——它们现在都落进 `WHEN OTHERS`，等于"什么都能按、什么都不区分"，见 P3 问题。

#### ③ 设置光标

```abap
    IF p_user IS NOT INITIAL.
      SET CURSOR FIELD 'P_PASS'.
    ENDIF.

  ENDMETHOD.
```

**做什么** — 仅当 `p_user` 非空（即屏幕上已经有用户名）时，把光标定位到 `P_PASS` 字段。

**为什么** — 这一行是**为 `MESSAGE E` 重绘场景写的**：首次显示时 `p_user` 为空，光标保持标准的 Tab 顺序（落在第一个可编辑字段，即 `P_USER`）；而当用户按 Enter 却被拒绝后重绘，`p_user` 已被填上内容，于是光标被强制跳到 `P_PASS`——**正好是校验失败的那一个字段**。这种"错误提示出现时自动把光标送到出错字段"的做法，能把用户的下一步动作缩短为零思考，是廉价而高性价比的体验提升。

**风险与改进** — ① **首次显示没有任何 `SET CURSOR`**，光标落在标准默认位置；而 `P_URL` 是被置灰的第一个字段，若被选中，用户看到的是一个灰框却能直接敲键盘（`screen-input = '0'` 会吞掉输入），表现为"打了字没反应"，容易让人误判为界面卡死。建议首显即定位到 `P_USER`。② `SET CURSOR FIELD 'P_PASS'` 与前一步的 `screen-invisible = '1'` 组合，意味着**光标被放进了用户看不见的字段**——这在标准屏幕上确实可用，但可用性上略反直觉，且不同 GUI/前端版本行为可能有差异，属于需要回归验证的细节。③ 同样存在字面量 `'P_PASS'` 的硬编码问题。

---

### 3.6 方法 `on_screen_event`（PAI：用户动作分派）

这一步分三步：① Enter 的校验与确认 ② F1 的帮助 ③ 其余动作视为取消。

#### ① Enter：校验与确认

```abap
    ASSERT sy-dynnr = c_dynnr.

    CASE iv_ucomm.
      WHEN 'OK'. " Enter
        IF p_user IS INITIAL OR p_pass IS INITIAL.
          " Empty credentials cannot be used for authentication, and returning them
          " is indistinguishable from cancelling the popup. The error message keeps
          " the popup open, so the input can be corrected
          MESSAGE 'User and password are obligatory' TYPE 'E'.
        ELSE:
          gv_confirm = abap_true.
          LEAVE TO SCREEN 0.
        ENDIF.
```

**做什么** — 断言屏幕号后按 `iv_ucomm` 分派：`'OK'`（即 Enter/绿勾）分支检查用户名与密码是否非空，任一为空就发一条 **E 级消息**（对话框不关闭，可当场改正）；两者都非空则把 `gv_confirm` 置真并 `LEAVE TO SCREEN 0` 退出动态屏。

**为什么** — 这是整个文件里**最需要业务理解的一处**。E 消息 + 不 `LEAVE` 的组合，正是动态选择屏的既定行为：E 消息会中断 PAI 处理但不退出屏幕，控制流重新走 PBO，对话框原地重绘，用户继续输入。代码里那段英文注释把设计理由讲得很清楚，值得直接引用：**空凭据无法用于认证，而"返回空凭据"与"用户取消"在调用方看来是无法区分的**。这就是为什么要用错误消息把弹窗钉在原地，而不是"友好地"让空值返回去——因为 `popup` 的取消分支会主动清空 `cv_user`/`cv_pass`，一旦允许空值确认，调用方拿到的是"空凭据"，那它与取消毫无区别，错误必然被吞掉。把"非法输入"用**不可被误认为合法**的通道反馈，是这个设计的正确内核。

`gv_confirm` 置真再 `LEAVE TO SCREEN 0` 的顺序也对：先记录意图，再跳出，避免退出动作导致状态丢失。

**风险与改进** — ① **"必须非空"是写死的策略**，而它对公开仓库、匿名克隆、以及某些只读 Token 场景是错的；调用方想走匿名访问，就只能绕过这个弹窗。更好的设计是把"是否允许空凭据"做成入参开关，或提供一个独立的"匿名继续"动作键，这样策略从"硬编码在 UI 里"变成"由调用方决策"。② `MESSAGE '...' TYPE 'E'` 用的是**英文字面量**而非消息类+文本符号，不可翻译、不可集中维护、无法被 ABAP 消息类工具检索——这是 SAP 明确不建议的写法（SAP 规范要求所有消息经消息类输出）。③ 整段逻辑没有区分"用户其实想输空密码但系统不允许"与"用户压根没输"，可以给 `p_user` / `p_pass` 分别的提示，但会牺牲简洁性，属于取舍。④ `MESSAGE` 之后没有 `RETURN`，依赖的是 ABAP 的 E 消息中断语义——这在标准屏编程里成立，但建议加一行注释固化这个隐式契约。

#### ② F1：打开帮助

```abap
      WHEN 'HELP'. " F1
        TRY.
            zcl_abapgit_services_abapgit=>open_abapgit_wikipage( 'guide-authentication.html' ).
          CATCH zcx_abapgit_exception ##NO_HANDLER.
        ENDTRY.
```

**做什么** — `'HELP'`（F1）分支调用 abapGit 服务类打开指定 Wiki 页面的认证指南，全程用 `TRY` 包住，只捕获 `zcx_abapgit_exception` 并**静默忽略**。

**为什么** — 用 F1 而不是 `POPUP` 塞一段长文本，是正确的方向：认证流程本身有坑（Token 权限范围、Token 过期、账号密码已启用 2FA、组织强制改密导致 Git 认证失败等），这些内容值得一篇指南。调用统一的服务类而不是自己 `CALL FUNCTION` 拼 URL，说明链接生成与浏览器拉起逻辑已被抽象，UI 只负责表达意图。`##NO_HANDLER` 抑制"异常未被处理"的代码检查，说明作者明知这里故意吞掉异常。

**风险与改进** — **吞掉异常后不给用户任何反馈，这是明确的问题**：当 Wiki 打不开（离线、无浏览器、网络策略拦截）时，用户按下 F1 屏幕上**毫无反应**，而这恰恰是他唯一需要帮助的时刻——体验上等同于"程序卡住了"。至少应该 `MESSAGE ... TYPE 'S'` 或 `'W'` 提示帮助页面当前不可用。此外 `guide-authentication.html` 是硬编码的页面名，文档改名或路径调整需要改 ABAP 代码并重新发布，缺少配置化或外部常量。

#### ③ 其余动作：视为取消

```abap
      WHEN OTHERS. " Escape
        gv_confirm = abap_false.
        LEAVE TO SCREEN 0.
    ENDCASE.

  ENDMETHOD.
```

**做什么** — 所有未列举的命令（Esc、Back、Exit、Ctrl+F3 等）统一把 `gv_confirm` 置为假并退出动态屏；`popup` 随之走取消分支清空调用方凭据。

**为什么** — 兜底分支的**默认值选得很对**：选"取消"而不是选"确认"。任何未知动作、任何没被 PAI 处理的路径，结果都是"什么都没发生"而不是"用未知/半截的值去做认证"——这是安全侧的 fail-safe 方向。而且 `gv_confirm = abap_false` 是**显式赋值**而非依赖初始值，即使将来有人删掉 `popup` 入口的复位，这一行仍保证语义正确。

**风险与改进** — ① **注释 `" Escape"` 与语义不符**：它捕获的远不止 Esc，还包括 `BACK`、`EXIT`、`SHIFT+F3` 等。把"所有其他动作"标注成"Escape"会误导后续维护者，也让代码审查时看不出这里其实做了**宽泛的动作归类决策**。② 归类过宽的代价是：将来若新增一个合法动作（例如"保存凭据"），它会被**静默当成取消**处理，用户点了没反应且没有任何报错。建议显式列出 `BACK`/`EXIT`/`ESC`，`WHEN OTHERS` 只作为真正异常的兜底并输出提示。③ 这里同样依赖框架把 `sy-ucomm` 正确传入；若派发契约不成立，PAI 永远不会到这里，`popup` 会一直阻塞在动态屏（见 P0 问题）。

---

### 3.7 方法 `enrich_title_by_hostname`

这一步分两步：① 正则抽取主机名 ② 有条件地覆写标题。

#### ① 正则抽取主机名

```abap
  METHOD enrich_title_by_hostname.

    DATA lv_host TYPE string.

    FIND REGEX 'https?://([^/^:]*)' IN iv_repo_url SUBMATCHES lv_host ##REGEX_POSIX.
```

**做什么** — 用 `FIND REGEX ... SUBMATCHES` 从仓库 URL 中匹配 `http://` 或 `https://` 之后、遇到第一个 `/`、冒号或 `^` 之前的连续字符，取第一个捕获组存入 `lv_host`；并显式声明使用 POSIX 正则引擎。

**为什么** — 不引入完整的 URL 解析类，只用一次正则拿到"给人看的站点名"，对对话框标题这种非精确用途是合理的成本权衡。`##REGEX_POSIX` 让表达式语义与 PCRE/ICU 对齐，避免 ABAP 正则的方言差异在换机器时产生意外。

**风险与改进** — 这段正则是**全文件安全风险最高的一处**。字符类 `[^/^:]` 里，`^` 只有出现在 `[` **之后第一位**才是"取反"，出现在中间是**字面量**。也就是说作者真正表达的是"匹配除 `/`、`^`、`:` 以外的字符"，多排除一个 `^` 属于笔误（无害但意图不清）。**真正的问题是匹配范围**：它把 `https://` 与第一个 `/` 或 `:` 之间的**全部字符**都当成主机名，而这段区间里恰恰可能装着凭据——

- `https://ghp_xxxxx@github.com/org/repo.git`（Token 内嵌在 userinfo，abapGit 与 GitHub 都真实支持这种 URL）→ 匹配结果是 `ghp_xxxxx@github.com`，**令牌原文被写进窗口标题**；
- `https://user:pass@host/repo.git` → 匹配结果是 `user`，标题变成 `Login: user`，既误导又泄露用户名。

窗口标题会出现在任务栏、会被同事看到、会进 STXD/屏幕录像。改进方向有二：优先使用 abapGit 已有的 URL 解析能力（项目内已有面向 URL 的类）直接取 host，而不是正则重造；退一步也必须在写入标题前**显式剥离 userinfo**（`@` 之前的部分）并对结果做长度/字符白名单校验。

#### ② 有条件地覆写标题

```abap
    IF lv_host IS NOT INITIAL AND lv_host <> space.
      CLEAR sc_title.
      CONCATENATE 'Login:' lv_host INTO sc_title IN CHARACTER MODE SEPARATED BY space.
    ENDIF.

  ENDMETHOD.
```

**做什么** — 只有在 `lv_host` 既非初始值、又非空格时才执行覆写：先 `CLEAR sc_title` 再用 `CONCATENATE ... IN CHARACTER MODE SEPARATED BY space` 把 `Login:` 与主机名拼成新标题。

**为什么** — 三处细节都值得学习。① **`IN CHARACTER MODE`** 是 7.40 之后处理字符串的正确写法：它避免了 `CONCATENATE` 默认按定长字符类型处理时的隐式类型转换与长度推断问题，在 `string` 参与运算时几乎总是应该显式指定。② **`CLEAR sc_title` 再拼接**，而不是直接 `CONCATENATE ... INTO sc_title`——后者在目标是定长字符类型且已有内容时行为依赖实现细节，显式清空把语义摆在明面上。③ **双重空值判断**（`IS NOT INITIAL` 与 `<> space` 并存）在字符串比较里非常必要：ABAP 字符串比较会忽略尾部空白，**空字符串与 `' '` 会被判为相等**，只写一个条件在某些路径下会漏判。这里虽然没能替代正确的 `sy-subrc` 检查（见下），但双保险的思路是对的。

**风险与改进** — ① **没有检查 `sy-subrc`**。`FIND` 未命中时返回 `sy-subrc = 1`，`SUBMATCHES` 的目标字段在这种情形下的取值依赖语句语义而非显式赋值；当前代码是靠下一层的空值判断兜底，属于**隐式契约**。更稳妥的做法是显式 `IF sy-subrc = 0.` 再取值。② **没有检查 `CONCATENATE` 的 `sy-subrc`**：目标 `sc_title` 是 `SELECTION-SCREEN TITLE` 隐式声明的定长文本字段，长度有限，而 `lv_host` 最长可达 255 字符，超长时 `CONCATENATE` 会**静默截断**并置 `sy-subrc = 4`，用户看到一个被砍掉一半的标题却毫不知情。③ `lv_host` 来自用户可控的 URL，未做任何字符白名单校验就写进标题文本；SAP 标题文本对 `%_` 等特殊转义有既定含义，理论上存在被输入内容影响标题显示的可能。建议至少做长度截断与非打印字符过滤。

---

### 3.8 `FORM password_popup`（对外门面）

```abap
FORM password_popup
      USING
        pv_repo_url TYPE string
      CHANGING
        cv_user     TYPE string
        cv_pass     TYPE string ##CALLED.

  lcl_password_dialog=>popup(
    EXPORTING
      iv_repo_url     = pv_repo_url
    CHANGING
      cv_user         = cv_user
      cv_pass         = cv_pass ).

ENDFORM.
```

**做什么** — 定义一个过程 `password_popup`：输入仓库 URL，输出凭据两个参数，方法体只有一次静态方法调用，把三个参数原样转发给 `lcl_password_dialog=>popup`。

**为什么** — **这是一次教科书式的"接口适配"**：abapGit 的调用方遍布报表、后台作业、类方法，习惯用 `PERFORM`；而对话框实现是 OO 的。`FORM` 在这里的作用就是**在传统过程式接口与 OO 实现之间架一座窄桥**，让调用方完全不需要知道类的存在。三个参数全部按名传递（`EXPORTING iv_repo_url = pv_repo_url`），这在 7.40 之后的项目中是强制规范，也让参数增删不会引起调用点错位。类名以 `lcl_` 前缀（local class）标注，`FINAL` 收口，整个类都不会泄漏到 `INCLUDE` 之外的命名空间——**避免与上层程序的其他局部类重名冲突**，这是 include 型源码必须遵守的纪律。

**风险与改进** — ① `cv_pass` 上的 `##CALLED` pragma 是本文件里唯一一个语义不明的标记：它承认这个参数只被"转发"而非直接使用，用于压制相应的代码检查提示。对一个承载密码的参数来说，**静默掉检查并不等于消除了问题**——正确的做法是不需要它（把 `FORM` 整体废弃，调用方直接用类方法，或在 include 里提供一个简洁的类型化接口）。建议至少查清该 pragma 的确切语义并加注释，否则它会成为下一个读代码的人的谜题。② 由于这是 include，`pv_repo_url` / `cv_user` / `cv_pass` 与全局的 `p_pass` 都是**上层程序的全局数据**，密码的可见范围因此扩大到整个上层程序，而不只是这个 `FORM`——这是 include 型密码组件必须被知晓的固有风险。③ `FORM` 本身无返回码，无法向调用方区分"确认""取消""参数非法"，调用方只能通过凭据是否为空去间接判断，这限制了错误上报能力。

---

## 四、执行流程全景图（数据视角）

```mermaid
sequenceDiagram
    participant CALLER as 调用方程序
    participant FORM as FORM password_popup
    participant POPUP as 方法 popup
    participant TITLE as 方法 enrich_title_by_hostname
    participant SCREEN as 动态选择屏 1002
    participant INIT as 方法 on_screen_init
    participant OUT as 方法 on_screen_output
    participant EVT as 方法 on_screen_event

    CALLER->>FORM: 传入仓库 URL 与 cv_user、cv_pass
    FORM->>POPUP: 传入 iv_repo_url 与 cv_user、cv_pass
    POPUP->>POPUP: 清空 p_pass，回填 p_url 与 p_user，gv_confirm 置假，预填提示文本
    POPUP->>TITLE: 传入 iv_repo_url
    TITLE-->>POPUP: 把 Login 加主机名 写入 sc_title
    POPUP->>SCREEN: CALL SELECTION-SCREEN 1002，起止行列取自 center 的计算结果
    SCREEN->>INIT: PBO 初始化阶段触发
    INIT-->>SCREEN: 写入 sc_title、sc_url、sc_user、sc_pass、sc_cmnt
    SCREEN->>OUT: 每次 PBO 触发
    OUT-->>SCREEN: 置灰 p_url 与 p_cmnt，隐藏 p_pass，装 DETL 状态栏，已填用户名则定位光标到 p_pass
    CALLER->>SCREEN: 输入用户名与密码并回车
    SCREEN->>EVT: PAI 触发，传入 sy-ucomm
    EVT->>EVT: 校验 p_user 与 p_pass 是否非空
    EVT-->>SCREEN: 为空则发 E 消息，控制流回到 OUT 重绘对话框
    EVT-->>SCREEN: 非空则 gv_confirm 置真并 LEAVE TO SCREEN 0
    SCREEN-->>POPUP: 控制权返回 popup
    POPUP-->>FORM: 确认则回填 cv_user 与 cv_pass，取消则清空二者
    POPUP->>POPUP: 清空 p_url、p_user、p_pass
    FORM-->>CALLER: 返回凭据
```

**做什么** — 从数据视角把"凭据"这条主线画清楚：仓库 URL 从调用方流入、经过 `popup` 落到全局参数 `p_url`（只读展示）、经 `enrich_title_by_hostname` 派生出标题；用户在屏幕上手动录入用户名与密码到全局参数；`on_screen_event` 只做校验与置标志；最终由 `popup` 依据标志决定把全局参数搬进调用方的 `CHANGING` 参数，还是丢弃。
**为什么** — 这张图刻意把 `MESSAGE E` 的分支画成"回到 `OUT` 而不是回到 `CALLER`"，因为**对话框的可交互性正是靠这一条回边维持的**；同时把凭据的"三个落点"（全局 `p_*` → 屏幕缓冲区 → `cv_*`）分开画，便于看清密码在什么时刻处于明文状态。
**风险与改进** — 图中 `SCREEN → INIT/OUT/EVT` 三条虚线同样依赖外部框架派发，本 include 内不存在这段代码；另外图中"用户手动录入"这一步是**唯一没有代码保证的环节**——密码在标准屏幕缓冲区里的隐藏只靠 `on_screen_output` 的字面量字段名支撑，一旦失效，图中这条数据线就会变成明文线（详见 3.5 与 P0 问题）。

---

## 五、问题清单与改进建议（按优先级）

| 优先级 | 问题 | 所在子程序 | 影响 | 改进建议 |
|--------|------|-----------|------|----------|
| 🔴 P0 | 正则把 URL 的 userinfo 当主机名抽走（`ghp_xxx@github.com`、`user:pass@host`），直接写进窗口标题 | 方法 `enrich_title_by_hostname` | 令牌或用户名出现在任务栏与 STXD 屏幕录像中，构成凭据泄露 | 改用项目内既有 URL 解析取真实 host；写入前剥离 `@` 之前的 userinfo 并加字符白名单 |
| 🔴 P0 | 密码掩码依赖字面量 `'P_PASS'` 与声明处 `p_pass` 的字符串对应，无编译期约束 | 方法 `on_screen_output` | 参数一旦改名，`screen-invisible` 静默失效，密码以明文显示 | 屏幕行名收敛为类常量并集中维护，改名处加断言注释；或改用可从字段自身推导的写法 |
| 🔴 P0 | 对话框的 PBO/PAI 驱动与回调注册代码不在本 include 内，确认只靠 `gv_confirm` | 方法 `popup`、方法 `on_screen_event` | 派发契约一旦不成立，Enter/Esc 均无响应，用户被困在弹窗；且无任何超时或兜底取消路径 | 把 PBO/PAI 驱动收进本 include，或在调用前显式注册并对未注册情况 `MESSAGE ... TYPE 'E'` |
| 🟠 P1 | "用户与密码必须非空"作为硬编码策略写死在 PAI 中 | 方法 `on_screen_event` | 公开仓库匿名克隆、只读 Token 等场景无法走该弹窗，只能绕过 | 把"是否允许空凭据"改为入参开关，或提供独立的"匿名继续"动作键 |
| 🟠 P1 | `CATCH zcx_abapgit_exception ##NO_HANDLER` 完全静默 | 方法 `on_screen_event` | F1 无反应，用户在最需要帮助时得不到任何信息，无法区分"无帮助"与"程序卡住" | 捕获后输出 `'S'` 或 `'W'` 消息说明帮助暂不可用 |
| 🟠 P1 | `p_pass` 与 `p_cmnt` 用 `TYPE c LENGTH 255`，而 `p_url`、`p_user` 用 `string` | 全局声明区（选择屏 1002 定义） | 类型语义不一致，定长空白填充导致尾部空格密码丢失，比较/判定行为易出意外 | 三处统一为 `TYPE string`，与项目其余代码风格一致 |
| 🟠 P1 | 同一字段 `P_CMNT` 被两个重叠 `IF` 先置灰后激活，正确性依赖判断顺序 | 方法 `on_screen_output` | 阅读反直觉，改动任一条件极易漏掉配套修改 | 改为 `CASE screen-name`，每个字段一次判定到底 |
| 🟠 P1 | 密码以 include 的全局参数形式驻留在上层程序内存中，直到 `popup` 返回才清除 | 全局声明区（选择屏 1002 定义）、方法 `popup` | 密码暴露窗口从"输入框"扩大到"整个上层程序的内存"，可被 STXD、内存快照、调试器取回 | 已做进出双 `CLEAR`，应进一步缩短驻留期；避免任何日志/消息携带密码，并将其登记为已知残余风险 |
| 🟡 P2 | 弹窗尺寸 `center(iv_width = 65, iv_height = 7)` 小于实际内容（横向约 78 列、纵向约 8 行） | 方法 `popup` | 右侧 URL/Token 尾部与提示行被裁切 | 按实际内容重算宽高，或缩短注释列宽与 `VISIBLE LENGTH`，让声明值与内容对齐 |
| 🟡 P2 | 用 `PARAMETERS` 承载只读提示文本 `p_cmnt` | 全局声明区（选择屏 1002 定义） | 多余的 `##SEL_WRONG`、多余的两段 toggle，文案不可翻译 | 改用 `SELECTION-SCREEN COMMENT ... TEXT-xxx FOR FIELD p_cmnt.`，天然只读且可翻译 |
| 🟡 P2 | `RS_SET_SELSCREEN_STATUS` 借用 `RSPFPAR` 且在每次 PBO 重复调用 | 方法 `on_screen_output` | 依赖标准生成程序模板，跨版本升级脆弱；全局状态泄漏到后续动态屏 | 初始化时设置一次即可；或改用自有状态栏并显式撤销 |
| 🟡 P2 | 界面文案与错误消息全部硬编码英文字面量（`'Login'`、`'Note'`、`'Press F1 for Help'`、`MESSAGE 'User and password are obligatory'`） | 方法 `on_screen_init`、方法 `popup`、方法 `on_screen_event` | 多语言系统不可翻译，无法集中维护与检索 | 文案用文本符号/消息类 + 文本元素承载，硬编码仅作兜底 |
| 🟡 P2 | `ASSERT sy-dynnr = c_dynnr` 被当作控制流使用 | 方法 `on_screen_output`、方法 `on_screen_event` | 生产系统上完全不生效，校验形同不存在；断言失败会终止程序 | 改为 `IF` 判断加 `RETURN`，需要强制时可保留 `ASSERT` 作为文档用途 |
| 🟡 P2 | `FIND` 与 `CONCATENATE` 均未检查 `sy-subrc` | 方法 `enrich_title_by_hostname` | 未命中时依赖语句隐式行为；超长主机名被静默截断进定长标题 | 分别检查 `sy-subrc = 0` 与截断分支，并对主机名做长度裁剪 |
| 🟢 P3 | 首次显示无 `SET CURSOR`，光标可能落在已置灰的 `P_URL` 上 | 方法 `on_screen_output` | 用户"敲键盘没反应"，易误判界面卡死 | 首显即定位到 `P_USER`，仅在报错重绘时定位到 `P_PASS` |
| 🟢 P3 | `WHEN OTHERS. " Escape` 实际捕获 Back、Exit、Ctrl+F3 等所有其他动作 | 方法 `on_screen_event` | 注释误导；将来新增合法动作会被静默当成取消 | 显式列举 `BACK`/`EXIT`/`ESC`，`WHEN OTHERS` 仅作异常兜底并输出提示 |
| 🟢 P3 | 正则字符类写作 `[^/^:]`，中间的 `^` 为字面量 | 方法 `enrich_title_by_hostname` | 多排除一个字符号，且掩盖了作者真实意图 | 改写为语义明确的表达式并加注释说明为何排除这三个字符 |
| 🟢 P3 | 帮助目标 `guide-authentication.html` 硬编码在代码里 | 方法 `on_screen_event` | 文档改名需改 ABAP 代码并重新发布 | 配置化或集中为常量；也可考虑改用 F1 帮助长文本以支持离线场景 |

---

## 六、整体评价与启发

### 6.1 优点

1. **把交互层外包给 SAP 内核，是这个文件最正确的判断。** 200 行代码里没有一行是自己画的控件，没有一行自己实现的焦点或 Tab 顺序。它承认"标准选择屏 + `MODIFY SCREEN` 已经是够用的模态对话框"，然后把全部创造力用在三个回调上。这是 senior engineer 的直觉：不要在 UI 基础设施上重复造轮子。
2. **凭据卫生贯穿始终。** 入口 `CLEAR p_pass` 防止上次残留外泄，出口 `CLEAR` 三个参数缩短驻留期，取消分支显式清空调用方的 `cv_*`（而不是"什么都不做"），密码字段 `screen-invisible`。四个动作方向一致：**任何"没拿到新凭据"的情况都必须表现为"清空"，不能表现为"沿用旧值"**。
3. **用 E 消息把弹窗钉在原地的设计非常克制。** 它没有为了"体验友好"而允许空凭据通过，而是选择了一条在语义上不可能被误认为成功的反馈通道，并在注释里写清了理由（"returning them is indistinguishable from cancelling the popup"）。**这种"为下游考虑的可观测性"是代码里最贵的品质之一。**
4. **失败方向的默认值选对了。** `gv_confirm` 的兜底分支、入口的复位、取消时的置假，三处都指向 `abap_false`。任何一个没走到预期分支的路径，结果都是"什么都没发生"，而不是"用半截数据继续"。

### 6.2 短板

1. **安全防线建立在字符串字面量之上。** 密码掩码靠 `screen-name = 'P_PASS'`，改名即失效且无任何提示。这是"方便改"与"改不坏"之间的典型取舍——这里选了方便，而它保护的是密码。
2. **URL 处理是整个组件最薄弱的一环。** 为省事用正则重造 URL 解析，结果把凭据一起吸进了标题；而项目内本就有 URL 相关的处理能力。同理，凭据传参类型（`c` 与 `string` 混用）、提示字段用 `PARAMETERS` 而非注释，都能看出**在"能跑就行"的惯性下积累的类型不一致**。
3. **契约在文件之外。** 回调派发机制、屏幕号、状态栏借用的来源程序，全部是隐式约定，且没有任何一处写在注释里。对一个要被别人 include 复用的组件来说，这是最容易踩坑的形态。

### 6.3 可学到的设计经验（4 条）

1. **能用标准机制换的，就别自己写。** 选择屏天生就是模态对话框：天自带 PBO/PAI、`sy-ucomm`、`MESSAGE E` 后重绘、`SET CURSOR`、`SET TITLEBAR`。识别出"现成机制已经覆盖了 80% 的需求"，然后只用 `LOOP AT SCREEN` + `MODIFY SCREEN` 补上那 20%（置灰、隐藏、状态栏），是这个文件最值得复制的思路。
2. **对话框的返回契约要想清楚，并且 fail-safe 方向要选对。** 没有返回值通道时，静态标志是标准解法；但更重要的判断是**"默认值是什么"**——确认类对话框的默认值必须是"取消"，这样所有未预期的路径都退化成"无害"，而不是"用错误数据继续做危险操作"。同理，"失败时清空输出缓冲区"与"失败时不赋值"是两种完全不同的语义。
3. **凭据的内存驻留时间是一等设计目标。** 密码在屏幕上的隐藏、在全局变量中的存活、在返回值中的传递、在日志中的缺席，这四件事需要被当作一个整体来设计。"进出双清空 + 取消分支显式清空 + 从不进消息"这三招，几乎可以原样搬到任何"从用户手里收敏感数据"的场景里。
4. **依赖名字约定的代码，必须把约定写进注释。** 三个 `on_screen_*` 的派发契约、屏幕行名与参数名的对应关系、状态栏借用的 `RSPFPAR` 来源——这些都是"编译器看不见、后人一改就崩"的隐性知识。**代码里最危险的不是复杂，而是那些看起来显然、实则只存在于作者脑子里的对应关系。**

---

*本报告严格基于 `abapGit__abapGit__zabapgit_password_dialog.prog.abap` 的实际源码内容撰写。所有问题定位均以子程序名称标注。*

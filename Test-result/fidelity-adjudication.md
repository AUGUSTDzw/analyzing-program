# 忠实度：16 条候选逐条定性

之前只验证了 3 条，剩 13 条悬着。现在全部定性，结论比预想严重。

## 分诊

`analyzing-programs-workspace/triage_fidelity.py`：对每条候选，打印源码里最接近的一行，
差异直接可见而不是靠推断。

分诊脚本自己有个 bug：探测串截断在 60 字符，`score` 永远超不过 60，
凡匹配 ≥60 字符的行都被判成 `genuine` —— 两条忠实行就是这样被误判的。
改成用整行做探测后，其中一条变回 `wrap`（101 字符公共前缀，忠实，只是折行不同）。

## 结果

| 判定 | 条数 |
|---|---|
| **实质失真** | **11** |
| 平凡：TYPES 头与字段行合并、句末 `.`→`;` | 3 |
| 忠实：折行不同、演示占位代码 | 3 |

**精确率 11/16 = 69%。**

## 三类实质失真

### 一、整段伪造（5 条，AVE L1124-1133）

报告写的：

```abap
READ TABLE gt_header_cache INTO DATA(ls_cached) WITH TABLE KEY trkorr = i_trkorr.
SELECT SINGLE trfunction, as4user, as4date, as4time, strkorr
  ...
  WHERE trkorr = @i_trkorr
  INTO (@DATA(lv_trfunction), @DATA(lv_as4user), @DATA(lv_as4date),
        @DATA(lv_as4time), @DATA(lv_strkorr)).
```

源码实际：

```abap
READ TABLE gt_header_cache INTO result WITH TABLE KEY trkorr = iv_trkorr.
SELECT e070~trfunction, e070~trstatus, e070~strkorr,
       e070~as4user, e070~as4date, e070~as4time, e07t~as4text
  INTO (@result-trfunction, @result-trstatus, @result-strkorr, ...)
  UPTO 1 ROWS
  FROM e070
  LEFT JOIN e07t ON e07t~trkorr = e070~trkorr
  WHERE e070~trkorr = @iv_trkorr
  ORDER BY e07t~as4text, e070~trstatus.
```

| 报告 | 源码 | 证据 |
|---|---|---|
| `i_trkorr` | `iv_trkorr` | `i_trkorr` **全源码 0 次**，`iv_trkorr` 45 次 |
| `SELECT SINGLE` | `UPTO 1 ROWS` + `EXIT` | 换了语句形式 |
| `@DATA(lv_as4user)` | `@result-as4user` | `lv_as4user` **0 次** |
| `INTO DATA(ls_cached)` | `INTO result` | 结构体分量改成内联声明 |
| 少了 `trstatus`、全部 `~` 限定、`LEFT JOIN` | — | 条件被删 |

参数名是**编的**。

### 二、语义反转（1 条，AVE L1597）—— 最严重

```abap
lt_new = ...load_ddls_source( i_objname = i_name i_versno = ls_latest-versno ).
lt_old = ...load_ddls_source( i_objname = i_name i_versno = ls_latest-versno ).  ← 报告
```

源码里 `lt_old` 用的是 **`ls_prior-versno`**。这段代码的全部意义就是比较新旧版本，
报告让它俩读同一个版本 —— **所引代码的含义被反转**，读者会得出相反结论。

这不是笔误，是把代码"改好看了"。

### 三、改写语句形式（5 条，AVE L740-743 + FI toolkit L1448）

`SWITCH #( ... WHEN x THEN expr )` 被改写成 `CASE. WHEN x. result = expr`；
`ftpost … is_bkpf-bldat` 被改成 `ls_bseg-bldat`（且报告自己引用的 SELECT 根本没选 `bldat`）。

## 关键：这 11 条全在通过闸门的报告里

AVE v1 那份通过了全部结构检查（六节、每块三层、四桶、Mermaid 可渲染），
密度诊断之外一切正常 —— 它含有**一段伪造的 SELECT 和一处语义反转**。

**这是"形状完好 ≠ 内容可信"最硬的证据**，也是之前那句
"闸门只管形状"从判断变成了实测。

## 处置：接成诊断项，不接成判定

69% 精确率不足以让报告失败（16 条里 3 条是标点/合并噪声）。
但足以值得一读 —— 与密度项同一个处理。

已在 `report_qc.py` 里实现（传入 source 时生效）：

```
note  11 quoted statement(s) of 1007 do not occur in the source.
      First at line 740: 'WHEN gc_type-class.   result = N... (+10 more).
      Check whether the report rewrote the source.
```

忠实报告（`abapgit_flow_logic`，62 条声明）**无误报**。
`tests/test_skill.py` 加了三项覆盖：忠实不报、改标识符要报、源码没有的要报。

其中一项首跑就失败 —— 我的合成 fixture 里没有 brief report 引用的那行，
所以"忠实"这个前提本身不成立。是 fixture 的错，不是检查的错，已修。

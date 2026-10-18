#!/usr/bin/env python3
"""
abap_deps_analyzer.py - ABAP 依赖分析器

功能:
1. 依赖关系分析 - 找出代码对随包标准库子集的类 / 接口类型引用
2. 待确认引用 - 索引里查不到的类型、方法、程序；一律标 info，不是缺陷判定
3. 未使用代码检测 - 启发式扫描未调用的方法和子程序

注意:
- 不解析 CALL FUNCTION / SELECT，函数模块、数据库表、数据元素测不到
- 随包的 abaplint-deps 是 abaplint/deps 的子集，
  「索引里没有」不等于「SAP 里没有」

使用:
    python abap_deps_analyzer.py <source.abap> [--deps <deps_dir>] [--format markdown|json] [--output <path>]
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


@dataclass
class StandardObject:
    """标准库对象信息"""
    name: str
    type: str  # class, interface, type, etc.
    path: str
    methods: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)


@dataclass
class Dependency:
    """依赖关系"""
    source_name: str
    target_name: str
    target_type: str
    usage_type: str  # type_reference, method_call, etc.
    location: str  # 子程序名或行号
    line_number: int


@dataclass
class Issue:
    """检测到的问题"""
    type: str  # unknown_type, unknown_method, signature_mismatch, etc.
    severity: str  # error, warning, info
    message: str
    location: str
    line_number: int
    suggestion: Optional[str] = None


@dataclass
class UnusedCode:
    """未使用的代码"""
    name: str
    type: str  # method, subroutine, form, etc.
    location: str
    line_number: int


# ABAP 运行时时序入口。它们在代码里没有调用点，报「未使用」是错的：
# CONSTRUCTOR 由 create object 触发，END_OF_PAGE 由分页触发，AT_LINE_SELECTION
# 由交互事件触发。谁都没有调用它们的语句可以写。
EVENT_NAMES = frozenset({
    'CONSTRUCTOR',
    'CLASS_CONSTRUCTOR',
    'DESTRUCTOR',
    'END_OF_PAGE',
    'AT_LINE_SELECTION',
    'AT_PAGING',
    'TOP_OF_PAGE',
    'END_OF_LIST',
    'AT_USER_COMMAND',
})


def _strip_comments(line: str) -> str:
    """去掉一行的注释部分。

    ABAP 里 " 起行内注释、* 起整行注释。" 不可能出现在字符串字面量里
    （字面量用单引号），所以按第一个 " 切就是对的。

    不剥注释就会把注释里的关键字当代码：「*appending values form final」
    会被读成 FORM FINAL，然后它永远不会被 PERFORM，于是稳定地报成未使用代码。
    """
    line = line.split('"', 1)[0]
    return '' if line.lstrip().startswith('*') else line


class ABAPDepsAnalyzer:
    """ABAP 依赖分析器"""

    def __init__(self, deps_dir: str):
        self.deps_dir = Path(deps_dir)
        self.standard_objects: Dict[str, StandardObject] = {}
        self.dependencies: List[Dependency] = []
        self.issues: List[Issue] = []
        self.unused_code: List[UnusedCode] = []
        self._build_index()

    def _build_index(self):
        """构建标准库索引"""
        if not self.deps_dir.exists():
            print(f"警告: deps 目录不存在: {self.deps_dir}")
            return

        print(f"正在索引标准库: {self.deps_dir}")

        for abap_file in self.deps_dir.rglob("*.abap"):
            try:
                content = abap_file.read_text(encoding='utf-8', errors='ignore')
                object_info = self._parse_object_file(abap_file, content)
                if object_info:
                    self.standard_objects[object_info.name.upper()] = object_info
            except Exception as e:
                print(f"警告: 无法解析文件 {abap_file}: {e}")

        print(f"索引完成: {len(self.standard_objects)} 个标准对象")

    def _parse_object_file(self, file_path: Path, content: str) -> Optional[StandardObject]:
        """解析单个对象文件"""
        # 使用完整文件名来确定对象类型和名称
        filename = file_path.name

        if filename.endswith('.clas.abap'):
            obj_type = 'class'
            obj_name = filename.replace('.clas.abap', '').upper()
        elif filename.endswith('.intf.abap'):
            obj_type = 'interface'
            obj_name = filename.replace('.intf.abap', '').upper()
        elif filename.endswith('.prog.abap'):
            obj_type = 'program'
            obj_name = filename.replace('.prog.abap', '').upper()
        else:
            return None

        obj = StandardObject(
            name=obj_name,
            type=obj_type,
            path=str(file_path.relative_to(self.deps_dir))
        )

        # 提取方法
        for match in re.finditer(r'(?:METHOD|FORM)\s+(\w+)', content, re.IGNORECASE):
            method_name = match.group(1).upper()
            if method_name not in obj.methods:
                obj.methods.append(method_name)

        # 提取属性
        for match in re.finditer(r'(?:DATA|TYPES|CONSTANTS)\s+(\w+)', content, re.IGNORECASE):
            attr_name = match.group(1).upper()
            if attr_name not in obj.attributes:
                obj.attributes.append(attr_name)

        return obj

    def analyze(self, source_file: str) -> dict:
        """分析源代码的依赖关系"""
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"源文件不存在: {source_file}")

        # 一个实例分析多份文件时不重置就会累加，第二份报告带上第一份的结论。
        # 三处都是 append 而不是赋值，所以这里必须显式清空。
        self.dependencies = []
        self.issues = []
        self.unused_code = []

        content = source_path.read_text(encoding='utf-8', errors='ignore')
        # 剥掉注释再交给三个扫描器，否则注释里的关键字会被当代码读。
        # 剥在前、不剥就白剥：三个扫描器各自再剥一次等于三处可以各自写错。
        content = '\n'.join(_strip_comments(line) for line in content.splitlines())
        print(f"分析文件: {source_file}")

        # 1. 提取引用
        self._extract_dependencies(content, source_path.name)

        # 2. 检测问题
        self._detect_issues(content, source_path.name)

        # 3. 检测未使用代码
        self._detect_unused_code(content, source_path.name)

        return {
            'dependencies': [self._dep_to_dict(d) for d in self.dependencies],
            'issues': [self._issue_to_dict(i) for i in self.issues],
            'unused_code': [self._unused_to_dict(u) for u in self.unused_code],
            'summary': self._generate_summary()
        }

    def _extract_dependencies(self, content: str, source_name: str):
        """提取依赖关系"""
        lines = content.split('\n')

        # 类引用 - 查找 TYPE REF TO 模式
        for i, line in enumerate(lines, 1):
            # TYPE REF TO 类名
            for match in re.finditer(r'\bTYPE\s+REF\s+TO\s+(\w+)', line, re.IGNORECASE):
                cls_name = match.group(1).upper()
                if cls_name in self.standard_objects:
                    self.dependencies.append(Dependency(
                        source_name=source_name,
                        target_name=cls_name,
                        target_type='class',
                        usage_type='type_reference',
                        location=f'line {i}',
                        line_number=i
                    ))

            # TYPE 类型引用 (非 REF TO)
            for match in re.finditer(r'\bTYPE\s+(\w+)', line, re.IGNORECASE):
                type_name = match.group(1).upper()
                # 排除 REF 关键字
                if type_name != 'REF' and type_name in self.standard_objects:
                    self.dependencies.append(Dependency(
                        source_name=source_name,
                        target_name=type_name,
                        target_type='type',
                        usage_type='type_reference',
                        location=f'line {i}',
                        line_number=i
                    ))

            # 接口引用
            for match in re.finditer(r'\bINTERFACES\s+(\w+)', line, re.IGNORECASE):
                intf_name = match.group(1).upper()
                if intf_name in self.standard_objects:
                    self.dependencies.append(Dependency(
                        source_name=source_name,
                        target_name=intf_name,
                        target_type='interface',
                        usage_type='interface_implementation',
                        location=f'line {i}',
                        line_number=i
                    ))

        # 方法调用
        for i, line in enumerate(lines, 1):
            # 方法调用: obj->method(
            for match in re.finditer(r'(\w+)->(\w+)\s*\(', line):
                obj_name = match.group(1).upper()
                method_name = match.group(2).upper()

                if obj_name in self.standard_objects:
                    self.dependencies.append(Dependency(
                        source_name=source_name,
                        target_name=obj_name,
                        target_type=self.standard_objects[obj_name].type,
                        usage_type='method_call',
                        location=f'line {i}: {method_name}',
                        line_number=i
                    ))

    def _local_type_names(self, content: str) -> Set[str]:
        """本文件内声明的类型名，统一大写。

        标准库索引里查不到的名字里，最大的一类根本不是外部依赖：局部类
        （lcl_x）、TYPES 定义、以及本文件自己声明的数据元素。把它们和「随包
        桩库里缺了这份」混为一谈，等于给每个用到局部类的文件都发一条假报警。
        """
        names: Set[str] = set()
        # CLASS x DEFINITION 后面的 FINAL / ABSTRACT / CREATE PUBLIC 是修饰，
        # 所以只要求 DEFINITION 出现在同一行的后半段。
        for pattern in (r'\bCLASS\s+([A-Za-z0-9_]+)(?=[^\n]*\bDEFINITION\b)',
                        r'\bINTERFACE\s+([A-Za-z0-9_]+)(?=[^\n]*\bDEFINITION\b)',
                        r'\b(?:TYPES?|CONSTANTS?|DATA)\s+([A-Za-z0-9_]+)'):
            for match in re.finditer(pattern, content, re.IGNORECASE):
                names.add(match.group(1).upper())
        return names

    def _detect_issues(self, content: str, source_name: str):
        """检测问题"""
        lines = content.split('\n')

        # 索引是 abaplint/deps 的一个子集，不是标准库本身。所以「不在索引里」
        # 只有两种解释：它确实不存在，或者随包桩库里缺了这份。这两种情况在输出里
        # 给同一个信号，写报告的人就分不清，因此一律标成 unresolved_* + info：
        # 这不是缺陷判定。
        local_types = self._local_type_names(content)
        bundle = len(self.standard_objects)

        # 检查 TYPE REF TO 引用的类是否存在
        for i, line in enumerate(lines, 1):
            # TYPE REF TO 类名
            for match in re.finditer(r'\bTYPE\s+REF\s+TO\s+(\w+)', line, re.IGNORECASE):
                type_name = match.group(1).upper()
                if type_name not in self.standard_objects and type_name not in local_types:
                    self.issues.append(Issue(
                        type='unresolved_type',
                        severity='info',
                        message=f'类型 {type_name} 不在随包的 {bundle} 个标准对象里',
                        location=f'line {i}',
                        line_number=i,
                        suggestion='可能是自定义类型，也可能只是随包桩库缺了这份；'
                                   'SAP 里很可能有，不要当作缺陷写进报告'
                    ))

            # TYPE 类型引用 (非 REF TO)
            for match in re.finditer(r'\bTYPE\s+(\w+)', line, re.IGNORECASE):
                type_name = match.group(1).upper()
                if type_name != 'REF' and type_name not in self.standard_objects:
                    # 可能是自定义类型，但如果是全大写且看起来像标准对象名，可能是问题
                    if (type_name.startswith('CL_') or type_name.startswith('IF_')
                            or type_name.startswith('CX_')) and type_name not in local_types:
                        self.issues.append(Issue(
                            type='unresolved_type',
                            severity='info',
                            message=f'类型 {type_name} 不在随包的 {bundle} 个标准对象里',
                            location=f'line {i}',
                            line_number=i,
                            suggestion='可能是自定义类型，也可能只是随包桩库缺了这份；'
                                       'SAP 里很可能有，不要当作缺陷写进报告'
                        ))

        # 检查方法调用
        for i, line in enumerate(lines, 1):
            # 方法调用: obj->method(
            for match in re.finditer(r'(\w+)->(\w+)\s*\(', line):
                obj_name = match.group(1).upper()
                method_name = match.group(2).upper()

                if obj_name in self.standard_objects:
                    obj = self.standard_objects[obj_name]
                    if method_name not in obj.methods:
                        # 随包的桩类只有骨架、几乎不声明方法，所以「桩里没有这个方法」
                        # 和「SAP 里没有这个方法」不是同一件事。
                        self.issues.append(Issue(
                            type='unresolved_method',
                            severity='info',
                            message=f'方法 {method_name} 未声明在 {obj_name} 的桩里',
                            location=f'line {i}',
                            line_number=i,
                            suggestion=f'随包桩类多为骨架、不列方法；'
                                       f'核对要用 {obj_name} 的真实接口定义，不要当作缺陷'
                        ))

        # 检查子程序调用
        for i, line in enumerate(lines, 1):
            # 检查 SUBMIT 调用
            for match in re.finditer(r'\bSUBMIT\s+(\w+)', line, re.IGNORECASE):
                prog_name = match.group(1).upper()
                if prog_name not in self.standard_objects:
                    self.issues.append(Issue(
                        type='unresolved_program',
                        severity='info',
                        message=f'程序 {prog_name} 不在随包的 {bundle} 个标准对象里',
                        location=f'line {i}',
                        line_number=i,
                        suggestion='SUBMIT 的目标通常是自定义 Z 程序，'
                                   '本来就不该在标准库里；不要当作缺陷写进报告'
                    ))
    def _detect_unused_code(self, content: str, source_name: str):
        """检测未使用的代码

        这是启发式，不是调用图。漏报比错报安全：把一个真被调用的子程序报成
        死代码，读者会去删一个还活着的 FORM；反过来漏掉一个真死代码，报告里
        只是一句没说出来。所以「调用」一侧从宽认定。
        """
        lines = content.split('\n')

        defined_forms = set()
        defined_methods = set()
        called_forms = set()
        called_methods = set()

        # 先收齐全部定义，再收调用。类实现体内可以在方法定义之前就调用它
        # （见下方裸调用），单遍按行扫描会把「在定义前面被调过」的方法错报成未使用。
        for line in lines:
            for match in re.finditer(r'\bFORM\s+(\w+)', line, re.IGNORECASE):
                defined_forms.add(match.group(1).upper())
            # CALL METHOD ref->foo 里的 METHOD ref 不是定义，是调用。
            for match in re.finditer(r'(?<!CALL )\bMETHOD\s+(\w+)', line, re.IGNORECASE):
                defined_methods.add(match.group(1).upper())

        for line in lines:
            # PERFORM 有两种写法：PERFORM foo. 与 PERFORM : foo. / PERFORM: foo.
            # 漏掉冒号式会把整类老写法都读成「从未被调用」。
            for match in re.finditer(r'\bPERFORM\s*(?::\s*|\s+)(\w+)', line, re.IGNORECASE):
                called_forms.add(match.group(1).upper())

            # 动态形式名 PERFORM (dynpro) 抓不到也没关系：它本身无法静态判定。
            # 实例调用 obj->method( 与静态调用 cl_x=>method( )。
            # 写成 ->+ 覆盖 -> 与 ->>；=>+ 覆盖 => 与 =>>。
            # 注意必须是 ->+ 而不是 ->>+：后者要求两个 > 起，会把所有实例
            # 调用都漏掉，于是「被 -> 调过的方法」全被报成未使用。
            for match in re.finditer(r'(\w+)\s*(?:=>+|->+)\s*(\w+)\s*\(', line):
                called_methods.add(match.group(2).upper())

            # 类实现体内的裸调用：set_tol( ) 调本类方法，前面没有 ->。
            # 只认本文件自己定义过的方法名，避免把关键字（IF (、COND (）当调用。
            for match in re.finditer(r'(?<![->.\w])([A-Za-z_][A-Za-z0-9_]*)\s*\(', line):
                name = match.group(1).upper()
                if name in defined_methods:
                    called_methods.add(name)

        # ALV 回调与 slis_t_events 以字符串字面量引用 FORM，代码里没有 PERFORM。
        # 字面量集合只与本文件定义过的 FORM 名求交，所以不会误伤别处的字符串。
        for match in re.finditer(r"'([A-Za-z0-9_]+)'", content):
            name = match.group(1).upper()
            if name in defined_forms:
                called_forms.add(name)

        for form_name in sorted((defined_forms - called_forms) - EVENT_NAMES):
            for i, line in enumerate(lines, 1):
                if re.search(rf'\bFORM\s+{form_name}\b', line, re.IGNORECASE):
                    self.unused_code.append(UnusedCode(
                        name=form_name,
                        type='form',
                        location=f'line {i}',
                        line_number=i
                    ))
                    break

        for method_name in sorted((defined_methods - called_methods) - EVENT_NAMES):
            for i, line in enumerate(lines, 1):
                if re.search(rf'(?<!CALL )\bMETHOD\s+{method_name}\b', line, re.IGNORECASE):
                    self.unused_code.append(UnusedCode(
                        name=method_name,
                        type='method',
                        location=f'line {i}',
                        line_number=i
                    ))
                    break

    def _dep_to_dict(self, dep: Dependency) -> dict:
        return {
            'source': dep.source_name,
            'target': dep.target_name,
            'target_type': dep.target_type,
            'usage_type': dep.usage_type,
            'location': dep.location,
            'line_number': dep.line_number
        }

    def _issue_to_dict(self, issue: Issue) -> dict:
        return {
            'type': issue.type,
            'severity': issue.severity,
            'message': issue.message,
            'location': issue.location,
            'line_number': issue.line_number,
            'suggestion': issue.suggestion
        }

    def _unused_to_dict(self, unused: UnusedCode) -> dict:
        return {
            'name': unused.name,
            'type': unused.type,
            'location': unused.location,
            'line_number': unused.line_number
        }

    def _generate_summary(self) -> dict:
        """生成摘要"""
        return {
            'total_dependencies': len(self.dependencies),
            'unique_targets': len(set(d.target_name for d in self.dependencies)),
            'total_issues': len(self.issues),
            'errors': len([i for i in self.issues if i.severity == 'error']),
            'warnings': len([i for i in self.issues if i.severity == 'warning']),
            'info': len([i for i in self.issues if i.severity == 'info']),
            'total_unused_code': len(self.unused_code)
        }


def format_markdown(result: dict) -> str:
    """格式化为 Markdown"""
    lines = []
    lines.append("# ABAP 依赖分析报告\n")

    # 摘要
    lines.append("## 摘要\n")
    summary = result['summary']
    lines.append(f"- 依赖总数: {summary['total_dependencies']}")
    lines.append(f"- 标准对象引用: {summary['unique_targets']}")
    lines.append(f"- 待确认项: {summary['total_issues']}")
    lines.append(f"  - 错误: {summary['errors']}")
    lines.append(f"  - 警告: {summary['warnings']}")
    lines.append(f"  - 提示: {summary['info']}")
    lines.append(f"- 未使用代码: {summary['total_unused_code']}（启发式，仅供人工复核）")
    lines.append("")

    # 依赖关系
    lines.append("## 依赖关系\n")
    if result['dependencies']:
        lines.append("| 来源 | 目标 | 类型 | 使用方式 | 位置 |")
        lines.append("|------|------|------|----------|------|")
        for dep in result['dependencies']:
            lines.append(f"| {dep['source']} | {dep['target']} | {dep['target_type']} | {dep['usage_type']} | {dep['location']} |")
    else:
        lines.append("未检测到对标准库的依赖")
    lines.append("")

    # 问题
    lines.append("## 待确认的引用（非缺陷判定）\n")
    if result['issues']:
        for issue in result['issues']:
            icon = '❌' if issue['severity'] == 'error' else '⚠️' if issue['severity'] == 'warning' else 'ℹ️'
            lines.append(f"### {icon} {issue['message']}")
            lines.append(f"- **类型**: {issue['type']}")
            lines.append(f"- **严重性**: {issue['severity']}")
            lines.append(f"- **位置**: {issue['location']}")
            if issue['suggestion']:
                lines.append(f"- **建议**: {issue['suggestion']}")
            lines.append("")
    else:
        lines.append("未检测到待确认的引用")
    lines.append("")

    # 未使用代码
    lines.append("## 未使用的代码（启发式）\n")
    if result['unused_code']:
        lines.append("| 名称 | 类型 | 位置 |")
        lines.append("|------|------|------|")
        for unused in result['unused_code']:
            lines.append(f"| {unused['name']} | {unused['type']} | {unused['location']} |")
    else:
        lines.append("所有代码都被使用")
    lines.append("")

    return '\n'.join(lines)


def format_json(result: dict) -> str:
    """格式化为 JSON"""
    return json.dumps(result, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='ABAP 依赖分析器')
    parser.add_argument('source', help='ABAP 源文件路径')
    parser.add_argument('--deps', default=None,
                        help='abaplint/deps 目录路径；省略时用随包副本')
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown', help='输出格式')
    parser.add_argument('--output', '-o', help='输出文件路径')

    args = parser.parse_args()

    # 解析依赖目录。依赖随本 skill 一起发布在 skill 根下（与 scripts/ 同级），
    # 装好的 skill 里 CWD 几乎从不是 skill 目录，所以默认值必须按脚本自身位置
    # 推导。
    #
    # 关键在「默认值不能按 CWD 解析」：CWD 里只要恰好存在一个 abaplint-deps/src
    # （比如按下面的兜底指引自己克隆了一份）就会静默取代随包副本。一次分析比对
    # 的是哪 184 个标准对象，整个输出都跟着变，而命令行上看不出来。
    # 显式 --deps 失效时仍然回落，但回落必须被说出来。
    skill_dir = Path(__file__).resolve().parent.parent
    possible_paths = [
        skill_dir / 'abaplint-deps' / 'src',  # 随本 skill 发布，唯一权威
        Path.cwd() / 'abaplint-deps' / 'src',  # 当前工作目录
        Path.cwd() / 'skill' / 'analyzing-programs' / 'abaplint-deps' / 'src',
    ]

    deps_dir = None
    if args.deps:
        if Path(args.deps).exists():
            deps_dir = Path(args.deps)
        else:
            print(f"提示: --deps 指向的目录不存在，回落到随包副本: {args.deps}")
    if deps_dir is None:
        for path in possible_paths:
            if path.exists():
                deps_dir = path
                break
    if deps_dir is None:
        # 依赖应当已经随 skill 打进来；到这里说明这份安装不完整，
        # 而不是用户没克隆仓库。所以先报"安装缺失"，克隆指引只作兜底。
        print("error  依赖目录不存在，本次分析未运行")
        print(f"尝试的路径: {args.deps}")
        for path in possible_paths:
            print(f"  {path}")
        print("本 skill 应当自带 abaplint-deps/，请确认安装完整，"
              "或用 --deps 指向 abaplint/deps 的 src 目录")
        print("  git clone https://github.com/abaplint/deps.git abaplint-deps")
        # 退 2 而不是 1：1 在本项目里是「跑完了、有缺陷」，而这里一个字都没比。
        # 只看退出码的调用方会把「没跑」读成「有缺陷」。
        sys.exit(2)

    if os.path.isdir(args.source):
        # docgen.py 与 report_qc.py 对同一种输入各有自己的拒绝消息，这里是同一次
        # 拒绝换了个形状。放任它走到 analyze() 里的 open()，两个平台都会抛
        # IsADirectoryError，被下面 except Exception 原样打出：文案既跟契约里
        # error  <path> 的形状对不上，也会让人去改一个其实没错的路径。
        print(f"error  {args.source} 是一个目录，不是源码文件，本次分析未运行")
        print("分析器需要一个 .abap 文件；要分析目录里的程序，先从中选一个文件。")
        sys.exit(2)

    try:
        # 创建分析器
        analyzer = ABAPDepsAnalyzer(str(deps_dir))

        # 分析
        result = analyzer.analyze(args.source)

        # 格式化输出
        if args.format == 'markdown':
            output = format_markdown(result)
        else:
            output = format_json(result)

        # 输出
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"报告已保存到: {args.output}")
        else:
            print(output)

        # 退出码：跑完就是 0，不管查到几条。
        #
        # 这里曾经是 `if summary['errors'] > 0: sys.exit(1)`，但那行永远到不了：
        # severity 的取值只有 'info'（四处 Issue 构造点写的都是 info），所以 errors
        # 恒为 0。更要紧的是语义：本分析器报的是「待确认的引用（非缺陷判定）」，
        # 不是缺陷。在本项目里退出码 1 的意思是「跑完了、有缺陷」，一个只报
        # 待确认项的工具用那个码会让只看退出码的调用方把「有 2 条待确认」读成
        # 「什么都没查到」，或者反过来。要看有没有待确认项，读正文的「待确认项」
        # 计数；本工具的退出码只区分「跑完了」(0) 和「没跑」(2)。
        #
        # 摘要里的 错误 / 警告 两行因此恒为 0，是预留字段（severity 将来分级时
        # 会用到），不是漏报。

    except FileNotFoundError as e:
        # 源文件或输出目录不存在：一个字都没比，所以是拒绝，不是缺陷。
        # 此前退 1，而 1 是「跑完了、有缺陷」。
        print(f"error  {e}")
        sys.exit(2)
    except Exception as e:
        print(f"error  {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
abap_deps_analyzer.py - ABAP 依赖分析器

功能:
1. 依赖关系分析 - 找出代码对标准库的依赖
2. 增强问题检测 - 检测引用不存在的类型、方法签名不匹配
3. 未使用代码检测 - 识别未调用的方法和子程序

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

        content = source_path.read_text(encoding='utf-8', errors='ignore')
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

    def _detect_issues(self, content: str, source_name: str):
        """检测问题"""
        lines = content.split('\n')

        # 检查 TYPE REF TO 引用的类是否存在
        for i, line in enumerate(lines, 1):
            # TYPE REF TO 类名
            for match in re.finditer(r'\bTYPE\s+REF\s+TO\s+(\w+)', line, re.IGNORECASE):
                type_name = match.group(1).upper()
                if type_name not in self.standard_objects:
                    self.issues.append(Issue(
                        type='unknown_type',
                        severity='warning',
                        message=f'类型 {type_name} 未在标准库中找到',
                        location=f'line {i}',
                        line_number=i,
                        suggestion='确认类型是否存在或是否已添加到 deps'
                    ))

            # TYPE 类型引用 (非 REF TO)
            for match in re.finditer(r'\bTYPE\s+(\w+)', line, re.IGNORECASE):
                type_name = match.group(1).upper()
                if type_name != 'REF' and type_name not in self.standard_objects:
                    # 可能是自定义类型，但如果是全大写且看起来像标准对象名，可能是问题
                    if type_name.startswith('CL_') or type_name.startswith('IF_') or type_name.startswith('CX_'):
                        self.issues.append(Issue(
                            type='unknown_type',
                            severity='warning',
                            message=f'类型 {type_name} 未在标准库中找到',
                            location=f'line {i}',
                            line_number=i,
                            suggestion='确认类型是否存在或是否已添加到 deps'
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
                        self.issues.append(Issue(
                            type='unknown_method',
                            severity='warning',
                            message=f'方法 {method_name} 不存在于 {obj_name}',
                            location=f'line {i}',
                            line_number=i,
                            suggestion=f'检查 {obj_name} 的可用方法列表'
                        ))

        # 检查子程序调用
        for i, line in enumerate(lines, 1):
            # 检查 SUBMIT 调用
            for match in re.finditer(r'\bSUBMIT\s+(\w+)', line, re.IGNORECASE):
                prog_name = match.group(1).upper()
                if prog_name not in self.standard_objects:
                    self.issues.append(Issue(
                        type='unknown_program',
                        severity='warning',
                        message=f'程序 {prog_name} 未在标准库中找到',
                        location=f'line {i}',
                        line_number=i,
                        suggestion='确认程序是否存在或是否已添加到 deps'
                    ))
    def _detect_unused_code(self, content: str, source_name: str):
        """检测未使用的代码"""
        lines = content.split('\n')

        # 收集所有定义的子程序/方法
        defined_forms = set()
        defined_methods = set()
        called_forms = set()
        called_methods = set()

        for i, line in enumerate(lines, 1):
            # 定义
            for match in re.finditer(r'\bFORM\s+(\w+)', line, re.IGNORECASE):
                defined_forms.add(match.group(1).upper())

            for match in re.finditer(r'\bMETHOD\s+(\w+)', line, re.IGNORECASE):
                defined_methods.add(match.group(1).upper())

            # 调用
            for match in re.finditer(r'\bPERFORM\s+(\w+)', line, re.IGNORECASE):
                called_forms.add(match.group(1).upper())

            for match in re.finditer(r'(\w+)->(\w+)\s*\(', line):
                called_methods.add(match.group(2).upper())

        # 检测未使用的 FORM
        for form_name in defined_forms - called_forms:
            # 找到定义位置
            for i, line in enumerate(lines, 1):
                if re.search(rf'\bFORM\s+{form_name}\b', line, re.IGNORECASE):
                    self.unused_code.append(UnusedCode(
                        name=form_name,
                        type='form',
                        location=f'line {i}',
                        line_number=i
                    ))
                    break

        # 检测未使用的方法
        for method_name in defined_methods - called_methods:
            for i, line in enumerate(lines, 1):
                if re.search(rf'\bMETHOD\s+{method_name}\b', line, re.IGNORECASE):
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
    lines.append(f"- 问题总数: {summary['total_issues']}")
    lines.append(f"  - 错误: {summary['errors']}")
    lines.append(f"  - 警告: {summary['warnings']}")
    lines.append(f"- 未使用代码: {summary['total_unused_code']}")
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
    lines.append("## 检测到的问题\n")
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
        lines.append("未检测到问题")
    lines.append("")

    # 未使用代码
    lines.append("## 未使用的代码\n")
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
    parser.add_argument('--deps', default='abaplint-deps/src', help='abaplint/deps 目录路径')
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown', help='输出格式')
    parser.add_argument('--output', '-o', help='输出文件路径')

    args = parser.parse_args()

    # 解析依赖目录
    deps_dir = Path(args.deps)
    if not deps_dir.exists():
        # 尝试多个可能的路径
        possible_paths = [
            Path(__file__).parent.parent.parent.parent / 'abaplint-deps' / 'src',  # 从项目根目录
            Path.cwd() / 'abaplint-deps' / 'src',  # 当前工作目录
            Path.cwd() / 'skill' / 'analyzing-programs' / 'abaplint-deps' / 'src',  # skill 目录下
        ]
        
        for path in possible_paths:
            if path.exists():
                deps_dir = path
                break
        else:
            print(f"错误: 依赖目录不存在")
            print(f"尝试的路径: {args.deps}")
            print("请先克隆 abaplint/deps: git clone https://github.com/abaplint/deps.git abaplint-deps")
            sys.exit(1)

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

        # 退出码
        if result['summary']['errors'] > 0:
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()
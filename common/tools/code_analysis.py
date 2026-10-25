"""基于 AST 的 Python 静态分析工具。

检测常见代码缺陷与坏味道，所有结果均带行号，供 LLM 审查时引用。
"""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, asdict

MAX_FUNC_LINES = 50
MAX_FUNC_ARGS = 6

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token)\s*=\s*['\"][^'\"]{4,}['\"]"
)


@dataclass
class Issue:
    rule: str        # 规则标识，如 mutable-default-arg
    severity: str    # high / medium / low
    line: int
    message: str


class _Analyzer(ast.NodeVisitor):
    def __init__(self, source: str) -> None:
        self.issues: list[Issue] = []
        self.source = source
        self._imports: list[tuple[str, int]] = []

    # ---------- 函数级检查 ----------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_function(self, node) -> None:
        # 可变默认参数
        defaults = list(node.args.defaults) + list(node.args.kw_defaults)
        for d in defaults:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                self.issues.append(Issue(
                    "mutable-default-arg", "high", node.lineno,
                    f"函数 `{node.name}` 使用了可变对象作为默认参数，默认参数在函数间共享，"
                    "容易引发隐蔽 Bug，建议改用 None 并在函数体内初始化",
                ))
        # 函数过长
        if node.end_lineno and node.end_lineno - node.lineno + 1 > MAX_FUNC_LINES:
            self.issues.append(Issue(
                "function-too-long", "medium", node.lineno,
                f"函数 `{node.name}` 长达 {node.end_lineno - node.lineno + 1} 行"
                f"（阈值 {MAX_FUNC_LINES} 行），建议拆分为多个职责单一的函数",
            ))
        # 参数过多
        n_args = len(node.args.args) + len(node.args.kwonlyargs)
        if n_args > MAX_FUNC_ARGS:
            self.issues.append(Issue(
                "too-many-args", "low", node.lineno,
                f"函数 `{node.name}` 有 {n_args} 个参数（阈值 {MAX_FUNC_ARGS} 个），"
                "建议用配置对象或 dataclass 聚合参数",
            ))
        # 缺少文档字符串
        if ast.get_docstring(node) is None and not node.name.startswith("_"):
            self.issues.append(Issue(
                "missing-docstring", "low", node.lineno,
                f"公开函数 `{node.name}` 缺少文档字符串（docstring）",
            ))

    # ---------- 异常处理 ----------
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.issues.append(Issue(
                "bare-except", "high", node.lineno,
                "裸 `except:` 会捕获包括 KeyboardInterrupt 在内的所有异常，"
                "掩盖真实错误，建议捕获具体异常类型",
            ))
        elif isinstance(node.type, ast.Name) and node.type.id == "Exception" and (
            isinstance(node.body[0], ast.Pass) if node.body else False
        ):
            self.issues.append(Issue(
                "swallowed-exception", "high", node.lineno,
                "`except Exception: pass` 吞掉了异常且无任何日志，问题难以排查",
            ))
        self.generic_visit(node)

    # ---------- 危险调用 ----------
    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            self.issues.append(Issue(
                "eval-exec-usage", "high", node.lineno,
                f"使用了 `{node.func.id}()`，存在代码注入风险，"
                "建议使用 ast.literal_eval 或显式解析逻辑替代",
            ))
        self.generic_visit(node)

    # ---------- 全局变量 ----------
    def visit_Global(self, node: ast.Global) -> None:
        self.issues.append(Issue(
            "global-statement", "medium", node.lineno,
            f"使用 global 修改全局变量 {node.names}，破坏封装性，建议通过参数或类属性传递状态",
        ))
        self.generic_visit(node)

    # ---------- 导入 ----------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._imports.append(((alias.asname or alias.name).split(".")[0], node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self._imports.append((alias.asname or alias.name, node.lineno))
        self.generic_visit(node)

    def check_unused_imports(self) -> None:
        tree_text = self.source
        for name, line in self._imports:
            # 去除 import 行自身后查找使用
            uses = sum(1 for l in tree_text.splitlines() if re.search(rf"\b{re.escape(name)}\b", l))
            if uses <= 1:
                self.issues.append(Issue(
                    "unused-import", "low", line,
                    f"导入的 `{name}` 未被使用，建议删除",
                ))

    def check_hardcoded_secrets(self) -> None:
        for i, line in enumerate(self.source.splitlines(), 1):
            if _SECRET_PATTERN.search(line):
                self.issues.append(Issue(
                    "hardcoded-secret", "high", i,
                    "疑似硬编码的密钥/密码，应改为环境变量或配置中心管理",
                ))


def _load_source(path: str | None, code: str | None) -> tuple[str | None, str | None]:
    """返回 (源码, 错误信息)。"""
    if path:
        if not os.path.isfile(path):
            return None, f"文件不存在: {path}"
        try:
            with open(path, encoding="utf-8") as f:
                return f.read(), None
        except UnicodeDecodeError:
            return None, f"文件编码无法解析（非 UTF-8）: {path}"
    if code:
        return code, None
    return None, "必须提供 path 或 code 参数之一"


def analyze_code(path: str | None = None, code: str | None = None) -> str:
    """AST 静态分析入口。"""
    source, err = _load_source(path, code)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return json.dumps(
            {"error": f"语法错误，无法分析: 第 {exc.lineno} 行: {exc.msg}"}, ensure_ascii=False
        )

    analyzer = _Analyzer(source)
    analyzer.visit(tree)
    analyzer.check_unused_imports()
    analyzer.check_hardcoded_secrets()
    analyzer.issues.sort(key=lambda i: i.line)
    return json.dumps(
        {
            "issue_count": len(analyzer.issues),
            "issues": [asdict(i) for i in analyzer.issues],
        },
        ensure_ascii=False,
        indent=2,
    )


def syntax_check(path: str | None = None, code: str | None = None) -> str:
    """语法检查入口。"""
    source, err = _load_source(path, code)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)
    try:
        compile(source, path or "<input>", "exec")
        return json.dumps({"ok": True, "message": "语法检查通过"}, ensure_ascii=False)
    except SyntaxError as exc:
        return json.dumps(
            {"ok": False, "line": exc.lineno, "message": exc.msg, "text": (exc.text or "").strip()},
            ensure_ascii=False,
        )

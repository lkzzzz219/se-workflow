"""文件操作工具：读取源代码、列举目录。"""

from __future__ import annotations

import json
import os

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt",
}

MAX_LINES = 400
MAX_FILE_SIZE = 200 * 1024  # 200 KB


def read_file(path: str) -> str:
    """读取源代码文件内容，附加行号，超长截断。"""
    if not os.path.isfile(path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    if os.path.getsize(path) > MAX_FILE_SIZE:
        return json.dumps({"error": f"文件过大（>{MAX_FILE_SIZE // 1024}KB），请指定更小的文件"}, ensure_ascii=False)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except UnicodeDecodeError:
        return json.dumps({"error": f"文件编码无法解析（非 UTF-8）: {path}"}, ensure_ascii=False)

    truncated = len(lines) > MAX_LINES
    numbered = [f"{i:>4} | {line}" for i, line in enumerate(lines[:MAX_LINES], 1)]
    return json.dumps(
        {
            "path": path,
            "total_lines": len(lines),
            "truncated": truncated,
            "content": "\n".join(numbered),
        },
        ensure_ascii=False,
    )


def list_files(directory: str, max_files: int = 50) -> str:
    """递归列出目录下的源代码文件。"""
    if not os.path.isdir(directory):
        return json.dumps({"error": f"目录不存在: {directory}"}, ensure_ascii=False)
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    files: list[str] = []
    for root, dirs, names in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in CODE_EXTENSIONS:
                files.append(os.path.relpath(os.path.join(root, name), directory))
                if len(files) >= max_files:
                    break
        if len(files) >= max_files:
            break
    return json.dumps({"directory": directory, "count": len(files), "files": files}, ensure_ascii=False)

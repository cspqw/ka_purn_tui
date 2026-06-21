# ── 文件操作工具 ─────────────────────────────────
"""文件工具：create_novel_folder / create_novel_file / write_file / append_to_file。

所有路径相对于当前小说项目根目录，沙箱校验防越权。
写操作后更新 NovelState.current_file / current_file_content / file_tree，
触发右侧 FilePreviewPanel 与 FileTreePanel 实时刷新。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..state.novel_state import NovelState
from .registry import ToolDef


def _resolve(state: NovelState, rel_path: str) -> Path | None:
    """把相对路径解析到项目根内，越权返回 None。"""
    if state.project_root is None:
        return None
    root = state.project_root.resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def _refresh_file_tree(state: NovelState) -> None:
    """重新扫描项目根，刷新 file_tree。"""
    if state.project_root is None or not state.project_root.exists():
        state.file_tree = []
        return
    from ..state.novel_state import FileNode

    def build(path: Path) -> FileNode:
        node = FileNode(
            name=path.name,
            path=str(path.relative_to(state.project_root.resolve())),
            is_dir=path.is_dir(),
        )
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                # 放行 .Project（工程文件目录可见），隐藏其他 dotfile
                if child.name.startswith(".") and child.name != ".Project":
                    continue
                node.children.append(build(child))
        return node

    state.file_tree = [build(state.project_root.resolve())]


def _set_current(state: NovelState, rel_path: str, content: str) -> None:
    state.current_file = rel_path
    state.current_file_content = content
    # 模型操作文件时，预览切回 model 模式，显示该文件
    state.preview_file = rel_path
    state.preview_content = content
    state.preview_source = "model"
    _refresh_file_tree(state)


def _create_novel_folder(state: NovelState, args: dict[str, Any]) -> str:
    path = args.get("path", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}（请先 /novel new 创建项目）"
    try:
        target.mkdir(parents=True, exist_ok=True)
        _refresh_file_tree(state)
        return f"已创建文件夹: {path}"
    except Exception as e:  # noqa: BLE001
        return f"创建文件夹失败: {e}"


def _create_novel_file(state: NovelState, args: dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}（请先 /novel new 创建项目）"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return f"文件已存在: {path}"
        target.write_text(content, encoding="utf-8")
        _set_current(state, path, content)
        return f"已创建文件: {path}"
    except Exception as e:  # noqa: BLE001
        return f"创建文件失败: {e}"


def _write_file(state: NovelState, args: dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}（请先 /novel new 创建项目）"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _set_current(state, path, content)
        return f"已写入文件: {path}（{len(content)} 字）"
    except Exception as e:  # noqa: BLE001
        return f"写入文件失败: {e}"


def _append_to_file(state: NovelState, args: dict[str, Any]) -> str:
    """追加内容到文件——写章节正文的核心，多次调用让用户实时看到内容增长。"""
    path = args.get("path", "")
    text = args.get("text", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}（请先 /novel new 创建项目）"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 读取现有内容（不存在则空）
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        new_content = existing + text
        target.write_text(new_content, encoding="utf-8")
        _set_current(state, path, new_content)
        return f"已追加到 {path}（+{len(text)} 字，共 {len(new_content)} 字）"
    except Exception as e:  # noqa: BLE001
        return f"追加文件失败: {e}"


def _edit_file(state: NovelState, args: dict[str, Any]) -> str:
    """增量编辑文件，避免每次重写整个文件。

    三种模式：
      - replace:  查找替换（find → replace，可多处）
      - lines:    替换指定行范围（start_line..end_line → text）
      - insert_after: 在 after_line 行后插入 text
    """
    path = args.get("path", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}"
    if not target.exists():
        return f"文件不存在: {path}（请先 create_novel_file）"
    try:
        content = target.read_text(encoding="utf-8")
        mode = args.get("mode", "replace")

        if mode == "replace":
            find = args.get("find", "")
            replace = args.get("replace", "")
            if not find:
                return "find 不能为空"
            if find not in content:
                return f"未找到要替换的内容（{len(find)} 字）"
            count = content.count(find)
            new_content = content.replace(find, replace)
            info = f"替换 {count} 处"

        elif mode == "lines":
            start = int(args.get("start_line", 1))
            end = int(args.get("end_line", start))
            text = args.get("text", "")
            lines = content.splitlines(keepends=True)
            if start < 1 or end > len(lines) or start > end:
                return f"行号越界（文件共 {len(lines)} 行）"
            replaced = "".join(lines[start - 1 : end])
            new_lines = lines[: start - 1] + ([text + "\n"] if text else []) + lines[end:]
            new_content = "".join(new_lines)
            info = f"替换第 {start}-{end} 行（删 {len(replaced)} 字）"

        elif mode == "insert_after":
            line = int(args.get("after_line", 0))
            text = args.get("text", "")
            lines = content.splitlines(keepends=True)
            if line < 0 or line > len(lines):
                return f"行号越界（文件共 {len(lines)} 行）"
            new_lines = lines[:line] + ([text + "\n"] if text else []) + lines[line:]
            new_content = "".join(new_lines)
            info = f"在第 {line} 行后插入"

        else:
            return f"未知模式: {mode}（支持 replace/lines/insert_after）"

        target.write_text(new_content, encoding="utf-8")
        _set_current(state, path, new_content)
        return f"已编辑 {path}（{info}，现 {len(new_content)} 字）"
    except Exception as e:  # noqa: BLE001
        return f"编辑文件失败: {e}"


def _delete_file(state: NovelState, args: dict[str, Any]) -> str:
    """将项目内文件移至 .pr/pre-delete/ 预删除区域。

    文件不会立即删除，而是移动到 .pr/pre-delete/ 目录下并打上预删除标签。
    模型仍可通过 read_file 读取预删除区域内的文件（路径如 .pr/pre-delete/ch01.md）。
    对话结束后：
    - 用户回复"确认删除"：所有预删除文件移至回收站
    - 用户拒绝：所有预删除文件恢复到原位
    - 用户无响应：文件继续留在预删除区域
    """
    path = args.get("path", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}"
    if not target.exists():
        return f"文件不存在: {path}"
    if target.is_dir():
        try:
            next(target.iterdir())
            return f"目录非空，无法删除: {path}"
        except StopIteration:
            pass  # 空目录，允许删除

    # 创建预删除目录
    pre_delete_dir = state.project_root / ".pr" / "pre-delete"
    try:
        pre_delete_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"创建预删除目录失败: {e}"

    # 移动到预删除区域（同名冲突时加时间戳）
    dest = pre_delete_dir / target.name
    if dest.exists():
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = pre_delete_dir / f"{ts}_{target.name}"

    try:
        import shutil
        shutil.move(str(target), str(dest))
    except Exception as e:
        return f"移动文件到预删除区域失败: {e}"

    # 记录预删除项
    state._pre_delete_items.append({
        "original": target,
        "pre_delete": dest,
        "display": path,
    })
    _refresh_file_tree(state)

    count = len(state._pre_delete_items)
    return (
        f"[预删除] 已移动 {path} → .pr/pre-delete/{dest.name}"
        f"（共 {count} 个预删除文件）。\n"
        f"文件仍可通过 read_file('.pr/pre-delete/{dest.name}') 读取。\n"
        f"用户回复\"确认删除\"将所有预删除文件移至回收站，"
        f"回复其他内容则恢复所有预删除文件。"
    )


def _rename_file(state: NovelState, args: dict[str, Any]) -> str:
    """重命名项目内的文件或文件夹。"""
    path = args.get("path", "")
    new_name = args.get("new_name", "")
    if not new_name:
        return "new_name 不能为空"
    # 禁止包含路径分隔符，只允许单纯的文件名/目录名
    if "/" in new_name or "\\" in new_name:
        return f"new_name 必须为单纯的文件名/目录名，不能包含路径: {new_name}"
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}"
    if not target.exists():
        return f"不存在: {path}"
    new_target = target.parent / new_name
    if new_target.exists():
        return f"目标已存在: {new_name}"
    try:
        target.rename(new_target)
        _refresh_file_tree(state)
        # 如果正在预览的文件被改名，更新预览路径
        if state.preview_file and _resolve(state, state.preview_file) == target:
            state.preview_file = str(new_target.relative_to(state.project_root.resolve()))
        return f"已重命名: {path} → {new_name}"
    except Exception as e:  # noqa: BLE001
        return f"重命名失败: {e}"


def _move_file(state: NovelState, args: dict[str, Any]) -> str:
    """将文件/文件夹移动到指定目录。"""
    path = args.get("path", "")
    dest_dir = args.get("dest_dir", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}"
    if not target.exists():
        return f"不存在: {path}"
    dest = _resolve(state, dest_dir)
    if dest is None:
        return f"目标目录无效或越权: {dest_dir}"
    if not dest.exists():
        return f"目标目录不存在: {dest_dir}（请先用 create_novel_folder 创建）"
    if not dest.is_dir():
        return f"目标不是目录: {dest_dir}"
    new_path = dest / target.name
    if new_path.exists():
        return f"目标已存在同名文件/文件夹: {new_path.name}"
    try:
        import shutil
        shutil.move(str(target), str(new_path))
        _refresh_file_tree(state)
        # 如果正在预览的文件被移动，更新预览路径
        if state.preview_file:
            resolved = _resolve(state, state.preview_file)
            if resolved == target:
                state.preview_file = str(new_path.relative_to(state.project_root.resolve()))
        return f"已移动: {path} → {dest_dir}/{target.name}"
    except Exception as e:  # noqa: BLE001
        return f"移动失败: {e}"


def perform_delete(state: NovelState) -> str:
    """将所有预删除区域内的文件移至回收站（send2trash），回退方案移至 .trash/。"""
    items = state._pre_delete_items
    if not items:
        return "预删除区域为空，无需操作"

    import shutil
    from datetime import datetime

    results: list[str] = []
    for item in list(items):
        pre_path = item["pre_delete"]
        display = item["display"]
        if not pre_path.exists():
            results.append(f"{display}: 文件已不存在，跳过")
            items.remove(item)
            continue

        try:
            try:
                import send2trash
                send2trash.send2trash(str(pre_path))
                method = "回收站"
            except ImportError:
                trash_dir = state.project_root / ".trash" if state.project_root else pre_path.parent / ".trash"
                trash_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = trash_dir / f"{ts}_{pre_path.name}"
                shutil.move(str(pre_path), str(dest))
                method = ".trash/"
            results.append(f"{display} → {method}")
            items.remove(item)
        except Exception as e:
            results.append(f"{display}: 删除失败 ({e})")

    _refresh_file_tree(state)
    return f"[已确认删除] 共处理 {len(results)} 个文件:\n" + "\n".join(f"  • {r}" for r in results)


def restore_pre_deleted(state: NovelState) -> str:
    """将所有预删除区域内的文件恢复到原始位置。"""
    items = state._pre_delete_items
    if not items:
        return "预删除区域为空，无需操作"

    import shutil

    results: list[str] = []
    for item in list(items):
        pre_path = item["pre_delete"]
        original = item["original"]
        display = item["display"]

        if not pre_path.exists():
            results.append(f"{display}: 预删除文件已不存在，跳过")
            items.remove(item)
            continue

        try:
            # 确保原始目录存在
            original.parent.mkdir(parents=True, exist_ok=True)
            # 如果原位已有同名文件，拒绝恢复
            if original.exists():
                results.append(f"{display}: 原位已存在同名文件，跳过恢复（预删除文件保留在 {pre_path}）")
                continue
            shutil.move(str(pre_path), str(original))
            results.append(f"{display} → 已恢复")
            items.remove(item)
        except Exception as e:
            results.append(f"{display}: 恢复失败 ({e})")

    _refresh_file_tree(state)
    return f"[已取消删除] 共处理 {len(results)} 个文件:\n" + "\n".join(f"  • {r}" for r in results)


def _read_project_file(state: NovelState, args: dict[str, Any]) -> str:
    """读取项目内任意文件内容（用于读取计划文件、设定文件等）。"""
    path = args.get("path", "")
    target = _resolve(state, path)
    if target is None:
        return f"路径无效或越权: {path}"
    if not target.exists():
        candidates = [
            state.project_root / ".Project" / path,
            state.project_root / path,
        ]
        found = None
        for c in candidates:
            if c.exists():
                found = c
                break
        if found is None:
            return f"文件不存在: {path}"
        target = found
    try:
        content = target.read_text(encoding="utf-8")
        max_chars = args.get("max_chars", 0)
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars] + f"\n...(截断，共 {len(content)} 字)"
        return content
    except Exception as e:  # noqa: BLE001
        return f"读取文件失败: {e}"


def _list_project_files(state: NovelState, args: dict[str, Any]) -> str:
    """列出指定目录下的 .md 文件，返回文件名 + 前 N 行作为简介。"""
    import re

    directory = args.get("directory", ".Project")
    max_lines = int(args.get("max_lines", 8))
    target = state.project_root / directory if state.project_root else None
    if target is None or not target.exists() or not target.is_dir():
        return f"目录不存在: {directory}"
    lines_out = []
    for f in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if not f.is_file() or not f.name.endswith(".md"):
            continue
        try:
            content = f.read_text(encoding="utf-8")
            all_lines = content.strip().split("\n")
            preview_lines = all_lines[:max_lines]
            preview = "\n  ".join(preview_lines)
            suffix = ""
            if len(all_lines) > max_lines:
                suffix = f"\n  ...(共 {len(all_lines)} 行，已截断前 {max_lines} 行)"
            lines_out.append(f"- {f.name} ({len(content)} 字):\n  {preview}{suffix}")
        except Exception:  # noqa: BLE001
            lines_out.append(f"- {f.name} (读取失败)")
    if not lines_out:
        return f"{directory} 下暂无 .md 文件"
    return "\n".join(lines_out)


FILE_TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        name="create_novel_folder",
        description="在项目内新建目录（路径相对项目根）。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相对项目根的目录路径"}},
            "required": ["path"],
        },
        handler=_create_novel_folder,
    ),
    ToolDef(
        name="create_novel_file",
        description="在项目内新建文件并写入初始内容。文件已存在则不覆盖。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件路径"},
                "content": {"type": "string", "description": "初始内容", "default": ""},
            },
            "required": ["path"],
        },
        handler=_create_novel_file,
    ),
    ToolDef(
        name="write_file",
        description="覆盖写入项目内任意文件内容。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    ),
    ToolDef(
        name="append_to_file",
        description="追加内容到项目内任意文件末尾。写章节正文时分段调用，用户可实时看到预览增长。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件路径"},
                "text": {"type": "string", "description": "要追加的文本片段"},
            },
            "required": ["path", "text"],
        },
        handler=_append_to_file,
    ),
    ToolDef(
        name="edit_file",
        description="增量编辑项目内任意文件。mode=replace 查找替换；mode=lines 替换行范围；mode=insert_after 在某行后插入。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件路径"},
                "mode": {"type": "string", "enum": ["replace", "lines", "insert_after"], "description": "编辑模式"},
                "find": {"type": "string", "description": "replace 模式：要查找的文本"},
                "replace": {"type": "string", "description": "replace 模式：替换为的文本"},
                "start_line": {"type": "integer", "description": "lines 模式：起始行号（从1开始）"},
                "end_line": {"type": "integer", "description": "lines 模式：结束行号（含）"},
                "after_line": {"type": "integer", "description": "insert_after 模式：在该行后插入"},
                "text": {"type": "string", "description": "lines/insert_after 模式：要写入的文本"},
            },
            "required": ["path", "mode"],
        },
        handler=_edit_file,
    ),
    ToolDef(
        name="delete_file",
        description="将项目内文件移至 .pr/pre-delete/ 预删除区域（不会立即删除）。文件移动后你仍可通过 read_file('.pr/pre-delete/文件名') 读取。用户回复\"确认删除\"后所有预删除文件才移至回收站，回复其他则恢复。禁止删除非空目录。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件/目录路径"},
            },
            "required": ["path"],
        },
        handler=_delete_file,
    ),
    ToolDef(
        name="rename_file",
        description="重命名项目内的文件或文件夹。new_name 只写新文件名/目录名，不包含路径。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "当前相对路径"},
                "new_name": {"type": "string", "description": "新文件名/目录名（不含路径分隔符）"},
            },
            "required": ["path", "new_name"],
        },
        handler=_rename_file,
    ),
    ToolDef(
        name="move_file",
        description="将项目内的文件/文件夹移动到指定目录（目标目录需已存在）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "当前相对路径"},
                "dest_dir": {"type": "string", "description": "目标目录（相对路径，需已存在）"},
            },
            "required": ["path", "dest_dir"],
        },
        handler=_move_file,
    ),
    ToolDef(
        name="read_file",
        description="读取项目内任意文件内容。支持 max_chars 截断（0=全部）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件路径"},
                "max_chars": {"type": "integer", "description": "最大返回字数（0=全部）", "default": 0},
            },
            "required": ["path"],
        },
        handler=_read_project_file,
    ),
    ToolDef(
        name="read_project_file",
        description="读取项目内任意文件内容（与 read_file 相同，保留兼容）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根的文件路径"},
                "max_chars": {"type": "integer", "description": "最大返回字数（0=全部）", "default": 0},
            },
            "required": ["path"],
        },
        handler=_read_project_file,
    ),
    ToolDef(
        name="list_project_files",
        description="列出项目内某目录下的 .md 文件及前 N 行简介（用于浏览计划文件、设定文件等）。默认列出 .Project，默认显示前 8 行，超出行数会标注截断。",
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "目录路径（相对项目根，默认 .Project）", "default": ".Project"},
                "max_lines": {"type": "integer", "description": "每个文件的简介行数", "default": 8},
            },
            "required": [],
        },
        handler=_list_project_files,
    ),
]

#!/usr/bin/env python3
"""
K.A-purn-tui 入口（薄包装）。

实际实现位于 ka_purn_tui 包：
  - 聊天模式（chat）：迁移自旧版 CLI
  - 小说创作模式（novel）：模型通过 tool call 操作章节/待办/文件，
    右侧实时追踪面板像代码编辑器一样显示模型正在编辑的文件。

启动：python deepseek_chat.py
依赖：pip install textual httpx rich
"""
from ka_purn_tui.app import main

if __name__ == "__main__":
    main()

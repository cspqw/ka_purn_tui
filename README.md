# K.A-purn-tui v0.1

> 终端界面下的 DeepSeek AI 助手 — 聊天 + 小说创作双模式，分屏实时追踪

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Textual](https://img.shields.io/badge/Textual-0.50%2B-purple)](https://textual.textualize.io/)
[![Version](https://img.shields.io/badge/version-0.2.0-green)]()

---

## 启动方式

 - 先install脚本安装依赖，然后在项目目录命令行执行python -m ka_purn_tui

## 功能特性

- **聊天模式** — 纯对话助手，支持预设切换、文件加载、思考模式
- **小说创作模式** — AI Agent 通过 16 个工具自主推进创作
  - 章节管理：设定总章数、切换章节、标记完成
  - 待办追踪：右侧面板实时显示创作进度，黄色指针标记当前任务
  - 文件操作：创建/追加/编辑/删除/重命名小说文件
  - 流式文件预览：右侧面板**实时**显示模型正在写入的文字
  - 常驻记忆：人物卡、世界观、大纲、风格说明永久保留在上下文
  - 计划模式：`/plan` 让模型先写计划，确认后再执行
- **上下文管理** — 三档水位自动压缩（精简 → 摘要 → 截断），1M token 窗口
- **多会话管理** — 新建/载入/重命名/删除会话，chat 与 novel 模式独立存储
- **自适应布局** — 窗口缩放时自动调整分栏比例，窄窗口自动折叠右侧

---

## 快速开始

### 前置要求

- Python 3.10+
- DeepSeek API Key ([获取地址](https://platform.deepseek.com/api_keys))

### 一键安装

**Windows:**
```batch
install.bat
```

**Linux / macOS:**
```bash
chmod +x install.sh && ./install.sh
```

### 手动安装

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"
```

### 配置 API Key

方式一 — 环境变量：
```bash
export DEEPSEEK_API_KEY=sk-your-key-here   # Linux/macOS
set DEEPSEEK_API_KEY=sk-your-key-here       # Windows
```

方式二 — `config.jsonc`：
```json
{
  "api_key": "sk-your-key-here"
}
```

### 启动

```bash
ka-purn-tui
# 或
python -m ka_purn_tui
```

---

## 界面布局

```
┌──────────────────────────────────────────────────────┐
│ [小说创作] deepseek-v4-pro | 思考:开/max | 上下文: [█████░░░░░] 12.34% │ 顶栏
├───────────────────────┬──────────────────────────────┤
│                       │  ▸ 第4章  ← 章节面板          │
│  你> 继续写下一章     │                              │
│                       │  待办             记忆       │
│  ┌─ 思考过程 ──────── │  ▸ 第5章正文...  人物卡      │
│  │ 用户要继续下一章.. │  ✓ 第4章正文...  世界观      │
│  └────────────────────│                              │
│  ───── 回答 ──────────│  » ch05.md  (流式 2366 字)   │
│  好的，开始写第五章。  │  铁柱站在操场上，汗水顺着    │
│                       │  脊背滑落。                      │
│  [sys] ++ ~122 tokens │                              │
│    | context: 461k    │       ← 文件实时预览          │
│                       │                              │
│  ← 聊天消息流          │                              │
├───────────────────────┴──────────────────────────────┤
│ /                                                      │ ← 输入栏
└──────────────────────────────────────────────────────┘
```

---

## 命令参考

### 通用命令

| 命令 | 说明 |
|------|------|
| `/mode chat` / `/mode novel` | 切换模式 |
| `/new [名称]` | 新建会话 |
| `/sessions` | 浏览/选择历史会话（模态屏） |
| `/load <id>` | 载入指定会话 |
| `/rename <名称>` | 重命名当前会话 |
| `/delete <id>` | 删除指定会话 |
| `/think on` / `/think off` | 开关思考模式 |
| `/effort high` / `/effort max` | 设置推理强度 |
| `/model <name>` | 切换模型 |
| `/load <文件路径>` | 加载文件到上下文 |
| `/clear` | 清空对话历史 |
| `/info` | 显示会话信息 |

### 小说模式专用

| 命令 | 说明 |
|------|------|
| `/novel new <名称>` | 新建小说项目 |
| `/novel open <路径>` | 打开已有项目 |
| `/chapter <n>` | 跳转查看第 n 章 |
| `/follow on` / `/follow off` | 开关文件预览自动滚动 |
| `/plan <描述>` | 计划模式：模型先写计划，确认后执行 |
| `/panel show` / `/panel hide` | 显示/隐藏右侧面板 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 提交输入 |
| `Shift+Enter` | 换行 |
| `Ctrl+R` | 切换右侧面板 |
| `Ctrl+C` | 停止推理 / 退出 |
| `Tab` | 命令补全（输入 `/` 后） |
| `↑` / `↓` | 翻阅历史输入 |

---

## 配置说明

详见 [`config_guide.md`](config_guide.md)。

主要配置项：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `model` | `deepseek-v4-pro` | 模型名称 |
| `max_tokens` | `16384` | 单次响应最大 token |
| `agent.max_rounds` | `12` | Agent 工具调用最大轮数 |
| `context.max_tokens` | `1_000_000` | 上下文窗口大小 |
| `context.warn_threshold` | `0.6` | 警戒水位 |
| `context.compress_threshold` | `0.8` | 压缩水位 |
| `context.critical_threshold` | `0.9` | 紧急截断水位 |
| `ui.width_narrow` | `100` | 窄布局阈值（列数） |
| `ui.width_wide` | `160` | 宽布局阈值（列数） |

---

## 依赖

```
textual >= 0.50.0     — TUI 框架
httpx >= 0.27.0       — HTTP 客户端
rich >= 13.7.0        — 终端富文本
tokenizers >= 0.19.0  — DeepSeek V3 token 精确计算
send2trash >= 1.8.0   — 文件回收站（可选）
```

---

## 技术架构

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，包含：
- 系统概览架构图（Mermaid）
- 核心数据流序列图
- 模块分层架构
- 关键设计决策说明
- 扩展指南

---

## 项目结构

```
deepseek-tui/
├── ka_purn_tui/               # Python 包
│   ├── app.py                # 主应用 (布局/命令/agent回路)
│   ├── config.py             # 配置/token估算/system prompt
│   ├── api/client.py         # DeepSeek API 客户端 (SSE流式)
│   ├── modes/                # 聊天模式 + 小说创作模式
│   ├── panels/               # 右侧面板 (章节/文件预览/待办)
│   ├── tools/                # 16 个创作工具 (注册/分发/执行)
│   ├── state/                # 状态管理 (NoveState/Session/ProjectState)
│   └── widgets/              # UI 组件 (ChatView/InputBar/Sessions)
├── docs/ARCHITECTURE.md      # 架构设计文档
├── install.bat / install.sh  # 一键安装脚本
├── pyproject.toml            # 项目元数据
└── config_guide.md           # 配置项说明
```

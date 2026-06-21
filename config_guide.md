# config.jsonc 配置说明

> K.A-purn-tui 的配置文件。程序运行时会用标准 JSON 格式重写此文件，
> **手动添加的注释会被冲掉**。如需查阅配置项含义，请参考本文档。

---

## 顶层字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | string | (必填) | DeepSeek API 密钥；会覆盖环境变量 `DEEPSEEK_API_KEY` |
| `base_url` | string | `https://api.deepseek.com` | API 基础地址 |
| `model` | string | `deepseek-v4-pro` | 模型名称，可选 `deepseek-v4-flash` / `deepseek-v4-pro` 等 |
| `reasoning_effort` | string | (无) | 推理努力程度：`high` / `max`；不设则走模型默认 |
| `thinking_enabled` | bool | `true` | 是否让模型输出思考/推理过程 |
| `max_tokens` | int | `16384` | **单次 API 调用的最大输出 token 数**（实际配置建议 163840） |
| `temperature` | float | `0.7` | 采样温度，0-2 之间，越高随机性越强 |
| `stream` | bool | `true` | 是否开启 SSE 流式响应（逐 token 输出） |
| `special_system_prompt` | string | `""` | 特殊系统提示词，会**前置插入**到所有 system prompt 最前面（含主对话、章节摘要、对话摘要），后接换行。设置后应用生效，清空用 `/special clear` |
| `current_mode` | string | `"chat"` | 当前运行模式：`chat`（对话）/ `novel`（小说创作） |
| `current_session_id` | string | (自动生成) | 当前激活的会话 ID |
| `current_preset` | string | `"default"` | 当前使用的预设名称 |
| `input_history` | string[] | `[]` | 输入历史，上下键翻阅已输入的命令 |
| `novel_projects` | object | `{}` | 小说项目映射：`{ 项目名称: 绝对路径 }`，由 `/novel new` 和 `/novel open` 自动维护 |

---

## `api` — API 行为配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `stream_max_retries` | int | `1` | SSE 流断流时最大重试次数。网络不稳定时可增大（如 5），避免创作中途被意外中断 |

---

## `ui` — UI 布局配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `width_narrow` | int | `100` | 终端宽度低于此值（列数）时切换为窄布局，右侧面板自动折叠 |
| `width_wide` | int | `160` | 终端宽度高于此值（列数）时切换为宽布局（2:1 分栏比例） |
| `width_hysteresis` | int | `5` | 布局切换滞回余量，避免在边界反复跳动 |
| `flush_threshold` | int | `80` | ChatView（左侧聊天区）行缓冲强制 flush 阈值（字符数），保证长段文本实时刷新 |

---

## `agent` — Agent 工具调用回路配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_rounds` | int | `12` | Agent 最多连续调用工具的轮数，达到后强制停止防止死循环 |

---

## `novel` — 小说模式配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system_prompt` | string | (内置默认) | 小说模式专用系统提示词。设置后覆盖 `DEFAULT_NOVEL_SYSTEM_PROMPT`。内置提示词含全部 16 个工具说明和创作规范。若只需微调部分规则，建议复制内置默认后修改 |

---

## `context` — 上下文管理配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_tokens` | int | `1000000` | 模型上下文窗口总 token 数上限（DeepSeek 1M） |
| `warn_threshold` | float | `0.6` | 警戒水位：超过时自动精简旧 tool result 和 reasoning_content |
| `compress_threshold` | float | `0.8` | 压缩水位：超过时异步调用模型生成早期对话摘要并删除原文 |
| `critical_threshold` | float | `0.9` | 紧急水位：超过时强制截断，仅保留 system + 最近 N 轮消息 |
| `sliding_window_rounds` | int | `6` | 滑动窗口保留的最近完整轮数（user→assistant→tool 为一轮） |
| `auto_compact_tool_results` | bool | `true` | 达到警戒水位时是否自动精简 tool result |
| `auto_summarize_on_chapter_done` | bool | `true` | 完成章节时是否自动调用模型生成章节摘要（注入 system prompt） |
| `chapter_summary_max_chars` | int | `400` | 自动生成的章节摘要最大字符数 |

### 水位线图解

```
内存占用率
  100% ┤
   90% ┤ ═══════════ 紧急 ── 强制截断，保留 system + 最近 N 轮
   80% ┤ ═══════════ 压缩 ── 异步摘要早期对话，删除原文
   60% ┤ ═══════════ 警戒 ── 精简旧 tool result / 删除 reasoning_content
    0% ┤ ═══════════ 正常
```

---

## `presets` — 系统提示词预设（chat 模式）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `default` | string | `"你是一个有帮助的助手，请用中文回答。"` | 默认预设 |
| `code` | string | (内置) | 程序员助手预设 |
| `writer` | string | (内置) | 写作助手预设 |
| `analyst` | string | (内置) | 数据分析助手预设 |

通过 `/preset use <name>` 切换，`/preset add <name> <prompt>` 新增自定义预设。

---

## `history` — 当前会话历史

程序自动维护，通常无需手动编辑。结构为消息数组：

```json
[
  { "role": "system", "content": "..." },
  { "role": "user", "content": "..." },
  { "role": "assistant", "content": "...", "reasoning_content": "..." },
  { "role": "tool", "content": "...", "tool_call_id": "..." }
]
```

---

## 常见问题

### `max_tokens`（顶层）和 `context.max_tokens` 有什么区别？

- **顶层 `max_tokens`**：单次 API 响应的**最大输出 token 数**。一次对话中模型最多回复这么多 token。
- **`context.max_tokens`**：上下文窗口**总容量**，等于发送的所有历史消息 token 数。用于水位线判断和压缩触发。

### 注释会被冲掉怎么办？

程序 `save_config()` 使用标准 `json.dump` 重写文件，不保留注释。如需查阅配置含义，请参考本文档。

### 如何修改 Agent 工具调用轮次限制？

修改 `agent.max_rounds` 的值即可。默认 12 轮对大多数创作任务够用，长篇小说可适当增大。

### `stream_max_retries` 设为多少合适？

默认 `1`（重试一次）。若遇到频繁断流，可设为 `3-5`。每次重试会重新发起请求，不重复计数 token。

### `flush_threshold` 的作用？

ChatView 对思考内容和回答内容使用行缓冲累积，只在收到 `\n` 时 flush 到 RichLog。若某行超过 `flush_threshold` 字符仍未换行，则强制 flush，避免长段落长时间不显示。此配置不影响文件预览面板——文件预览采用清空+全量重写策略。

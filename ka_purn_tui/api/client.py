# ── DeepSeek API 客户端（异步流式 + tool calling）─────────
"""DeepSeekClient：用 httpx 异步流式请求，支持 reasoning_content / content / tool_calls。

通过 async generator 产出 ChatEvent，由 App worker 消费并更新 UI。
支持 agent 回路：工具调用结果以 role:"tool" 回传后可继续多轮。

上下文管理：三档水位（警戒/压缩/紧急），主动精简 tool result、删除旧 reasoning_content、
必要时强制截断。压缩档需要 App worker 调用 summarize_text 异步生成摘要。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ..config import estimate_tokens

# 触发流式预览的工具：arguments 流式累积时实时 yield tool_streaming
_STREAMING_TOOLS = {"append_to_file", "create_novel_file", "write_file", "edit_file"}

# 上下文管理动作
ContextAction = Literal["none", "compact", "summarize", "truncate"]


@dataclass
class ChatEvent:
    """流式事件。"""

    kind: Literal["thinking", "answer", "tool_call", "tool_streaming", "done", "error"]
    text: str = ""
    # tool_call / tool_streaming 专用
    tool_call_id: str = ""
    tool_name: str = ""
    tool_args: str = ""  # 原始 JSON 字符串（流式时为已累积的部分）
    # error 专用
    error: str = ""


class DeepSeekClient:
    """DeepSeek API 异步客户端。"""

    TIMEOUT = 300.0

    def __init__(self, config: dict[str, Any]):
        self.api_key = config["api_key"]
        self.base_url = config["base_url"]
        self.model = config["model"]
        self.thinking_enabled = config.get("thinking_enabled", True)
        self.reasoning_effort = config.get("reasoning_effort")
        self.max_tokens = config.get("max_tokens", 16_384)
        self.temperature = config.get("temperature", 0.7)
        self.messages: list[dict[str, Any]] = list(config.get("history", []))
        # ── API 行为配置 ──
        api_cfg = config.get("api", {})
        self.stream_max_retries: int = int(api_cfg.get("stream_max_retries", 1))
        # ── 上下文管理配置 ──
        ctx_cfg = config.get("context", {})
        self.context_max_tokens: int = int(ctx_cfg.get("max_tokens", 1_000_000))
        self.warn_threshold: float = float(ctx_cfg.get("warn_threshold", 0.6))
        self.compress_threshold: float = float(ctx_cfg.get("compress_threshold", 0.8))
        self.critical_threshold: float = float(ctx_cfg.get("critical_threshold", 0.9))
        self.sliding_window_rounds: int = int(ctx_cfg.get("sliding_window_rounds", 6))
        self.auto_compact_tool_results: bool = bool(ctx_cfg.get("auto_compact_tool_results", True))
        # 水位告警回调：(action, ratio) -> None，由 App 设置
        self.on_context_warning: Callable[[str, float], None] | None = None
        # 工具定义 token 缓存
        self._tool_tokens: int = 0

    # ── 消息管理 ──
    def add_message(self, role: str, content: str | None = None, **extra: Any) -> None:
        msg: dict[str, Any] = {"role": role}
        if content is not None:
            msg["content"] = content
        msg.update(extra)
        self.messages.append(msg)
        self._manage_context()

    def set_system(self, content: str) -> None:
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = content
        else:
            self.messages.insert(0, {"role": "system", "content": content})

    def clear(self, system_prompt: str = "") -> None:
        self.messages = []
        self._tool_tokens = 0
        if system_prompt:
            self.set_system(system_prompt)

    def load_messages(self, messages: list[dict[str, Any]]) -> None:
        """替换当前会话的完整消息历史（用于载入历史会话）。

        会深拷贝避免外部修改影响内部状态。
        """
        self.messages = [dict(m) for m in messages]
        self._manage_context()

    # ── 上下文管理（三档水位）──
    def context_ratio(self) -> float:
        """当前上下文占用比例（0-1）。"""
        tokens = estimate_tokens(self.messages)
        if self._tool_tokens:
            tokens += self._tool_tokens
        return tokens / self.context_max_tokens if self.context_max_tokens else 0.0

    def cache_tool_tokens(self, tools: list[dict] | None) -> None:
        """缓存工具定义的 token 数（使用 DeepSeek V3 官方 tokenizer）。"""
        if not tools:
            self._tool_tokens = 0
            return
        import json
        from ..config import estimate_tokens
        try:
            raw = json.dumps(tools, ensure_ascii=False)
            # 用真实 tokenizer 编码 JSON 字符串
            self._tool_tokens = estimate_tokens([{"content": raw}])
        except Exception:
            self._tool_tokens = 0

    def _manage_context(self) -> ContextAction:
        """根据水位线管理上下文，返回采取的动作。

        - none: 无需处理
        - compact: 已精简旧 tool result / reasoning_content（同步完成）
        - summarize: 需要摘要早期对话（由 App worker 异步调用 summarize_text）
        - truncate: 已强制截断（同步完成）
        """
        tokens = estimate_tokens(self.messages)
        if self._tool_tokens:
            tokens += self._tool_tokens
        if tokens == 0:
            return "none"
        ratio = tokens / self.context_max_tokens
        if ratio < self.warn_threshold:
            return "none"
        if ratio < self.compress_threshold:
            # 🟡 警戒：精简旧 tool result 和 reasoning_content
            if self.auto_compact_tool_results:
                self._compact_old_messages()
            self._notify_warning("警戒", ratio)
            return "compact"
        if ratio < self.critical_threshold:
            # 🟠 压缩：需要摘要早期对话（App worker 处理）
            self._notify_warning("压缩", ratio)
            return "summarize"
        # 🔴 紧急：强制截断
        self._force_truncate()
        self._notify_warning("紧急", ratio)
        return "truncate"

    def _notify_warning(self, level: str, ratio: float) -> None:
        if self.on_context_warning:
            try:
                self.on_context_warning(level, ratio)
            except Exception:  # noqa: BLE001
                pass

    def _compact_old_messages(self) -> None:
        """精简滑动窗口之外的消息。

        - 删除旧 assistant 的 reasoning_content（思考过程已过去）
        - 精简旧 tool result content（保留前 80 字 + 提示）
        - 精简旧 assistant tool_calls 的 arguments 中的 text/content 字段
        """
        # 每轮约 3-4 条消息（user→assistant→tool→...→assistant）
        keep_count = self.sliding_window_rounds * 4
        if len(self.messages) <= keep_count + 1:
            return
        # system 消息（index 0）永远不精简
        compact_start = 1 if self.messages and self.messages[0].get("role") == "system" else 0
        compact_end = len(self.messages) - keep_count
        for i in range(compact_start, compact_end):
            msg = self.messages[i]
            role = msg.get("role")
            # 删除 reasoning_content（思考过程已过去，不再需要）
            if "reasoning_content" in msg:
                del msg["reasoning_content"]
            # 精简 tool result
            if role == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 100:
                    msg["content"] = content[:80] + f"...[已精简，原 {len(content)} 字]"
            # 精简 assistant 的 tool_calls arguments
            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    continue
                for tc in tool_calls:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    args_str = fn.get("arguments", "")
                    if not isinstance(args_str, str) or len(args_str) < 200:
                        continue
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        continue
                    tool_name = fn.get("name", "")
                    # 文件写入类工具：精简 text/content 字段
                    if tool_name in ("append_to_file", "write_file", "create_novel_file"):
                        field_name = "text" if tool_name == "append_to_file" else "content"
                        if field_name in args and isinstance(args[field_name], str):
                            original_len = len(args[field_name])
                            if original_len > 100:
                                args[field_name] = args[field_name][:50] + f"...[已精简，原 {original_len} 字]"
                                args["_compacted"] = True
                                fn["arguments"] = json.dumps(args, ensure_ascii=False)

    def _force_truncate(self) -> None:
        """紧急截断：只保留 system + 最近 N 条消息。"""
        keep_count = self.sliding_window_rounds * 3
        system_msgs: list[dict[str, Any]] = []
        rest_msgs: list[dict[str, Any]] = []
        for m in self.messages:
            if m.get("role") == "system":
                system_msgs.append(m)
            else:
                rest_msgs.append(m)
        if len(rest_msgs) <= keep_count:
            return
        self.messages = system_msgs + rest_msgs[-keep_count:]

    async def summarize_text(self, system_prompt: str, user_prompt: str, max_chars: int = 800) -> str:
        """独立调用模型生成摘要（不走主对话流，不污染历史）。

        system_prompt 应已由调用方通过 apply_special_prompt 处理。
        禁用思考模式以节省 token 和时间。失败返回空字符串（调用方需兜底）。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": min(self.max_tokens, 2048),
            "temperature": 0.3,  # 摘要用低温度保证稳定
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    return ""
                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    return ""
                text = choices[0].get("message", {}).get("content", "").strip()
                return text[:max_chars] if text else ""
        except Exception:  # noqa: BLE001
            return ""

    # ── 请求构造 ──
    def _build_payload(self, tools: list[dict] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        # 文档明确：思考开关默认为 enabled，关闭必须显式传 {"type": "disabled"}
        # 见 https://api-docs.deepseek.com/zh-cn/guides/thinking_mode
        payload["thinking"] = {"type": "enabled" if self.thinking_enabled else "disabled"}
        if tools:
            payload["tools"] = tools
        return payload

    # ── 流式请求 ──
    async def chat(
        self,
        user_input: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """发送用户消息并流式产出事件。

      # 会自动把 user_input 加入历史。若模型返回 tool_calls，产出 tool_call 事件后
        # 由调用方执行工具并把结果加入历史，再调用 continue_after_tools 继续生成。
        """
        self.cache_tool_tokens(tools)
        self.add_message("user", user_input)
        async for ev in self._stream(self._build_payload(tools)):
            yield ev

    async def continue_after_tools(self, tools: list[dict] | None = None) -> AsyncIterator[ChatEvent]:
        """工具结果已加入历史后，继续请求模型生成（agent 回路）。"""
        self.cache_tool_tokens(tools)
        async for ev in self._stream(self._build_payload(tools)):
            yield ev

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[ChatEvent]:
        """核心流式解析：解析 SSE，累积 tool_calls 分片，产出事件。

        遇到 RemoteProtocolError 等网络断流且尚未收到任何内容时，会按
        api.stream_max_retries 配置重试，减少创作被意外中断的概率。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        max_retries = max(0, self.stream_max_retries)

        for attempt in range(max_retries + 1):
            # 累积器（每次尝试重新初始化，避免重试时内容重复）
            answer_buf: list[str] = []
            thinking_buf: list[str] = []
            tool_calls: dict[int, dict[str, str]] = {}  # index -> {id, name, arguments}

            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as resp:
                        if resp.status_code != 200:
                            body = await resp.aread()
                            msg = body.decode("utf-8", errors="replace")[:300]
                            yield ChatEvent(kind="error", error=f"HTTP {resp.status_code}: {msg}")
                            return

                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            finish = choice.get("finish_reason")

                            # 思考内容
                            reasoning = delta.get("reasoning_content", "")
                            if reasoning:
                                thinking_buf.append(reasoning)
                                yield ChatEvent(kind="thinking", text=reasoning)

                            # 回答内容
                            content = delta.get("content", "")
                            if content:
                                answer_buf.append(content)
                                yield ChatEvent(kind="answer", text=content)

                            # 工具调用（分片累积）
                            for tc in delta.get("tool_calls", []):
                                idx = tc.get("index", 0)
                                slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if tc.get("id"):
                                    slot["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    slot["name"] = fn["name"]
                                if fn.get("arguments"):
                                    was_empty = not slot["arguments"]
                                    slot["arguments"] += fn["arguments"]
                                    # 文件写入类工具：每个分片都通知 UI（实时预览）
                                    # 其他工具：仅首次分片通知 UI（显示"正在调用..."）
                                    if slot["name"] in _STREAMING_TOOLS or was_empty:
                                        yield ChatEvent(
                                            kind="tool_streaming",
                                            tool_name=slot["name"],
                                            tool_args=slot["arguments"],
                                        )

                            # 完成判定
                            if finish in ("tool_calls", "stop"):
                                break

            except httpx.RemoteProtocolError:
                # 未收到任何内容时允许重试，避免服务端偶发断流打断创作
                if attempt < max_retries and not answer_buf and not thinking_buf and not tool_calls:
                    continue
                yield ChatEvent(kind="error", error="连接被服务端中断（RemoteProtocolError），请稍后重试")
                return
            except httpx.TimeoutException:
                # 保留已收到的部分回答
                if answer_buf:
                    self.messages.append({"role": "assistant", "content": "".join(answer_buf)})
                yield ChatEvent(kind="error", error="请求超时（300秒）")
                return
            except httpx.ConnectError:
                yield ChatEvent(kind="error", error="连接失败，请检查网络或 API 地址")
                return
            except Exception as e:  # noqa: BLE001
                yield ChatEvent(kind="error", error=f"{type(e).__name__}: {e}")
                return

            # 本尝试成功：先把 assistant 消息（含 tool_calls）写入历史
            # 必须在 yield tool_call 之前，否则 add_tool_result 的 role:tool
            # 会跑到 assistant 之前，触发 HTTP 400
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if answer_buf:
                assistant_msg["content"] = "".join(answer_buf)
            else:
                assistant_msg["content"] = None
            # 文档要求：进行了工具调用的轮次，reasoning_content 必须回传给 API，
            # 否则后续请求会返回 400。非工具调用轮次回传会被忽略，所以统一保留。
            # 见 https://api-docs.deepseek.com/zh-cn/guides/thinking_mode#工具调用
            if thinking_buf:
                assistant_msg["reasoning_content"] = "".join(thinking_buf)
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tool_calls[i]["id"],
                        "type": "function",
                        "function": {
                            "name": tool_calls[i]["name"],
                            "arguments": tool_calls[i]["arguments"],
                        },
                    }
                    for i in sorted(tool_calls.keys())
                    if tool_calls[i]["name"]
                ]
            self.messages.append(assistant_msg)
            self._manage_context()

            # 产出工具调用事件（此时 assistant 消息已在历史中，
            # 调用方 add_tool_result 写入的 role:tool 会正确跟在后面）
            for idx in sorted(tool_calls.keys()):
                tc = tool_calls[idx]
                if tc["name"]:
                    yield ChatEvent(
                        kind="tool_call",
                        tool_call_id=tc["id"],
                        tool_name=tc["name"],
                        tool_args=tc["arguments"],
                    )

            yield ChatEvent(kind="done", text="".join(answer_buf))
            return

    # ── 工具结果回传 ──
    def add_tool_result(self, tool_call_id: str, result: str) -> None:
        """把工具执行结果以 role:"tool" 加入历史，供 agent 回路继续。"""
        self.add_message("tool", result, tool_call_id=tool_call_id)

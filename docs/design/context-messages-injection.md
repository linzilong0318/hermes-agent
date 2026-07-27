# 上下文消息注入方案 — context_messages

## 背景与问题

### 当前状态

在 `/api/sessions/{id}/chat[/stream]` 接口中，业务方需要将一些**元数据**（如 `session_id`、文件附件下载链接、业务标签等）在 LLM 调用时传给模型，但**不希望这些元数据出现在前端展示的用户消息历史中**。

### 当前做法及其问题

当前使用 `system_message`（请求 body 字段）来传递元数据。这个字段在内部映射为 `ephemeral_system_prompt`，流程如下：

```
请求 body.system_message
  → _handle_session_chat_stream L2117
    → _run_agent(ephemeral_system_prompt=system_prompt) L2169
      → _create_agent(ephemeral_system_prompt=...) L4290
        → AIAgent.__init__(ephemeral_system_prompt=...) L1507
          → run_conversation L867-868: effective_system += "\n\n" + agent.ephemeral_system_prompt
```

`ephemeral_system_prompt` 在 API 调用时追加到系统提示词末尾，不持久化到 session DB。**每个请求创建一个新 AIAgent**，所以值理论上每轮都是新鲜的。

### 为什么有问题

1. **`ephemeral_system_prompt` 是追加到缓存的系统提示词（`_cached_system_prompt`）之后的**，而系统提示词从 session DB 恢复（`_restore_or_build_system_prompt`），元数据只是"附件"在末尾，不是对话上下文的一部分
2. 经过多轮对话后，模型注意力集中在对话历史的内容上，系统提示词末尾的附加信息容易被"注意力稀释"
3. 如果某轮没传 `system_message`，那轮就没有任何元数据注入
4. **本质问题**：`system_message` 的设计意图是"单次指令覆盖/追加"，不是"携带业务元数据随每轮请求进入 LLM 上下文"

---

## 数据流全景

### 关键文件与符号

| 文件                                | 关键点                             | 行号范围   |
| ----------------------------------- | ---------------------------------- | ---------- |
| `gateway/platforms/api_server.py` | `_handle_session_chat_stream`    | L2102-2238 |
| `gateway/platforms/api_server.py` | `_handle_session_chat`           | L2060-2099 |
| `gateway/platforms/api_server.py` | `_run_agent`                     | L4249-4327 |
| `gateway/platforms/api_server.py` | `_create_agent`                  | L1390-1520 |
| `run_agent.py`                    | `AIAgent.__init__`               | L492-567   |
| `run_agent.py`                    | `AIAgent._compress_context`      | L5685-5698 |
| `agent/agent_init.py`             | `init_agent`                     | L326, L633 |
| `agent/turn_context.py`           | `build_turn_context`             | L119-617   |
| `agent/conversation_loop.py`      | `run_conversation`               | L537-5530  |
| `agent/conversation_loop.py`      | system prompt 组装（含 ephemeral） | L851-870   |
| `agent/conversation_loop.py`      | prefill_messages 注入              | L912-917   |

### 一次 `/api/sessions/{id}/chat/stream` 请求的全链路

```
┌─ 请求进入 ──────────────────────────────────────────────────────────┐
│ _handle_session_chat_stream(request)                                │
│   ├─ body["message"]       → user_message       (用户输入)          │
│   ├─ body["system_message"] → system_prompt     (→ ephemeral)       │
│   └─ (未来) body["context_messages"] → 本方案新增                   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─ _run_and_signal() ─────────────────────────────────────────────────┐
│   history = _conversation_history_for_session(session_id)          │
│   // (未来) 此处不修改 history，用 prefill_messages 机制            │
│   _run_agent(user_message, conversation_history=history,            │
│              ephemeral_system_prompt=system_prompt)                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─ _run_agent() ──────────────────────────────────────────────────────┐
│   loop.run_in_executor(None, _run)  ← 线程池执行                    │
│     ├─ _create_agent(ephemeral_system_prompt=...)                   │
│     │   → AIAgent(prefill_messages=...)  ← (未来也传 context)      │
│     └─ agent.run_conversation(user_message, conversation_history)   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─ run_conversation() (conversation_loop.py) ─────────────────────────┐
│   build_turn_context() → turn_context.py                            │
│     ├─ restore_or_build_system_prompt() → L310-360                  │
│     │   DB → _cached_system_prompt (永久提示词)                     │
│     ├─ active_system_prompt = _cached_system_prompt                 │
│     └─ messages = list(conversation_history) + [user_msg]           │
│                                                                     │
│   ↓ 进入 while(api_call_count < max_iterations) 循环前              │
│                                                                     │
│   api_messages 构建:                                                │
│     ├─ api_messages = sanitize(messages)                            │
│     ├─ effective_system = active_system_prompt                      │
│     ├─ if agent.ephemeral_system_prompt:                            │
│     │     effective_system += "\n\n" + agent.ephemeral_system_prompt │
│     ├─ api_messages = [{role:"system", content:effective_system}]   │
│     │                + api_messages                                 │
│     ├─ if agent.prefill_messages:          ← ★ 注入点               │
│     │     api_messages.insert(sys_offset, prefill_messages)         │
│     └─ (API call with tools)                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 关键机制：`prefill_messages`

`AIAgent` 已有 `prefill_messages` 参数，在 `agent_init.py:633` 保存为 `agent.prefill_messages`，在 `conversation_loop.py:912-917` 注入：

```python
# Inject ephemeral prefill messages right after the system prompt
# but before conversation history. Same API-call-time-only pattern.
if agent.prefill_messages:
    sys_offset = 1 if (api_messages and api_messages[0].get("role") == "system") else 0
    for idx, pfm in enumerate(agent.prefill_messages):
        api_messages.insert(sys_offset + idx, pfm.copy())
```

**特性**：

- ✅ **API-call-time only**：只在发送给 LLM 的消息列表中存在
- ✅ **不持久化**：不写入 session DB，不改变 `_cached_system_prompt`
- ✅ **不污染用户消息**：前端读取 `/api/sessions/{id}/messages` 看不到这些消息
- ✅ **不破坏 prompt caching**：因为不修改系统提示词缓存
- ✅ **支持任意 role**：可以是 `assistant`、`user` 或 `system` 格式的消息

---

## 推荐方案：context_messages → prefill_messages

### 概述

在请求 body 中增加一个 `context_messages` 字段（JSON 数组），业务方通过这个字段传入元数据或额外信息。`context_messages` 在 `api_server.py` 内部通过 `_run_agent` → `_create_agent` 线程到 `AIAgent.__init__(prefill_messages=...)`，由已有的 `prefill_messages` 注入机制在 API 调用时插入。

### 数据流（改动后）

```
请求 body
  ├─ "message": "用户的问题"
  └─ "context_messages": [           ← 新增
       {"role": "assistant", "content": "[上下文]\nSession: xxx\n附件: https://..."}
     ]
         │
         ▼
_handle_session_chat_stream
  ├─ 解析 body["context_messages"] → 校验数组格式
  ├─ user_message = body["message"]  ← 不变
  ├─ 不修改 conversation_history
  └─ _run_agent(..., context_messages=parsed)  ← 新增参数传递
         │
         ▼
_run_agent
  └─ _create_agent(..., context_messages=context_messages)
         │
         ▼
_create_agent
  └─ AIAgent(..., prefill_messages=context_messages)
         │
         ▼
run_conversation  →  prefill_messages 注入点 (L912-917)
  [system prompt]
  [context_messages]     ← 插入在 system prompt 之后
  [conversation history] ← 不变的原始历史
  [user message]         ← 用户原始输入
```

### 改动明细

只涉及 **1 个文件**：`gateway/platforms/api_server.py`

#### 改动 1：`_handle_session_chat_stream` — 解析 `context_messages`

**位置**：L2117-L2119 附近（在 `system_prompt` 解析之后）

```python
# 新增：解析上下文消息
context_messages = body.get("context_messages")
if context_messages is not None:
    if not isinstance(context_messages, list):
        return web.json_response(
            _openai_error("context_messages must be an array"),
            status=400,
        )
    for i, cm in enumerate(context_messages):
        if not isinstance(cm, dict) or "role" not in cm or "content" not in cm:
            return web.json_response(
                _openai_error(
                    f"context_messages[{i}] must have 'role' and 'content' fields"
                ),
                status=400,
            )
```

同时修改调用 `_run_agent` 的语句，增加 `context_messages` 参数：

```python
result, usage = await self._run_agent(
    user_message=user_message,
    conversation_history=history,
    ephemeral_system_prompt=system_prompt,
    context_messages=context_messages or None,  # ← 新增
    session_id=session_id,
    stream_delta_callback=_delta,
    tool_progress_callback=_tool_progress,
    gateway_session_key=gateway_session_key,
)
```

#### 改动 2：`_handle_session_chat` — 对称改动（非流式接口）

**位置**：L2075-L2085 附近

与流式接口相同的解析逻辑和参数传递。

#### 改动 3：`_run_agent` — 增加 `context_messages` 参数

**位置**：L4249-L4262（函数签名），L4289-L4298（`_create_agent` 调用）

```python
async def _run_agent(
    self,
    user_message: str,
    conversation_history: List[Dict[str, str]],
    ephemeral_system_prompt: Optional[str] = None,
    context_messages: Optional[List[Dict[str, Any]]] = None,  # ← 新增
    session_id: Optional[str] = None,
    ...
) -> tuple:
```

在 `_run` 内部：

```python
agent = self._create_agent(
    ephemeral_system_prompt=ephemeral_system_prompt,
    context_messages=context_messages,  # ← 新增
    session_id=session_id,
    ...
)
```

#### 改动 4：`_create_agent` — 转换为 `prefill_messages`

**位置**：L1390-L1400（函数签名），L1501-L1519（AIAgent 构造调用）

```python
def _create_agent(
    self,
    ephemeral_system_prompt: Optional[str] = None,
    context_messages: Optional[List[Dict[str, Any]]] = None,  # ← 新增
    session_id: Optional[str] = None,
    ...
) -> Any:
```

在 `AIAgent(__init__)` 调用处：

```python
agent = AIAgent(
    model=model,
    **runtime_kwargs,
    ...
    ephemeral_system_prompt=ephemeral_system_prompt or None,
    prefill_messages=context_messages,  # ← 新增
    ...
)
```

### 无改动的模块

以下模块完全不需要修改：

| 模块                                  | 原因                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------ |
| `run_agent.py`                      | `AIAgent.__init__` 已有 `prefill_messages` 参数                      |
| `agent/agent_init.py`               | `init_agent` 已处理 `prefill_messages` → `agent.prefill_messages` |
| `agent/conversation_loop.py`        | `prefill_messages` 注入点 (L912-917) 无需修改                          |
| `agent/turn_context.py`             | 不涉及                                                                   |
| `agent/system_prompt.py`            | 不涉及                                                                   |
| `hermes_state.py`                   | 不涉及数据库                                                             |
| `agent/conversation_compression.py` | 压缩时不处理`prefill_messages`                                         |
| 前端代码                              | 只需关注新字段                                                           |

### 不改 DB 的原因

`prefill_messages` 机制本身就是 API-call-time only：

```
conversation_loop.py:914-917
  → api_messages.insert(offset, pfm)
  → 只影响发给 LLM 的 messages 列表
  → 不影响 persist_to_db()、_persist_session()、finalize_turn()
  → 前端读 GET /api/sessions/{id}/messages 看不到
```

### 前端请求示例

```json
POST /api/sessions/{session_id}/chat/stream
{
    "message": "请帮我解读这个文件的内容",
    "context_messages": [
        {
            "role": "assistant",
            "content": "[会话上下文]\n会话ID: abc-123\n关联项目ID: proj-456\n附件链接: https://storage.example.com/files/report.pdf"
        },
        {
            "role": "user",
            "content": "附件的下载链接已在上方给出，请先下载再解读。"
        }
    ]
}
```

前端展示消息列表时，只取 `message` 字段作为用户输入显示；`context_messages` 只由服务端处理，不参与渲染。

### 两种 context_messages role 的用途对比

| role            | LLM 中的位置                     | 推荐用途                                |
| --------------- | -------------------------------- | --------------------------------------- |
| `"assistant"` | 像一个"助手已知信息"出现在对话中 | 传递 session 元数据、业务标签、系统状态 |
| `"user"`      | 像"用户额外说明"出现在对话中     | 传递文件附件链接、指令约束、格式要求    |

推荐用 `"assistant"` 作为元数据容器（模型更容易将其理解为"背景事实"而非"用户指令"）。

---

## 备选方案对比

| 方案                                              | 改动量           | 文件数      | 优点                         | 缺点                                                                                             |
| ------------------------------------------------- | ---------------- | ----------- | ---------------------------- | ------------------------------------------------------------------------------------------------ |
| **⭐ context_messages → prefill_messages** | **~20 行** | **1** | 利用已有机制，0 侵入核心模块 | 前端需感知新字段（但不强制）                                                                     |
| user_message + persist_user_message               | ~15 行           | 1           | 复用已有 persist 机制        | 元数据混入用户消息文本，影响 token 计数                                                          |
| 注入 conversation_history                         | ~10 行           | 1           | 最简单直接                   | 破坏`_turn_transcript_messages` 中的前缀匹配逻辑（L2177），导致 SSE run.completed 返回错误消息 |
| 继续用 system_message + 改缓存                    | 3+ 文件          | 3+          | 不改前端                     | 破坏 prompt caching 设计，高风险                                                                 |

---

## 特别提醒

### 1. 不要修改 `conversation_history` 来注入

修改 `conversation_history` 会触发 `_turn_transcript_messages`（api_server.py:2177）中的前缀匹配逻辑，该函数通过 `_response_messages_turn_start_index`（L4037）**从 history 中做前缀匹配来定位当前轮次的起始位置**。注入额外消息后，历史前缀会发生变化，匹配可能失败退回到 0，导致 `run.completed` 事件中的 `messages` 字段泄露全部历史（参考 `hermes-contributor-pitfalls` 技能中的陷阱 1）。

### 2. `context_messages` 的 role 要合理

不推荐用 `"system"` role 的 context message。如果 `context_messages` 第一条是 `{"role": "system"}`，某些模型的 API 会要求连续 system 消息合并，且可能影响系统提示词的缓存前缀。推荐使用 `"assistant"` 或 `"user"`。

### 3. `context_messages` 是逐轮请求携带的

每个请求的 `context_messages` 都是独立的，不会在 session 中累积（因为 `prefill_messages` 是 AIAgent 实例级的，而每个请求创建新 Agent）。如果业务方需要某些元数据在每轮都存在，需要在每个请求的 body 中都传入。

---

## 测试建议

### 单元测试

在 `tests/gateway/test_session_api.py` 中增加：

1. **context_messages 格式校验**：传入非数组、数组元素缺 role/content → 400
2. **context_messages 注入**：mock `_run_agent`，验证 `context_messages` 参数传递正确
3. **context_messages 不影响消息持久化**：验证 GET /api/sessions/{id}/messages 不包含 context_messages
4. **context_messages 与 system_message 共存**：两者同时传入，验证均正常生效

### E2E 测试

1. 创建 session → 带 `context_messages` 发消息 → 验证模型能引用上下文 → 验证消息历史不含 context_messages
2. 多轮对话：每轮带不同 `context_messages` → 验证模型准确感知每轮的元数据

# Bug Fix: SSE 流式接口在上下文压缩后泄露全部历史消息

## 概述

调用 `/api/sessions/{id}/chat/stream` 接口时，当上下文非常长触发了压缩（context compression），SSE 的 `run.completed` 事件中会包含全部历史消息，而不是仅当前轮次的消息。

### 影响范围

- **文件**: `gateway/platforms/api_server.py`
- **函数**: `_response_messages_turn_start_index` (L4037)
- **调用方**: `_handle_session_chat_stream` → `_turn_transcript_messages` → `_response_messages_turn_start_index`
- **触发条件**: 会话上下文超过压缩阈值，`context_compressor` 在 agent 运行期间触发了压缩

## 根因分析

### 数据流

```
_handle_session_chat_stream (api_server.py:2102)
  │
  ├─ L2165: history = _conversation_history_for_session(session_id)
  │          ← 从 DB 加载会话历史（压缩前）
  │
  ├─ L2166: result = await _run_agent(conversation_history=history, ...)
  │          ← 代理运行。压缩在 conversation_loop.py:4924-4933 触发，
  │            messages 被重写，但 history 变量未更新
  │
  ├─ L2177: turn_messages = _turn_transcript_messages(history, ...)
  │          ← history 是压缩前的旧值
  │
  └─ L2190: "messages": turn_messages ← 注入 run.completed 事件
```

### 缺陷代码

`_response_messages_turn_start_index`（修复前）通过**前缀值匹配**来定位当前轮次起点：

```python
prior = list(conversation_history)          # 压缩前从 DB 加载的旧历史
current_user = {"role": "user", "content": user_message}
expected_prefix = prior + [current_user]

# 尝试 1：旧历史 + 当前用户消息 匹配 result["messages"] 前缀
if agent_messages[:len(expected_prefix)] == expected_prefix:
    return len(expected_prefix)   # 压缩后：失败——前缀已被 summary 替换

# 尝试 2：仅旧历史匹配
if prior and agent_messages[:len(prior)] == prior:
    return len(prior)             # 压缩后：也失败

# 兜底：返回 0 → turn = agent_messages[0:] —— 全部消息泄露！
return 0
```

压缩（`context_compressor.py:compress`）用摘要替换中段历史后，`result["messages"]` 的前缀是压缩摘要（`[CONTEXT COMPACTION]...`），与 DB 中加载的原始 `conversation_history` 完全不一致，两个前缀匹配均失败，函数返回 0。

### 压缩保证 user_message 一定存在

`context_compressor.py` 中的 `_find_tail_cut_by_tokens`（L2855）明确保证：

> "Never cuts inside a tool_call/result group. **Always ensures the most recent user message is in the tail**"

压缩后的 tail 消息（包含当前 `user_message`）被**原样复制**到 `compressed` 结果中（L3296-3324），因此 `result["messages"]` 中一定存在当前 `user_message`。

## 修复方案

### 策略

**从末尾向前搜索 `user_message`** 替代前缀值匹配。这是当前轮次最可靠的边界标记：无论压缩如何改写历史，当前 `user_message` 始终在压缩后的 tail 中。从末尾向前搜索确保找到最新出现的匹配（处理重复文本的边界情况）。

### 代码改动

**文件**: `gateway/platforms/api_server.py`，方法 `_response_messages_turn_start_index`

新增 Strategy 1（反向扫描），保留 Strategy 2（前缀匹配兜底）：

```python
# ── Strategy 1: reverse-scan for the current user message ──────
current_user = {"role": "user", "content": user_message}
for i in range(len(agent_messages) - 1, -1, -1):
    msg = agent_messages[i]
    if (
        isinstance(msg, dict)
        and msg.get("role") == "user"
        and msg.get("content") == user_message
    ):
        return i

# ── Strategy 2: prefix-match fallbacks ─────────────────────────
# (保留，用于 user_message 在 agent_messages 中不存在的极端情况)
prior = list(conversation_history)
expected_prefix = prior + [current_user]
if agent_messages[:len(expected_prefix)] == expected_prefix:
    return len(expected_prefix)
if prior and agent_messages[:len(prior)] == prior:
    return len(prior)
return 0
```

### 改动特点

- **最小侵入**: 仅修改一个方法，约 20 行
- **向后兼容**: 无压缩场景行为完全不变
- **健壮**: 不依赖调用者持有最新的 `conversation_history`，而是直接分析 `result["messages"]` 本身

## 测试

### 新增测试

**文件**: `tests/gateway/test_session_api.py`

| 测试 | 场景 | 验证内容 |
|------|------|----------|
| `test_turn_transcript_resilient_to_compression_prefix_mismatch` | 压缩后 history 前缀被 summary 替换 | `run.completed` 仅包含当前轮 assistant/tool 消息，不泄露 summary 和历史 |
| `test_turn_transcript_handles_duplicate_user_message_text` | 相同文本在历史和当前轮各出现一次 | 从末尾搜索确保找到当前轮的 `user_message`，不会截取到历史 |
| `test_turn_transcript_normal_path_unchanged` | 正常（无压缩）路径 | 回归测试：正常行为不受影响 |

### 已有测试覆盖

- `test_session_chat_stream_run_completed_carries_turn_transcript` — 正常 turn transcript 结构

### 运行结果

```
scripts/run_tests.sh tests/gateway/test_session_api.py -v
→ 15 tests passed, 0 failed
```

## 验证建议

由于当前没有可复现的 session，建议以下方式验证修复：

1. **写一个集成测试脚本**：创建一个长上下文的 session（连续发 50+ 轮消息），然后调用 `/chat/stream`，解析 SSE 中的 `run.completed` 事件，断言 `messages` 数组不包含早期历史消息。

2. **手动验证**：
   - 启动 hermes gateway
   - 通过 API 创建 session 并连续发送大量消息直到触发压缩
   - 调用 `/chat/stream`，检查 SSE 流中的 `run.completed` 事件

## 文件清单

| 文件 | 改动类型 |
|------|----------|
| `gateway/platforms/api_server.py` | 修复 `_response_messages_turn_start_index` |
| `tests/gateway/test_session_api.py` | 新增 3 个测试用例 |

## 日期

2026-07-23

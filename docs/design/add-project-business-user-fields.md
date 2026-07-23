# Hermes Session 增加 project_id / business_user_id 字段

## 背景

Hermes Agent 作为 agent 服务端需与后端业务服务交互。后端存在项目和用户的权限控制机制，需要将会话与 `project_id`（项目 ID）和 `business_user_id`（业务用户 ID）关联。之前后端只能通过全量拉取 session 列表再在应用层过滤，效率低且无法利用数据库索引。

## 改动方案

在 Hermes Session 的数据库层和 API 层新增两个冗余字段 `project_id` / `business_user_id`，支持：
1. **POST /api/sessions** 创建时传入并持久化
2. **GET /api/sessions** 列表查询时作为过滤条件
3. 响应体中携带这两个字段供下游消费

## 涉及文件

| 文件 | 改动数 |
|------|--------|
| `hermes_state.py` | 4 处（schema + 索引 + insert + query） |
| `gateway/platforms/api_server.py` | 3 处（create + list + response） |

## 实施细节

### 1. hermes_state.py — 数据库层

#### 1a. SCHEMA_SQL 加列（第 764-765 行）

在 sessions 表的 `system_prompt TEXT` 之后、`parent_session_id TEXT` 之前追加：

```diff
     system_prompt TEXT,
+    project_id TEXT,
+    business_user_id TEXT,
     parent_session_id TEXT,
```

`_reconcile_columns()` 自动检测缺失列并执行 `ALTER TABLE ADD COLUMN` —— 无需版本迁移，已有数据库下次启动时自动补充。

#### 1b. DEFERRED_INDEX_SQL 加组合索引（第 912-913 行）

```diff
 CREATE INDEX IF NOT EXISTS idx_sessions_handoff_state
     ON sessions(handoff_state, started_at);
+CREATE INDEX IF NOT EXISTS idx_sessions_project_user
+    ON sessions(project_id, business_user_id, started_at DESC);
```

`WHERE project_id = ? AND business_user_id = ? ORDER BY started_at DESC` 可走索引范围扫描，避免全表扫。

#### 1c. _insert_session_row() 加参数及 INSERT 语句（第 1767-1768 行）

函数签名新增两个可选参数：

```diff
     def _insert_session_row(
         self,
         ...
         cwd: str = None,
+        project_id: str = None,
+        business_user_id: str = None,
     ) -> None:
```

INSERT 语句的列列表、placeholder 数量和 VALUES 元组同步更新：

```diff
                 """INSERT INTO sessions (
                    id, source, user_id, session_key, chat_id, chat_type, thread_id,
-                   model, model_config, system_prompt, parent_session_id, cwd, started_at
+                   model, model_config, system_prompt,
+                   project_id, business_user_id,
+                   parent_session_id, cwd, started_at
                 )
-                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
+                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        ...
+                       project_id = COALESCE(sessions.project_id, excluded.project_id),
+                       business_user_id = COALESCE(sessions.business_user_id, excluded.business_user_id)""",
```

VALUES 元组追加两个参数：`project_id, business_user_id`。

`create_session(session_id, source, **kwargs)` 使用 `**kwargs` 透传，**无需改动**。

#### 1d. list_sessions_rich() 加过滤参数（第 3372-3373 行）

函数签名新增：

```diff
     def list_sessions_rich(
         self,
         ...
         compact_rows: bool = False,
+        project_id: str = None,
+        business_user_id: str = None,
     ) -> List[Dict[str, Any]]:
```

WHERE 子句构建段追加（第 3453-3458 行）：

```diff
         if archived_only:
             where_clauses.append("s.archived = 1")
         elif not include_archived:
             where_clauses.append("s.archived = 0")
+        if project_id is not None:
+            where_clauses.append("s.project_id = ?")
+            params.append(project_id)
+        if business_user_id is not None:
+            where_clauses.append("s.business_user_id = ?")
+            params.append(business_user_id)
```

参数通过 `?` 占位符绑定，防止 SQL 注入。

---

### 2. api_server.py — API 层

#### 2a. _handle_create_session() 接收字段（第 1917-1925 行）

```diff
+        project_id = body.get("project_id")
+        business_user_id = body.get("business_user_id")
+        if project_id is not None and not isinstance(project_id, str):
+            return web.json_response(_openai_error("project_id must be a string", code="invalid_project_id"), status=400)
+        if business_user_id is not None and not isinstance(business_user_id, str):
+            return web.json_response(_openai_error("business_user_id must be a string", code="invalid_business_user_id"), status=400)
-        db.create_session(session_id, "api_server", model=str(model) if model else None, system_prompt=system_prompt)
+        db.create_session(
+            session_id, "api_server",
+            model=str(model) if model else None,
+            system_prompt=system_prompt,
+            project_id=project_id,
+            business_user_id=business_user_id,
+        )
```

#### 2b. _handle_list_sessions() 支持查询过滤（第 1874-1882 行）

```diff
+        project_id = request.query.get("project_id") or None
+        business_user_id = request.query.get("business_user_id") or None
         sessions = db.list_sessions_rich(
             source=source,
             limit=limit,
             offset=offset,
             include_children=include_children,
             order_by_last_active=True,
+            project_id=project_id,
+            business_user_id=business_user_id,
         )
```

#### 2c. _session_response() 暴露字段（第 1813 行）

```diff
         safe_keys = (
             ...
-            "_lineage_root_id",
+            "_lineage_root_id", "project_id", "business_user_id",
         )
```

---

## API 使用示例

### 创建会话时传入

```bash
curl -X POST http://localhost:8642/api/sessions \
  -H "Authorization: Bearer sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "项目A调试会话",
    "project_id": "proj-alpha",
    "business_user_id": "user-789"
  }'
```

### 按项目+用户筛选会话

```bash
# 查询项目 proj-alpha 下业务用户 user-789 的所有会话
curl "http://localhost:8642/api/sessions?project_id=proj-alpha&business_user_id=user-789&limit=20&offset=0" \
  -H "Authorization: Bearer sk-xxx"
```

### 响应示例

```jsonc
{
  "object": "list",
  "data": [
    {
      "id": "api_1742567890_a1b2c3d4",
      "source": "api_server",
      "model": "gpt-4o",
      "title": "项目A调试会话",
      "project_id": "proj-alpha",
      "business_user_id": "user-789",
      "started_at": 1742567890.0,
      "message_count": 5,
      "last_active": 1742568890.0,
      "preview": "帮我查一下订单..."
    }
  ],
  "limit": 20,
  "offset": 0,
  "has_more": false
}
```

---

## 测试验证

| 测试套件 | 结果 |
|----------|------|
| `tests/gateway/test_session_api.py` | 12 passed |
| `tests/hermes_cli/test_web_server.py` | 385 passed |
| `tests/test_hermes_state.py` | 366 passed |

---

## 安全 / 兼容性

- **向后兼容**：新列允许 `NULL`，已有会话不受影响；未传 `project_id` / `business_user_id` 的请求行为不变
- **SQL 注入防护**：所有传值通过参数化查询 `?` 绑定
- **认证防护**：所有 `/api/sessions` 接口受 `Authorization: Bearer` 保护（当配置了 `API_SERVER_KEY` 时）
- **零侵入**：不修改 Hermes 内部用户/权限模型，仅做冗余存储+API 透传

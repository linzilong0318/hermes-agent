# Nacos 服务注册 & 业务依赖集成 — 改动方案

## 背景

Hermes Agent 容器化部署到 Ubuntu 服务器，需要通过 Nacos 完成服务注册与心跳保活。同时后端业务需要文档处理能力（PDF 提取、docx 转换、md2pdf）。本次改动将相关依赖纳入 pyproject.toml 统一管理，并用 s6-overlay 原生方式管理 Nacos 注册 daemon。

## 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `pyproject.toml` | 修改 | 新增 `nacos` 和 `docx` 两个 extras |
| `uv.lock` | 自动更新 | `uv lock` 生成，新增 20 个包 |
| `Dockerfile` | 修改 | uv sync 添加 `--extra nacos --extra docx` |
| `docker/nacos_daemon.py` | **新建** | Nacos 心跳 daemon 独立脚本 |
| `docker/s6-rc.d/nacos-registrar/type` | **新建** | s6 服务类型: `longrun` |
| `docker/s6-rc.d/nacos-registrar/run` | **新建** | 启动脚本 |
| `docker/s6-rc.d/nacos-registrar/finish` | **新建** | 退出处理脚本（env-gated） |
| `docker/s6-rc.d/nacos-registrar/dependencies.d/base` | **新建** | s6 基础依赖声明 |
| `docker/s6-rc.d/user/contents.d/nacos-registrar` | **新建** | 注册到 user bundle |
| 核心源码 | **零改动** | 不碰 Hermes 核心 Python 代码 |

---

## 1. pyproject.toml — 新增 extras

在 `youtube` extra 和 `web` extra 之间插入两个新 extra：

```toml
# Nacos service discovery — fork-specific, for Docker container Nacos registration
# daemon. Pinned to 1.0.0 per verified working setup.
nacos = ["nacos-sdk-python==1.0.0"]
# Document processing — fork-specific, for backend document handling skills
# (PDF extraction, docx conversion, markdown-to-pdf).
docx = ["pymupdf==1.28.0", "pymupdf4llm==1.28.0", "python-docx==1.2.0", "md2pdf==3.1.1"]
```

### 包含的依赖

| extra | 包 | 版本 | 用途 |
|-------|-----|------|------|
| `nacos` | nacos-sdk-python | 1.0.0 | Nacos 服务注册与心跳 |
| `docx` | pymupdf | 1.28.0 | PDF 处理（MuPDF 绑定） |
| `docx` | pymupdf4llm | 1.28.0 | LLM 友好的 PDF 文本提取 |
| `docx` | python-docx | 1.2.0 | .docx 文件读写 |
| `docx` | md2pdf | 3.1.1 | Markdown 转 PDF |

> `md2pdf` 会传递依赖 `weasyprint`（基于 CSS 的 PDF 渲染引擎），这是其正常工作所需要。

---

## 2. Dockerfile — uv sync 添加 extras

第 221 行 uv sync 命令追加 `--extra nacos --extra docx`：

```dockerfile
RUN uv sync --frozen --no-install-project \
    --extra all --extra messaging --extra anthropic --extra bedrock \
    --extra azure-identity --extra hindsight --extra matrix \
    --extra nacos --extra docx
```

这样在 Docker build 阶段就把 Nacos 和文档处理依赖预装到镜像中了。

---

## 3. docker/nacos_daemon.py — Nacos 心跳守护程序

从用户已验证的内联 heredoc Python 脚本提取为独立文件，放在 `/opt/hermes/docker/nacos_daemon.py`。

### 改进点

| 对比原 heredoc | 新文件 |
|----------------|--------|
| 内联在 bash 中，难维护 | 独立 `.py` 文件，语法高亮 + lint |
| 日志混在 stdout | 输出到 stderr（s6 捕获到日志系统） |
| 心跳间隔硬编码 5s | 支持 `NACOS_HEARTBEAT_INTERVAL` 环境变量覆盖 |
| 打印到 stdout 与 nohup 混合 | 统一 logging 输出到 stderr |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NACOS_SERVER_ADDRESSES` | —（必填） | Nacos 地址，如 `10.120.7.99:8848` |
| `NACOS_NAMESPACE` | `""` | Nacos 命名空间 ID |
| `NACOS_GROUP_NAME` | `DEFAULT_GROUP` | 分组名 |
| `NACOS_SERVICE_NAME` | `hermes-agent` | 服务注册名 |
| `NACOS_SERVICE_PORT` | `8642` | 服务端口 |
| `NACOS_USERNAME` | `nacos` | Nacos 用户名 |
| `NACOS_PASSWORD` | `nacos` | Nacos 密码 |
| `NACOS_HEARTBEAT_INTERVAL` | `5` | 心跳间隔（秒） |

### 工作流程

```
1. 读取环境变量 → NacosConfig dataclass
2. 通过 UDP 连接 8.8.8.8:80 获取容器 IP
3. 创建 NacosClient（server_addresses + namespace + auth）
4. 调用 add_naming_instance() 注册服务
5. 进入 while True 心跳循环：send_heartbeat() → sleep(interval)
6. 任意异常 → 日志打印 → 重试等待 1s → 继续
```

---

## 4. s6-overlay 服务定义 — nacos-registrar

### 目录结构

```
docker/s6-rc.d/nacos-registrar/
├── type                   # longrun
├── run                    # 启动脚本（with-contenv + s6-setuidgid）
├── finish                 # 退出处理（env-gated）
└── dependencies.d/
    └── base               # 空文件，声明依赖 base bundle
```

### 生命周期

```
容器启动
  └─ /init (PID 1, s6-svscan)
       ├─ cont-init.d/...          ← stage2-hook（UID remap, chown, 配置）
       ├─ nacos-registrar (longrun) ← 本方案的 Nacos 心跳 daemon
       │    ├─ NACOS_SERVER_ADDRESSES 为空? → exit 0 → finish exit 125 → slot down
       │    └─ 有配置? → s6-setuidgid hermes → python nacos_daemon.py
       │         ├─ 注册成功 → 心跳循环（持续运行）
       │         ├─ 崩溃 → s6-supervise 自动重启
       │         └─ 容器停止 → SIGTERM → 进程终止
       ├─ main-hermes (longrun)   ← 已有占位（sleep infinity）
       └─ dashboard (longrun)     ← 已有，受 HERMES_DASHBOARD 控制
```

### finish 脚本的 env-gate

与 `dashboard` 服务的模式完全一致：

| NACOS_SERVER_ADDRESSES | run 行为 | finish 行为 |
|------------------------|----------|-------------|
| 未设置 / 空 | exit 0 | exit 125 → s6 标记为 permanently down，不重启 |
| 已设置 | 启动 daemon | exit 0 → 异常退出时 s6 自动重启 |

---

## 5. 测试验证

| 测试套件 | 结果 |
|----------|------|
| `tests/gateway/test_session_api.py` | 12 passed |
| `tests/test_hermes_state.py` | 366 passed |
| `tests/test_packaging_metadata.py` | 11 passed |
| `uv lock` 依赖解析 | 253 packages resolved in 5.21s |

---

## 6. 构建设置

```bash
# 构建镜像
docker build \
  --build-arg HERMES_GIT_SHA=$(git rev-parse HEAD) \
  -t hermes-agent:latest \
  .

# 运行容器（带 Nacos）
docker run -d \
  -e NACOS_SERVER_ADDRESSES="10.120.7.99:8848" \
  -e NACOS_NAMESPACE="public" \
  -e NACOS_SERVICE_NAME="hermes-agent" \
  -e NACOS_SERVICE_PORT="8642" \
  -e NACOS_USERNAME="nacos" \
  -e NACOS_PASSWORD="nacos" \
  -p 8642:8642 \
  hermes-agent:latest
  hermes gateway run

# 运行容器（不带 Nacos — Nacos 服务自动跳过）
docker run -d \
  -p 8642:8642 \
  hermes-agent:latest
  hermes gateway run
```

### 验证 Nacos 注册

```bash
# 查看 Nacos daemon 日志（通过 s6）
docker exec <container> cat /opt/data/logs/nacos-registrar/current

# 或直接查 Nacos 控制台（服务列表应出现 hermes-agent）
```

---

## 7. 注意事项

1. **不要修改 Hermes 上游核心源码**：所有改动都是 Docker 层和 pyproject.toml extras，保持与 upstream 的最小 diff，降低后续合并冲突。
2. **`md2pdf` 会引入 weasyprint**：这是一个基于 CSS 的 PDF 渲染引擎，需要系统字体和 Cairo/Pango 库。Dockerfile 中已有的 `gcc`、`g++`、`cmake`、`python3-dev` 等 build-time 工具链已满足其原生扩展编译需求。
3. **nacos-sdk-python 1.0.0**：用户已验证可用的版本，虽非最新（3.2.0），但 `add_naming_instance` + `send_heartbeat` API 稳定不变，无需升级。

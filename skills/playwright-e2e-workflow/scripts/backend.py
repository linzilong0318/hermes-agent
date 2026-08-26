#!/opt/hermes/.venv/bin/python3
"""playwright-e2e-workflow 后端接口公共库(纯 stdlib + nacos-sdk-python 可选)。

供 fetch_config.py / upload_artifact.py 复用:
- 接口前缀: 默认通过 Nacos 动态发现(nacos-sdk-python),失败回退固定地址
  DEFAULT_PREFIX(可 --prefix 显式覆盖,见 resolve_backend_prefix)
- 兼容两种响应 envelope: {code,msg}(文档示例) 与 {success,message}(实测)
  成功判定: code=="200" 或 success==true
- HTTP GET / multipart POST(不依赖 requests)
"""
import json
import mimetypes
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

mimetypes.add_type("application/json", ".json")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/plain", ".ts")

DEFAULT_PREFIX = "http://10.120.7.97:8005/ai-test"  # 回退前缀(Nacos 发现失败时使用)

# ---- Nacos 服务发现(前缀动态化,失败回退 DEFAULT_PREFIX) ----
# 环境变量可覆盖;默认值与经用户验证的 discover_and_call.py 参考脚本一致。
NACOS_DEFAULTS = {
    "NACOS_SERVER_ADDRESSES": "10.120.7.97:8848",
    "NACOS_NAMESPACE": "",
    "NACOS_USERNAME": "nacos",
    "NACOS_PASSWORD": "",
    "NACOS_GROUP_NAME": "DEFAULT_GROUP",
    "BACKEND_SERVICE_NAME": "ai-test",  # 既是 Nacos 服务名,也是 URL 路径前缀(容器启动注入,默认 ai-test)
}
NACOS_TIMEOUT_SECONDS = 5  # 有界超时:Nacos 不可达时快速回退,避免长时间挂起

_backend_prefix_cache = None


def resolve_backend_prefix(force: bool = False) -> str:
    """解析后端接口前缀(形如 http://ip:port/ai-test)。

    优先级: 显式 --prefix(调用方处理)> Nacos 动态发现 > DEFAULT_PREFIX 回退。
    - 成功结果缓存本次进程(force=True 强制重新发现);
    - NACOS_DISABLED=1 直接跳过 Nacos 走固定地址(调试逃生舱);
    - Nacos 发现失败(包未装/连不上/无健康实例)时打印 [warn] 并回退,不退出。
    """
    global _backend_prefix_cache
    if _backend_prefix_cache and not force:
        return _backend_prefix_cache

    if os.environ.get("NACOS_DISABLED"):
        print(f"[info] NACOS_DISABLED=1,跳过 Nacos,使用固定前缀 {DEFAULT_PREFIX}")
        base = DEFAULT_PREFIX
    else:
        try:
            base = _discover_via_nacos()
            print(f"[info] Nacos 发现后端前缀: {base}")
        except Exception as e:
            print(f"[warn] Nacos 服务发现失败({e}),回退固定前缀 {DEFAULT_PREFIX}", file=sys.stderr)
            base = DEFAULT_PREFIX

    _backend_prefix_cache = base
    return base


def _discover_via_nacos() -> str:
    """通过 Nacos 发现后端服务,返回 http://{ip}:{port}/{service_name}。

    - 懒导入 nacos: 未安装抛 ImportError,由 resolve_backend_prefix 捕获后回退;
    - 无健康实例/实例缺 ip 抛 RuntimeError;
    - 用 socket.setdefaulttimeout 做有界超时(对底层 requests/urllib3 生效),保证快速回退。
    """
    import socket

    import nacos  # 懒导入:未安装抛 ImportError → 触发回退
    # 注意: nacos-sdk-python 3.x 起 API 重构(v2.nacos,构造参数与方法完全不同);
    # 容器统一使用 1.0.0(实测兼容),本代码按 1.0.0 接口(NacosClient(server_addresses=...)
    # + list_naming_instance(service, group_name=...))编写;若为 3.x 会在此抛异常并回退固定地址。

    server = os.environ.get("NACOS_SERVER_ADDRESSES") or NACOS_DEFAULTS["NACOS_SERVER_ADDRESSES"]
    namespace = os.environ.get("NACOS_NAMESPACE") or NACOS_DEFAULTS["NACOS_NAMESPACE"]
    username = os.environ.get("NACOS_USERNAME") or NACOS_DEFAULTS["NACOS_USERNAME"]
    password = os.environ.get("NACOS_PASSWORD") or NACOS_DEFAULTS["NACOS_PASSWORD"]
    group = os.environ.get("NACOS_GROUP_NAME") or NACOS_DEFAULTS["NACOS_GROUP_NAME"]
    service = os.environ.get("BACKEND_SERVICE_NAME") or NACOS_DEFAULTS["BACKEND_SERVICE_NAME"]

    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(NACOS_TIMEOUT_SECONDS)
    try:
        client = nacos.NacosClient(
            server_addresses=server,
            namespace=namespace,
            username=username,
            password=password,
        )
        instances = client.list_naming_instance(service, group_name=group)
    finally:
        socket.setdefaulttimeout(old_timeout)

    hosts = (instances or {}).get("hosts") or []
    healthy = [h for h in hosts if h.get("healthy", False)]
    if not healthy:
        raise RuntimeError(f"服务 {service} 无健康实例({len(hosts)} 个实例均不健康)")
    inst = healthy[0]
    ip = inst.get("ip") or inst.get("host") or ""
    port = inst.get("port", 8080)
    if not ip:
        raise RuntimeError(f"服务 {service} 健康实例缺少 ip 字段")
    return f"http://{ip}:{port}/{service}"


# ---- 后端接口常量(v6:五类接口,见 SKILL.md「后端接口」) ----
API_CONFIG_DETAIL = "/api/v1/web-test/config/detail"      # 拉基准配置(可带重复 resourceList 过滤)
API_FUNCTION_RESOURCES = "/api/v1/web-test/function/resources"  # 场景 B:按 functionUid 取脚本/计划/报告
API_FUNCTION_SAVE = "/api/v1/web-test/function/save"       # 场景 A:同步数据库(functionUid 可选:空=新建,传=删除历史记录并新建,见 publish_artifacts.py)
API_UPLOAD_RAW = "/file/upload"           # 裸 MinIO 上传(只认 file 字段,带业务参数即 00001)
API_UPLOAD_BIZ = "/api/v1/file/upload"    # 业务上传(query type/sessionId/functionUid,按类型整表替换)


def http_get(url: str, timeout: int = 20):
    """GET,返回 (http_status, body_text)。网络异常抛 urllib 异常由调用方处理。"""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def http_post_multipart(url: str, fields: dict, file_field: str, file_path: str,
                        timeout: int = 90):
    """POST multipart/form-data(纯 stdlib 手工拼装)。
    返回 (http_status, body_text)。"""
    boundary = "----hermes-e2e-%08x" % random.randrange(16 ** 8)
    chunks = []
    for k, v in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    fname = os.path.basename(file_path)
    file_ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        fdata = f.read()
    chunks.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
         f'filename="{fname}"\r\nContent-Type: {file_ctype}\r\n\r\n').encode()
    )
    chunks.append(fdata)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def http_post_json(url: str, body: dict, timeout: int = 30):
    """POST application/json。返回 (http_status, body_text)。"""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def parse_envelope(body: str):
    """解析响应体,兼容 {code,msg} 与 {success,message}。
    返回 (ok: bool, code: str, message: str, data: any)。"""
    try:
        d = json.loads(body)
    except Exception:
        return False, "PARSE_ERR", f"非 JSON 响应: {body[:200]}", None
    data = d.get("data")
    if "success" in d:
        ok = d.get("success") is True
        code = str(d.get("code") or ("200" if ok else "00001"))
        msg = str(d.get("message") or "")
    else:
        code = str(d.get("code") or "")
        ok = code == "200"
        msg = str(d.get("msg") or "")
    return ok, code, msg, data


def session_id_from_env() -> str:
    """sessionId 直接用环境变量 $HERMES_SESSION_ID,不询问用户。"""
    sid = os.environ.get("HERMES_SESSION_ID", "").strip()
    if not sid:
        print("错误: 环境变量 HERMES_SESSION_ID 为空,无法确定 sessionId", file=sys.stderr)
        sys.exit(2)
    return sid


def die(msg: str, code: int = 2):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)
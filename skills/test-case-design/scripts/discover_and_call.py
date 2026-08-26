#!/usr/bin/env python3
"""
Nacos 服务发现 + REST API 调用 —— 通用模块。

可作为库导入使用，也可作为独立脚本运行。

=== 作为库使用 ===
    import sys
    sys.path.insert(0, '/path/to/scripts')
    from discover_and_call import discover_service, build_url, call_api, call_api_multipart

=== 作为独立脚本运行 ===
    python scripts/discover_and_call.py

环境变量：
    NACOS_SERVER_ADDRESSES  - Nacos 服务器地址 (e.g. 10.120.7.97:8848)
    NACOS_NAMESPACE         - Nacos 命名空间 ID
    NACOS_USERNAME          - Nacos 登录用户名
    NACOS_PASSWORD          - Nacos 登录密码
    BACKEND_SERVICE_NAME    - 要发现的后端服务名（同时也是 URL 路径中的服务名前缀）
    NACOS_GROUP_NAME        - Nacos 分组名 (可选, 默认 DEFAULT_GROUP)

URL 拼接规则：http://{ip}:{port}/{service_name}/{api_path}

安全规则：
    - 所有 print 输出均不包含密码等敏感值
    - 调试输出中用户名仅显示前 4 字符
"""
import os
import sys
import json
import urllib.request
import urllib.error


# ============================================================================
# 环境变量工具
# ============================================================================

def get_env_or_fail(key):
    """读取必需环境变量，不存在则报错退出。"""
    val = os.environ.get(key)
    if not val:
        print(f"[FATAL] 环境变量 {key} 未设置")
        print("[HINT] 请确认已 export 所需环境变量。当前 NACOS_* 变量：")
        for k, v in sorted(os.environ.items()):
            if k.startswith('NACOS_') or k.startswith('BACKEND_'):
                if 'PASSWORD' in k or 'TOKEN' in k or 'SECRET' in k or 'KEY' in k:
                    display = '***' if v else '(空)'
                else:
                    display = f'{v[:4]}***' if v and len(v) > 4 else (v or '(空)')
                print(f"        {k}={display}")
        sys.exit(1)
    return val


def mask_sensitive(key, value):
    """对敏感环境变量的值进行脱敏，仅保留前 4 字符。"""
    if not value:
        return '(空)'
    sensitive_keys = {'PASSWORD', 'TOKEN', 'SECRET', 'KEY', 'CREDENTIAL'}
    for sk in sensitive_keys:
        if sk in key.upper():
            return '***'
    if len(value) > 4:
        return f'{value[:4]}***'
    return value


# ============================================================================
# Nacos 服务发现
# ============================================================================

def discover_service(client, service_name, group_name='DEFAULT_GROUP'):
    """
    从 Nacos 发现 service_name 的第一个健康实例。

    Args:
        client: NacosClient 实例
        service_name: 服务名称
        group_name: Nacos 分组名

    Returns:
        (ip: str, port: int)
    """
    instances = client.list_naming_instance(service_name, group_name=group_name)
    if not instances or not instances.get('hosts'):
        print(f"[ERROR] 未发现服务实例: {service_name}")
        sys.exit(1)

    hosts = instances['hosts']
    print(f"[INFO] 发现 {len(hosts)} 个实例:")
    for h in hosts:
        print(f"  - {h.get('ip')}:{h.get('port')}  healthy={h.get('healthy')}")

    healthy = [h for h in hosts if h.get('healthy', False)]
    if not healthy:
        print("[ERROR] 没有健康的实例可用")
        sys.exit(1)

    inst = healthy[0]
    ip = inst.get('ip') or inst.get('host', '')
    port = inst.get('port', 8080)
    print(f"[INFO] 选择实例: {ip}:{port}")
    return ip, port


def build_url(ip, port, service_name, api_path):
    """
    拼接完整 URL。

    Args:
        ip: 服务 IP
        port: 服务端口
        service_name: 服务名（作为 URL 路径前缀）
        api_path: API 路径，必须以 '/' 开头

    Returns:
        完整 URL 字符串，如 http://10.0.0.1:8080/my-service/api/v1/endpoint
    """
    return f'http://{ip}:{port}/{service_name}{api_path}'


# ============================================================================
# API 调用
# ============================================================================

def call_api(url, method='POST', payload=None, headers=None, timeout=60):
    """
    发起 JSON API 请求。

    Args:
        url: 完整请求 URL
        method: HTTP 方法
        payload: JSON 请求体（dict，可为 None）
        headers: 额外的请求头
        timeout: 超时秒数

    Returns:
        (status_code: int, response_body: str)
    """
    if headers is None:
        headers = {}
    headers.setdefault('Content-Type', 'application/json')

    body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    print(f"[INFO] {method} {url}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode('utf-8')
            print(f"[SUCCESS] HTTP {resp.status}")
            print(f"[SUCCESS] 响应: {resp_body[:500]}{'...(截断)' if len(resp_body) > 500 else ''}")
            return resp.status, resp_body
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode('utf-8', errors='replace')
        print(f"[ERROR] HTTP {e.code}")
        print(f"[ERROR] 响应: {resp_body[:500]}")
        return e.code, resp_body
    except Exception as e:
        print(f"[ERROR] 请求异常: {e}")
        return 0, str(e)


def call_api_multipart(url, file_path, query_params=None, timeout=60):
    """
    发起 multipart/form-data 文件上传请求。

    Args:
        url: 完整请求 URL（不含 query string）
        file_path: 要上传的文件路径
        query_params: URL query 参数字典，如 {'type': 'REPORT', 'sessionId': 'xxx'}
        timeout: 超时秒数

    Returns:
        (status_code: int, response_body: str)
    """
    import uuid

    boundary = f'----FormBoundary{uuid.uuid4().hex[:16]}'

    # 构建 multipart body
    with open(file_path, 'rb') as f:
        file_data = f.read()

    file_name = os.path.basename(file_path)
    body_parts = []
    body_parts.append(f'--{boundary}'.encode('utf-8'))
    body_parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"'
        .encode('utf-8')
    )
    # 根据文件扩展名自动推断 MIME type，兜底为 application/octet-stream
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_path)
    body_parts.append(f'Content-Type: {mime_type or "application/octet-stream"}'.encode('utf-8'))
    body_parts.append(b'')
    body_parts.append(file_data)
    body_parts.append(f'--{boundary}--'.encode('utf-8'))

    body = b'\r\n'.join(body_parts)

    # 拼接 query string
    full_url = url
    if query_params:
        from urllib.parse import urlencode
        full_url = f'{url}?{urlencode(query_params)}'

    headers = {
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    }

    req = urllib.request.Request(full_url, data=body, headers=headers, method='POST')

    print(f"[INFO] POST {full_url}")
    print(f"[INFO] 上传文件: {file_name} ({len(file_data)} bytes)")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode('utf-8')
            print(f"[SUCCESS] HTTP {resp.status}")
            print(f"[SUCCESS] 响应: {resp_body[:500]}{'...(截断)' if len(resp_body) > 500 else ''}")
            return resp.status, resp_body
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode('utf-8', errors='replace')
        print(f"[ERROR] HTTP {e.code}")
        print(f"[ERROR] 响应: {resp_body[:500]}")
        return e.code, resp_body
    except Exception as e:
        print(f"[ERROR] 请求异常: {e}")
        return 0, str(e)


# ============================================================================
# 独立运行入口
# ============================================================================

if __name__ == '__main__':
    from nacos import NacosClient

    # --- 读取环境变量 ---
    SERVER_ADDRESSES = os.environ.get('NACOS_SERVER_ADDRESSES', '10.120.7.97:8848')
    NAMESPACE = os.environ.get('NACOS_NAMESPACE', '')
    USERNAME = os.environ.get('NACOS_USERNAME', 'nacos')
    PASSWORD = os.environ.get('NACOS_PASSWORD', '')
    SERVICE_NAME = get_env_or_fail('BACKEND_SERVICE_NAME')
    GROUP_NAME = os.environ.get('NACOS_GROUP_NAME', 'DEFAULT_GROUP')

    print(f"[INFO] Nacos 地址: {SERVER_ADDRESSES}")
    print(f"[INFO] 命名空间: {NAMESPACE[:4]}***" if NAMESPACE and len(NAMESPACE) > 4 else f"[INFO] 命名空间: {NAMESPACE}")
    print(f"[INFO] 后端服务名: {SERVICE_NAME}")
    print(f"[INFO] Nacos 分组: {GROUP_NAME}")

    # --- 创建 Nacos 客户端 ---
    client = NacosClient(
        server_addresses=SERVER_ADDRESSES,
        namespace=NAMESPACE,
        username=USERNAME,
        password=PASSWORD,
    )

    # --- 发现服务 ---
    ip, port = discover_service(client, SERVICE_NAME, GROUP_NAME)

    # --- 发送测试请求 ---
    API_PATH = '/api/v1/testcase/save'
    url = build_url(ip, port, SERVICE_NAME, API_PATH)

    payload = {
        'sessionId': 'test_session',
        'cases': [
            {
                'caseCode': 'TC_TEST_001',
                'batchNo': '20260722000000001',
                'title': '验证连通性测试用例',
                'type': 1,
                'module': '连通性测试',
                'subModule': '',
                'priority': 2,
                'preconditions': '1. 系统正常运行',
                'steps': '1. 发送连通性测试请求',
                'expectedResults': '1. 接口正常响应',
            }
        ],
    }

    print(f"\n[INFO] 请求体: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    call_api(url, method='POST', payload=payload)

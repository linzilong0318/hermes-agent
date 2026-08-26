#!/usr/bin/env python3
"""
上传测试用例到后端服务。

流程：Nacos 服务发现 → 读取本地 JSON 文件 → POST 到 /api/v1/testcase/save

Usage:
  python scripts/upload_cases.py --payload-file <JSON_PATH> [--session-id <ID>]

环境变量依赖（与 discover_and_call.py 相同）：
  NACOS_SERVER_ADDRESSES, NACOS_NAMESPACE, NACOS_USERNAME, NACOS_PASSWORD,
  BACKEND_SERVICE_NAME, NACOS_GROUP_NAME (可选)

安全规则：不打印密码等敏感环境变量值。
"""
import argparse
import json
import os
import sys
import urllib.error

# 将 scripts 目录加入 path，以便导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from discover_and_call import (
    get_env_or_fail,
    discover_service,
    build_url,
    call_api,
    mask_sensitive,
)


def main():
    parser = argparse.ArgumentParser(
        description='上传测试用例到后端服务（自动通过 Nacos 发现服务地址）'
    )
    parser.add_argument('--payload-file', required=True,
                        help='用例 JSON 文件路径（由阶段二生成的 cases_payload.json）')
    parser.add_argument('--session-id', default=None,
                        help='会话标识（可选，默认从 JSON 文件中读取）')
    args = parser.parse_args()

    # --- 1. 检查 JSON 文件 ---
    if not os.path.exists(args.payload_file):
        print(f"[FATAL] JSON 文件不存在: {args.payload_file}")
        sys.exit(1)

    with open(args.payload_file, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    session_id = args.session_id or payload.get('sessionId', 'unknown')
    case_count = len(payload.get('cases', []))
    print(f"[INFO] Session ID: {session_id}")
    print(f"[INFO] 用例数量: {case_count}")

    if case_count == 0:
        print("[ERROR] JSON 文件中没有用例数据（cases 数组为空）")
        sys.exit(1)

    # --- 2. 读取环境变量 ---
    SERVER_ADDRESSES = os.environ.get('NACOS_SERVER_ADDRESSES', '10.120.7.97:8848')
    NAMESPACE = os.environ.get('NACOS_NAMESPACE', '')
    USERNAME = os.environ.get('NACOS_USERNAME', 'nacos')
    PASSWORD = os.environ.get('NACOS_PASSWORD', '')
    SERVICE_NAME = get_env_or_fail('BACKEND_SERVICE_NAME')
    GROUP_NAME = os.environ.get('NACOS_GROUP_NAME', 'DEFAULT_GROUP')

    print(f"[INFO] Nacos 地址: {SERVER_ADDRESSES}")

    # --- 3. 创建 Nacos 客户端并发现服务 ---
    from nacos import NacosClient
    client = NacosClient(
        server_addresses=SERVER_ADDRESSES,
        namespace=NAMESPACE,
        username=USERNAME,
        password=PASSWORD,
    )

    ip, port = discover_service(client, SERVICE_NAME, GROUP_NAME)

    # --- 4. 拼接 URL 并上传 ---
    API_PATH = '/api/v1/testcase/save'
    url = build_url(ip, port, SERVICE_NAME, API_PATH)

    print(f"[INFO] 开始上传 {case_count} 条用例...")
    status, resp_body = call_api(url, method='POST', payload=payload, timeout=120)

    if 200 <= status < 300:
        try:
            resp = json.loads(resp_body)
            if resp.get('success'):
                print(f"\n[SUCCESS] 用例上传成功！共 {case_count} 条")
                sys.exit(0)
            else:
                print(f"\n[ERROR] 后端返回失败: {resp.get('message', '未知错误')}")
                sys.exit(1)
        except json.JSONDecodeError:
            print(f"\n[WARN] 无法解析响应 JSON，但 HTTP 状态码正常 ({status})")
            sys.exit(0)
    else:
        print(f"\n[ERROR] 上传失败，HTTP {status}")
        sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
上传文档（PDF）到后端文件服务。

流程：Nacos 服务发现 → multipart/form-data 上传到 /api/v1/file/upload

Usage:
  # 上传待澄清需求清单
  python scripts/upload_file.py \
      --file /opt/data/tmp/test-case-design/{sessionId}/待澄清需求清单_{batchNo}.pdf \
      --session-id {sessionId} \
      --batch-no {batchNo} \
      --type CHECKLIST

  # 上传测试用例评审报告
  python scripts/upload_file.py \
      --file /opt/data/tmp/test-case-design/{sessionId}/测试用例评审报告_{batchNo}.pdf \
      --session-id {sessionId} \
      --batch-no {batchNo} \
      --type REPORT

环境变量依赖（与 discover_and_call.py 相同）：
  NACOS_SERVER_ADDRESSES, NACOS_NAMESPACE, NACOS_USERNAME, NACOS_PASSWORD,
  BACKEND_SERVICE_NAME, NACOS_GROUP_NAME (可选)

安全规则：不打印密码等敏感环境变量值。
"""
import argparse
import json
import os
import sys

# 将 scripts 目录加入 path，以便导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from discover_and_call import (
    get_env_or_fail,
    discover_service,
    build_url,
    call_api_multipart,
)


def main():
    parser = argparse.ArgumentParser(
        description='上传 PDF 文档到后端文件服务（自动通过 Nacos 发现服务地址）'
    )
    parser.add_argument('--file', required=True,
                        help='要上传的 PDF 文件路径')
    parser.add_argument('--session-id', required=True,
                        help='会话标识')
    parser.add_argument('--batch-no', required=True,
                        help='批次号')
    parser.add_argument('--type', required=True, choices=['CHECKLIST', 'REPORT'],
                        help='上传类型：CHECKLIST（待澄清需求清单）或 REPORT（评审报告）')
    args = parser.parse_args()

    # --- 1. 检查文件是否存在 ---
    if not os.path.exists(args.file):
        print(f"[FATAL] 文件不存在: {args.file}")
        sys.exit(1)

    file_size = os.path.getsize(args.file)
    print(f"[INFO] Session ID: {args.session_id}")
    print(f"[INFO] 批次号: {args.batch_no}")
    print(f"[INFO] 上传类型: {args.type}")
    print(f"[INFO] 文件: {args.file} ({file_size} bytes)")

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
    API_PATH = '/api/v1/file/upload'
    url = build_url(ip, port, SERVICE_NAME, API_PATH)

    query_params = {
        'type': args.type,
        'sessionId': args.session_id,
        'batchNo': args.batch_no,
    }

    status, resp_body = call_api_multipart(url, args.file, query_params, timeout=120)

    if 200 <= status < 300:
        try:
            resp = json.loads(resp_body)
            if resp.get('success'):
                file_url = resp.get('data', {}).get('url', '')
                print(f"\n[SUCCESS] 文件上传成功！")
                if file_url:
                    print(f"[INFO] 文件访问链接: {file_url}")
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

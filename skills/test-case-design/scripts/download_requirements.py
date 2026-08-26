#!/usr/bin/env python3
"""
统一下载需求文档脚本。支持 PDF/DOCX，自动处理中文 URL 编码，内置重试机制。

Usage:
  python scripts/download_requirements.py --url <URL> --output <PATH> [--session-id <ID>]

Returns 0 on success, non-zero on failure.

依赖：标准库 urllib，无需额外安装。
"""
import argparse
import os
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import quote, urlparse, unquote


def detect_format(url):
    """从 URL 中自动识别文件格式（.pdf / .docx）"""
    # 先尝试从原始 URL 路径中检测
    path = urlparse(url).path
    path_lower = path.lower()
    if path_lower.endswith('.docx'):
        return 'docx'
    elif path_lower.endswith('.pdf'):
        return 'pdf'

    # 尝试从 URL 解码后的路径检测（处理已编码的中文 URL）
    decoded_path = unquote(path).lower()
    if decoded_path.endswith('.docx'):
        return 'docx'
    elif decoded_path.endswith('.pdf'):
        return 'pdf'

    # 默认按 PDF 处理
    print(f"[WARN] 无法从 URL 后缀识别文件格式，默认按 PDF 处理")
    return 'pdf'


def encode_url(url):
    """
    对 URL 中的非 ASCII 字符（如中文）进行百分号编码。
    保留已编码的部分和安全的 ASCII 字符。
    """
    parsed = urlparse(url)
    # 对路径和查询参数中的中文等字符进行编码
    encoded_path = quote(unquote(parsed.path), safe='/:@!$&\'()*+,;=-._~')
    encoded_query = quote(unquote(parsed.query), safe='/:@!$&\'()*+,;=-._~')
    result = parsed._replace(path=encoded_path, query=encoded_query).geturl()
    if result != url:
        print(f"[INFO] URL 中的特殊字符已自动编码")
    return result


def download_with_retry(url, output_path, max_retries=3):
    """
    下载文件，内置指数退避重试机制。

    Args:
        url: 下载链接（已经过编码处理）
        output_path: 文件保存路径
        max_retries: 最大重试次数

    Returns:
        (success: bool, file_size: int)
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[INFO] 下载尝试 {attempt}/{max_retries} ...")

            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    )
                }
            )

            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()

            if len(data) == 0:
                raise ValueError("下载的文件内容为空（0 bytes）")

            # 确保目标目录存在
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

            with open(output_path, 'wb') as f:
                f.write(data)

            file_size = os.path.getsize(output_path)
            print(f"[SUCCESS] 下载完成: {output_path} ({file_size} bytes)")
            return True, file_size

        except urllib.error.HTTPError as e:
            last_error = e
            print(f"[ERROR] HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            last_error = e
            print(f"[ERROR] 网络错误: {e.reason}")
        except Exception as e:
            last_error = e
            print(f"[ERROR] {e}")

        if attempt < max_retries:
            wait_time = 2 ** (attempt - 1)  # 1s, 2s, 4s
            print(f"[INFO] {wait_time}s 后重试...")
            time.sleep(wait_time)

    print(f"[FATAL] 下载失败，已重试 {max_retries} 次")
    return False, 0


def main():
    parser = argparse.ArgumentParser(
        description='下载需求文档（支持 PDF/DOCX），自动编码中文 URL，内置重试'
    )
    parser.add_argument('--url', required=True,
                        help='需求文档下载链接')
    parser.add_argument('--output', required=True,
                        help='文件保存路径（含文件名）')
    parser.add_argument('--session-id', default='unknown',
                        help='会话标识（用于日志输出）')
    args = parser.parse_args()

    print(f"[INFO] Session ID: {args.session_id}")

    # 1. 识别文件格式（编码前先检测，保留原始后缀信息）
    file_format = detect_format(args.url)
    print(f"[INFO] 识别文件格式: {file_format.upper()}")

    # 2. 编码 URL（处理中文字符）
    encoded_url = encode_url(args.url)

    # 3. 下载文件
    success, size = download_with_retry(encoded_url, args.output)

    if success and size > 0:
        print(f"[INFO] 文件大小: {size} bytes")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

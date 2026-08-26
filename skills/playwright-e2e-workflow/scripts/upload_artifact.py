#!/opt/hermes/.venv/bin/python3
"""阶段 6:上传测试产物到后端文件上传接口。

用法:
  upload_artifact.py --type TEST_SCRIPT|TEST_PLAN|TEST_REPORT --file <路径>
                     [--session-id <sid>] [--function-uid <uid>] [--prefix <base>]

行为:
  1. POST {prefix}/api/v1/file/upload
     query: type/sessionId/functionUid + multipart file
  2. 若后端 4xx 提示参数解析失败,自动降级: 参数改放 form 字段重试(--form-mode 强制)
  3. 成功判定: success==true 或 code=="200",且 data.url 非空
  4. 打印 data 回显(含 url 上传地址)

退出码: 0=成功; 2=失败(如实报告,不伪造 url)
"""
import argparse
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import (  # noqa: E402
    die, http_post_multipart, parse_envelope, resolve_backend_prefix,
    session_id_from_env,
)

API_UPLOAD = "/api/v1/file/upload"
VALID_TYPES = ("TEST_SCRIPT", "TEST_PLAN", "TEST_REPORT")


def main() -> int:
    ap = argparse.ArgumentParser(description="上传测试产物(TEST_SCRIPT/TEST_PLAN/TEST_REPORT)")
    ap.add_argument("--type", required=True, choices=VALID_TYPES, help="产物类型")
    ap.add_argument("--file", required=True, help="本地上传文件路径")
    ap.add_argument("--session-id", default=None, help="默认取 $HERMES_SESSION_ID")
    ap.add_argument("--function-uid", required=True,
                    help="前端预创建分配的 Web 功能 UID(真实值,占位符需先向用户确认)")
    ap.add_argument("--prefix", default=None,
                    help="接口前缀(默认 Nacos 动态发现,失败回退固定地址;显式传则覆盖)")
    ap.add_argument("--form-mode", action="store_true",
                    help="强制参数放 form 字段(默认 query 失败后自动降级)")
    args = ap.parse_args()

    sid = args.session_id or session_id_from_env()
    if not os.path.isfile(args.file):
        die(f"文件不存在: {args.file}")
    if not args.function_uid or args.function_uid.startswith("xxxx"):
        die(f"functionUid 不是真实值({args.function_uid!r}),须向用户确认后再上传,不要猜测")

    prefix = args.prefix or resolve_backend_prefix()
    url = f"{prefix}{API_UPLOAD}"
    query_params = {"type": args.type, "sessionId": sid, "functionUid": args.function_uid}
    form_params = dict(query_params)  # 降级模式: 参数放 form 字段

    attempts = [("query", query_params)]
    if args.form_mode:
        attempts = [("form", form_params)]
    else:
        attempts.append(("form", form_params))

    last_err = None
    for mode, params in attempts:
        target_url = url
        fields = {}
        if mode == "query":
            from urllib.parse import urlencode
            target_url = f"{url}?{urlencode(params)}"
        else:
            fields = params
        try:
            status, body = http_post_multipart(target_url, fields, "file", args.file)
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            last_err = f"网络错误: {e}"
            continue
        except Exception as e:
            last_err = f"请求异常: {e}"
            continue

        if status >= 400:
            last_err = f"HTTP {status}: {body[:300]}"
            if "参数" in body or "解析" in body:
                continue  # 4xx 参数解析失败 → 降级 form 模式重试
            break
        ok, code, msg, data = parse_envelope(body)
        if not ok:
            last_err = f"[{code}] {msg}"
            continue
        if not data or not data.get("url"):
            last_err = f"响应无 data.url: {body[:300]}"
            continue
        print(f"[ok] 上传成功 type={args.type}")
        print(f"     sessionId={data.get('sessionId')} fileName={data.get('fileName')}")
        print(f"     relativePath={data.get('relativePath')} type={data.get('type')}")
        print(f"     url={data.get('url')}")
        return 0

    die(f"上传失败({args.type}): {last_err or '未知错误'}")

if __name__ == "__main__":
    sys.exit(main())
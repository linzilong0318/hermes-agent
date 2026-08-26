#!/opt/hermes/.venv/bin/python3
"""场景 B:按 functionUid 拉取该功能的测试脚本/测试计划/旧测试报告。

用法:
  fetch_resources.py --function-uid <uid> [--session-id <sid>] [--prefix <base>]
                     [--e2e-root <dir>]

行为:
  1. GET {prefix}/api/v1/web-test/function/resources?functionUid={uid}
  2. 下载(filePath 是 MinIO 公开 URL,直连 GET;保留原文件名):
       scriptList     -> {e2e-root}/tests/<原名>          (待修复对象)
       testPlanList   -> {e2e-root}/specs/<原名>          (仅对齐用例意图,不上传不保留)
       testReportList -> {e2e-root}/report/prev-test-results.json (仅修复参考,直接丢弃;多份时后覆盖前)
  3. 打印各列表摘要与下载结果

退出码: 0=成功; 2=functionUid 无效/该功能无脚本(无法修复)/网络错误
"""
import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import (  # noqa: E402
    API_FUNCTION_RESOURCES, die, http_get, parse_envelope, resolve_backend_prefix,
)


def default_e2e_root() -> str:
    sid = os.environ.get("HERMES_SESSION_ID", "")
    return os.path.join("/opt/data/e2e", sid) if sid else "/opt/data/e2e"


def download(url: str, target: str) -> int:
    try:
        urllib.request.urlretrieve(url, target)
    except urllib.error.URLError as e:
        die(f"下载失败 {url}: {e}")
    except Exception as e:
        die(f"下载异常 {url}: {e}")
    return os.path.getsize(target)


def main() -> int:
    ap = argparse.ArgumentParser(description="场景 B:下载 function 的测试脚本/计划/旧报告")
    ap.add_argument("--function-uid", required=True,
                    help="Web 功能 UID(message 提供;占位符须先向用户确认)")
    ap.add_argument("--session-id", default=None, help="默认取 $HERMES_SESSION_ID")
    ap.add_argument("--prefix", default=None,
                    help="接口前缀(默认 Nacos 动态发现,失败回退固定地址;显式传则覆盖)")
    ap.add_argument("--e2e-root", default=default_e2e_root(), help="会话工作区根目录")
    args = ap.parse_args()

    if not args.function_uid or args.function_uid.startswith("xxxx"):
        die(f"functionUid 不是真实值({args.function_uid!r}),须先向用户确认,不要猜测")

    prefix = args.prefix or resolve_backend_prefix()
    url = f"{prefix}{API_FUNCTION_RESOURCES}?functionUid={urllib.parse.quote(args.function_uid)}"
    try:
        status, body = http_get(url)
    except urllib.error.URLError as e:
        die(f"function/resources 请求失败: {e}")
    except Exception as e:
        die(f"function/resources 请求异常: {e}")
    if status != 200:
        die(f"function/resources HTTP {status}: {body[:300]}")
    ok, code, msg, data = parse_envelope(body)
    if not ok:
        die(f"function/resources 返回失败 [{code}] {msg}(functionUid 无效时如实报告)")

    print(f"[ok] functionUid={data.get('functionUid') or args.function_uid}")

    def fetch_list(key: str, subdir: str, rename=None) -> int:
        items = data.get(key) or []
        if not items:
            print(f"[warn] {key} 为空")
            return 0
        os.makedirs(os.path.join(args.e2e_root, subdir), exist_ok=True)
        n = 0
        for it in items:
            fname = rename or os.path.basename(it.get("fileName") or "unnamed")
            target = os.path.join(args.e2e_root, subdir, fname)
            size = download(it["filePath"], target)
            print(f"     - {fname} ({size} 字节) <- {it['filePath']}")
            n += 1
        return n

    print("[ok] scriptList(测试脚本,修复对象):")
    ns = fetch_list("scriptList", "tests")
    print("[ok] testPlanList(测试计划,对齐用例意图,不上传):")
    np_ = fetch_list("testPlanList", "specs")
    print("[ok] testReportList(旧报告,仅修复参考,直接丢弃):")
    nr = fetch_list("testReportList", "report", rename="prev-test-results.json")

    if ns == 0:
        die("该 function 无测试脚本,无法执行修复;向用户确认 functionUid 是否正确")
    print(f"[ok] 下载完成: 脚本 {ns} 个, 计划 {np_} 个, 旧报告 {nr} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
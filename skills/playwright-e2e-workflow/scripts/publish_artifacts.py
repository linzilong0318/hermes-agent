#!/opt/hermes/.venv/bin/python3
"""场景 A 收尾:三个产物裸传 MinIO + function/save 同步后端数据库(一步到位)。

用法(每个产物二选一:本地文件路径 或 已上传 previewUrl):
  publish_artifacts.py --script-file <path> | --script-url <url>
                       --plan-file <path>   | --plan-url <url>
                       --report-file <path> | --report-url <url>
                       --project-uid <uid> --folder-uid <uid>
                       --display-name <名称> --relative-path <页面路径>
                       [--description <描述>] [--test-case-uids a,b]
                       [--resource-uids a,b] [--function-uid <uid>]
                       [--session-id <sid>] [--prefix <base>] [--dry-run]

行为:
  1. 给了文件路径的产物: POST {prefix}/file/upload(**裸传,只带 file 字段**,
     带任何业务参数都会 00001,实测)→ 每个 previewUrl 拿到**立即打印**
  2. 给了 URL 的产物: 跳过裸传(续传重试模式,已上传文件继续有效)
  3. 三个 previewUrl 齐全后: POST {prefix}/api/v1/web-test/function/save
     body = message 元数据透传 + resourceList[
       {resourceType:2, fileName:脚本名,   filePath:previewUrl},
       {resourceType:3, fileName:计划名,   filePath:previewUrl},
       {resourceType:4, fileName:报告名,   filePath:previewUrl}]
  4. 打印新建 functionUid(save 返回 data)

失败语义(实测确认): save 失败(含参数校验 00004)后端**不会创建记录**,
  只有成功才创建 → 重试永远安全; 重试时把上次打印的 previewUrl 传回
  --*-url 只重跑 save,无需重新裸传。

--function-uid 可选(场景 A 的 Web 功能 functionUid):
 传真实值 = body 透传 functionUid,意图删除该历史记录并新建新记录。占位符 xxxx 仍拒绝。

退出码: 0=成功; 2=参数错误/元数据占位符/上传或 save 失败
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import (  # noqa: E402
    API_FUNCTION_SAVE, API_UPLOAD_RAW, die, http_post_json, http_post_multipart,
    parse_envelope, resolve_backend_prefix, session_id_from_env,
)

RESOURCE_TYPE = {"script": 2, "plan": 3, "report": 4}
ARTIFACT_LABEL = {"script": "测试脚本", "plan": "测试计划", "report": "测试报告"}


def url_basename(url: str) -> str:
    return os.path.basename(urllib.parse.urlparse(url).path) or "unnamed"


def main() -> int:
    ap = argparse.ArgumentParser(description="场景 A 收尾: 3×裸传 + function/save")
    for art, label in (("script", "测试脚本"), ("plan", "测试计划"), ("report", "测试报告")):
        g = ap.add_mutually_exclusive_group(required=True)
        g.add_argument(f"--{art}-file", help=f"{label}本地文件路径(裸传上传)")
        g.add_argument(f"--{art}-url", help=f"{label}已上传 previewUrl(续传模式,跳过裸传)")
    ap.add_argument("--project-uid", required=True, help="所属项目空间(message,占位符须先询问)")
    ap.add_argument("--folder-uid", required=True, help="所属测试目录(message,占位符须先询问)")
    ap.add_argument("--display-name", required=True, help="Web 功能名称(message;缺失询问,实在没有用固定文案)")
    ap.add_argument("--relative-path", required=True, help="Web 页面相对路径(message,驱动探索,必填无兜底)")
    ap.add_argument("--description", default="", help="功能描述(message;也用于理解测试需求)")
    ap.add_argument("--test-case-uids", default="", help="关联用例(message,逗号分隔)")
    ap.add_argument("--resource-uids", default="", help="静态资源 selectedResourceUids(message,逗号分隔)")
    ap.add_argument("--function-uid", default="", help="可选: 不传=新建记录;传=覆盖更新指定历史记录(场景 A 的 Web 功能 functionUid)")
    ap.add_argument("--session-id", default=None, help="默认取 $HERMES_SESSION_ID")
    ap.add_argument("--prefix", default=None,
                    help="接口前缀(默认 Nacos 动态发现,失败回退固定地址;显式传则覆盖)")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的请求,不真正调用后端")
    args = ap.parse_args()

    sid = args.session_id or session_id_from_env()
    prefix = args.prefix or resolve_backend_prefix()

    # 元数据校验: 必填且非占位符(displayName/description 缺省兜底是 agent 的事,
    # 但占位符 xxxx 仍拒绝,防止把假值写进后端)
    for label, v in (("projectUid", args.project_uid), ("folderUid", args.folder_uid),
                     ("displayName", args.display_name), ("relativePath", args.relative_path)):
        if not v or v.startswith("xxx"):
            die(f"{label} 缺失或为占位符({v!r}),须先向用户确认,不要猜测")
    # functionUid 可选(后端支持): 空=新建记录;真实值=覆盖更新指定历史记录;
    # 占位符仍拒绝,不把垃圾值带进 body
    if args.function_uid and args.function_uid.startswith("xxx"):
        die(f"functionUid 为占位符({args.function_uid!r}),须先向用户确认,不要猜测")

    artifacts = {}
    for art in ("script", "plan", "report"):
        f = getattr(args, f"{art}_file")
        u = getattr(args, f"{art}_url")
        if f:
            if not os.path.isfile(f):
                die(f"{ARTIFACT_LABEL[art]}文件不存在: {f}")
            artifacts[art] = {"kind": "file", "path": f}
        else:
            if not (u or "").startswith("http"):
                die(f"{ARTIFACT_LABEL[art]} URL 非法: {u!r}")
            artifacts[art] = {"kind": "url", "url": u}

    # 步骤 1: 裸传(只有文件路径的产物;URL 的跳过)
    for art in ("script", "plan", "report"):
        if artifacts[art]["kind"] == "url":
            print(f"[info] {ARTIFACT_LABEL[art]} 使用已上传 URL,跳过裸传")
            continue
        url = f"{prefix}{API_UPLOAD_RAW}"
        if args.dry_run:
            print(f"[dry-run] POST {url} (multipart file=@{artifacts[art]['path']})")
            continue
        try:
            status, body = http_post_multipart(url, {}, "file", artifacts[art]["path"])
        except urllib.error.HTTPError as e:
            die(f"裸传 {ARTIFACT_LABEL[art]} HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}")
        except urllib.error.URLError as e:
            die(f"裸传 {ARTIFACT_LABEL[art]} 网络错误: {e}(重试可用已打印的 previewUrl 走 --*-url)")
        except Exception as e:
            die(f"裸传 {ARTIFACT_LABEL[art]} 请求异常: {e}")
        if status >= 400:
            die(f"裸传 {ARTIFACT_LABEL[art]} HTTP {status}: {body[:300]}")
        ok, code, msg, data = parse_envelope(body)
        if not ok:
            die(f"裸传 {ARTIFACT_LABEL[art]} 返回失败 [{code}] {msg}(注意: /file/upload 只认 file 字段,带任何业务参数都会 00001)")
        pv = (data or {}).get("previewUrl") or ""
        if not pv:
            die(f"裸传 {ARTIFACT_LABEL[art]} 响应无 previewUrl: {body[:300]}")
        artifacts[art]["url"] = pv
        print(f"[ok] 裸传 {ARTIFACT_LABEL[art]} 成功 -> previewUrl={pv}")

    # 步骤 2: function/save
    file_names = {art: (os.path.basename(artifacts[art]["path"]) if artifacts[art]["kind"] == "file"
                        else url_basename(artifacts[art]["url"]))
                  for art in ("script", "plan", "report")}
    urls = {art: artifacts[art].get("url", "") for art in ("script", "plan", "report")}

    if args.dry_run:
        print("[dry-run] 以下为将提交的 function/save body:")
        body = build_body(args, urls, file_names)
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0

    missing = [ARTIFACT_LABEL[art] for art, u in urls.items() if not u]
    if missing:
        die(f"以下产物未拿到 previewUrl,不执行 save: {missing}(先解决上传失败,或把已成功的 URL 传回 --*-url 续传)")

    url = f"{prefix}{API_FUNCTION_SAVE}"
    body = build_body(args, urls, file_names)
    try:
        status, resp = http_post_json(url, body)
    except urllib.error.URLError as e:
        die(f"function/save 请求失败: {e}(save 失败不会创建记录,可带已打印的 previewUrl 用 --*-url 重试)")
    except Exception as e:
        die(f"function/save 请求异常: {e}")
    if status >= 400:
        die(f"function/save HTTP {status}: {resp[:300]}")
    ok, code, msg, data = parse_envelope(resp)
    if not ok:
        die(f"function/save 返回失败 [{code}] {msg}(save 失败不创建记录,带已打印 previewUrl 重试即可)")
    print(f"[ok] function/save 成功,functionUid={data}(新建或覆盖更新,视是否传 --function-uid)")
    return 0


def build_body(args, urls: dict, file_names: dict) -> dict:
    body = {
        "projectUid": args.project_uid,
        "folderUid": args.folder_uid,
        "displayName": args.display_name,
        "relativePath": args.relative_path,
        "description": args.description,
        "selectedTestCaseUids": [u.strip() for u in args.test_case_uids.split(",") if u.strip()],
        "selectedResourceUids": [u.strip() for u in args.resource_uids.split(",") if u.strip()],
        "resourceList": [
            {"resourceType": RESOURCE_TYPE[art],
             "fileName": file_names[art],
             "filePath": urls[art]}
            for art in ("script", "plan", "report")
        ],
    }
    if args.function_uid:
        body["functionUid"] = args.function_uid  # 可选: 传=覆盖更新指定历史记录,不传=新建
    return body


if __name__ == "__main__":
    sys.exit(main())
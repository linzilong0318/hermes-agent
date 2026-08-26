#!/opt/hermes/.venv/bin/python3
"""阶段 1:拉取基准配置并物化 template(v6:静态资源不再下载,脚本内运行时下载)。

用法:
  fetch_config.py [--session-id <sid>] [--prefix <base>] [--e2e-root <dir>]
                  [--resource-uids uid1,uid2 ...]
                  [--list-resources]           # 只列项目全部资源(核对 resourceUid 近失),不写 template

行为:
  1. GET {prefix}/api/v1/web-test/config/detail?sessionId={sid}[&resourceList=...]
     --resource-uids 以**重复 resourceList 查询参数**按 resourceUid 过滤(OR 语义,
     实测确认),对应场景 A message 里的 selectedResourceUids;场景 B 不传(忽略静态资源)
  2. 成功: 写 {e2e-root}/template/playwright.config.ts 与 global-setup.ts(覆盖)
  3. 静态资源**不下载**: 打印返回资源的 fileName+filePath 清单,由 agent 写进测试
     脚本,测试运行时下载到脚本同目录(多环境通用,路径不落死)
  4. 资源防护(第一层): --resource-uids 给了 N 个、过滤返回 M 个:
       N>0 且 M==0 → 退出码 2,提示 agent 先跑 --list-resources 核对近失
        (2026-08-17 实测:用户 uid 可能抄错一位,列全量后按文件名与功能描述吻合度确认修正),
        无接近匹配再询问用户;上传类用例无文件可测,不能静默跳过,也不能伪造资源
       0<M<N → WARN 打印缺失清单,继续(点名缺失文件的上传用例会在自验证暴露)
  5. --list-resources: 只打印项目全部静态资源(uid/fileName/filePath),不写 template,
     退出码 0 —— 用于 resourceUid 未命中时核对近失/查找真实 uid

退出码: 0=成功; 2=会话未绑定项目/网络错误/参数错误/资源全部失效
"""
import argparse
import os
import re
import sys
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import (  # noqa: E402
    API_CONFIG_DETAIL, die, http_get, parse_envelope, resolve_backend_prefix,
    session_id_from_env,
)


def default_e2e_root() -> str:
    """默认会话工作区:固定 /opt/data/e2e/<HERMES_SESSION_ID>(方案 B,5.0 起)。"""
    sid = os.environ.get("HERMES_SESSION_ID", "")
    if sid:
        return os.path.join("/opt/data/e2e", sid)
    return "/opt/data/e2e"


def extract_base_url(cfg_text: str) -> str:
    """从 playwrightConfig 文本提取 baseURL(v6 响应已无独立 baseUrl 字段)。"""
    m = re.search(r"baseURL:\s*(?:process\.env\.BASE_URL\s*\|\|\s*)?['\"]([^'\"]+)['\"]", cfg_text)
    return m.group(1) if m else "(未找到 baseURL,以 playwrightConfig 全文为准)"


def main() -> int:
    ap = argparse.ArgumentParser(description="拉取后端基准配置到 template/(v6:不下载静态资源)")
    ap.add_argument("--session-id", default=None, help="默认取 $HERMES_SESSION_ID")
    ap.add_argument("--prefix", default=None,
                    help="接口前缀(默认 Nacos 动态发现,失败回退固定地址;显式传则覆盖)")
    ap.add_argument("--e2e-root", default=default_e2e_root(),
                    help="会话工作区根目录(默认 /opt/data/e2e/<HERMES_SESSION_ID>)")
    ap.add_argument("--resource-uids", default="",
                    help="逗号分隔的 selectedResourceUids(场景 A 静态资源),以重复 resourceList 参数过滤")
    ap.add_argument("--list-resources", action="store_true",
                    help="只列出项目全部静态资源(不写 template),用于核对 resourceUid 近失/查找真实 uid")
    args = ap.parse_args()

    sid = args.session_id or session_id_from_env()
    prefix = args.prefix or resolve_backend_prefix()
    template_dir = os.path.join(args.e2e_root, "template")
    os.makedirs(template_dir, exist_ok=True)

    uids = [u.strip() for u in args.resource_uids.split(",") if u.strip()]
    url = f"{prefix}{API_CONFIG_DETAIL}?sessionId={urllib.parse.quote(sid)}"
    for u in uids:
        url += f"&resourceList={urllib.parse.quote(u)}"
    try:
        status, body = http_get(url)
    except urllib.error.URLError as e:
        die(f"config/detail 请求失败: {e}(接口不可达时如实报告,不要伪造配置)")
    except Exception as e:
        die(f"config/detail 请求异常: {e}")

    if status != 200:
        die(f"config/detail HTTP {status}: {body[:300]}")

    ok, code, msg, data = parse_envelope(body)
    if not ok:
        # A05010 = 会话未绑定项目
        die(f"config/detail 返回失败 [{code}] {msg}(会话未绑定项目时如实报告)")

    if args.list_resources:
        resources = data.get("resourceList") or []
        print(f"[ok] 项目资源共 {len(resources)} 项:")
        for r in resources:
            print(f"  {r.get('resourceUid')}  {r.get('fileName')}  {r.get('filePath')}")
        return 0

    # 写 template 文件
    with open(os.path.join(template_dir, "playwright.config.ts"), "w") as f:
        f.write(data["playwrightConfig"])
    with open(os.path.join(template_dir, "global-setup.ts"), "w") as f:
        f.write(data["globalSetup"])
    print(f"[ok] template/playwright.config.ts + global-setup.ts 已写入 ({len(data['playwrightConfig'])}/{len(data['globalSetup'])} 字节)")
    print(f"[ok] baseURL={extract_base_url(data['playwrightConfig'])}")

    # 资源清单(v6:只打印,不下载;下载逻辑在测试脚本内,运行时落到脚本同目录)
    resources = data.get("resourceList") or []
    if uids:
        print(f"[ok] resourceList 过滤返回 {len(resources)}/{len(uids)} 项(message selectedResourceUids):")
        for r in resources:
            print(f"     - fileName={r.get('fileName')} resourceUid={r.get('resourceUid')}")
            print(f"       filePath={r.get('filePath')}  <- 写进测试脚本,运行时下载到脚本同目录")
        if len(resources) == 0:
            die("--resource-uids 全部未命中(占位符或已失效): 先跑 --list-resources 核对近失(如 uid 抄错一位、文件名与功能描述吻合),确认后按修正 uid 重跑;无接近匹配再询问用户;上传类用例无文件可测,不要伪造资源")
        if len(resources) < len(uids):
            got = {r.get("resourceUid") for r in resources}
            missing = [u for u in uids if u not in got]
            print(f"[WARN] {len(missing)} 项未命中: {missing} —— 点名这些文件的上传用例会在自验证时暴露失败")
    else:
        print(f"[info] 未传 --resource-uids(修复场景或无需静态资源),项目资源共 {len(resources)} 项,不列出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
#!/opt/hermes/.venv/bin/python3
"""阶段 0:工作区体检(方案 B:纯 CLI,无 MCP,2026-08-13)。

用法:
  preflight.py [--e2e-root <dir>] [--skill-dir <dir>]

工作区(方案 B,5.0 架构):
  - 固定 /opt/data/e2e/<HERMES_SESSION_ID>(真实目录),不依赖任何自发现/指针/符号链接。
  - sid 由 hermes 显式注入 terminal 子进程环境(契约行为,实测可靠),无需探测。
  - 多用户隔离 = 每会话一个目录,并发互不干扰,一眼看穿。
  - 历史:4.x 曾用 .mcp/<watchdog_pid> 目录 + ppid 链自发现 + .ws-<sid> 指针文件,
    以对齐 MCP server 的 -c 工作区;5.0 起 MCP 全部移除,agent 与 CLI 读写同一
    sid 目录,pid 自发现机制随之删除(其依赖 hermes 进程模型,存在模型漂移风险)。

自动动作(无需手工):
  1. 强制从技能目录同步脚本到工作区(权威副本在技能 scripts/,运行副本每次覆盖):
       prepare.mjs / cleanup.mjs  -> <root>/scripts/
       login.mjs / seed.spec.ts   -> <root>/
  2. 共享根 node_modules 缺失时自动创建软链(指向全局 playwright 包,各会话
     配置加载器向上解析自动命中,无需每个会话各自链接)
  3. 本会话 Xvfb display 未运行时自动启动(display = 99 + sha1(sid) % 16,
     多会话并发各用各的 display,互不干扰;无 sid 时固定 :99)

检查项:
  [必需] 共享层: node、python(uv 全局)、浏览器目录、Xvfb(本会话 display)、共享 node_modules
  [必需] 会话层: e2e 根存在、template/ 基准配置、工作区脚本(同步后)
  [提示] 会话层: auth.json 登录态、物化产物、遗留生成物(提示 cleanup)

退出码: 0=无阻塞项可继续; 1=存在 FAIL 阻塞项; 2=用法错误
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

SHARED_ROOT = "/opt/data/e2e"
BROWSER_PATH = "/opt/hermes/.playwright"
PYTHON = "/opt/hermes/.venv/bin/python3"
DEFAULT_SKILL_DIR = "/opt/data/skills/playwright-e2e-workflow"

# 物化后应当存在的文件(与 template/ 中的基准配置对应)
MATERIALIZED = ["playwright.config.ts", "global-setup.ts", "auth.json"]
# 生成物目录:存在且非空 → 提示上次未清理
ARTIFACT_DIRS = ["tests", "specs", "report", "test-results"]
# 会话层脚本:(技能目录相对路径, 会话目录相对路径) —— 每轮强制同步
SESSION_SCRIPTS = [
    ("scripts/prepare.mjs", "scripts/prepare.mjs"),
    ("scripts/cleanup.mjs", "scripts/cleanup.mjs"),
    ("scripts/login.mjs", "login.mjs"),
    ("scripts/seed.spec.ts", "seed.spec.ts"),
]
# 共享 node_modules 软链:(链接名, 全局包路径) —— 缺失时自动创建
NODE_LINKS = [
    ("@playwright/test", "/usr/local/lib/node_modules/@playwright/test"),
    ("playwright", "/usr/local/lib/node_modules/playwright"),
    ("playwright-core", "/usr/local/lib/node_modules/playwright/node_modules/playwright-core"),
]
XVFB_BASE = 99
XVFB_RANGE = 16  # :99 ~ :114,按 sid 哈希映射


def section(title: str):
    print(f"\n== {title} ==")


def report(level: str, msg: str):
    print(f"[{level}] {msg}")


def session_display(key: str) -> int:
    """确定性分配 display 号:99 + sha1(key) % 16(key = sid;无 sid 回退固定 99)。"""
    if not key:
        return XVFB_BASE
    return XVFB_BASE + int(hashlib.sha1(key.encode("utf-8", "replace")).hexdigest(), 16) % XVFB_RANGE


def xvfb_running(disp: int) -> bool:
    out = subprocess.run(["ps", "-C", "Xvfb", "-o", "args="], capture_output=True, text=True).stdout
    return any(f":{disp} " in line or line.rstrip().endswith(f":{disp}") for line in out.splitlines())


def start_xvfb(disp: int) -> bool:
    log = open(f"/tmp/xvfb-{disp}.log", "a")
    try:
        subprocess.Popen(
            ["Xvfb", f":{disp}", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
            stdout=log, stderr=log, start_new_session=True,
        )
        subprocess.run(["sleep", "1"])
        return xvfb_running(disp)
    except FileNotFoundError:
        return False


def sync_script(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    os.chmod(dst, 0o755)


def sync_session_scripts(skill_dir: str, root: str) -> None:
    """从技能目录强制同步会话层脚本(权威副本 -> 运行副本,每次覆盖)。"""
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    for rel_src, rel_dst in SESSION_SCRIPTS:
        sync_script(os.path.join(skill_dir, rel_src), os.path.join(root, rel_dst))
    report("ok", f"已同步 {len(SESSION_SCRIPTS)} 个会话脚本 -> {root}")


def ensure_shared_node_modules() -> None:
    """共享根 node_modules 软链缺失时自动创建(幂等)。"""
    nm = os.path.join(SHARED_ROOT, "node_modules")
    created = []
    for name, target in NODE_LINKS:
        if not os.path.exists(target):
            continue
        p = os.path.join(nm, name)
        if os.path.islink(p) or os.path.isdir(p):
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(target, p)
        created.append(name)
    if created:
        report("ok", f"共享 node_modules 已创建软链: {', '.join(created)}")
    elif os.path.isdir(nm):
        report("ok", "共享 node_modules 存在")
    else:
        report("WARN", "共享 node_modules 缺失且无可用全局包(检查全局 playwright 安装)")


def main() -> int:
    ap = argparse.ArgumentParser(description="e2e 工作区体检(方案 B:纯 CLI,无 MCP)")
    ap.add_argument("--e2e-root", default=None,
                    help="会话工作区根目录(默认 /opt/data/e2e/<HERMES_SESSION_ID>)")
    ap.add_argument("--skill-dir", default=DEFAULT_SKILL_DIR, help="技能目录(脚本权威副本来源)")
    args = ap.parse_args()

    sid = os.environ.get("HERMES_SESSION_ID", "")
    if args.e2e_root:
        root = args.e2e_root
    elif sid:
        root = os.path.join(SHARED_ROOT, sid)
    else:
        root = SHARED_ROOT  # 无 sid:回退旧单层工作区

    fails = 0
    warns = 0

    section("会话工作区(方案 B:sid 目录,无 MCP 自发现)")
    report("info", f"sid={sid or '(无,回退单层)'}")
    report("ok", f"工作区(agent 与 CLI 同一位置): {root}")

    disp = session_display(sid)

    section("自动同步(每轮强制)")
    if not os.path.isdir(args.skill_dir):
        report("FAIL", f"技能目录不存在: {args.skill_dir}")
        fails += 1
    else:
        os.makedirs(root, exist_ok=True)
        sync_session_scripts(args.skill_dir, root)

    section("共享层环境")
    if shutil.which("node"):
        report("ok", f"node: {subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()}")
    else:
        report("FAIL", "node 不在 PATH")
        fails += 1
    if os.path.isfile(PYTHON):
        report("ok", f"python(uv 全局): {PYTHON}")
    else:
        report("FAIL", f"python 解释器缺失: {PYTHON}")
        fails += 1
    if os.path.isdir(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")):
        report("ok", f"PLAYWRIGHT_BROWSERS_PATH={os.environ['PLAYWRIGHT_BROWSERS_PATH']}")
    elif os.path.isdir(BROWSER_PATH):
        report("ok", f"PLAYWRIGHT_BROWSERS_PATH(默认): {BROWSER_PATH}")
    else:
        report("FAIL", f"浏览器目录不存在: {BROWSER_PATH}")
        fails += 1
    if xvfb_running(disp):
        report("ok", f"Xvfb :{disp} 在跑(display 按 sid 分配)")
    elif start_xvfb(disp):
        report("ok", f"Xvfb :{disp} 已自动启动(会话独立 display)")
    else:
        report("FAIL", f"Xvfb :{disp} 启动失败 —— 手工启动: Xvfb :{disp} -screen 0 1920x1080x24 -nolisten tcp")
        fails += 1
    ensure_shared_node_modules()

    section("会话层目录结构")
    if not os.path.isdir(root):
        report("FAIL", f"会话工作区不存在: {root}")
        fails += 1
        print()
        report("FAIL", f"共 {fails} 个阻塞项,先修复再继续")
        return 1
    report("ok", f"会话工作区: {root}")
    for d in ["template", "scripts", "template/assets"]:
        p = os.path.join(root, d)
        if os.path.isdir(p):
            report("ok", f"存在 {d}")
        else:
            report("WARN", f"缺少目录 {d}(template/assets 为 5.x 遗留,v6 静态资源不本地下载,可忽略)")
            warns += 1

    section("template 基准配置(后端拉取唯一来源,勿手工改)")
    for f in ["playwright.config.ts", "global-setup.ts"]:
        p = os.path.join(root, "template", f)
        if os.path.isfile(p):
            report("ok", f"template/{f} ({os.path.getsize(p)} 字节)")
        else:
            report("FAIL", f"缺少 template/{f} —— 先跑 fetch_config.py 拉取")
            fails += 1

    section("会话工作区脚本(每轮已强制同步)")
    for rel in [d for _, d in SESSION_SCRIPTS]:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            report("ok", f"存在 {rel}")
        else:
            report("FAIL", f"缺少 {rel}(同步失败?)")
            fails += 1

    section("登录态与产物状态(信息性)")
    auth = os.path.join(root, "auth.json")
    if os.path.isfile(auth):
        report("info", "auth.json 存在(可能有效,冒烟测试会验证)")
    else:
        report("info", "auth.json 不存在 —— 物化后需 DISPLAY=:<n> node login.mjs 登录")
    materialized_missing = [f for f in MATERIALIZED if not os.path.isfile(os.path.join(root, f))]
    if materialized_missing:
        report("info", f"未物化文件: {', '.join(materialized_missing)} —— 先跑 prepare.mjs")
    dirty = [d for d in ARTIFACT_DIRS
             if os.path.isdir(os.path.join(root, d)) and os.listdir(os.path.join(root, d))]
    if dirty:
        report("WARN", f"存在上次生成物: {', '.join(dirty)} —— 若已上传,可 node scripts/cleanup.mjs 清理")
        warns += 1
    else:
        report("info", "无遗留生成物")

    print()
    if fails:
        report("FAIL", f"共 {fails} 个阻塞项,先修复再继续")
        return 1
    report("ok", f"体检通过({warns} 个提示项,不阻塞)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
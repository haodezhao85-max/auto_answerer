# -*- coding: utf-8 -*-
"""auto_answerer 入口。

用法：
  python main.py                正常答题流程（弹浏览器 -> 手动登录/进入任务页 -> 回车）
  python main.py --probe        只探查当前页面结构并保存，用于适配新平台
  python main.py --url https://...   指定起始地址
  python main.py --no-pause     跳过“手动就绪后回车”的等待（已登录且已在任务页时用）
  python main.py --auto-submit  答完后自动点“提交”（谨慎！默认只答不交）

配置见 config.json；API Key 放项目根目录 .env（见 .env.example）。
答题记录与探查结果保存在 out/ 目录。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from answerer import util  # noqa: E402
from answerer import nav  # noqa: E402
from answerer.controller import Runner, dump_probe  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(description="网页自动答题工具 (ITEST/学习通等)")
    ap.add_argument("--probe", action="store_true", help="探查模式：导出页面题目结构")
    ap.add_argument("--url", default=None, help="起始页面地址，覆盖 config.json 的 target_url")
    ap.add_argument("--no-pause", action="store_true", help="跳过“登录/就绪后回车”等待")
    ap.add_argument("--auto-submit", action="store_true", help="答完后自动点击提交")
    ap.add_argument("--max-pages", type=int, default=None, help="最多翻页数")
    ap.add_argument("--rewind", type=int, default=0, help="开始前点 N 次“上一题”回退到第1题")
    return ap


def _ready_pause():
    print("\n" + "=" * 64)
    print("如果跳到了登录页：请在弹出的浏览器里【手动登录】，")
    print("并手动导航到【要作答的那一个任务/测验页面】（可以先点“开始答题”）。")
    print("全部就绪后，回到这个终端窗口按回车继续。")
    print("=" * 64 + "\n")
    input(">>> 就绪后按回车继续… ")


def _ready_pause_attach():
    print("\n" + "=" * 64)
    print("请在你的浏览器里打开【要作答/探查的那个任务页面】（本程序不会")
    print("自己打开或关闭浏览器，只接管你选定的标签页进行读题与作答）。")
    print("就绪后，回到这个终端窗口按回车继续。")
    print("=" * 64 + "\n")
    input(">>> 就绪后按回车继续… ")


def _ask(prompt, default=""):
    """无人值守时输入不可用，直接返回默认值。"""
    try:
        return input(prompt)
    except EOFError:
        return default


def run_probe(page, cfg, root):
    dump_probe(page, cfg, root, log=lambda m, tag="info": print(m))


def run_quiz(page, cfg, root):
    Runner(page, cfg, root, log=lambda m, tag="info": print(m)).run()


def main():
    util.console_utf8()
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent

    cfg = util.load_json(root / "config.json")
    if (root / ".env").exists():
        util.load_env(root / ".env")
    if args.url:
        cfg["target_url"] = args.url
    if args.auto_submit:
        cfg["auto_submit"] = True
    if args.max_pages:
        cfg["max_pages"] = args.max_pages

    mode = cfg.get("mode", "attach")
    if mode == "launch":
        # 旧模式：程序自己打开浏览器（默认已不使用）
        profiles = root / "profiles" / "chrome"
        ud_raw = cfg.get("browser_user_data_dir") or ""
        if ud_raw.strip():
            user_data_dir = Path(os.path.expandvars(ud_raw.strip()))
            print("\n⚠ 当前使用你真实的 Edge 配置目录。请先【完全关闭所有 Edge 窗口】。")
            print("  若关闭后仍提示配置被占用，可运行:  taskkill /F /IM msedge.exe")
        else:
            user_data_dir = profiles
            user_data_dir.mkdir(parents=True, exist_ok=True)
        channel = cfg.get("browser_channel") or None
        p, context, page = nav.open_browser(user_data_dir, headless=cfg.get("headless", False), channel=channel)
        try:
            try:
                page.goto(cfg["target_url"], timeout=60000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"打开页面告警(可忽略，多半是网络慢): {e}")
            time.sleep(2)
            if cfg.get("login_pause", True) and not args.no_pause:
                _ready_pause()
            if args.probe:
                run_probe(page, cfg, root)
            else:
                run_quiz(page, cfg, root)
        finally:
            nav.close_browser(p, context)
    else:
        # 默认模式(attach)：连接用户自己打开的浏览器，绝不新开窗口
        cdp = cfg.get("cdp_url", "http://127.0.0.1:9222")
        try:
            p, browser, ctx = nav.connect_browser(cdp)
        except Exception as e:
            print(f"✖ 无法连接浏览器调试端口 ({cdp})：{e}")
            print("  请先双击 start_edge_debug.bat 打开带调试通道的 Edge，再运行本程序。")
            return
        try:
            if cfg.get("login_pause", True) and not args.no_pause:
                _ready_pause_attach()
            tabs = nav.list_tabs(ctx)
            if not tabs:
                print("没有找到打开的标签页：请先在 Edge 里打开任务页面，再重新运行。")
                return
            # 自动优先选答题页标签，找不到再询问
            page = None
            for _i, pg, _t, url in tabs:
                if "answer" in url:
                    page = pg
                    break
            if page is None:
                for _i, pg, _t, url in tabs:
                    if "itest" in url:
                        page = pg
                        break
            if page is None:
                if len(tabs) == 1:
                    page = tabs[0][1]
                else:
                    print("\n当前 Edge 打开的标签页：")
                    for i, (_i, _pg, title, url) in enumerate(tabs):
                        print(f"  [{i}] {title[:40]}  {url[:80]}")
                    sel = _ask("输入要操作的标签页序号(直接回车选 0): ", "0").strip()
                    try:
                        sel_i = int(sel) if sel else 0
                    except ValueError:
                        sel_i = 0
                    sel_i = max(0, min(sel_i, len(tabs) - 1))
                    page = tabs[sel_i][1]
            if args.rewind:
                for k in range(int(args.rewind)):
                    ok, kw = nav.click_action(page, ["上一题", "Previous"], prefer_last=False)
                    if not ok:
                        print(f"回退第 {k + 1} 次时未找到“上一题”，停止回退。")
                        break
                    page.wait_for_timeout(1200)
                print(f"已尝试回退 {args.rewind} 次。")
            print(f"已连接标签页: {page.url[:100]}")
            if args.probe:
                run_probe(page, cfg, root)
            else:
                run_quiz(page, cfg, root)
        finally:
            nav.release(p)


if __name__ == "__main__":
    main()

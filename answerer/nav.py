# -*- coding: utf-8 -*-
"""浏览器管理 + 翻页/提交按钮查找。"""
from pathlib import Path

CLICKABLE_CSS = (
    'button, a, input[type="button"], input[type="submit"], '
    '[role="button"], .btn, .button, .layui-btn, .el-button'
)


def _on_dialog(dialog):
    # 确认/提示类弹窗自动点确定，避免卡死；其余放行
    if dialog.type in ("confirm", "alert", "beforeunload"):
        try:
            dialog.accept()
        except Exception:
            pass
    else:
        try:
            dialog.dismiss()
        except Exception:
            pass


def open_browser(user_data_dir, headless=False, channel=None):
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    kw = dict(
        user_data_dir=str(user_data_dir),
        headless=headless,
        locale="zh-CN",
        accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        no_viewport=True,
    )
    if channel:
        kw["channel"] = channel
    context = p.chromium.launch_persistent_context(**kw)
    context.on("dialog", _on_dialog)
    page = context.pages[0] if context.pages else context.new_page()
    return p, context, page


def close_browser(p, context):
    try:
        context.close()
    except Exception:
        pass
    try:
        p.stop()
    except Exception:
        pass


def connect_browser(cdp_url="http://127.0.0.1:9222"):
    """连接一个已由用户自己打开的浏览器（需带 --remote-debugging-port）。

    返回 (playwright, browser, context)；不会打开/关闭任何浏览器窗口。
    """
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(cdp_url)
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError("浏览器里没有可用的上下文(context)")
    ctx = contexts[0]
    ctx.on("dialog", _on_dialog)
    return p, browser, ctx


def list_tabs(ctx):
    tabs = []
    for i, pg in enumerate(ctx.pages):
        try:
            url = pg.url
        except Exception:
            url = ""
        try:
            title = pg.title()
        except Exception:
            title = ""
        tabs.append((i, pg, title, url))
    return tabs


def release(p):
    """仅释放 Playwright 连接，保持用户浏览器继续运行。"""
    try:
        p.stop()
    except Exception:
        pass


def _ok_frame(f):
    if not f.url:
        return False
    return not (f.url.startswith("about:") or f.url.startswith("devtools://"))


def click_action(page, keywords, prefer_last=True):
    """在所有 frame 里找文字含关键字的可点元素并点击。

    返回 (是否点成功, 命中的关键字)。找不到返回 (False, None)。
    """
    for f in page.frames:
        if not _ok_frame(f):
            continue
        base = f.locator(CLICKABLE_CSS)
        for kw in keywords:
            loc = base.filter(has_text=kw)
            cnt = loc.count()
            if cnt == 0:
                continue
            rng = range(cnt - 1, -1, -1) if prefer_last else range(cnt)
            for k in rng:
                cand = loc.nth(k)
                try:
                    if not cand.is_visible():
                        continue
                    try:
                        cand.scroll_into_view_if_needed(timeout=2500)
                    except Exception:
                        pass
                    cand.click(timeout=6000)
                    return True, kw
                except Exception:
                    continue
    return False, None

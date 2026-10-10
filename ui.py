# -*- coding: utf-8 -*-
"""自动答题助手 · 图形界面（深色圆角风格，整合全部功能）

功能：一键启动调试浏览器 / 连接 / 选标签页 / 探查 / 全自动答题(可停止、逐题确认、探针模式)。
答题逻辑复用 answerer.controller。
"""
import base64
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import winsound
import zlib
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from answerer import util  # noqa: E402
from answerer import nav  # noqa: E402
from answerer import llm  # noqa: E402
from answerer.controller import Runner, dump_probe  # noqa: E402

# 可选大模型服务商（OpenAI 兼容接口预设）
PROVIDERS = [
    {"name": "DeepSeek", "base": "https://api.deepseek.com", "model": "deepseek-chat",
     "env": "DEEPSEEK_API_KEY"},
    {"name": "OpenAI", "base": "https://api.openai.com/v1", "model": "gpt-4o-mini",
     "env": "OPENAI_API_KEY"},
    {"name": "通义千问", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": "qwen-plus", "env": "DASHSCOPE_API_KEY"},
    {"name": "智谱GLM", "base": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4-flash", "env": "ZHIPU_API_KEY"},
    {"name": "Moonshot(Kimi)", "base": "https://api.moonshot.cn/v1",
     "model": "moonshot-v1-8k", "env": "MOONSHOT_API_KEY"},
    {"name": "自定义", "base": "", "model": "", "env": "LLM_API_KEY"},
]

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
DETACHED = 0x00000008 | 0x00000200

# 配色（极简扁平浅色风）
C_BG = "#eef0f4"          # 页面底色(浅灰)
C_CARD = "#ffffff"        # 卡片/面板
C_PANEL = "#ffffff"       # 兼容旧引用=卡片
C_FILL = "#f1f3f6"        # 轻填充(悬停/次级)
C_PANEL2 = "#f1f3f6"      # 兼容旧引用=轻填充
C_LINE = "#e3e7ec"        # 分隔线/描边
C_TITLE = "#3b6cf0"       # 主强调(蓝)
C_TITLE_DK = "#2f55c4"    # 强调深
C_TEXT = "#1f2937"
C_DIM = "#6b7280"
C_RED = "#e5484d"
C_OK = "#16a34a"

LEVELS = {"info": "INFO", "ok": "OK", "warn": "WARN", "error": "ERROR", "sys": "SYS", "data": "DATA"}
LOG_COLORS = {"INFO": "#0f6bed", "DATA": "#0e7c66", "OK": "#17803d",
              "WARN": "#b45309", "ERROR": "#dc2626", "SYS": "#6d28d9"}


def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def make_icon_png_b64():
    """生成 32x32 青绿底+白色▶ 的应用图标（PNG→base64，无第三方依赖）。"""
    w = h = 32
    teal = (15, 181, 169, 255)
    deep = (29, 36, 46, 255)
    white = (255, 255, 255, 255)

    def inside_tri(x, y):
        ax, ay, bx, by, cx, cy = 10.0, 9.0, 24.0, 16.5, 10.0, 24.0

        def side(px, py, ux, uy, vx, vy):
            return (px - ux) * (vy - uy) - (vx - ux) * (py - uy)

        d1 = side(x, y, ax, ay, bx, by)
        d2 = side(x, y, bx, by, cx, cy)
        d3 = side(x, y, cx, cy, ax, ay)
        return d1 >= 0 and d2 >= 0 and d3 >= 0

    rows = []
    for y in range(h):
        row = bytearray([0])  # filter: None
        for x in range(w):
            if x == 0 or y == 0 or x == w - 1 or y == h - 1:
                c = deep
            elif inside_tri(x + 0.5, y + 0.5):
                c = white
            else:
                c = teal
            row += bytes(c)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


class RoundBtn(tk.Canvas):
    """圆角扁平按钮（Canvas 绘制：填充+细描边+悬停/禁用态）。"""

    def __init__(self, master, text, bg, command, width=180, height=44,
                 fg="#ffffff", font=("Microsoft YaHei UI", 10, "bold"), outline=None,
                 hover_bg=None):
        super().__init__(master, width=width, height=height,
                         bg=master["bg"], highlightthickness=0, bd=0)
        self.bg = bg
        self.fg = fg
        self.text = text
        self.font = font
        self.command = command
        self.outline = outline if outline is not None else bg
        self.hover_bg = hover_bg or self._lighten(bg)
        self.enabled = True
        self._draw()
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _draw(self, hover=False):
        self.delete("all")
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        if not self.enabled:
            fill, text_c, oc = "#eef0f3", "#aab2bd", ""
        elif hover:
            fill, text_c = self.hover_bg, self.fg
            oc = self.outline if self.bg == "#ffffff" else ""
        else:
            fill, text_c = self.bg, self.fg
            oc = self.outline if self.bg == "#ffffff" else ""
        _round_rect(self, 1, 1, w - 1, h - 1, 10, fill=fill, outline=oc)
        self.create_text(w / 2, h / 2, text=self.text, fill=text_c, font=self.font)

    @staticmethod
    def _lighten(hex_color, f=0.06):
        c = hex_color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        r = min(255, int(r + (255 - r) * f))
        g = min(255, int(g + (255 - g) * f))
        b = min(255, int(b + (255 - b) * f))
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _darken(hex_color, f=0.08):
        c = hex_color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        r = max(0, int(r * (1 - f)))
        g = max(0, int(g * (1 - f)))
        b = max(0, int(b * (1 - f)))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _hover(self, on):
        if self.enabled:
            self._draw(hover=on)

    def _click(self, _e):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, on):
        self.enabled = on
        self._draw()


class Toggle(tk.Button):
    """行为开关（浅色 chip 风格）：● 开(蓝调) / ○ 关(灰)。"""

    def __init__(self, master, text, default=False, on_toggle=None):
        self.on = default
        self.text = text
        self.on_toggle = on_toggle
        super().__init__(master, text="", command=self.flip,
                         bd=0, relief="flat", anchor="w", height=1,
                         font=("Microsoft YaHei UI", 9),
                         cursor="hand2", padx=12, pady=8)
        self._paint()

    def _label(self):
        return ("● " if self.on else "○ ") + self.text

    def _paint(self):
        if self.on:
            self.configure(text=self._label(), bg="#eaf0fe", fg=C_TITLE_DK,
                           activebackground="#dce6fc", activeforeground=C_TITLE_DK)
        else:
            self.configure(text=self._label(), bg=C_FILL, fg="#566070",
                           activebackground="#e4e8ee", activeforeground="#566070")

    def flip(self):
        self.on = not self.on
        self._paint()
        if self.on_toggle:
            self.on_toggle(self.on)

    def set_on(self, on):
        self.on = bool(on)
        self._paint()

    def get(self):
        return self.on


class App:
    def __init__(self, root):
        self.root = root
        # 使用标准系统标题栏（保证任务栏有程序图标/可最小化）
        root.title("自动答题助手 · iTEST")
        root.configure(bg=C_BG)
        root.geometry("920x780+200+80")
        self.q = queue.Queue()
        self.connected = False
        self.tabs = []
        self.busy = False
        self.paused = False
        self.runner_stop = None
        self.gate_ev = None

        self.cfg = util.load_json(ROOT / "config.json")
        if (ROOT / ".env").exists():
            util.load_env(ROOT / ".env")
        self.cdp_url = self.cfg.get("cdp_url", "http://127.0.0.1:9222")

        self._build()
        self._setup_icon()
        self._tick_clock()
        self.log("就绪。操作流程：① 启动调试浏览器 → ② 连接浏览器 → 在浏览器打开任务页 → ③ 开始答题。", "sys")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._drain)
        self.root.bind("<Control-l>", lambda e: self._clear_log())

    # ---------------- 界面 ----------------
    def _setup_icon(self):
        """给窗口/任务栏设置专属图标。"""
        try:
            from tkinter import PhotoImage
            self._icon = PhotoImage(data=make_icon_png_b64())
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def _build(self):
        # 顶部：白底标题行 + 底部细线
        self.bar = tk.Frame(self.root, bg="#ffffff", height=46)
        self.bar.pack(fill="x")
        self.bar.pack_propagate(False)
        tk.Label(self.bar, text="  ⚡ 自动答题助手", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=14, pady=6)
        tk.Label(self.bar, text="网页自动作答 · iTEST · 本地运行", bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", pady=6)
        self.dot_var = tk.StringVar(value="● 未连接浏览器")
        tk.Label(self.bar, textvariable=self.dot_var, bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="right", padx=16, pady=6)
        tk.Frame(self.bar, bg=C_LINE, height=1).pack(side="bottom", fill="x")

        # 状态卡：时间 / API 状态 / API 按钮
        panel = tk.Frame(self.root, bg="#ffffff")
        panel.pack(fill="x", padx=18, pady=(14, 6))
        self.clock_var = tk.StringVar(value="--:--:--")
        tk.Label(panel, text="◎", bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(10, 0), pady=9)
        tk.Label(panel, text="服务器时间", bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", pady=9)
        tk.Label(panel, textvariable=self.clock_var, bg="#ffffff", fg=C_TEXT,
                 font=("Consolas", 12, "bold")).pack(side="left", padx=(6, 16), pady=9)
        tk.Frame(panel, bg=C_LINE, width=1).pack(side="left", fill="y", pady=8)
        llm_cfg = self.cfg.get("llm", {})
        prov = llm_cfg.get("provider") or "DeepSeek"
        env_name = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
        key_ok = bool((os.environ.get(env_name) or "").strip())
        self.provider_var = tk.StringVar(value=f"{prov} · {llm_cfg.get('model', '')}  ● "
                                               f"{'Key 已配置' if key_ok else 'Key 未配置'}")
        self.api_lbl = tk.Label(panel, textvariable=self.provider_var, bg="#ffffff",
                                fg=(C_OK if key_ok else C_RED),
                                font=("Microsoft YaHei UI", 9))
        self.api_lbl.pack(side="left", padx=14, pady=9)
        self.b_api_set = RoundBtn(panel, "⚙ API 设置", "#ffffff", self._open_api_settings,
                                  width=120, height=32, fg="#374151", outline=C_LINE,
                                  font=("Microsoft YaHei UI", 9))
        self.b_api_test = RoundBtn(panel, "检测连接", C_TITLE,
                                   lambda: self._start_thread(self._test_api, "检测连接"),
                                   width=110, height=32, fg="#ffffff",
                                   font=("Microsoft YaHei UI", 9))
        self.b_api_set.pack(side="right", padx=(0, 12), pady=6)
        self.b_api_test.pack(side="right", padx=8, pady=6)

        # 行为设置卡：两列开关
        frm = tk.Frame(self.root, bg="#ffffff")
        frm.pack(fill="x", padx=18, pady=6)
        tk.Label(frm, text="行为设置", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=14, pady=(10, 4))
        tk.Label(frm, text="答题前可调整的策略选项", bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=14)
        cols = tk.Frame(frm, bg="#ffffff")
        cols.pack(fill="x", padx=12, pady=(6, 12))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        self.tg_skip = Toggle(cols, "跳过无题干题(听力等，不瞎猜)", True)
        self.tg_rewind = Toggle(cols, "回退到第1题再开始", True)
        self.tg_sound = Toggle(cols, "完成提示音", True)
        self.tg_step = Toggle(cols, "逐题确认模式", False)
        self.tg_dry = Toggle(cols, "探针模式(只生成不填写)", False)
        self.tg_check = Toggle(cols, "答后校验(未生效自动重试)", True)
        for i, tg in enumerate((self.tg_skip, self.tg_rewind, self.tg_sound,
                                self.tg_step, self.tg_dry, self.tg_check)):
            tg.grid(row=i % 3, column=i // 3, sticky="ew", padx=6, pady=4)

        # 运行卡：连接 / 标签页 / 主按钮
        runcard = tk.Frame(self.root, bg="#ffffff")
        runcard.pack(fill="x", padx=18, pady=6)
        tk.Label(runcard, text="运行控制", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        inner = tk.Frame(runcard, bg="#ffffff")
        inner.pack(fill="x", padx=14, pady=(8, 14))
        # 第一步：调试浏览器
        brow = tk.Frame(inner, bg="#ffffff")
        brow.pack(fill="x")
        tk.Label(brow, text="①", bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=(0, 4))
        tk.Label(brow, text="调试浏览器", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.b_launch = RoundBtn(brow, "启动调试浏览器", C_TITLE_DK, self._on_launch,
                                 width=150, height=32, font=("Microsoft YaHei UI", 9))
        self.b_connect = RoundBtn(brow, "连接浏览器", "#ffffff", self._on_connect,
                                  width=110, height=32, fg="#374151", outline=C_LINE,
                                  font=("Microsoft YaHei UI", 9))
        self.b_launch.pack(side="right", padx=4, pady=4)
        self.b_connect.pack(side="right", padx=4, pady=4)
        tk.Frame(inner, bg=C_LINE, height=1).pack(fill="x", pady=6)
        # 第二步：标签页
        tabrow = tk.Frame(inner, bg="#ffffff")
        tabrow.pack(fill="x", pady=2)
        tk.Label(tabrow, text="② 答题页标签", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Dark.TCombobox", fieldbackground="#ffffff", background="#ffffff",
                        foreground=C_TEXT, arrowcolor=C_TITLE, bordercolor=C_LINE,
                        lightcolor=C_LINE, darkcolor=C_LINE)
        self.tab_var = tk.StringVar(value="(未选择)")
        self.cmb = ttk.Combobox(tabrow, textvariable=self.tab_var, state="readonly",
                                style="Dark.TCombobox")
        self.cmb.pack(side="left", fill="x", expand=True, padx=10)
        tk.Button(tabrow, text="↻ 刷新", command=lambda: self._start_thread(self._refresh_tabs_worker, "刷新标签页"),
                  bg=C_FILL, fg=C_TEXT, bd=0, padx=10, activebackground="#e4e8ee",
                  font=("Microsoft YaHei UI", 9), cursor="hand2").pack(side="left")
        tk.Frame(inner, bg=C_LINE, height=1).pack(fill="x", pady=6)
        # 第三步：模式选择
        moderow = tk.Frame(inner, bg="#ffffff")
        moderow.pack(fill="x", pady=2)
        tk.Label(moderow, text="③ 模式", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.tg_normal = Toggle(moderow, "普通模式(读网页控件)", True)
        self.tg_capture = Toggle(moderow, "抓包模式(截取接口报文)", False,
                                 on_toggle=lambda on: on and self._switch_mode())
        self.tg_normal.pack(side="left", padx=(10, 6))
        self.tg_capture.pack(side="left", padx=6)
        tk.Frame(inner, bg=C_LINE, height=1).pack(fill="x", pady=6)
        # 第四步：主按钮
        mainrow = tk.Frame(inner, bg="#ffffff")
        mainrow.pack(fill="x", pady=2)
        self.b_run = RoundBtn(mainrow, "▶ 开始答题", C_TITLE, self._on_run, width=240, height=50,
                              font=("Microsoft YaHei UI", 12, "bold"))
        self.b_stop = RoundBtn(mainrow, "■ 停止", "#ffffff", self._stop, width=110, height=50,
                               fg=C_RED, outline=C_RED,
                               font=("Microsoft YaHei UI", 11, "bold"))
        self.b_run.pack(side="left", padx=(0, 10))
        self.b_stop.pack(side="left", padx=10)
        row2 = tk.Frame(inner, bg="#ffffff")
        row2.pack(fill="x", pady=(6, 0))
        self.b_probe = RoundBtn(row2, "探查页面", "#ffffff", self._on_probe, width=110, height=32,
                                fg="#374151", outline=C_LINE, font=("Microsoft YaHei UI", 9))
        self.b_export = RoundBtn(row2, "导出结果与日志", "#ffffff", self._export, width=150, height=32,
                                 fg="#374151", outline=C_LINE, font=("Microsoft YaHei UI", 9))
        self.b_clear = RoundBtn(row2, "清除日志", "#ffffff", self._clear_log, width=96, height=32,
                                fg="#374151", outline=C_LINE, font=("Microsoft YaHei UI", 9))
        self.b_hist = RoundBtn(row2, "清空历史记录", "#ffffff", self._on_clear_history,
                               width=124, height=32, fg=C_RED, outline=C_RED,
                               font=("Microsoft YaHei UI", 9))
        self.b_probe.pack(side="left", padx=(0, 10))
        self.b_export.pack(side="left", padx=10)
        self.b_clear.pack(side="left", padx=10)
        self.b_hist.pack(side="left", padx=10)

        # 日志卡
        logwrap = tk.Frame(self.root, bg="#ffffff")
        logwrap.pack(fill="both", expand=True, padx=18, pady=(6, 2))
        loghead = tk.Frame(logwrap, bg="#ffffff")
        loghead.pack(fill="x")
        tk.Label(loghead, text="运行日志", bg="#ffffff", fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=14, pady=(8, 2))
        self.prog_var = tk.StringVar(value="进度：空闲")
        tk.Label(loghead, textvariable=self.prog_var, bg="#ffffff", fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="right", padx=14)
        self.txt = tk.Text(logwrap, bg="#fbfcfe", fg="#111827", bd=0,
                           font=("Consolas", 9), padx=12, pady=8,
                           highlightthickness=0, state="disabled")
        self.txt.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        for lv, color in LOG_COLORS.items():
            self.txt.tag_configure(lv, foreground=color)

        tk.Label(self.root, text="仅限个人学习使用 | 请遵守学校考试与平台规则",
                 bg=C_BG, fg=C_DIM, font=("Microsoft YaHei UI", 8)
                 ).pack(pady=(0, 8))

    # ---------------- 基础行为 ----------------
    def _tick_clock(self):
        self.clock_var.set(time.strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _minimize(self):
        self.root.iconify()

    def log(self, msg, tag="info"):
        level = LEVELS.get(tag, "INFO")
        if msg.startswith("  → "):
            level = "DATA"
        self.q.put((time.strftime("%H:%M:%S"), f"[{level}] {msg}", tag if level != "DATA" else "data"))

    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and len(item) == 2 and item[0] == "__done__":
                    self.busy = False
                    self.paused = False
                    self._set_buttons(True)
                    self.log(f"任务「{item[1]}」结束。", "sys")
                elif isinstance(item, tuple) and len(item) == 2 and item[0] == "__status__":
                    self.dot_var.set(item[1])
                elif isinstance(item, tuple) and len(item) == 2 and item[0] == "__progress__":
                    self.prog_var.set(item[1])
                elif isinstance(item, tuple) and len(item) == 2 and item[0] == "__tabs__":
                    tabs = item[1]
                    self.tabs = tabs
                    self.cmb["values"] = [f"[{i}] {t[:32]}  {u[:56]}" for i, _p, t, u in tabs]
                    auto = next((i for i, (_i, _p, _t, u) in enumerate(tabs) if "answer" in u), None)
                    if auto is None and tabs:
                        auto = 0
                    if auto is not None:
                        self.cmb.current(auto)
                        self.dot_var.set(f"● 已连接 | {tabs[auto][2][:32]}")
                elif isinstance(item, tuple) and len(item) == 2 and item[0] == "__pause__":
                    self.paused = True
                elif isinstance(item, tuple) and len(item) == 2 and item[0] == "__api__":
                    ok, msg = item[1]
                    lcfg = self.cfg.get("llm", {})
                    prov = lcfg.get("provider") or "DeepSeek"
                    self.provider_var.set(f"{prov} · {lcfg.get('model', '')}  ● "
                                          f"{'连接正常' if ok else '连接失败'}")
                    self.api_lbl.configure(fg=(C_OK if ok else C_RED))
                else:
                    ts, msg, tag = item
                    level = msg.split("]", 1)[0].lstrip("[")
                    self.txt.configure(state="normal")
                    self.txt.insert("end", f"[{ts}] {msg}\n", level if level in LOG_COLORS else "INFO")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._drain)

    def _set_buttons(self, state):
        for b in (self.b_launch, self.b_connect, self.b_run, self.b_probe):
            b.set_enabled(state)

    def _start_thread(self, fn, name):
        if self.busy:
            self.log("已有任务进行中，请先等待或点“停止”。", "warn")
            return
        self.busy = True
        self._set_buttons(False)
        self.log(f"任务「{name}」开始…", "sys")
        threading.Thread(target=self._wrap, args=(fn, name), daemon=True).start()

    def _wrap(self, fn, name):
        try:
            fn()
        except Exception as e:
            self.log(f"任务「{name}」出错: {e}", "error")
        finally:
            self.q.put(("__done__", name))

    # ---------------- 按钮动作 ----------------
    def _switch_mode(self):
        """普通/抓包 互斥切换。"""
        if self.tg_capture.get():
            self.tg_normal.set_on(False)
        else:
            self.tg_capture.set_on(False)

    def _on_launch(self):
        self._start_thread(self._launch_edge, "启动浏览器")

    def _on_connect(self):
        self._start_thread(self._connect, "连接浏览器")

    def _on_probe(self):
        self._start_thread(self._probe, "探查页面")

    def _on_run(self):
        if self.paused and self.busy and self.gate_ev is not None:
            self.gate_ev.set()   # 逐题确认模式：放行下一题
            self.log("已放行，继续下一题…", "sys")
            return
        self._start_thread(self._run_quiz, "自动答题")

    def _export(self):
        try:
            text = self.txt.get("1.0", "end")
            out = ROOT / "out"
            out.mkdir(exist_ok=True)
            f = out / f"ui_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            f.write_text(text, encoding="utf-8")
            os.startfile(str(out))
            self.log(f"已导出日志: {f.name}，并打开 out 文件夹。", "ok")
        except Exception as e:
            self.log(f"导出失败: {e}", "error")

    def _clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self.log("日志已清空。", "sys")

    def _on_clear_history(self):
        if messagebox.askyesno(
                "清空历史记录",
                "确定删除 out 目录下所有 run_*/probe_* 历史记录吗？\n"
                "（不影响程序运行，当前界面日志保留；删除后无法找回）",
                parent=self.root):
            self._start_thread(self._clear_history_worker, "清空历史")

    def _clear_history_worker(self):
        import shutil
        out = ROOT / "out"
        deleted = 0
        if out.exists():
            for child in out.iterdir():
                if child.is_dir() and (child.name.startswith("run_")
                                       or child.name.startswith("probe_")):
                    shutil.rmtree(child, ignore_errors=True)
                    deleted += 1
        self.log(f"✅ 已清理 {deleted} 个历史记录文件夹。", "ok")

    def _stop(self):
        if self.runner_stop is not None:
            self.runner_stop.set()
            self.log("已发出停止指令(当前步骤完成后停止)…", "warn")
        else:
            self.log("当前没有正在运行的答题任务。", "info")

    # ---------------- API 设置与检测 ----------------
    def _test_api(self):
        self.log("正在检测 API 连接…", "sys")
        ok, msg = llm.test_connection(self.cfg.get("llm", {}))
        self.q.put(("__api__", (ok, msg)))
        self.log(("✅ " if ok else "❌ ") + msg, "ok" if ok else "error")

    def _open_api_settings(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("API 设置")
        dlg.configure(bg=C_BG)
        dlg.geometry("580x360")
        dlg.transient(self.root)
        dlg.grab_set()
        pad = {"padx": 10, "pady": 5}
        llm_cfg = self.cfg.get("llm", {})
        names = [p["name"] for p in PROVIDERS]
        cur = llm_cfg.get("provider") or "DeepSeek"
        if cur not in names:
            cur = "自定义"
        base0 = llm_cfg.get("base_url", "")
        model0 = llm_cfg.get("model", "")
        env0 = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")

        def lbl(row, text):
            tk.Label(row, text=text, bg=C_BG, fg=C_DIM,
                     font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        def ent(row, var, show=None, width=64):
            e = tk.Entry(row, textvariable=var, bg=C_PANEL2, fg=C_TEXT,
                         insertbackground=C_TEXT, relief="flat", show=show, width=width)
            e.pack(fill="x", padx=(0, 6))
            return e

        r1 = tk.Frame(dlg, bg=C_BG); r1.pack(fill="x", **pad)
        lbl(r1, "服务商")
        var_prov = tk.StringVar(value=cur)
        cb = ttk.Combobox(r1, textvariable=var_prov, values=names, state="readonly",
                          style="Dark.TCombobox")
        cb.pack(fill="x")

        r2 = tk.Frame(dlg, bg=C_BG); r2.pack(fill="x", **pad)
        lbl(r2, "接口地址 base_url")
        var_base = tk.StringVar(value=base0)
        ent(r2, var_base)

        r3 = tk.Frame(dlg, bg=C_BG); r3.pack(fill="x", **pad)
        lbl(r3, "模型名")
        var_model = tk.StringVar(value=model0)
        ent(r3, var_model)

        r4 = tk.Frame(dlg, bg=C_BG); r4.pack(fill="x", **pad)
        lbl(r4, "API Key（留空表示沿用已保存的 Key）")
        var_key = tk.StringVar()
        ent(r4, var_key, show="*")

        r5 = tk.Frame(dlg, bg=C_BG); r5.pack(fill="x", **pad)
        lbl(r5, "环境变量名（一般随服务商自动，无需改）")
        var_env = tk.StringVar(value=env0)
        ent(r5, var_env, width=40)

        def on_provider(_e=None):
            pv = next((p for p in PROVIDERS if p["name"] == var_prov.get()), PROVIDERS[-1])
            if pv["base"]:   # 预设：自动填地址/模型/环境变量名
                var_base.set(pv["base"])
                var_model.set(pv["model"])
                var_env.set(pv["env"])

        cb.bind("<<ComboboxSelected>>", on_provider)
        on_provider()

        status = {"ok": True}

        def save(silent=False):
            base = var_base.get().strip()
            model = var_model.get().strip()
            env = (var_env.get().strip() or "LLM_API_KEY")
            key = var_key.get().strip()
            if not base.startswith("http"):
                self.log("接口地址必须以 http(s):// 开头", "error")
                status["ok"] = False
                return False
            if not model:
                self.log("模型名不能为空", "error")
                status["ok"] = False
                return False
            newllm = dict(llm_cfg)
            newllm.update(base_url=base, model=model, api_key_env=env,
                          provider=var_prov.get())
            try:
                cfg_all = util.load_json(ROOT / "config.json")
                cfg_all["llm"] = newllm
                util.dump_json(ROOT / "config.json", cfg_all)
            except Exception as e:
                self.log(f"保存 config.json 失败: {e}", "error")
                status["ok"] = False
                return False
            self.cfg["llm"] = newllm
            if key:
                try:
                    util.set_env_file(ROOT / ".env", env, key)
                except Exception as e:
                    self.log(f"保存 .env 失败: {e}", "error")
                    status["ok"] = False
                    return False
            else:
                util.load_env(ROOT / ".env")
            if not silent:
                self.log(f"✅ 已保存 API：{var_prov.get()} · {model}", "ok")
                self.q.put(("__api__", (True, f"配置已保存：{var_prov.get()} · {model}")))
            return True

        def save_close():
            if save():
                dlg.destroy()

        def save_test():
            if save():
                dlg.destroy()
                self._start_thread(self._test_api, "检测连接")

        r6 = tk.Frame(dlg, bg=C_BG); r6.pack(fill="x", padx=10, pady=(10, 8))
        tk.Button(r6, text="保存", command=save_close, bg=C_TITLE, fg="white", bd=0,
                  width=12, activebackground=C_TITLE_DK, cursor="hand2").pack(side="left", padx=4)
        tk.Button(r6, text="保存并检测连接", command=save_test, bg=C_TITLE_DK, fg="white", bd=0,
                  width=16, activebackground="#2a4aa8", cursor="hand2").pack(side="left", padx=4)
        tk.Button(r6, text="取消", command=dlg.destroy, bg=C_FILL, fg=C_TEXT, bd=0,
                  width=8, activebackground="#e4e8ee", cursor="hand2").pack(side="left", padx=4)

    # ---------------- 功能实现（工作线程） ----------------
    def _launch_edge(self):
        edge = next((e for e in EDGE_CANDIDATES if os.path.exists(e)), None)
        if not edge:
            self.log("未找到 Edge/Chrome 可执行文件。", "error")
            return
        name = os.path.basename(edge)
        self.log(f"正在关闭现有浏览器 {name} …", "sys")
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
        time.sleep(2)
        copy_dir = ROOT / "profiles" / "edge_copy"
        src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")
        if os.path.isdir(src) and not (copy_dir / "Local State").exists():
            self.log("首次运行：正在复制你的浏览器配置(1-2GB，请耐心等待1-3分钟)…", "sys")
            subprocess.run(
                ["robocopy", src, str(copy_dir), "/E",
                 "/XD", "Cache", "Code Cache", "GPUCache", "Crashpad",
                 "/R:1", "/W:1", "/NFL", "/NDL"],
                capture_output=True,
            )
        self.log("正在启动带调试端口的浏览器(端口 9222)…", "sys")
        subprocess.Popen(
            [edge, "--remote-debugging-port=9222", "--remote-allow-origins=*",
             f"--user-data-dir={copy_dir}", "--restore-last-session"],
            creationflags=DETACHED, close_fds=True,
        )
        for _ in range(60):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1) as r:
                    if r.status == 200:
                        self.log("✅ 调试浏览器已就绪(记录都在)。", "ok")
                        return
            except Exception:
                pass
        self.log("端口仍未就绪：请确认浏览器已打开，稍后点“② 连接浏览器”重试。", "warn")

    def _pick_url(self, tabs):
        """按当前下拉选择优先，其次自动找答题页 URL。返回 (index, url) 或 (None, None)。"""
        if not tabs:
            return None, None
        try:
            sel = self.cmb.current()
        except Exception:
            sel = -1
        if 0 <= sel < len(tabs):
            return sel, tabs[sel][3]
        for i, (_i, _p, _t, u) in enumerate(tabs):
            if "answer" in u:
                return i, u
        return 0, tabs[0][3]

    def _connect(self):
        # Playwright 对象不能跨线程使用：每次任务都“独立连接、用完即断”，
        # 浏览器进程本身不会关闭，重连开销很小。
        self.log("正在连接浏览器调试端口…", "sys")
        try:
            p, _browser, ctx = nav.connect_browser(self.cdp_url)
        except Exception as e:
            self.log(f"连接失败: {e}", "error")
            self.log("请先点「① 启动调试浏览器」，或手动运行 start_edge_debug.bat。", "sys")
            self.connected = False
            self.q.put(("__status__", "● 未连接"))
            return
        try:
            tabs = nav.list_tabs(ctx)
            self.connected = True
            self.q.put(("__tabs__", tabs))
            self.q.put(("__status__", "● 已连接"))
            self.log(f"✅ 已连接浏览器，共 {len(tabs)} 个标签页。", "ok")
        finally:
            nav.release(p)

    def _refresh_tabs_worker(self):
        try:
            p, _browser, ctx = nav.connect_browser(self.cdp_url)
        except Exception as e:
            self.log(f"刷新标签页失败(未连接): {e}", "warn")
            return
        try:
            tabs = nav.list_tabs(ctx)
            self.connected = True
            self.q.put(("__tabs__", tabs))
            self.log(f"共 {len(tabs)} 个标签页。", "info")
        finally:
            nav.release(p)

    def _run_quiz(self):
        if self.paused and self.busy and self.gate_ev is not None:
            self.gate_ev.set()   # 逐题确认模式：放行下一题
            self.log("已放行，继续下一题…", "sys")
            return
        try:
            p, _browser, ctx = nav.connect_browser(self.cdp_url)
        except Exception as e:
            self.log(f"连接浏览器失败: {e}", "error")
            self.log("请先点「① 启动调试浏览器」，再点「② 连接浏览器」。", "sys")
            return
        try:
            tabs = nav.list_tabs(ctx)
            _i, _u = self._pick_url(tabs)
            page = tabs[_i][1] if _i is not None else None
            if page is None:
                self.log("没有可用标签页。", "warn")
                return
            self._do_run(page)
        finally:
            nav.release(p)

    def _do_run(self, page):
        stop = threading.Event()
        self.runner_stop = stop
        cfg = dict(self.cfg)
        cfg["skip_unknown_stem"] = self.tg_skip.get()
        cfg["dry_run"] = self.tg_dry.get()
        cfg["verify_fill"] = bool(self.tg_check.get())
        cfg["answer_mode"] = "capture" if self.tg_capture.get() else "normal"
        cfg["vision"] = dict(self.cfg.get("vision", {}))
        gate = threading.Event() if self.tg_step.get() else None
        self.gate_ev = gate
        try:
            page.bring_to_front()
        except Exception:
            pass
        if self.tg_rewind.get():
            n = int(self.cfg.get("rewind_steps", 6))
            for k in range(n):
                if stop.is_set():
                    break
                ok, kw = nav.click_action(page, ["上一题", "Previous"], prefer_last=False)
                if not ok:
                    self.log(f"回退第 {k + 1} 次未找到“上一题”，停止回退(应已在第1题)。", "sys")
                    break
                page.wait_for_timeout(900)
            self.log("回退完成，开始答题。", "sys")

        def logfn(m, tag="info"):
            if gate is not None and m.startswith("⏸ 已暂停"):
                self.q.put(("__pause__", ""))
            self.log(m, tag)

        runner = Runner(
            page, cfg, ROOT,
            log=logfn,
            progress=lambda pno, stage, info: self.q.put(("__progress__", f"第 {pno} 页 | {info}")),
            stop=stop,
            gate=gate,
        )
        res = runner.run()
        self.q.put(("__progress__", f"完成：共答 {res['pages']} 页，跳过 {res['skipped']} 题"))
        self.q.put(("__status__", "● 答题结束(未自动交卷)" if not cfg["auto_submit"] else "● 已自动提交"))
        self.log("全部完成。请到浏览器里人工检查后点「交卷」。", "ok")
        if self.tg_sound.get():
            for _ in range(3):
                winsound.Beep(880, 220)
                time.sleep(0.12)

    def _probe(self):
        try:
            p, _browser, ctx = nav.connect_browser(self.cdp_url)
        except Exception as e:
            self.log(f"连接浏览器失败: {e}", "error")
            return
        try:
            tabs = nav.list_tabs(ctx)
            _i, _u = self._pick_url(tabs)
            page = tabs[_i][1] if _i is not None else None
            if page is None:
                self.log("没有可用标签页。", "warn")
                return
            self.log("探查当前页…", "sys")
            items = dump_probe(page, self.cfg, ROOT, log=lambda m, tag="info": self.log(m, tag))
            self.log(f"探查完成，共识别 {len(items)} 道题。", "ok")
        finally:
            nav.release(p)

    def _on_close(self):
        if self.runner_stop is not None:
            self.runner_stop.set()
        self.root.destroy()


def main():
    util.console_utf8()
    root = tk.Tk()
    App(root)
    if "--smoke" in sys.argv:
        print("SMOKE_LAUNCHED")
        root.after(2000, root.destroy)
    root.mainloop()
    if "--smoke" in sys.argv:
        print("SMOKE_OK")


if __name__ == "__main__":
    main()

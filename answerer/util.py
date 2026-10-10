# -*- coding: utf-8 -*-
"""通用小工具：读取 JSON/环境变量、时间戳目录、控制台编码等。"""
import json
import os
import re
import sys
import time
from pathlib import Path


def console_utf8():
    """Windows 下控制台可能默认 GBK，切到 UTF-8 避免打印中文报错。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_env(path):
    """把 .env 文件中的 KEY=VALUE 读进环境变量（已存在的环境变量优先）。"""
    p = Path(path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def set_env_file(path, key, value):
    """把 key=value 写入 .env（保留其它行；已存在则覆盖）。"""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value


def ts_dir(root, prefix):
    d = Path(root) / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def collapse(s, limit=None):
    s = re.sub(r"\s+", " ", s or "").strip()
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return s

# -*- coding: utf-8 -*-
"""读题器：从页面(含 iframe)里抓取【当前可见】的题目控件。

关键设计（针对真实 iTEST 平台调优）：
  * 只收集可见控件（getBoundingClientRect 有尺寸、display/visibility 未隐藏），
    整卷渲染但被 CSS 隐藏的其他页题目会被自动忽略 —— 天然支持“一页一题”。
  * 每个控件记录从近到远 10 层祖先容器的文字(ctxs)，题干从最近一层
    扣除选项文字后非空的那层选取。
  * 每个同 name 的单选/复选组 = 一道选择题；每个文本框 = 填空；
    textarea/contenteditable 按实际高度区分问答题/作文题；select = 下拉单选。
"""
import re

from .util import collapse

SELECTORS = {
    "choice": 'input[type="radio"], input[type="checkbox"]',
    "text": 'input[type="text"], input[type="number"], input:not([type])',
    "area": "textarea",
    "ce": '[contenteditable="true"]',
    "select": "select",
}

JS_COLLECT = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const ownText = (el) => clean(Array.from(el.childNodes)
      .filter(n => n.nodeType === 3).map(n => n.textContent).join(' '));
  const labelText = (el) => {
    if (el.id) {
      const lf = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lf && clean(lf.innerText)) return clean(lf.innerText).slice(0, 120);
    }
    const c = el.closest('label');
    if (c && clean(c.innerText)) return clean(c.innerText).slice(0, 120);
    let p = el.parentElement, d = 0;
    while (p && p !== document.body && d < 4) {
      const t = ownText(p);
      if (t && t.length <= 60) return t;
      p = p.parentElement; d++;
    }
    return '';
  };
  const visible = (el) => {
    try {
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return false;
      const st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden') return false;
      if (!el.offsetParent && st.position !== 'fixed') return false;
      return true;
    } catch (e) { return false; }
  };
  const ancestors = (el) => {
    const out = [];
    let p = el.parentElement, d = 0;
    while (p && p !== document.body && d < 10) {
      const t = clean(p.innerText || '');
      if (t && t.length <= 600) out.push(t.slice(0, 600));
      p = p.parentElement; d++;
    }
    return out;
  };
  const rowCtx = (el) => {
    let p = el.parentElement, d = 0;
    while (p && p !== document.body && d < 6) {
      if (visible(p)) {
        const t = clean(p.innerText || '');
        if (t && t.length >= 1 && t.length <= 160) return t;
      }
      p = p.parentElement; d++;
    }
    return '';
  };
  const groupKey = (el) => {
    // 找“最近、内含 2~12 个选择控件、文字不过长”的祖先，作为该选项所属题目容器
    let p = el.parentElement, d = 0;
    while (p && p !== document.body && d < 9) {
      let c = 0;
      try { c = p.querySelectorAll('input[type="radio"],input[type="checkbox"]').length; } catch (e) {}
      if (c >= 2 && c <= 12) {
        const t = clean(p.innerText || '');
        if (t && t.length <= 900) {
          const u = p.id ? ('#' + p.id) : (p.className ? '.' + String(p.className).slice(0, 60)
                                                    : p.tagName);
          return u + '::' + c;
        }
      }
      p = p.parentElement; d++;
    }
    return 'solo';
  };
  const radios = [];
  document.querySelectorAll('input[type="radio"],input[type="checkbox"]').forEach((el, i) => {
    let hiddenRow = false;
    if (!visible(el)) {
      // 兼容“选项块可见、input 隐藏”的平台(学习通/问卷等)
      if (!rowCtx(el)) return;
      hiddenRow = true;
    }
    radios.push({i, name: el.name || '', type: el.type, checked: el.checked,
      disabled: el.disabled, opt: labelText(el), ctxs: ancestors(el),
      hiddenRow, gk: groupKey(el)});
  });
  const texts = [];
  document.querySelectorAll('input[type="text"],input[type="number"],input:not([type])').forEach((el, i) => {
    if (!visible(el)) return;
    texts.push({i, type: el.type || 'text', disabled: el.disabled, ctxs: ancestors(el)});
  });
  const areas = [];
  document.querySelectorAll('textarea,[contenteditable="true"]').forEach((el, i) => {
    if (!visible(el)) return;
    let h = 0;
    try { h = el.getBoundingClientRect().height; } catch (e) {}
    let rows = (el.tagName === 'TEXTAREA') ? (el.rows || 2) : 3;
    if (h > 60) rows = Math.max(rows, Math.round(h / 24));
    areas.push({i, ce: el.tagName !== 'TEXTAREA', rows,
      disabled: !!el.disabled, ctxs: ancestors(el)});
  });
  const selects = [];
  document.querySelectorAll('select').forEach((el, i) => {
    if (!visible(el)) return;
    selects.push({i, disabled: el.disabled,
      opts: Array.from(el.options).map(o => (o.text || '').trim()).filter(Boolean),
      ctxs: ancestors(el)});
  });
  const choiceBlocks = [];
  document.querySelectorAll('[class*="answerBg"]').forEach(el => {
    if (!visible(el)) return;
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role !== 'radio' && role !== 'checkbox') return;
    const sp = el.querySelector('span[class*="addChoice"], span[class*="num_option"]');
    const letter = sp ? (sp.textContent || '').trim().slice(0, 1) : '';
    const qid = sp ? (sp.getAttribute('qid') || '') : '';
    const content = clean((el.querySelector('.answer_p') || el).innerText || '')
      .replace(letter, '').replace(/^[A-H]\s*/, '').trim().slice(0, 220);
    const cls = ' ' + (el.className || '') + ' ';
    choiceBlocks.push({qid, letter, role, content, checked: /(check|active|selected|hover)/.test(cls),
      ctxs: ancestors(el)});
  });
  // ---- 通用“选项行”识别：文字以 A./B./C. 开头且可点击(有 onclick)的 div/li/p… ----
  const isOptTxt = (s) => /^[A-H][.、．)）]\s*\S/.test(s || '');
  const optRowsIn = (el) => {
    if (!el.querySelectorAll) return 0;
    let c = 0;
    el.querySelectorAll('div,li,section,p,span').forEach((x) => {
      const r = x.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      const t = clean(x.innerText || '');
      if (isOptTxt(t) && t.length <= 240) c++;
    });
    return c;
  };
  const keyGen = (el) => {
    let p = el.parentElement, d = 0;
    while (p && p !== document.body && d < 9) {
      const c = optRowsIn(p);
      if (c >= 2 && c <= 12) {
        const u = p.id ? ('#' + p.id) : (p.className ? '.' + String(p.className).slice(0, 60) : p.tagName);
        return u + '::' + c;
      }
      p = p.parentElement; d++;
    }
    return 'g-solo';
  };
  const clickTarget = (el) => {
    let n = el, d = 0;
    while (n && d < 5) {
      if (n.getAttribute && n.getAttribute('onclick')) return n;
      n = n.parentElement; d++;
    }
    return el;
  };
  const genOpts = [];
  const seenKeys = {};
  document.querySelectorAll('div,li,section,p,span').forEach((el) => {
    if (!visible(el)) return;
    const t = clean(el.innerText || '').trim();
    if (!isOptTxt(t) || t.length > 240) return;
    const pe = el.parentElement;
    const pt = pe ? clean(pe.innerText || '').trim() : '';
    if (pt === t) return;                    // 中间层（父与子同文）
    let dup = false;
    if (el.querySelectorAll && t.length > 4) {
      el.querySelectorAll('div,li,section,p,span').forEach((ch) => {
        if (ch !== el && clean(ch.innerText || '').trim() === t) dup = true;
      });
    }
    if (dup) return;
    const ct = clickTarget(el);
    const letter = t.charAt(0);
    const key = keyGen(ct);
    seenKeys[key] = (seenKeys[key] || 0) + 1;
    genOpts.push({letter, text: t.slice(0, 240), key, ctxs: ancestors(ct)});
  });
  const bodyText = clean(document.body.innerText || '').slice(0, 800);
  return {url: location.href, radios, texts, areas, selects, choiceBlocks, genOpts, bodyText};
}
"""

KIND_CN = {
    "single": "单选题/判断题",
    "multi": "多选题",
    "fill": "填空题",
    "select": "下拉单选题",
    "open": "问答题(文本框)",
    "essay": "作文/翻译/大题(textarea)",
}

STEM_UNKNOWN = "(题干未能自动截取，请结合选项推断)"


def _ok_frame(f):
    if not f.url:
        return False
    return not (f.url.startswith("about:") or f.url.startswith("devtools://"))


def collect_raw(page):
    """返回 [{frame_index, url, data}]，data 即 JS 采集的当前可见四类控件列表。"""
    raws = []
    for fi, f in enumerate(page.frames):
        if not _ok_frame(f):
            continue
        try:
            data = f.evaluate(JS_COLLECT)
        except Exception:
            continue
        raws.append({"frame_index": fi, "url": f.url, "data": data})
    return raws


def _clean_noise(s):
    s = re.sub(r"字数统计[:：]\s*\d+", "", s or "")
    s = re.sub(r"(上一题|下一题|交卷|保存)", "", s or "")
    return collapse(s, 400)


def _trim_lead(s):
    """去掉题干行首的‘题号/编号+点号’，但保留年份数字（如 1978年12月）。"""
    s = (s or "").lstrip()
    while True:
        m = re.match(r"^\d+\s*[.、)）]\s*", s)
        if not m:
            break
        s = s[m.end():]
    # 再去掉开头无意义的序号前缀文字（“第2题：”之类）
    m = re.match(r"^第\s*\d+\s*题?[：:、\s]*", s)
    if m:
        s = s[m.end():]
    return s.strip()


def _pick_ctx(d):
    """从近到远找第一个内容足够的容器文字作为上下文。"""
    ctxs = d.get("ctxs") or []
    best = ""
    for t in ctxs:
        if len(t) >= 6:
            best = t
            break
    if len(best) < 15:
        for t in ctxs:
            if len(t) >= 15:
                best = t
                break
    return _clean_noise(best) or "(无上下文)"


def _clean_stem(opts):
    """组题干：从近到远逐层扣除选项文字，取第一个非空结果。"""
    ctxs = (opts[0].get("ctxs") or []) if opts else []
    for t in ctxs:
        s = t
        for o in opts:
            ot = (o.get("opt") or "").strip()
            if len(ot) >= 2:
                s = s.replace(ot, " ")
        s = collapse(s, 400)
        s = _trim_lead(s)
        s = _clean_noise(s)
        if len(s) >= 3:
            return s
    return STEM_UNKNOWN


def to_items(raws):
    """把 collect_raw 的结果转成模型可读的题目列表。"""
    items = []
    for fi, fr in enumerate(raws):
        data = fr["data"]
        body = collapse(data.get("bodyText", ""), 800)
        fallback = (f"(该空附近无可见文字，页面整体文字如下：{body})"
                    if body else "(无上下文)")
        # ---- 选择题：优先按“题目容器”分组；无则退回 name 分组 ----
        groups, order = {}, []
        for r in data.get("radios", []):
            key = r.get("gk") or r.get("name") or f"__auto_{r['i']}"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)
        # solo 容器里的单选项：尝试用 name 再合并（老平台的同名分组）
        merged = {}
        for k, v in groups.items():
            if k == "solo" and v:
                byname = {}
                for r in v:
                    nk = r.get("name") or f"__auto_{r['i']}"
                    byname.setdefault(nk, []).append(r)
                for nk2, v2 in byname.items():
                    if nk2 not in merged:
                        merged[nk2] = []
                    merged[nk2] += v2
            else:
                if k not in merged:
                    merged[k] = []
                merged[k] += v
        groups, order = merged, list(merged.keys())
        for gi0, key in enumerate(order):
            opts = groups[key]
            if len(opts) > 30:  # 兜底：整页共用一个容器时按单选项拆分
                for o in opts:
                    items.append({
                        "id": f"choice-{fi}-{gi0}-{o['i']}", "kind": "single",
                        "stem": _pick_ctx(o), "frame": fi,
                        "options": [{"gi": o["i"], "text": o.get("opt") or f"(选项{o['i']})"}],
                    })
                continue
            kind = "multi" if any(o["type"] == "checkbox" for o in opts) else "single"
            stem = _noise_unknown(_clean_stem(opts))
            if _is_chrome_control(stem):
                continue   # 筛选栏等非题目选择控件
            # 只有 1 个选项的“多选”且题干未知 → 基本是筛选/装饰控件，硬性丢弃
            if kind == "multi" and len(opts) == 1:
                one_txt = (opts[0].get("text") or opts[0].get("opt") or "")
                if stem == STEM_UNKNOWN or _is_chrome_control(one_txt):
                    continue
            items.append({
                "id": f"choice-{fi}-{gi0}", "kind": kind, "stem": stem, "frame": fi,
                "options": [{"gi": o["i"], "text": o.get("opt") or f"(选项{o['i']})"} for o in opts],
            })
        # ---- 填空题 ----
        for t in data.get("texts", []):
            if t.get("disabled"):
                continue
            stem = _pick_ctx(t)
            if stem == "(无上下文)":
                stem = fallback
            if _is_chrome_control(stem):
                continue   # 列表页筛选/工具栏控件，不是题目空，跳过
            items.append({
                "id": f"fill-{fi}-{t['i']}", "kind": "fill",
                "stem": stem,
                "frame": fi, "idx": t["i"],
            })
        # ---- textarea / contenteditable ----
        for a in data.get("areas", []):
            if a.get("disabled"):
                continue
            kind = "essay" if (a.get("rows") or 3) >= 8 else "open"
            stem = _pick_ctx(a)
            if stem == "(无上下文)":
                stem = fallback
            items.append({
                "id": f"area-{fi}-{a['i']}", "kind": kind,
                "stem": stem,
                "frame": fi, "idx": a["i"], "ce": a.get("ce", False), "rows": a.get("rows", 3),
            })
        # ---- 下拉 ----
        for s in data.get("selects", []):
            if s.get("disabled"):
                continue
            stem = _pick_ctx(s)
            if stem == "(无上下文)":
                stem = fallback
            items.append({
                "id": f"select-{fi}-{s['i']}", "kind": "select",
                "stem": stem,
                "frame": fi, "idx": s["i"],
                "options": [{"gi": k, "text": t} for k, t in enumerate(s.get("opts", []))],
            })
    return items


def summarize(items):
    from collections import Counter
    c = Counter(it["kind"] for it in items)
    return dict(c)


_CHROME_TOKENS = ("作答状态", "发布时间", "正序", "倒序", "重置", "仅查看计入考核",
                 "搜索", "筛选", "请输入", "全部状态", "页码", "上一页", "下一页",
                 "条记录", "每页显示")


def _is_chrome_control(stem):
    """判断填空上下文是否只是列表页筛选/工具栏控件（而非真实题目空）。"""
    s = stem or ""
    return any(tok in s for tok in _CHROME_TOKENS) and len(s) <= 80


def _noise_unknown(stem):
    """列表/状态类短噪声题干标记为“未知”，交由跳过策略处理。"""
    s = (stem or "").strip()
    if 0 < len(s) <= 14 and any(tok in s for tok in ("已完成", "未完成", "已交", "未交",
                                                     "0/", "搜索", "筛选")):
        return STEM_UNKNOWN
    return s


def build_gen_items(raws):
    """通用“选项行”页（选项是文字 A./B.… + onclick 的自定义控件，无 input/answerBg）。"""
    items = []
    for fi, fr in enumerate(raws):
        opts_raw = fr["data"].get("genOpts") or []
        if not opts_raw:
            continue
        groups, order = {}, []
        for g in opts_raw:
            k = g.get("key") or "g-solo"
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(g)
        for gi0, key in enumerate(order):
            g = sorted(groups[key], key=lambda x: (x.get("letter") or "Z"))
            if len(g) < 2:
                continue
            first = g[0]
            ctxs = first.get("ctxs") or []
            multi = any(("多选" in x or "不定项" in x or "多项" in x) for x in ctxs[:6])
            stem = ""
            for t in ctxs:
                s = t
                for o in g:
                    ot = (o.get("text") or "").strip()
                    if len(ot) >= 2:
                        s = s.replace(ot, " ")
                s = collapse(s, 500)
                s = _trim_lead(s)
                s = _clean_noise(s)
                if len(s) >= 3:
                    stem = s
                    break
            if _is_chrome_control(stem):
                continue
            options = [{"gi": k, "text": (o.get("text") or "")[:220],
                        "letter": o.get("letter") or ""} for k, o in enumerate(g)]
            items.append({
                "id": f"gen-{fi}-{gi0}",
                "kind": "multi" if multi else "single",
                "stem": stem, "frame": fi, "genopts": True, "options": options,
            })
    return items


def build_block_items(raws):
    """把“点击型选项块”(class 含 answerBg, role=radio/checkbox, 无 input)组装成题目。

    兼容学习通/超星这类页面：<div class="answerBg singleoption" onclick="addChoice(this)">
      <span qid=.. class=..>A</span><div class="answer_p"><p>选项内容</p></div></div>
    """
    items = []
    for fi, fr in enumerate(raws):
        blocks = fr["data"].get("choiceBlocks") or []
        if not blocks:
            continue
        groups, order = {}, []
        for b in blocks:
            key = b.get("qid") or (b.get("letter", "?") + "|" + (b.get("content", "")[:12]))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(b)
        for gi0, key in enumerate(order):
            opts = sorted(groups[key], key=lambda x: (x.get("letter") or "Z"))
            if not opts:
                continue
            kind = "multi" if any((b.get("role") or "") == "checkbox" for b in opts) else "single"
            # 题干：取首个选项容器向上最近的有意义文本，并扣除选项内容
            ctxs = (opts[0].get("ctxs") or []) if opts else []
            stem = ""
            for t in ctxs:
                s = t
                for o in opts:
                    c = (o.get("content") or "").strip()
                    if len(c) >= 2:
                        s = s.replace(c, " ")
                s = collapse(s, 400)
                s = re.sub(r"^[\s\d#.\-、:：;；,，]*", "", s).strip()
                s = _clean_noise(s)
                if len(s) >= 3:
                    stem = s
                    break
            opts_list = []
            for k, o in enumerate(opts):
                letter = (o.get("letter") or "?")
                content = (o.get("content") or "").strip()
                opts_list.append({"gi": k, "text": f"{letter}. {content}".strip(),
                                  "letter": letter})
            if not opts_list:
                continue
            item = {
                "id": f"block-{fi}-{gi0}", "kind": kind, "stem": stem,
                "frame": fi, "qid": key, "block": True, "options": opts_list,
            }
            items.append(item)
    return items


def letter_bank_info(items):
    """检测“词库选词页”：整页都是填空，题干带 A–J 词库。

    返回 {'bank': 词库文本, 'sentences': 按顺序的句子列表, 'fills': 填空项}
    无法识别时返回 None。
    """
    fills = [it for it in items if it["kind"] == "fill"]
    if len(fills) < 5 or len(fills) != len(items):
        return None
    stem = fills[0].get("stem") or ""
    starts = [m.end() for m in re.finditer(r"\bA\s*[)）]", stem)]
    ends = [m.end() for m in re.finditer(r"\bJ\s*[)）]", stem)]
    if not starts or not ends:
        return None
    bank = collapse(stem[starts[0] - 1: ends[-1]], 800)
    tail = stem[ends[-1]:]
    m2 = re.search(r"[;；]\s*(?=[A-Za-z])", tail)
    sentences_raw = tail[m2.end():] if m2 else tail.lstrip(";； ,，")
    sentences_raw = re.sub(r"^[\s\d#.\-、:：]*", "", sentences_raw)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“])", sentences_raw) if p.strip()]
    n = len(fills)
    sentences = parts[:n]
    if len(parts) < n:
        sentences = parts + ["".join(parts[n:])] * (n - len(parts)) if parts else [""] * n
    elif len(parts) > n:
        sentences = parts[:n]
    if not sentences or not bank:
        return None
    return {"bank": bank, "sentences": sentences, "fills": fills}

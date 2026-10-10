# -*- coding: utf-8 -*-
"""回填器：把模型给出的答案点/填进页面控件。

由于读题和回填之间页面没有刷新，控件下标仍然有效；个别控件在
回填后被前端隐藏/重建导致下标失效，此时会捕获异常并记录日志，
不影响其余题目。
"""
from .reader import SELECTORS

RADIO_CSS = SELECTORS["choice"]
TEXT_CSS = SELECTORS["text"]
AREA_CSS = SELECTORS["area"] + ", " + SELECTORS["ce"]
SELECT_CSS = SELECTORS["select"]


def _click_choice(loc, want_checked=True):
    """兼容隐藏 input：优先点击可见的包裹元素触发框架事件，再校正勾选状态。"""
    try:
        loc.evaluate(
            """(el) => {
                let n = el;
                while (n && n !== document.body) {
                    if (n.tagName && ['LABEL','LI','DIV','SPAN','A'].indexOf(n.tagName) >= 0 &&
                        n.getClientRects().length > 0) {
                        n.click();
                        return;
                    }
                    n = n.parentElement;
                }
            }"""
        )
    except Exception:
        pass
    # 强制置为选中（兼容隐藏 input / div 型选项），再派发事件
    try:
        loc.evaluate(
            """(el) => {
                if (!el.checked) {
                    el.checked = true;
                    ['click', 'change', 'input'].forEach(t =>
                        el.dispatchEvent(new Event(t, {bubbles: true})));
                }
            }"""
        )
    except Exception:
        pass
    try:
        if loc.is_checked() is not want_checked:
            loc.check(force=True, timeout=3000)
    except Exception:
        pass


def _click_block(fr, qid, letter):
    """点击学习通式选项块（按 qid+字母定位 span，再点父级 answerBg）。"""
    try:
        fr.evaluate(
            """(args) => {
                const [qid, letter] = args;
                const els = Array.from(document.querySelectorAll(
                    'span[class*="addChoice"], span[class*="num_option"]'))
                    .filter(s => /^[A-H]$/.test((s.textContent || '').trim()))
                    .sort((a, b) => (a.textContent || '') < (b.textContent || '') ? -1 : 1);
                let sp = null;
                if (qid) sp = els.find(s => (s.getAttribute('qid') || '') === qid
                                          && (s.textContent || '').trim() === letter);
                if (!sp) sp = els.find(s => (s.textContent || '').trim() === letter);
                if (sp) {
                    const bg = sp.closest('[class*="answerBg"]') || sp.parentElement;
                    if (bg) { bg.click(); bg.focus && bg.focus(); }
                }
            }""",
            [qid or "", letter],
        )
    except Exception:
        pass


def _click_gen_option(fr, letter):
    """点击“通用选项行”（文字 A. xxx，onclick 在自身或祖先上）。"""
    try:
        fr.evaluate(
            """(letter) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const pat = new RegExp('^' + letter + '[.、．)）]\\\\s');
              const targets = [];
              document.querySelectorAll('div,li,section,p,span').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) return;
                const t = clean(el.innerText || '');
                if (!pat.test(t) || t.length > 240) return;
                const pe = el.parentElement;
                if (pe && clean(pe.innerText || '') === t) return;
                targets.push(el);
              });
              for (const el of targets) {
                let n = el, d = 0;
                while (n && d < 5) {
                  if (n.getAttribute && n.getAttribute('onclick')) { n.click(); return; }
                  n = n.parentElement; d++;
                }
              }
              if (targets.length) targets[0].click();
            }""",
            letter,
        )
    except Exception:
        pass


def _fill_input(loc, text, timeout=6000):
    try:
        loc.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass
    try:
        loc.fill(str(text), timeout=timeout)
    except Exception:
        # 可能是 contenteditable/只读等，走 JS 赋值
        loc.evaluate(
            """(el, t) => {
                el.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value');
                if (setter && setter.set && el.tagName === 'INPUT') setter.set.call(el, t);
                else el.textContent = t;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
            str(text),
        )


def _parse_multi(value, n_opts):
    if isinstance(value, (list, tuple)):
        idxs = [int(v) for v in value]
    else:
        idxs = [int(v.strip()) for v in str(value).split(",") if v.strip() != ""]
    return [i for i in idxs if 0 <= i < n_opts]


def apply_answers(page, items, answers, log=print):
    """items 与 answers(字典) 对应；返回失败列表 [(item_id, 原因)]。"""
    frames = [f for f in page.frames]
    failed = []
    for it in items:
        aid = it["id"]
        value = answers.get(aid)
        if value is None or value == "":
            log(f"  ⚠ {aid} 无答案，跳过")
            failed.append((aid, "no answer"))
            continue
        fi = it.get("frame", 0)
        if fi >= len(frames):
            failed.append((aid, "frame lost"))
            continue
        fr = frames[fi]
        kind = it["kind"]
        try:
            if kind in ("single", "select"):
                v = int(str(value))
                opts = it.get("options") or []
                if not (0 <= v < len(opts)):
                    failed.append((aid, f"选项下标越界:{v}"))
                    continue
                gi = opts[v]["gi"]
                if it.get("block"):   # 点击型选项块（学习通/超星）
                    _click_block(fr, it.get("qid", ""), opts[v].get("letter", ""))
                elif it.get("genopts"):
                    _click_gen_option(fr, opts[v].get("letter", ""))
                elif kind == "single":
                    _click_choice(fr.locator(RADIO_CSS).nth(gi))
                else:
                    fr.locator(SELECT_CSS).nth(it["idx"]).select_option(
                        label=opts[v]["text"], timeout=5000
                    )
                log(f"  ✅ {aid} 已选 选项[{v}]")
            elif kind == "multi":
                sel = _parse_multi(value, len(it.get("options") or []))
                if not it.get("block"):
                    # 先清除该题其余勾选，避免旧的全选残留
                    wanted = set(sel)
                    for k, o in enumerate(it["options"]):
                        if k in wanted:
                            continue
                        loc = fr.locator(RADIO_CSS).nth(o["gi"])
                        try:
                            if loc.is_checked():
                                loc.uncheck(force=True)
                        except Exception:
                            pass
                for v in sel:
                    gi = it["options"][v]["gi"]
                    if it.get("block"):
                        _click_block(fr, it.get("qid", ""),
                                     it["options"][v].get("letter", ""))
                    elif it.get("genopts"):
                        _click_gen_option(fr, it["options"][v].get("letter", ""))
                    else:
                        _click_choice(fr.locator(RADIO_CSS).nth(gi))
                log(f"  ✅ {aid} 已选 {value}")
                total = len(it.get("options") or [])
                if sel and total >= 3 and len(sel) == total:
                    log(f"  ⚠ {aid} 选择了全部 {total} 个选项——"
                        f"若该多选并非“全选”题，请人工核对/取消误选", "warn")
            elif kind == "fill":
                _fill_input(fr.locator(TEXT_CSS).nth(it["idx"]), value)
                log(f"  ✅ {aid} 已填入: {str(value)[:60]}")
            elif kind in ("open", "essay"):
                loc = fr.locator(AREA_CSS).nth(it["idx"])
                if it.get("ce"):
                    loc.click(timeout=3000)
                    _fill_input(loc, value)
                else:
                    _fill_input(loc, value)
                log(f"  ✅ {aid} 已写入({kind}): {str(value)[:50]}…")
            else:
                failed.append((aid, f"unknown kind {kind}"))
        except Exception as e:  # noqa: BLE001
            failed.append((aid, f"{type(e).__name__}: {e}"))
            log(f"  ❌ {aid} 回填失败: {e}")
    return failed


def verify_answers(page, items, answers):
    """回读校验：输入型题检查是否真正选中/填入。返回未生效的 [(id, 说明)]。

    点击型选项块(block)无法可靠读取选中标记，跳过（由人工确认）。
    """
    frames = [f for f in page.frames]
    bad = []
    for it in items:
        aid = it["id"]
        value = answers.get(aid)
        if value in (None, ""):
            continue
        if it.get("block"):
            continue
        fi = it.get("frame", 0)
        if fi >= len(frames):
            continue
        fr = frames[fi]
        kind = it["kind"]
        try:
            if kind in ("single", "multi"):
                idxs = ([int(str(value))] if kind == "single"
                        else _parse_multi(value, len(it.get("options") or [])))
                opts = it.get("options") or []
                for k in idxs:
                    if not (0 <= k < len(opts)):
                        bad.append((aid, "下标越界"))
                        break
                    gi = opts[k]["gi"]
                    if not fr.locator(RADIO_CSS).nth(gi).is_checked():
                        bad.append((aid, "未选中"))
                        break
            elif kind == "fill":
                got = (fr.locator(TEXT_CSS).nth(it["idx"]).input_value() or "").strip()
                if got != str(value).strip():
                    bad.append((aid, f"值={got!r}"))
            elif kind in ("open", "essay"):
                got = (fr.locator(AREA_CSS).nth(it["idx"]).input_value() or "").strip()
                want = str(value).strip()
                if got != want and not got.startswith(want[:30]):
                    bad.append((aid, "内容不符"))
        except Exception:
            pass
    return bad

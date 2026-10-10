# -*- coding: utf-8 -*-
"""答题流程控制器：run(逐页自动答题) 与 dump_probe(探查) 的单一实现，
供命令行(main.py)与图形界面(ui.py)共用。"""
import time

from . import util
from . import nav, reader, llm, filler


def _has_real_question(items):
    """判断识别结果里是否有“真题目”（多选项≥2、或题干非未知的填空/问答/下拉）。"""
    for it in items:
        if len(it.get("options") or []) >= 2:
            return True
        stem = it.get("stem") or ""
        if it["kind"] in ("fill", "open", "essay", "select") \
                and stem and stem not in (reader.STEM_UNKNOWN, "(无上下文)"):
            return True
    return False


def _annotate_fill_positions(items):
    """连续且题干相同的填空，标注“本句连续 n 空，本空第 k 个”，避免模型重复填同一内容。"""
    out = []
    i, n = 0, len(items)
    while i < n:
        if items[i]["kind"] == "fill":
            j = i
            while (j + 1 < n and items[j + 1]["kind"] == "fill"
                   and items[j + 1].get("stem") == items[i].get("stem")):
                j += 1
            cnt = j - i + 1
            if cnt > 1:
                for k in range(i, j + 1):
                    it = dict(items[k])
                    it["stem"] = (it["stem"]
                                  + f"（本句连续挖 {cnt} 个空，本空为其中第 {k - i + 1} 个，"
                                    "请只填本空答案，勿重复整句内容）")
                    out.append(it)
            else:
                out.append(items[i])
            i = j + 1
        else:
            out.append(items[i])
            i += 1
    return out


class Runner:
    def __init__(self, page, cfg, root, log=None, progress=None, stop=None, gate=None):
        self.page = page          # 已连接的页面(答题页)
        self.cfg = cfg
        self.root = root          # 项目根目录 Path
        self.log = log or (lambda msg, tag="info": None)
        self.progress = progress or (lambda page_no, stage, info: None)
        self.stop = stop          # threading.Event 或 None
        self.gate = gate          # threading.Event：逐题确认模式下每答完一题等待 set()
        self.out_dir = None
        self._cap_resps = []
        self._cap_attached = False

    def _report_capture(self, page_no):
        """把最近一次抓到的题目接口报文文本展示到日志（供阅读/解析题干）。"""
        if not self._cap_resps:
            return
        import re as _re
        resp = self._cap_resps[-1]
        try:
            txt = resp.text()
        except Exception:
            return
        body = _re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", txt)
        body = _re.sub(r"<[^>]+>", " ", body)
        vis = util.collapse(body, 700)
        if vis:
            self.log(f"📦[抓包] 第{page_no}页接口文本(题干片段): {vis[:550]}", "data")

    def run(self):
        cfg = self.cfg
        out_dir = util.ts_dir(self.root / "out", "run")
        self.out_dir = out_dir
        page_no = 0
        empty_run = 0
        max_pages = int(cfg.get("max_pages", 100))
        settle = float(cfg.get("page_settle_ms", 1500)) / 1000.0
        skipped_total = 0
        if cfg.get("answer_mode") == "capture":
            def _on_resp(resp):
                try:
                    url = resp.url or ""
                    if "chaoxing" in url and "getTheNextQuestion" in url:
                        self._cap_resps.append(resp)
                        if len(self._cap_resps) > 8:
                            self._cap_resps.pop(0)
                except Exception:
                    pass
            try:
                self.page.on("response", _on_resp)
                self.log("📡 抓包模式：已监听题目接口，每次翻页自动截取报文…", "sys")
            except Exception as e:
                self.log(f"抓包监听失败: {e}", "warn")
        while True:
            if self.stop is not None and self.stop.is_set():
                self.log("⏹ 已手动停止。", "warn")
                break
            page_no += 1
            if page_no > max_pages:
                self.log(f"达到最大翻页数 {max_pages}，停止。", "warn")
                break
            time.sleep(settle)
            self.progress(page_no, 0, "读取页面")
            # 轮询等待真实题目渲染（避免翻页后页面尚未出题就误判为空）
            items, raws = [], None
            for _try in range(6):
                raws = reader.collect_raw(self.page)
                items = reader.to_items(raws)
                if not items:
                    items = reader.build_block_items(raws)
                if not items:
                    items = reader.build_gen_items(raws)
                if _has_real_question(items):
                    break
                time.sleep(0.8)
            self._report_capture(page_no)
            if not items:
                # OCR 兜底：第一次“读不到题”时，若开启了截图OCR且配了视觉模型，先截图识别展示
                if empty_run == 0 and cfg.get("vision", {}).get("enabled") \
                        and cfg.get("vision", {}).get("base_url"):
                    try:
                        png = self.page.screenshot(type="png")
                        info = llm.ocr_page(cfg.get("vision", {}), png)
                        qs = info.get("questions") or []
                        self.log(f"🧪 OCR 兜底：识别到 {len(qs)} 道(图片/特殊渲染)题目 → 用文字模型作答：", "sys")
                        if qs:
                            ans = llm.answer_ocr_questions(cfg.get("llm", {}), info)
                            for q in qs:
                                no = q.get("no")
                                line = f"    题{no} [{q.get('type', '?')}] {str(q.get('text'))[:90]}"
                                if q.get("options"):
                                    line += " | 选项: " + "; ".join(str(o)[:50] for o in q.get("options"))
                                if no is not None and str(no) in ans:
                                    line += f"  → 参考: {str(ans[str(no)])[:80]}"
                                self.log(line)
                        else:
                            self.log("    (OCR 未识别出题目，截图内容以日志为准)", "sys")
                        self.log("    ↑ OCR 兜底仅作参考/人工录入；图片型题目暂不自动点击。", "warn")
                    except Exception as e:
                        self.log(f"  OCR 兜底失败: {e}", "warn")
                empty_run += 1
                if empty_run >= 4:
                    self.log("连续 4 页都没有可作答控件——可能不在答题页上。"
                             "请确认浏览器当前显示的是真正的题目页（有选项/输入框），再点「开始答题」。", "warn")
                    break
                self.log(f"[第{page_no}页] 没有找到可作答控件 → 尝试翻页一次…({empty_run}/4)")
                ok, kw = nav.click_action(self.page, cfg.get("next_keywords", []))
                if not ok:
                    self.log("没有翻页按钮：流程结束，或当前不是题目页。", "warn")
                    break
                continue
            empty_run = 0
            self.log(f"[第{page_no}页] 发现题目: {reader.summarize(items)}")
            util.dump_json(out_dir / f"page{page_no}_questions.json", items)

            # ---- 词库选词页专用通道（整页 A–J 词库填空，按字母作答）----
            if cfg.get("bank_letter_mode", True):
                info = reader.letter_bank_info(items)
                if info:
                    self.log(f"  ✒ 检测到词库选词页(A–J 词库 + {len(info['fills'])} 空) → 按字母作答。", "info")
                    try:
                        letters = llm.ask_letter_bank(cfg.get("llm", {}), info["bank"], info["sentences"])
                    except Exception as e:
                        self.log(f"  词库作答失败: {e}", "error")
                        letters = []
                    if letters:
                        ans = {it["id"]: ch for it, ch in zip(info["fills"], letters)}
                        util.dump_json(out_dir / f"page{page_no}_answers.json", ans)
                        for it, ch in zip(info["fills"], letters):
                            self.log(f"  → {it['id']} [{ch}]")
                        self.progress(page_no, 2, "回填字母")
                        if not cfg.get("dry_run", False):
                            filler.apply_answers(self.page, info["fills"], ans,
                                                 log=lambda m: self.log(m))
                    ok, kw = nav.click_action(self.page, cfg.get("next_keywords", []))
                    if not ok:
                        self.log("[结束] 未找到翻页按钮——这通常是最后一页，答题已完成。")
                        break
                    self.log(f"→ 已点击「{kw}」，继续下一页…")
                    continue

            doable, skipped = [], []
            if cfg.get("skip_unknown_stem", True):
                for it in items:
                    if it["kind"] in ("single", "multi") and it.get("stem") == reader.STEM_UNKNOWN:
                        skipped.append(it)
                    else:
                        doable.append(it)
            else:
                doable = items
            if skipped:
                skipped_total += len(skipped)
                self.log(f"  ⏭ 跳过 {len(skipped)} 道无题干题(多为听力): {[s['id'] for s in skipped]}", "warn")
            if not doable:
                self.log("  本页没有可自动作答的题 → 翻页")
                ok, kw = nav.click_action(self.page, cfg.get("next_keywords", []))
                if not ok:
                    self.log("[结束] 没有翻页按钮。")
                    break
                continue
            self.progress(page_no, 1, "DeepSeek 生成答案…")
            self.log("调用 DeepSeek 生成答案…")
            doable = _annotate_fill_positions(doable)  # 相同题干的连续空标注第几空
            ans = llm.ask_answers(cfg.get("llm", {}), doable)
            util.dump_json(out_dir / f"page{page_no}_answers.json", ans)
            for it in doable:
                v = ans.get(it["id"])
                preview = str(v)[:60] if v not in (None, "") else "(空)"
                self.log(f"  → {it['id']} [{it['kind']}] {preview}")
            self.progress(page_no, 2, "回填答案")
            if cfg.get("dry_run", False):
                self.log("  🧪 探针模式：只生成答案，不填写页面。", "sys")
            else:
                failed = filler.apply_answers(self.page, doable, ans, log=lambda m: self.log(m))
                if failed:
                    self.log(f"  有 {len(failed)} 项回填失败（跳过）: {failed}", "warn")
                # ---- 检查行为：回读校验，未生效自动重试一次 ----
                if cfg.get("verify_fill", True):
                    try:
                        time.sleep(0.3)
                        verifiable = [it for it in doable if not it.get("block")]
                        block_n = len(doable) - len(verifiable)
                        bad = filler.verify_answers(self.page, doable, ans)
                        if bad:
                            bad_ids = {x[0] for x in bad}
                            self.log(f"  检查发现 {len(bad)} 项未生效 → 自动重试一次: "
                                     f"{[x[0] for x in bad]}", "warn")
                            subm = {k: v for k, v in ans.items() if k in bad_ids}
                            items2 = [it for it in verifiable if it["id"] in bad_ids]
                            if items2:
                                filler.apply_answers(
                                    self.page, items2, subm,
                                    log=lambda m: self.log("   [重试] " + m, "warn"))
                                time.sleep(0.2)
                            bad2 = filler.verify_answers(self.page, verifiable, ans)
                            if bad2:
                                self.log(f"  ❌ 检查：仍有 {len(bad2)} 项未生效，请人工处理: {bad2}", "error")
                            else:
                                self.log("  ✅ 检查：重试后全部生效", "ok")
                        elif verifiable:
                            self.log(f"  ✅ 检查：{len(verifiable)} 项已回读确认生效"
                                     + (f"；另有 {block_n} 项块选项无法回读，请肉眼确认" if block_n else ""), "ok")
                    except Exception as e:
                        self.log(f"  校验过程异常(已忽略): {e}", "warn")
            # 逐题确认模式：等待用户放行
            if self.gate is not None:
                self.log("⏸ 已暂停（逐题确认模式），点「开始答题/继续」作答下一题…", "sys")
                while not self.gate.is_set():
                    if self.stop is not None and self.stop.is_set():
                        break
                    time.sleep(0.2)
                self.gate.clear()
                if self.stop is not None and self.stop.is_set():
                    self.log("⏹ 已手动停止。", "warn")
                    break
            if self.stop is not None and self.stop.is_set():
                self.log("⏹ 已手动停止。", "warn")
                break
            ok, kw = nav.click_action(self.page, cfg.get("next_keywords", []))
            if not ok:
                self.log("[结束] 未找到翻页按钮——这通常是最后一页，答题已完成。")
                break
            self.log(f"→ 已点击「{kw}」，继续下一页…")
        self.progress(page_no, 3, "完成")
        if cfg.get("auto_submit"):
            ok, kw = nav.click_action(self.page, cfg.get("submit_keywords", []))
            self.log(
                f"→ 自动提交：点击「{kw}」{'成功' if ok else '失败(未找到按钮)，请手动提交'}",
                "ok" if ok else "warn",
            )
        else:
            self.log("⚠ 默认不自动提交。请人工检查后手动点「交卷」。", "warn")
        self.log(f"答题记录目录: {out_dir}")
        return {"pages": page_no, "skipped": skipped_total, "out_dir": str(out_dir)}


def dump_probe(page, cfg, root, log=None):
    """探查当前页：导出结构 JSON + 截图。"""
    log = log or (lambda msg, tag="info": None)
    raws = reader.collect_raw(page)
    items = reader.to_items(raws)
    out_dir = util.ts_dir(root / "out", "probe")
    util.dump_json(out_dir / "raw_frames.json", raws)
    util.dump_json(out_dir / "items.json", items)
    try:
        page.screenshot(path=str(out_dir / "page.png"), full_page=True)
    except Exception:
        try:
            page.screenshot(path=str(out_dir / "page.png"))
        except Exception:
            pass
    log(f"页面 URL: {page.url}")
    log(f"识别到题目: {reader.summarize(items)}")
    for it in items[:12]:
        log(f"  - [{it['kind']}] {it['stem'][:80]}")
    log(f"已保存: {out_dir}", "ok")
    return items

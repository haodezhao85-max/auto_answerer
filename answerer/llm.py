# -*- coding: utf-8 -*-
"""大模型答案生成器：调用 DeepSeek(OpenAI 兼容) 接口，要求返回严格 JSON。

value 约定：
  单选题/判断/下拉 -> 选项下标字符串，如 "2"
  多选题           -> 下标数组或逗号分隔串，如 [0,2]
  填空/问答/作文   -> 填写的文本字符串
"""
import json
import os
import time

from openai import OpenAI

from .reader import KIND_CN

SYSTEM = (
    "你是一个网页测验自动答题引擎。只返回一个 JSON 对象，禁止输出任何解释、前后缀或 Markdown。\n"
    'JSON 格式: {"answers": [{"id": "题目id", "value": 答案}]}\n'
    "- 单选题/判断题/下拉题：value 为所选选项的下标字符串，下标从 0 开始，如 \"2\"；\n"
    '- 多选题：value 为下标数组，如 [0, 2]；只选有把握正确且确满足题意的项，'
    "除非题目明确要求“全选”，否则不要全选；\n"
    "- 填空题：value 为要填入的文本；上下文句子里的空格即待填位置，请结合全句与常识作答；\n"
    "- 问答题：value 为简要完整的作答文本；\n"
    "- 翻译题：若题干是待翻译的句子/短文（含括号指定的必用词），value 只输出译文本身"
    "（按要求的目标语言，通常中文译英文，且必须用上括号里指定的单词/短语），不要附加解释；\n"
    "- 作文题：value 为写好的整篇文章。英文作文若未规定词数请写 120~220 词，结构完整、语言地道；中文作文按要求字数。\n"
    "- 必须为列表中的每一道题都给出 answer，id 原样返回，不要漏题、不要改 id。\n"
    "- 依据题干与上下文作答；信息不足时给出最合理的推断，不要空答。\n"
)


def _need_key(cfg_llm):
    env_name = cfg_llm.get("api_key_env", "DEEPSEEK_API_KEY")
    key = (os.environ.get(env_name) or "").strip()
    if not key:
        raise RuntimeError(
            f"未找到 API Key（环境变量 {env_name}）。请在项目目录执行："
            "复制 .env.example 为 .env 并填入你的 DeepSeek Key。"
        )
    return key


def _render_item(idx, it):
    lines = [f"[{idx}] (id={it['id']}) 题型：{KIND_CN.get(it['kind'], it['kind'])}"]
    lines.append(f"题干/上下文：{it.get('stem') or '(无)'}")
    opts = it.get("options")
    if opts:
        lines.append("选项：")
        lines += [f"  {k}. {o['text'][:120]}" for k, o in enumerate(opts)]
    return "\n".join(lines)


def _messages(items, retry_hint=""):
    user = [f"共 {len(items)} 题，逐题作答：\n"]
    user += [_render_item(i + 1, it) for i, it in enumerate(items)]
    msg = [{"role": "system", "content": SYSTEM}]
    if retry_hint:
        msg.append({"role": "user", "content": "上一轮输出不合法：" + retry_hint})
    msg.append({"role": "user", "content": "\n\n".join(user)})
    return msg


def _parse(content):
    s = (content or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1]
        s = s.rsplit("```", 1)[0].strip()
    try:
        obj = json.loads(s)
    except Exception:
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b <= a:
            raise ValueError("模型没有返回 JSON")
        obj = json.loads(s[a:b + 1])
    if isinstance(obj, dict):
        arr = obj.get("answers", obj)
    else:
        arr = obj
    if isinstance(arr, dict):
        arr = [arr]
    out = {}
    for x in arr:
        if isinstance(x, dict) and "id" in x and "value" in x:
            out[str(x["id"])] = x["value"]
    return out


def _ask_once(cfg_llm, items, retry_hint=""):
    key = _need_key(cfg_llm)
    client = OpenAI(
        api_key=key,
        base_url=cfg_llm.get("base_url", "https://api.deepseek.com"),
        timeout=cfg_llm.get("timeout", 120),
    )
    kwargs = dict(
        model=cfg_llm.get("model", "deepseek-chat"),
        messages=_messages(items, retry_hint),
        temperature=cfg_llm.get("temperature", 0.2),
    )
    # DeepSeek 支持 json_object 模式；个别网关不支持时降级为普通输出再解析
    try:
        resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    except Exception:
        resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    return _parse(content)


def ask_letter_bank(cfg_llm, bank, sentences):
    """词库选词页：给定 A–J 词库与按序句子，返回每个句子对应的大写字母列表。"""
    import json as _json

    key = _need_key(cfg_llm)
    client = OpenAI(
        api_key=key,
        base_url=cfg_llm.get("base_url", "https://api.deepseek.com"),
        timeout=cfg_llm.get("timeout", 120),
    )
    n = len(sentences)
    system = (
        "你是网页测验答题引擎。只返回一个 JSON 对象，不要输出任何其他文字。\n"
        '格式：{"letters": ["E", "G", ...]}，letters 数组长度必须等于句子数量。\n'
        "- 词库为 A)–J) 共 10 条释义（也可是英文词条）；\n"
        "- 每个句子对应词库中的一个词（句子中已出现该词或可由句意推断）；\n"
        "- 判断每句与词库哪一条最匹配，输出该条的大写字母（A–J 之一）；\n"
        "- letters 顺序与句子 1..n 一一对应，禁止重复说明文字。\n"
    )
    user = f"词库：\n{bank}\n\n句子：\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    last_err = ""
    retries = int(cfg_llm.get("max_retries", 2))
    for _ in range(retries + 1):
        msgs = [{"role": "system", "content": system}]
        if last_err:
            msgs.append({"role": "user", "content": "上次输出不合法：" + last_err})
        msgs.append({"role": "user", "content": user})
        kwargs = dict(model=cfg_llm.get("model", "deepseek-chat"), messages=msgs,
                      temperature=cfg_llm.get("temperature", 0.2))
        try:
            resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception:
            resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        try:
            obj = _json.loads(content)
            arr = obj.get("letters") if isinstance(obj, dict) else obj
            if not isinstance(arr, list) or len(arr) != n:
                raise ValueError(f"letters 数量 {len(arr) if isinstance(arr, list) else '?'} != {n}")
            out = [str(x).strip().upper() for x in arr]
            if not all(ch in "ABCDEFGHIJ" for ch in out):
                raise ValueError("存在非 A–J 的字母")
            return out
        except Exception as e:
            last_err = f"{e}；请严格按 JSON 格式输出恰好 {n} 个 A-J 大写字母。"
    raise RuntimeError(f"词库作答多次失败: {last_err}")


def test_connection(cfg_llm):
    """连通性检测：发一个最小请求，返回 (ok, 消息)。"""
    t0 = time.perf_counter()
    try:
        key = _need_key(cfg_llm)
    except Exception as e:
        return False, str(e)
    try:
        client = OpenAI(
            api_key=key,
            base_url=cfg_llm.get("base_url", "https://api.deepseek.com"),
            timeout=20,
        )
        r = client.chat.completions.create(
            model=cfg_llm.get("model", "deepseek-chat"),
            messages=[{"role": "user", "content": "只回复两个字母：OK"}],
            max_tokens=5,
            temperature=0,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        model = r.model or cfg_llm.get("model", "?")
        return True, f"连接成功（模型 {model}，延迟 {ms}ms）"
    except Exception as e:
        return False, f"连接失败: {e}"


def ask_answers(cfg_llm, items):
    """按批调用模型，返回 {item_id: value}。缺某题时会自动重试一次。"""
    chunk = int(cfg_llm.get("chunk_size", 25))
    retries = int(cfg_llm.get("max_retries", 2))
    answers = {}
    for start in range(0, len(items), chunk):
        part = items[start:start + chunk]
        got = None
        last_err = ""
        for attempt in range(retries + 1):
            try:
                got = _ask_once(cfg_llm, part, last_err)
                missing = [it["id"] for it in part if it["id"] not in got]
                if missing:
                    last_err = "漏掉了这些题的答案: " + ", ".join(missing)
                    got = None
                    continue
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"解析失败({e})，请严格按 JSON 格式重新输出全部题目。"
        if got is None:
            raise RuntimeError(f"第 {start // chunk + 1} 批题目经多次重试仍失败：{last_err}")
        answers.update(got)
    return answers


def _vision_client(cfg_vis):
    env_name = cfg_vis.get("api_key_env", "ZHIPU_API_KEY")
    key = (os.environ.get(env_name) or "").strip()
    if not key:
        raise RuntimeError(f"视觉模型 Key 缺失（环境变量 {env_name}）。")
    return OpenAI(
        api_key=key,
        base_url=cfg_vis.get("base_url", "https://open.bigmodel.cn/api/paas/v4"),
        timeout=cfg_vis.get("timeout", 90),
    )


def ocr_page(cfg_vis, image_png):
    """把整屏截图交给视觉模型，识别其中的题目，返回结构化信息。

    返回 {"text": ..., "questions": [{"no":1,"type":"single","text":"...","options":["A. ..."]}, ...]}
    """
    import base64 as _b64

    b64 = _b64.b64encode(image_png).decode("ascii")
    data_url = "data:image/png;base64," + b64
    client = _vision_client(cfg_vis)
    system = (
        "你是网页截图的OCR与题目识别助手。请识别图中所有题目并严格返回JSON：\n"
        '{"questions":[{"no":题目序号,"type":"single|multi|judge|fill|essay",'
        '"text":"题干","options":["选项文本(若可见)"],'
        '"answer_hint":"若图中自带提示/答案可见则填写，否则为空"}],'
        '"note":"其它说明"}\n'
        "不要遗漏题目；无法识别的选项留空；禁止编造。"
    )
    model = cfg_vis.get("model", "glm-4v-flash")
    last = None
    for _ in range(2):
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": "识别这张答题页面截图："},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
            temperature=0.1,
        )
        content = resp.choices[0].message.content or ""
        try:
            obj = json.loads(content)
            if not isinstance(obj.get("questions"), list):
                raise ValueError("缺少 questions 数组")
            return obj
        except Exception as e:
            last = e
    raise RuntimeError(f"OCR 解析失败: {last}")


def answer_ocr_questions(cfg_llm, ocr_info):
    """把 OCR 出的题目文本交给普通模型作答，返回 {题号: 答案}。"""
    qs = ocr_info.get("questions") or []
    items = []
    for idx, q in enumerate(qs):
        text = q.get("text") or ""
        opts = q.get("options") or []
        if opts and q.get("type") in ("single", "judge"):
            kind = "single"
        elif opts and q.get("type") == "multi":
            kind = "multi"
        else:
            kind = "open"
        items.append({
            "id": f"ocr-{idx}", "kind": kind, "stem": text,
            "options": [{"gi": k, "text": o} for k, o in enumerate(opts)] if opts else [],
        })
    if not items:
        return {}
    ans = ask_answers(cfg_llm, items)
    return {str(qs[i].get("no", i + 1)): ans[f"ocr-{i}"] for i in range(len(items))}

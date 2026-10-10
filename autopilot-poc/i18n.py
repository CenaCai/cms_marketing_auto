# -*- coding: utf-8 -*-
"""cockpit 极简 i18n：默认英文（en），可切换中文（zh）。

设计要点
--------
1. **单点收口**：全站页面都经 `cockpit._page()` 输出，这里提供 `translate_html()`
   在该出口做一次后处理翻译。因此不需要在 5000+ 行 cockpit.py 里逐处插入 t() 调用。
2. **整词精确匹配**：只替换「文本节点内容完全等于某个已知中文短语」的情况。
   用户自己填的 Brief 目标、campaign 名称、AI 生成的「理由/依据」审计流水
   不会出现在字典里，因此不会被误伤。
3. **线程安全**：ThreadingHTTPServer 是多线程的，语言状态放 threading.local()，
   避免并发请求互相串味。
4. **中文模式零成本**：lang=zh 时直接返回原文，行为与改造前完全一致。

语言来源优先级：URL ?lang= > Cookie cockpit_lang > 默认 en
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading

# ----------------------------- 语言状态 -----------------------------
LOCAL = threading.local()
DEFAULT_LANG = "en"
SUPPORTED = ("en", "zh")
COOKIE_NAME = "cockpit_lang"

_HERE = os.path.dirname(os.path.abspath(__file__))
DICT_PATH = os.path.join(_HERE, "i18n_dict.json")

# 懒加载的 ZH->EN 字典（进程内缓存）
_DICT: dict | None = None
_DICT_LOCK = threading.Lock()


def _dict() -> dict:
    """加载 ZH->EN 字典；缺失时降级为空字典（页面退回中文，不会崩）。"""
    global _DICT
    if _DICT is not None:
        return _DICT
    with _DICT_LOCK:
        if _DICT is None:
            try:
                with open(DICT_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                # 键值统一做 HTML 实体解码：运行时查表用的是解码后的文本
                # （_norm 会 unescape），若字典存的是 &quot; 形态则永远匹配不上。
                _DICT = {_norm(k): v for k, v in raw.items()}
            except Exception:
                _DICT = {}
    return _DICT


def set_lang(lang: str | None) -> str:
    """设置当前请求线程的语言，返回规范化后的值。"""
    v = (lang or "").strip().lower()
    if v.startswith("zh"):
        v = "zh"
    elif v.startswith("en"):
        v = "en"
    else:
        v = DEFAULT_LANG
    LOCAL.lang = v
    return v


def get_lang() -> str:
    return getattr(LOCAL, "lang", DEFAULT_LANG)


def is_en() -> bool:
    return get_lang() == "en"


# ----------------------------- 语言解析 -----------------------------
def parse_cookie(header: str | None) -> str | None:
    """从 Cookie 头里取 cockpit_lang。"""
    if not header:
        return None
    for part in header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k.strip() == COOKIE_NAME:
            return _html.unescape(v.strip()).strip("\"'")
    return None


def resolve(handler, query_lang: str | None = None) -> str:
    """根据 请求参数 > Cookie > 默认 的优先级解析语言，并写入线程状态。"""
    if query_lang:
        return set_lang(query_lang)
    ck = parse_cookie(getattr(handler, "headers", {}).get("Cookie")
                      if getattr(handler, "headers", None) else None)
    if ck:
        return set_lang(ck)
    return set_lang(DEFAULT_LANG)


def cookie_header(lang: str) -> str:
    """构造 Set-Cookie 头，供切换语言时下发。"""
    return f"{COOKIE_NAME}={lang}; Path=/; Max-Age=31536000; SameSite=Lax"


# ----------------------------- HTML 翻译 -----------------------------
# 文本节点：>内容<。
# 内容里允许出现字面量 '>'（例如规则文案 "D>90 天 → 5"），但不能出现 '<'（那是标签边界），
# 且必须以 '<' 收尾以确保不跨越标签贪婪吞并。
_TEXT_NODE = re.compile(r">([^<]+)<")
# 输入框占位符属性：placeholder='...' / placeholder="..."。
# placeholder 是标签属性而非文本节点（>文本< 规则覆盖不到），需单独通道翻译；
# 同样走「整词精确命中字典才替换」，用户自己输入的 value 不受影响。
_PLACEHOLDER_ATTR = re.compile(r"(placeholder=)(['\"])(.*?)\2")
# 受保护区域的占位符（_SKIP_BLOCK 摘出 code/script/style 后替换成它）
_PH = "\x00P%d\x00"
_PH_RE = re.compile(r"\x00P\d+\x00")
# 需要跳过翻译的区域：脚本/样式/代码/开发日志原文
_SKIP_BLOCK = re.compile(
    r"(<script\b.*?</script>)|(<style\b.*?</style>)|(<code\b.*?</code>)",
    re.IGNORECASE | re.DOTALL,
)


def _norm(s: str) -> str:
    """归一化：HTML 实体解码 + 折叠空白。

    递归解码（最多 3 层）：页面里存在双重转义的节点，例如 SVG <title> 中的
    `&amp;quot;` —— cockpit 用 _esc() 转义了一次，模板里又带了 &quot; 字面量。
    单层 unescape 后仍残留实体，导致与字典键失配。递归到稳定即可覆盖这类情况。
    """
    prev = None
    cur = s
    for _ in range(3):
        if cur == prev:
            break
        prev = cur
        cur = _html.unescape(cur)
    return re.sub(r"\s+", " ", cur).strip()


def translate_html(doc: str) -> str:
    """把 HTML 中「整词命中字典」的文本节点替换为英文。"""
    if not doc or not is_en():
        return doc
    table = _dict()
    if not table:
        return doc

    # 保护不可翻译区域：用占位符把它们摘出来，翻译完再放回
    protected: list[str] = []

    def _stash(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00P{len(protected) - 1}\x00"

    work = _SKIP_BLOCK.sub(_stash, doc)

    def _repl(m: re.Match) -> str:
        raw = m.group(1)
        # 节点里可能夹着受保护区域的占位符（如 `取值来源：频次/24h \x00P0\x00`）。
        # 查表前把占位符摘掉（并记下它的位置），否则整词匹配必然失败。
        holes = _PH_RE.findall(raw)
        probe = _PH_RE.sub("", raw) if holes else raw
        key = _norm(probe)
        if not key:
            return m.group(0)
        en = table.get(key)
        if en is None:
            return m.group(0)
        # 保留原文的前后空白与标签结构
        lead = probe[: len(probe) - len(probe.lstrip())]
        trail = probe[len(probe.rstrip()):]
        # 占位符在原文里通常位于末尾（`标签 <code>值</code>`），
        # 译文替换的是「标签」部分，故把占位符接在译文之后即可保持原有顺序。
        body = en + "".join(holes)
        return ">" + lead + body + trail + "<"

    out = _TEXT_NODE.sub(_repl, work)

    # 属性通道：placeholder 里的示例文案（整词命中字典才替换；
    # 译文不得包含引号，否则会破坏属性定界——字典值需自查）
    def _ph_repl(m: re.Match) -> str:
        key = _norm(m.group(3))
        if not key:
            return m.group(0)
        en = table.get(key)
        if en is None:
            return m.group(0)
        return m.group(1) + m.group(2) + en + m.group(2)

    out = _PLACEHOLDER_ATTR.sub(_ph_repl, out)

    # 还原受保护区域
    for i, blk in enumerate(protected):
        out = out.replace(f"\x00P{i}\x00", blk)
    return out


def t(zh: str) -> str:
    """服务端字符串翻译（非 HTML 场景，如 title、JSON 响应）。"""
    if not is_en():
        return zh
    return _dict().get(_norm(zh), zh)

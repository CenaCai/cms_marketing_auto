"""
Mautic Client — 把提案推送到 {base_url}/s/（经 REST API）
=====================================================================
- 认证：Mautic 7 = OAuth2 client_credentials（POST /oauth/v2/token 换 Bearer）
  —— legacy 的 per-user api_key/api_secret Basic Auth 在 Mautic 7.1.3 已移除
     （无 users.api_key 列、无 ApiKeyAuthenticator；见 app/config/security.php：
      /api 与 /s/ 防火墙均开 fos_oauth:true，接受 Bearer）。
- 事件图走 /api/campaigns/new 创建时一并写入 events + canvasSettings + lists
- 默认 dry-run：未填 client_id/client_secret 时只回调用清单，不真正发请求
- 仅用标准库 urllib（零依赖）

    调用顺序：
  1) POST /oauth/v2/token               换 access_token（grant_type=client_credentials）
  2) POST /api/campaigns/new            创建（isPublished=False）+ events + canvasSettings + lists
  3) POST /api/campaigns/<id>/edit      审批后上线（仅 approved=True 时）
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

# 资产列表进程内缓存（Mautic 全量拉取慢，避免每页刷新重复请求）
_ASSET_CACHE_TTL = 300  # 秒
_ASSET_CACHE = {"ts": 0.0, "data": None}
_CAMP_CACHE = {"ts": 0.0, "data": None}
# Stats API 缓存：同一进程内重复取相同 table 直接走内存（auto_feedback 一个事件一查，3 个事件 = 3 次拉）
_STATS_CACHE_TTL = 120  # 秒
_STATS_CACHE: dict[str, dict] = {}  # table → {"ts": float, "rows": list}
_STATS_LOCK_NAME = "_stats_lock"
import threading as _thr_stats  # noqa: E402
try:
    _STATS_LOCK = _thr_stats.Lock()
except Exception:  # pragma: no cover
    _STATS_LOCK = None
_ASSET_LOCK = threading.Lock()

# 绕过任何 HTTP 代理直连 Mautic（沙箱环境下 localhost 经默认代理会偶发 502；
# 本机无代理配置时 ProxyHandler({}) 为 no-op，无副作用）
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))


def load_config(env: str) -> dict:
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if env not in cfg:
        raise SystemExit(f"config.json 没有环境 '{env}'")
    return cfg[env]


def _oauth_creds(cfg: dict) -> tuple:
    """返回 (client_id, client_secret)。优先新字段，兼容 legacy api_key/api_secret。"""
    cid = (cfg.get("client_id") or cfg.get("api_key") or "").strip()
    sec = (cfg.get("client_secret") or cfg.get("api_secret") or "").strip()
    return (cid, sec)


def _safe_json(s: str):
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return s[:500]


def _stats_get(table: str, env: str = "local", limit: int = 1000, timeout: int = 40) -> list:
    """读取 Stats API 整表 → 列表（本地按需过滤；Mautic 7 stats 接口对 where/filter 支持不全，先取全量）。
    进程内缓存 _STATS_CACHE_TTL 秒，避免同一次 auto-feedback 对同一 table 反复拉。"""
    cache_key = f"{env}:{table}:{limit}"
    now = time.time()
    cached = _STATS_CACHE.get(cache_key)
    if cached and (now - cached["ts"]) < _STATS_CACHE_TTL:
        return cached["rows"]
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return []
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return []
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception:  # noqa: BLE001
        return []
    res = _get(base, f"/api/stats/{table}?limit={limit}", token, timeout=timeout)
    if not isinstance(res, dict):
        return []
    bucket = res.get("stats", res)
    if isinstance(bucket, list):
        rows = [r for r in bucket if isinstance(r, dict)]
    elif isinstance(bucket, dict):
        if "items" in bucket and isinstance(bucket["items"], list):
            rows = [r for r in bucket["items"] if isinstance(r, dict)]
        else:
            rows = [r for r in bucket.values() if isinstance(r, dict)]
    else:
        rows = []
    _STATS_CACHE[cache_key] = {"ts": now, "rows": rows}
    return rows


def _parse_dt(s: str):
    """宽松解析 Mautic 时间串 'YYYY-MM-DD HH:MM:SS' → datetime；空串返回 None。"""
    if not s:
        return None
    from datetime import datetime
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s[:19], fmt[:19] if "+" not in s and "T" not in fmt else fmt)
        except Exception:  # noqa: BLE001
            pass
    return None


def _in_date(s: str, date_str: str) -> bool:
    """判断 Mautic 时间串 s 是否属于 date_str (YYYY-MM-DD) 当天。"""
    dt = _parse_dt(s)
    if not dt:
        return False
    return dt.strftime("%Y-%m-%d") == date_str


def _get_token(base_url: str, client_id: str, client_secret: str, timeout: int = 15) -> str:
    """OAuth2 client_credentials 换 access_token；失败抛 RuntimeError（带原因）。"""
    url = f"{base_url}/oauth/v2/token"
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _safe_json(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"token 获取失败 HTTP {e.code}: {_safe_json(e.read().decode('utf-8', 'replace'))}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"token 获取网络错误: {e}")
    if not isinstance(data, dict) or not data.get("access_token"):
        raise RuntimeError(f"token 响应异常: {data}")
    return data["access_token"]


def _post(base_url: str, path: str, body: dict, token: str, timeout: int = 15) -> dict:
    """POST JSON，带 Bearer token。"""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"url": url, "status": resp.status, "body": _safe_json(raw)}
    except urllib.error.HTTPError as e:
        return {"url": url, "status": e.code, "body": _safe_json(e.read().decode("utf-8", "replace"))}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": 0, "body": f"网络/连接错误: {e}"}


def _get(base_url: str, path: str, token: str, timeout: int = 15):
    """GET 读取 Mautic 资源，带 Bearer token；失败/无凭证返回 None（调用方据此判定未连接）。"""
    url = f"{base_url}{path}"
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return _safe_json(raw)
    except Exception:  # noqa: BLE001
        return None


def _patch(base_url: str, path: str, body: dict, token: str, timeout: int = 15) -> dict:
    """PATCH JSON，带 Bearer token。Mautic 7 的 campaign publish 必须用 PATCH（非 POST/PUT）。"""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"url": url, "status": resp.status, "body": _safe_json(raw)}
    except urllib.error.HTTPError as e:
        return {"url": url, "status": e.code, "body": _safe_json(e.read().decode("utf-8", "replace"))}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": 0, "body": f"网络/连接错误: {e}"}


def _aliasify(name: str) -> str:
    """把任意中文/特殊字符名转成 Mautic 兼容的 alias（小写字母数字+下划线，长度 ≤50）。"""
    import re as _re
    s = _re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return (s or "asset")[:50]


def _find_by_name(items: list, name: str):
    """从 [{id,name,alias}, ...] 列表里按 name（精确）或 alias（精确）找资产。"""
    if not name or not items:
        return None
    alias = _aliasify(name)
    for it in items:
        if isinstance(it, dict) and it.get("id"):
            if it.get("name") == name:
                return it
            if it.get("alias") == alias or it.get("alias") == name:
                return it
    return None


def ensure_segment(name: str, env: str = "local", timeout: int = 15) -> dict:
    """按 name 找 segment；找不到就 POST 新建；返回 {"id","name","alias","created":bool}。
    失败/无凭证返回 {"id": None, "error": "..."}。"""
    if not name:
        return {"id": None, "error": "name 为空"}
    try:
        cfg = load_config(env)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"load_config: {e}"}
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return {"id": None, "error": "未配置 OAuth client_id/secret"}
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"token 获取失败: {e}"}

    # 1) 查现有：先按 name 搜索
    res = _get(base, f"/api/segments?search={urllib.parse.quote(name)}&limit=10", token, timeout)
    if isinstance(res, dict):
        bucket = res.get("lists") or {}
        items = (list(bucket.values()) if isinstance(bucket, dict) else bucket) if bucket else []
        existing = _find_by_name(items if isinstance(items, list) else [], name)
        if existing:
            return {"id": int(existing["id"]), "name": existing.get("name"), "alias": existing.get("alias"), "created": False}

    # 2) 新建（草稿下线）
    alias = _aliasify(name)
    body = {"name": name, "alias": alias, "isPublished": False, "isGlobal": False, "filters": []}
    r = _post(base, "/api/segments/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        seg = (r["body"] or {}).get("list") or {}
        new_id = seg.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "alias": alias, "created": True}
    return {"id": None, "error": f"POST /api/segments/new HTTP {r['status']}: {_format_err(r['body'])}"}


def ensure_email(name: str, subject: str = "", env: str = "local", list_id: int = None, email_type: str = "transactional", timeout: int = 15) -> dict:
    """按 name 找 email；找不到就 POST 新建（草稿）；返回 {"id","subject","created":bool,"error"?}。
    subject 仅在新建时使用（已有 email 不会覆盖其内容）。
    email_type: 默认 "transactional"（campaign events 用的就是 transactional，无需挂 list）；
                "list" 时 Mautic 要求 lists，但 segment id 通常不被接受（"所选的选项无效"）。
    """
    if not name:
        return {"id": None, "error": "name 为空"}
    try:
        cfg = load_config(env)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"load_config: {e}"}
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return {"id": None, "error": "未配置 OAuth client_id/secret"}
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"token 获取失败: {e}"}

    res = _get(base, f"/api/emails?search={urllib.parse.quote(name)}&limit=10", token, timeout)
    if isinstance(res, dict):
        bucket = res.get("emails") or {}
        items = (list(bucket.values()) if isinstance(bucket, dict) else bucket) if bucket else []
        existing = _find_by_name(items if isinstance(items, list) else [], name)
        if existing:
            return {"id": int(existing["id"]), "name": existing.get("name"), "created": False}

    alias = _aliasify(name)
    body = {
        "name": name,
        "alias": alias,
        "subject": subject or name,
        "isPublished": False,
        "emailType": email_type,
        "customHtml": f"<p>{subject or name}</p>",
    }
    # 只有 list 类型才需要 lists 字段；transactional 不需要
    if email_type == "list" and list_id:
        body["lists"] = [{"id": int(list_id)}]
    r = _post(base, "/api/emails/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        em = (r["body"] or {}).get("email") or {}
        new_id = em.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "created": True}
    return {"id": None, "error": f"POST /api/emails/new HTTP {r['status']}: {_format_err(r['body'])}"}


def ensure_landing_page(name: str, url: str = "", env: str = "local", timeout: int = 15) -> dict:
    """按 name 找 landing page；找不到就 POST 新建（草稿）；返回 {"id","created":bool,"error"?}。
    若给了 url 用 redirect（meta-refresh 兜底），否则占位 HTML。"""
    if not name:
        return {"id": None, "error": "name 为空"}
    try:
        cfg = load_config(env)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"load_config: {e}"}
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return {"id": None, "error": "未配置 OAuth client_id/secret"}
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"token 获取失败: {e}"}

    res = _get(base, f"/api/pages?search={urllib.parse.quote(name)}&limit=10", token, timeout)
    if isinstance(res, dict):
        bucket = res.get("pages") or []
        items = bucket if isinstance(bucket, list) else (list(bucket.values()) if isinstance(bucket, dict) else [])
        existing = _find_by_name(items, name)
        if existing:
            return {"id": int(existing["id"]), "name": existing.get("name"), "created": False}

    alias = _aliasify(name)
    html = f'<html><body><p>{name}</p>{"<meta http-equiv=\"refresh\" content=\"0;url=" + url + "\">" if url else ""}</body></html>'
    body = {"name": name, "alias": alias, "isPublished": False, "customHtml": html, "title": name}
    r = _post(base, "/api/pages/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        pg = (r["body"] or {}).get("page") or {}
        new_id = pg.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "created": True}
    return {"id": None, "error": f"POST /api/pages/new HTTP {r['status']}: {_format_err(r['body'])}"}


def _format_err(body) -> str:
    """把 Mautic 错误响应体（dict / str）压成一行。"""
    if isinstance(body, dict):
        errs = body.get("errors") or []
        if isinstance(errs, list) and errs:
            parts = []
            for e in errs[:3]:
                if isinstance(e, dict):
                    parts.append(str(e.get("message") or e.get("detail") or e))
                else:
                    parts.append(str(e))
            return "；".join(parts)
        if body.get("message"):
            return str(body["message"])
        return json.dumps(body, ensure_ascii=False)[:300]
    if isinstance(body, str):
        return body[:300]
    return str(body)[:300]


def mautic_read_assets(env: str = "local") -> dict:
    """
    读取 Mautic 已存在的资产（email / segment / landingpage），供驾驶舱判断
    「新建 vs 调用已有」。
    防御式：任何错误、缺凭证、连接失败 → {"available": False, ...空列表}。
    成功结果进程内缓存 _ASSET_CACHE_TTL 秒（Mautic 全量列表较慢，避免每页刷新都重拉）。
    """
    with _ASSET_LOCK:
        if _ASSET_CACHE["data"] is not None and (time.time() - _ASSET_CACHE["ts"]) < _ASSET_CACHE_TTL:
            return _ASSET_CACHE["data"]
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return {"available": False, "emails": [], "segments": [], "pages": []}
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return {"available": False, "emails": [], "segments": [], "pages": []}
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e), "emails": [], "segments": [], "pages": []}

    out = {"available": True, "emails": [], "segments": [], "pages": []}
    # (输出键, API 路径, 响应中承载资产的键名)
    # 实测 Mautic 7：emails→{"emails":{id:{...}}}；segments→{"lists":{id:{...}}}；pages→{"pages":[{...}]}
    # 全量列表较慢（emails ~18s / segments ~15s），故拉取超时放宽到 45s。
    endpoints = (
        ("emails", "/api/emails?limit=0", "emails"),
        ("segments", "/api/segments?limit=0", "lists"),
        ("pages", "/api/pages?limit=0", "pages"),
    )
    for key, path, bucket_key in endpoints:
        res = _get(base, path, token, timeout=45)
        if res is None:  # 连接失败 → 整体判定为未连接
            return {"available": False, "reason": "连接失败", "emails": [], "segments": [], "pages": []}
        # Mautic 7 返回形态：{"emails": {"56": {...}}} 或 {"lists": {"54": {...}}}（按 id 键的字典）
        # 以及 pages：{"pages": [{...}]}（列表）
        # legacy 返回：{"emails": {"total":N,"items":[...]}} 或 {"emails":[...]}
        bucket = res.get(bucket_key, res) if isinstance(res, dict) else res
        if isinstance(bucket, dict):
            if "items" in bucket:
                items = bucket["items"]
            elif "lists" in bucket:
                items = list(bucket["lists"].values()) if isinstance(bucket["lists"], dict) else bucket["lists"]
            else:
                items = list(bucket.values())  # Mautic 7 按 id 键的字典
        elif isinstance(bucket, list):
            items = bucket
        else:
            items = []
        out[key] = [
            {"id": it.get("id"), "name": it.get("name"), "alias": it.get("alias")}
            for it in items if isinstance(it, dict)
        ]
    with _ASSET_LOCK:
        _ASSET_CACHE["ts"] = time.time()
        _ASSET_CACHE["data"] = out
    return out


def mautic_read_campaigns(env: str = "local") -> dict:
    """读取 Mautic campaigns 列表 → {"available": bool, "by_id": {id: name}, "by_name": {name: id}}。
    进程内缓存 _ASSET_CACHE_TTL 秒（供 campaign 名→id / id→名 反查）。"""
    with _ASSET_LOCK:
        if _CAMP_CACHE["data"] is not None and (time.time() - _CAMP_CACHE["ts"]) < _ASSET_CACHE_TTL:
            return _CAMP_CACHE["data"]
    empty = {"available": False, "by_id": {}, "by_name": {}}
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return empty
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return empty
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception:  # noqa: BLE001
        return empty
    res = _get(base, "/api/campaigns?limit=0", token, timeout=45)
    if res is None:
        return empty
    b = res.get("campaigns") if isinstance(res, dict) else res
    if isinstance(b, dict):
        items = list(b.values())
    elif isinstance(b, list):
        items = b
    else:
        items = []
    by_id, by_name = {}, {}
    for it in items:
        if isinstance(it, dict) and it.get("id") is not None:
            nm = (it.get("name") or "").strip()
            by_id[str(it["id"])] = nm
            if nm:
                by_name[nm] = str(it["id"])
    out = {"available": True, "by_id": by_id, "by_name": by_name}
    with _ASSET_LOCK:
        _CAMP_CACHE["ts"] = time.time()
        _CAMP_CACHE["data"] = out
    return out


def mautic_get_campaign(campaign_id, env: str = "local") -> dict:
    """读取单个 campaign（不缓存，保证改名后实时同步）→ {"id","name","events"}；失败/缺失返回 {}。"""
    if not campaign_id:
        return {}
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return {}
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return {}
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception:  # noqa: BLE001
        return {}
    res = _get(base, f"/api/campaigns/{campaign_id}", token, timeout=10)
    if not isinstance(res, dict):
        return {}
    c = res.get("campaign", res)
    if not isinstance(c, dict):
        return {}
    return {"id": c.get("id"), "name": (c.get("name") or "").strip(), "events": c.get("events") or []}


def push(proposal: dict, env: str = "local", approved: bool = False) -> dict:
    """
    推送提案到 Mautic。返回结构化结果（含每步状态）。
    凭证缺失/无效 → dry-run，仅回调用清单。

    新增「依赖资产确保存在」步骤：先看 proposal.mautic_lists / events 里是否引用了
    未在 Mautic 真实存在的 segment / email / landing page，若有就按 name 自动新建
    （草稿下线），把真实 ID 写回 events.properties.email 与 lists[].id。
    这样 plan 阶段不需要预先知道 ID，PoC 端到端即可一键推送。
    """
    cfg = load_config(env)
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)

    if not client_id or not client_secret:
        return {
            "dry_run": True,
            "note": "config.json 未填 client_id/client_secret，仅生成调用清单（未触碰 Mautic）",
            "calls": proposal.get("api_calls") or [],
        }

    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"dry_run": True, "note": f"凭证无效/无法获取 token: {e}", "calls": proposal.get("api_calls") or []}

    goal_cid = proposal["campaign"]["goal_id"]
    steps = []

    # ===== 0) 依赖资产 ensure：Mautic 7 campaign 必须有 contact source（segment），否则 400；
    #     events[].properties.email 也必须是真实 email id（0 占位会执行失败）；
    #     email 创建也必须挂到 list（否则 400），所以先建 segment、把 segment id 传给 ensure_email。
    ensure_log = []
    seg_id = None
    # 0.1 segment（lists）：proposal.mautic_lists 为空时，按 strategy_ref.segment_ref 自动建
    if not proposal.get("mautic_lists"):
        seg_name = ((proposal.get("strategy_ref") or {}).get("segment_ref")
                    or proposal.get("campaign", {}).get("audience_segment") or "")
        if seg_name:
            rseg = ensure_segment(seg_name, env=env)
            ensure_log.append({"asset": "segment", "name": seg_name, **rseg})
            if rseg.get("id"):
                seg_id = rseg["id"]
                proposal["mautic_lists"] = [{"id": seg_id}]
            else:
                return {
                    "dry_run": False, "env": env, "campaign_id": None,
                    "steps": steps,
                    "ensure_log": ensure_log,
                    "error": f"无法创建/解析 segment '{seg_name}'：{rseg.get('error','?')}",
                }
    else:
        # mautic_lists 已有 → 取第一个 id 作为 email 落点
        try:
            seg_id = int((proposal["mautic_lists"][0] or {}).get("id"))
        except (TypeError, ValueError, IndexError):
            seg_id = None

    # 0.2 email（events[].properties.email == 0 时按 strategy_ref.email_ref 自动建）
    str_ref = proposal.get("strategy_ref") or {}
    main_email_name = str_ref.get("email_ref") or ""
    followup_email_name = str_ref.get("email_followup_ref") or ""
    # 已解析 email id 缓存（避免同一 email 被 ensure 多次）
    email_id_cache: dict = {}

    def _resolve_email_id(name: str, subject: str):
        if not name:
            return None
        if name in email_id_cache:
            return email_id_cache[name]
        rem = ensure_email(name, subject=subject, env=env, list_id=seg_id)
        ensure_log.append({"asset": "email", "name": name, **rem})
        email_id_cache[name] = rem.get("id")
        return rem.get("id")

    if isinstance(proposal.get("mautic_events"), list):
        for ev in proposal["mautic_events"]:
            props = ev.get("properties") or {}
            if ev.get("type") == "email.send" and (props.get("email") in (0, None, "")):
                # 主邮件 vs 兜底邮件：用 subject 含「提醒」判定走 followup_ref，否则走 main
                subject = (ev.get("name") or "").replace("发送邮件：", "")
                if followup_email_name and ("提醒" in subject or "followup" in subject.lower()):
                    name = followup_email_name
                else:
                    name = main_email_name
                eid = _resolve_email_id(name, subject)
                if eid:
                    props["email"] = eid
            ev["properties"] = props

    # 0.3 关键：plan 阶段若 strategy.segment_id 缺失 → mautic_canvas.connections 没有
    #     「lists → 根事件」连线，导致 Mautic 报「orphan events」无法发布。
    #     这里补一条从 lists source 连到第一个无父节点的根事件。
    canvas = proposal.get("mautic_canvas") or {}
    conns = canvas.get("connections") or []
    nodes = canvas.get("nodes") or []
    if proposal.get("mautic_lists") and nodes:
        target_ids = {c.get("targetId") for c in conns if isinstance(c, dict)}
        source_ids = {c.get("sourceId") for c in conns if isinstance(c, dict)}
        # 找「无父节点的事件 id」= 根事件
        events = proposal.get("mautic_events") or []
        ev_by_id = {e.get("id"): e for e in events if isinstance(e, dict) and e.get("id")}
        root_id = None
        for ev in events:
            if isinstance(ev, dict) and not ev.get("parent") and ev.get("id"):
                root_id = ev["id"]
                break
        # 如果 root_id 还没有作为某条 connection 的 targetId，就补一条 lists→root
        if root_id and root_id not in target_ids:
            conns.append({
                "sourceId": "lists",
                "targetId": root_id,
                "anchors": {"source": "leadsource", "target": "top"},
            })
        canvas["connections"] = conns
        proposal["mautic_canvas"] = canvas

    # 1) 创建 campaign（默认下线），同时带上 Mautic 7 期望的 events + canvasSettings（+ lists）
    create_body = {"name": goal_cid, "isPublished": False}
    if proposal.get("mautic_events"):
        create_body["events"] = proposal["mautic_events"]
    if proposal.get("mautic_canvas"):
        create_body["canvasSettings"] = proposal["mautic_canvas"]
    if proposal.get("mautic_lists"):
        create_body["lists"] = proposal["mautic_lists"]
    r1 = _post(base, "/api/campaigns/new", create_body, token)
    steps.append({"step": "create_campaign_with_events", **r1})
    new_id = None
    if isinstance(r1["body"], dict):
        new_id = (r1["body"].get("campaign") or {}).get("id")

    # 2) 审批通过后上线
    if new_id and approved:
        # Mautic 7：发布用 PATCH /api/campaigns/{id}/edit（POST/404，PUT/500，PATCH 才能正确处理）
        try:
            r3 = _patch(base, f"/api/campaigns/{new_id}/edit",
                        {"isPublished": True}, token)
            steps.append({"step": "publish", **r3})
        except Exception as e:  # noqa: BLE001
            steps.append({"step": "publish", "status": 0, "body": f"网络/连接错误: {e}"})

    return {
        "dry_run": False, "env": env, "campaign_id": new_id,
        "steps": steps, "ensure_log": ensure_log,
    }


# ---------------------- 每日自动取数（email_stats 等） ----------------------
def fetch_email_event_stats(event_id, date_str: str, env: str = "local") -> dict:
    """按 Mautic campaign 事件 id + 日期，取该事件的 email_stats 行：
    发送数 sent = 行数(排除 is_failed=1)；
    打开数 opened = sum(open_count)（更准，反映重复打开）或 is_read=1 行数。
    返回 {"sent": int, "opened": int, "_matched_rows": int}"""
    rows = _stats_get("email_stats", env=env, limit=2000, timeout=40)
    if not rows:
        return {"sent": 0, "opened": 0, "_matched_rows": 0}
    eid = str(event_id)
    sent = 0
    opened = 0
    matched = 0
    for r in rows:
        if str(r.get("source") or "") != "campaign.event":
            continue
        if str(r.get("source_id") or "") != eid:
            continue
        if not _in_date(r.get("date_sent", ""), date_str):
            continue
        if str(r.get("is_failed") or "0") == "1":
            continue
        matched += 1
        sent += 1
        try:
            opened += int(r.get("open_count") or 0)
        except (TypeError, ValueError):
            if str(r.get("is_read") or "0") == "1":
                opened += 1
    return {"sent": sent, "opened": opened, "_matched_rows": matched}


def fetch_landing_page_clicks(page_id, date_str: str, env: str = "local") -> int:
    """按落地页 id + 日期，取 page_hits 中匹配的行数（视为该页点击）。
    Mautic 把 email 链接点击经 channel_url_trackables 落到 page_hits，按 page_id 统计。"""
    if not page_id:
        return 0
    rows = _stats_get("page_hits", env=env, limit=2000, timeout=40)
    pid = str(page_id)
    n = 0
    for r in rows:
        if str(r.get("page_id") or "") != pid:
            continue
        if not _in_date(r.get("date_hit", ""), date_str):
            continue
        n += 1
    return n


def fetch_form_submissions(form_id, date_str: str, env: str = "local") -> int:
    """按 form id + 日期，取 form_submissions 行数（视为该 form 的"转化"事件）。"""
    if not form_id:
        return 0
    rows = _stats_get("form_submissions", env=env, limit=2000, timeout=40)
    fid = str(form_id)
    n = 0
    for r in rows:
        if str(r.get("form_id") or "") != fid:
            continue
        if not _in_date(r.get("date_submitted", ""), date_str):
            continue
        n += 1
    return n


def fetch_unsub_count(env: str = "local", date_str: str = "") -> int:
    """退订：lead_donotcontact 中 date_added 在 date_str 当天的行数（best effort，按天统计全量退订）。"""
    rows = _stats_get("lead_donotcontact", env=env, limit=2000, timeout=40)
    if not date_str:
        return len(rows)
    n = 0
    for r in rows:
        # lead_donotcontact 常见字段 date_added
        for k in ("date_added", "dateUnsubscribed", "dateAdded"):
            if r.get(k) and _in_date(str(r[k]), date_str):
                n += 1
                break
    return n


def _event_props(ev: dict) -> dict:
    """统一从 Mautic 事件对象取 properties（兼容 ev 顶层字段与 ev.properties）。"""
    p = ev.get("properties") or {}
    if not isinstance(p, dict):
        p = {}
    # 兼容：email 字段可能直接在 properties，也可能在 channelId
    if not p.get("email") and ev.get("channelId"):
        try:
            p["email"] = int(ev["channelId"])
        except (TypeError, ValueError):
            pass
    if not p.get("page") and ev.get("channelId"):
        try:
            p["page"] = int(ev["channelId"])
        except (TypeError, ValueError):
            pass
    return p


def auto_feedback_for_campaign(mcid, date_str: str, env: str = "local") -> dict:
    """对单个 Mautic campaign，按 date_str 聚合五指标。
    返回 {sent, opened, clicked, converted, unsub, conv_rate, unsub_rate, _evidence, _errors}。"""
    info = mautic_get_campaign(mcid, env=env)
    events = info.get("events") or []
    out = {"sent": 0, "opened": 0, "clicked": 0, "converted": 0, "unsub": 0,
           "conv_rate": 0.0, "unsub_rate": 0.0, "_evidence": [], "_errors": []}
    if not events:
        out["_errors"].append("no_events")
        return out
    sent_total, opened_total, clicked_total, converted_total = 0, 0, 0, 0
    for ev in events:
        et = (ev.get("type") or "").lower()
        p = _event_props(ev)
        try:
            if et == "email.send":
                eid = ev.get("id")
                s = fetch_email_event_stats(eid, date_str, env=env)
                sent_total += s["sent"]; opened_total += s["opened"]
                if s["sent"]:
                    out["_evidence"].append(f"email.send(ev={eid}, email={p.get('email')}) → sent={s['sent']} opened={s['opened']}")
            elif et == "page.hit":
                pid = p.get("page")
                if pid:
                    c = fetch_landing_page_clicks(pid, date_str, env=env)
                    clicked_total += c        # 计入 clicked：Mautic 把邮件链接点击经 channel_url_trackables 落到 page_hits
                    converted_total += c     # 同时计入 converted：LP 访问即转化（无 form 时 page.hit 是 Mautic 原生唯一信号）
                    if c:
                        out["_evidence"].append(
                            f"page.hit(ev={ev.get('id')}, page={pid}) → visits={c} (clicked + converted)")
            elif et in ("form.submit",):
                fid = p.get("form")
                if fid:
                    c = fetch_form_submissions(fid, date_str, env=env)
                    converted_total += c     # form 提交累加在 converted 上（比 page.hit 更深的转化信号）
                    if c:
                        out["_evidence"].append(f"form.submit(ev={ev.get('id')}, form={fid}) → submits={c}")
        except Exception as e:  # noqa: BLE001
            out["_errors"].append(f"{et}({ev.get('id')}): {e}")
    out["sent"] = sent_total
    out["opened"] = opened_total
    out["clicked"] = clicked_total
    out["converted"] = converted_total
    out["unsub"] = fetch_unsub_count(env=env, date_str=date_str)
    out["conv_rate"] = round(converted_total / sent_total, 4) if sent_total else 0.0
    out["unsub_rate"] = round(out["unsub"] / sent_total, 4) if sent_total else 0.0
    return out


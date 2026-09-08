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


def push(proposal: dict, env: str = "local", approved: bool = False) -> dict:
    """
    推送提案到 Mautic。返回结构化结果（含每步状态）。
    凭证缺失/无效 → dry-run，仅回调用清单。
    """
    cfg = load_config(env)
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)

    if not client_id or not client_secret:
        return {
            "dry_run": True,
            "note": "config.json 未填 client_id/client_secret，仅生成调用清单（未触碰 Mautic）",
            "calls": proposal["api_calls"],
        }

    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"dry_run": True, "note": f"凭证无效/无法获取 token: {e}", "calls": proposal["api_calls"]}

    goal_cid = proposal["campaign"]["goal_id"]
    steps = []

    # 1) 创建 campaign（默认下线），同时带上 Mautic 7 期望的 events + canvasSettings（+ lists）
    #    —— 事件图连线（parent/child）由 canvasSettings.connections 在 setEvents() 里建立。
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
        r3 = _post(base, f"/api/campaigns/{new_id}/edit",
                   {"isPublished": True}, token)
        steps.append({"step": "publish", **r3})

    return {"dry_run": False, "env": env, "campaign_id": new_id, "steps": steps}

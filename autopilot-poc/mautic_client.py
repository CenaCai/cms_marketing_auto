"""
Mautic Client — 把提案推送到 {base_url}/s/（经 REST API）
=====================================================================
- 认证：HTTP Basic（config.json 的 api_key/api_secret）
- 更新类路由走 /api/v2（合并规格附录 C）
- 事件图不可经普通 API 改 → 走 applyAction（附录 B）
- 默认 dry-run：未填凭证时只回调用清单，不真正发请求
- 仅用标准库 urllib（零依赖）

调用顺序：
  1) POST /s/api/v2/campaigns/new       创建（isPublished=False）
  2) POST /s/api/v2/campaigns/<id>/applyAction  写入事件图（plan_hash + graph）
  3) POST /s/api/v2/campaigns/<id>/edit 审批后上线（仅 approved=True 时）
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config(env: str) -> dict:
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if env not in cfg:
        raise SystemExit(f"config.json 没有环境 '{env}'")
    return cfg[env]


def _post(base_url: str, path: str, body: dict, auth: tuple, timeout: int = 15) -> dict:
    url = f"{base_url}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if auth[0]:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"url": url, "status": resp.status, "body": _safe_json(raw)}
    except urllib.error.HTTPError as e:
        return {"url": url, "status": e.code, "body": _safe_json(e.read().decode("utf-8", "replace"))}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": 0, "body": f"网络/连接错误: {e}"}


def _safe_json(s: str):
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return s[:500]


def _get(base_url: str, path: str, auth: tuple, timeout: int = 15):
    """GET 读取 Mautic 资源；失败/无凭证返回 None（调用方据此判定未连接）。"""
    url = f"{base_url}{path}"
    req = urllib.request.Request(url, method="GET")
    if auth[0]:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
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
    """
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return {"available": False, "emails": [], "segments": [], "pages": []}
    base = cfg["base_url"]
    auth = (cfg.get("api_key", ""), cfg.get("api_secret", ""))
    if not auth[0] or not auth[1]:
        return {"available": False, "emails": [], "segments": [], "pages": []}

    out = {"available": True, "emails": [], "segments": [], "pages": []}
    endpoints = (
        ("emails", "/s/api/emails"),
        ("segments", "/s/api/segments"),
        ("pages", "/s/api/landingpages"),
    )
    for key, path in endpoints:
        res = _get(base, path, auth)
        if res is None:  # 连接失败 → 整体判定为未连接
            return {"available": False, "emails": [], "segments": [], "pages": []}
        # Mautic 返回形态：{"emails": {"total":N,"items":[...]}} 或 {"emails":[...]}
        bucket = res.get(key, res) if isinstance(res, dict) else res
        if isinstance(bucket, dict):
            bucket = bucket.get("items", bucket.get("lists", []))
        items = bucket if isinstance(bucket, list) else []
        out[key] = [
            {"id": it.get("id"), "name": it.get("name"), "alias": it.get("alias")}
            for it in items if isinstance(it, dict)
        ]
    return out


def push(proposal: dict, env: str = "local", approved: bool = False) -> dict:
    """
    推送提案到 Mautic。返回结构化结果（含每步状态）。
    凭证缺失 → dry-run，仅回调用清单。
    """
    cfg = load_config(env)
    base = cfg["base_url"]
    auth = (cfg.get("api_key", ""), cfg.get("api_secret", ""))

    if not auth[0] or not auth[1]:
        return {
            "dry_run": True,
            "note": "config.json 未填 api_key/api_secret，仅生成调用清单（未触碰 Mautic）",
            "calls": proposal["api_calls"],
        }

    cid = proposal["campaign"]["goal_id"]
    steps = []

    # 1) 创建 campaign（默认下线）
    r1 = _post(base, "/s/api/v2/campaigns/new",
               {"name": cid, "isPublished": False}, auth)
    steps.append({"step": "create_campaign", **r1})
    new_id = None
    if isinstance(r1["body"], dict):
        new_id = (r1["body"].get("campaign") or {}).get("id")

    # 2) applyAction 写事件图
    if new_id:
        r2 = _post(base, f"/s/api/v2/campaigns/{new_id}/applyAction",
                   {"action": "importEventGraph",
                    "plan_hash": proposal["plan_hash"],
                    "graph": proposal["graph"]}, auth)
        steps.append({"step": "applyAction_event_graph", **r2})

        # 3) 审批通过后上线
        if approved:
            r3 = _post(base, f"/s/api/v2/campaigns/{new_id}/edit",
                       {"isPublished": True}, auth)
            steps.append({"step": "publish", **r3})

    return {"dry_run": False, "env": env, "campaign_id": new_id, "steps": steps}

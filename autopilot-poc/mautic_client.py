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
  2) POST /api/campaigns/new            创建（isPublished=True）+ events + canvasSettings + lists
  3) POST /api/campaigns/<id>/edit      幂等确认上线（创建即已上线；approved=True 时再 PATCH 一次）
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


# 进程内 access_token 缓存：Mautic 7 的 /oauth/v2/token 偶发超时，
# 缓存避免每次 push 都重取，也降低抖动导致 dry-run 的概率。Mautic token 默认 3600s 有效。
_TOKEN_CACHE = {"token": None, "exp": 0.0}

def _get_token(base_url: str, client_id: str, client_secret: str, timeout: int = 60) -> str:
    """OAuth2 client_credentials 换 access_token；失败抛 RuntimeError（带原因）。
    带进程内缓存（TTL 3000s）+ 重试（最多 3 次，仅网络超时重试），跨过 token 端点偶发超时。"""
    import time as _t
    now = _t.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp"] > now:
        return _TOKEN_CACHE["token"]
    url = f"{base_url}/oauth/v2/token"
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    last_err = None
    for _ in range(1, 4):
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = _safe_json(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last_err = f"token 获取失败 HTTP {e.code}: {_safe_json(e.read().decode('utf-8', 'replace'))}"
            break  # 凭证错等 HTTP 错误不重试
        except Exception as e:  # noqa: BLE001
            last_err = f"token 获取网络错误: {e}"
            continue  # 网络超时 → 重试
        if isinstance(data, dict) and data.get("access_token"):
            tok = data["access_token"]
            try:
                ttl = int(data.get("expires_in", 3600))
            except (TypeError, ValueError):
                ttl = 3600
            _TOKEN_CACHE["token"] = tok
            _TOKEN_CACHE["exp"] = now + max(ttl - 600, 60)
            return tok
        last_err = f"token 响应异常: {data}"
        break
    raise RuntimeError(last_err or "token 获取失败")


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


def _basic_header(cfg: dict):
    """Mautic 7 Projects API(/api/v2/projects) 走 Basic 认证(Mautic 用户账号)，与资产端
    OAuth2 client_credentials Bearer 不同。从 config 的 basic_user/basic_password 取；
    缺则返回 None（调用方降级，不建 project）。"""
    import base64
    u = (cfg.get("basic_user") or "").strip()
    p = (cfg.get("basic_password") or "").strip()
    if not u or not p:
        return None
    return "Basic " + base64.b64encode(f"{u}:{p}".encode("utf-8")).decode("ascii")


def _v2_req(method: str, base_url: str, path: str, body: dict = None,
            auth: str = None, timeout: int = 60) -> dict:
    """Mautic 7 API Platform(/api/v2) 请求，Basic 认证。复用 mautic_client 启动时安装的
    ProxyHandler({}) opener（绕过沙箱代理），故 localhost 直连可达。返回 {status, body}。"""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if auth:
        req.add_header("Authorization", auth)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return {"status": resp.status, "body": json.loads(raw)}
            except Exception:
                return {"status": resp.status, "body": raw[:500]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            b = json.loads(raw)
        except Exception:
            b = raw[:500]
        return {"status": e.code, "body": b}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "body": f"网络/连接错误: {e}"}


def _attach_project(base: str, res: str, aid, pid, token: str, timeout: int = 60):
    """把已存在(reuse)的资产关联到 project（PATCH projects=[pid]）。新建资产在 POST body 已带
    projects，无需此步。res ∈ segments/emails/pages/forms/campaigns。"""
    try:
        _patch(base, f"/api/{res}/{aid}/edit", {"projects": [pid]}, token, timeout=timeout)
    except Exception:  # noqa: BLE001
        pass


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


def _build_email_html(subject: str, activity: str = "", discount: dict = None,
                      landing_page_url: str = "", is_followup: bool = False) -> str:
    """生成结构化营销邮件正文（内联样式，邮件客户端兼容）。
    替代旧的 <p>主题</p> 空壳——至少是可发出去的完整邮件。"""
    act = activity or subject
    discount_html = ""
    if isinstance(discount, dict) and discount.get("enabled") and discount.get("pct"):
        discount_html = (
            f'<p style="margin:12px 0;font-size:16px;color:#b12704;font-weight:bold">'
            f'专属优惠：{int(discount["pct"])}% OFF</p>'
        )
    intro = "这封是补发提醒，别错过你的专属权益。" if is_followup else "这是为你准备的活动专属信息，敬请查收。"
    cta = ""
    if landing_page_url:
        cta = (
            '<a href="' + landing_page_url + '" '
            'style="display:inline-block;margin:16px 0;padding:12px 28px;background:#b12704;'
            'color:#ffffff;text-decoration:none;border-radius:4px;font-size:15px">查看 / 购票</a>'
        )
    return (
        '<div style="max-width:600px;margin:0 auto;font-family:-apple-system,\'PingFang SC\','
        '\'Microsoft YaHei\',sans-serif;color:#222;line-height:1.7">'
        f'<h1 style="font-size:20px;margin:0 0 10px;color:#111">{act}</h1>'
        '<p style="margin:0 0 8px;color:#444">亲爱的用户，您好：</p>'
        f'<p style="margin:0 0 8px;color:#444">{intro}</p>'
        f'{discount_html}'
        f'{cta}'
        '<p style="margin:24px 0 0;font-size:12px;color:#999">如不希望再收到此类邮件，可点击退订。</p>'
        '</div>'
    )


def _build_landing_page_html(activity: str, cta_label: str = "立即购票",
                           form_html: str = None) -> str:
    """生成结构化落地页（替代旧 <p>名字</p> 占位）。

    form_html：Mautic 表单渲染后的 HTML（如 form.cachedHtml），非空时直接内嵌进落地页，
    使「落地页中有填写个人信息提交的表单」真正落地。直接内联 HTML（而非 {form=alias} token），
    规避该 token 经 Mautic API 保存时被内容过滤器剥离（实测 /api/pages/new 会把 {form=...} 整段丢弃）。

    CTA：「立即购票」按钮——若内嵌了表单，则改为提交该表单的 <button form=...>（纯 HTML、
    不依赖 JS，规避 Mautic 内容净化器剥离 onclick）；表单自身也带提交按钮，二者一致导向转化。
    无表单时回落占位 <a href="#">，避免在页面渲染无效外链。
    """
    form_block = ""
    form_id = ""
    if form_html:
        # 给内嵌 Mautic 表单打 id，使下方 CTA 用 form= 关联提交（无需 JS）
        if "<form" in form_html:
            form_html = form_html.replace("<form", '<form id="autopilot-lp-form"', 1)
            form_id = "autopilot-lp-form"
        form_block = (
            '<div style="margin-top:24px;padding:20px;background:#fafafa;'
            'border:1px solid #eee;border-radius:8px">'
            f'{form_html}</div>'
        )
    if form_id:
        cta = (
            f'<button type="submit" form="{form_id}" '
            'style="display:inline-block;margin-top:16px;padding:12px 28px;'
            'background:#b12704;color:#ffffff;text-decoration:none;border:none;border-radius:4px;'
            f'font-size:15px;cursor:pointer">{cta_label}</button>'
        )
    else:
        cta = (
            '<a href="#" style="display:inline-block;margin-top:16px;padding:12px 28px;'
            'background:#b12704;color:#ffffff;text-decoration:none;border-radius:4px">'
            f'{cta_label}</a>'
        )
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<title>{activity}</title></head>'
        '<body style="font-family:-apple-system,\'PingFang SC\',sans-serif;background:#f7f7f5;'
        'margin:0;padding:40px">'
        '<div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:8px;'
        'padding:40px 32px">'
        f'<h1 style="font-size:24px;margin:0 0 12px">{activity}</h1>'
        '<p style="color:#555;line-height:1.7">活动详情与购票入口即将开放，敬请期待。</p>'
        f'{form_block}'
        f'{cta}'
        '</div></body></html>'
    )


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


def ensure_segment(name: str, env: str = "local", timeout: int = 15, project_id: int = None) -> dict:
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

    # 2) 新建（草稿下线）。Mautic 7 的 /api/segments/new 表单不接受 filters / isGlobal
    #    （会报 400: properties: 该表单中不可有额外字段 / operator 无效），故只发最小字段；
    #    筛选条件若需要，后续用 edit 接口补。空筛选 segment 作为 campaign 联系来源足够。
    alias = _aliasify(name)
    body = {"name": name, "alias": alias, "isPublished": True}
    if project_id:
        body["projects"] = [int(project_id)]
    r = _post(base, "/api/segments/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        seg = (r["body"] or {}).get("list") or {}
        new_id = seg.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "alias": alias, "created": True}
    return {"id": None, "error": f"POST /api/segments/new HTTP {r['status']}: {_format_err(r['body'])}"}


def ensure_email(name: str, subject: str = "", env: str = "local", list_id: int = None, email_type: str = "transactional", timeout: int = 15, custom_html: str = None, project_id: int = None) -> dict:
    """按 name 找 email；找不到就 POST 新建（草稿）；返回 {"id","subject","created":bool,"error"?}。
    subject 仅在新建时使用（已有 email 不会覆盖其内容）。
    custom_html：新建时的正文；缺省用结构化模板（不再生成 <p>主题</p> 空壳）。
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
        "isPublished": True,
        "emailType": email_type,
        "customHtml": custom_html if custom_html else _build_email_html(subject or name, name),
    }
    # 只有 list 类型才需要 lists 字段；transactional 不需要
    if email_type == "list" and list_id:
        body["lists"] = [{"id": int(list_id)}]
    if project_id:
        body["projects"] = [int(project_id)]
    r = _post(base, "/api/emails/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        em = (r["body"] or {}).get("email") or {}
        new_id = em.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "created": True}
    return {"id": None, "error": f"POST /api/emails/new HTTP {r['status']}: {_format_err(r['body'])}"}


def ensure_landing_page(name: str, url: str = "", env: str = "local", timeout: int = 15,
                      custom_html: str = None, form_html: str = None, project_id: int = None) -> dict:
    """按 name 找 landing page；找不到就 POST 新建（草稿）；返回 {"id","alias","created":bool,"error"?}。
    正文默认用结构化落地页模板；若给了 url 内嵌 meta-refresh 跳转（mautic_code_mode 标准路径）；
    form_embed 非空时把表单 token 嵌进正文（落地页内嵌表单）。"""
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
        # 落地页 API 返回 title（name 为 None），故按 title/alias 查重
        alias = _aliasify(name)
        existing = None
        for it in items:
            if isinstance(it, dict) and it.get("id"):
                if (it.get("title") == name) or (it.get("alias") == alias):
                    existing = it
                    break
        if existing:
            eid = int(existing["id"])
            # 重推时若提供了 form_html/custom_html，PATCH 更新正文（保证表单内嵌在重推时也能修好，幂等）
            if form_html or custom_html:
                _nh = custom_html or _build_landing_page_html(name, form_html=form_html)
                if url:
                    _nh = _nh.replace("</head>", f'<meta http-equiv="refresh" content="0;url={url}"></head>')
                try:
                    _patch(base, f"/api/pages/{eid}/edit", {"customHtml": _nh}, token, timeout=timeout)
                except Exception:
                    pass
            return {"id": eid, "name": existing.get("title") or existing.get("name"),
                    "alias": existing.get("alias"), "created": False, "updated": bool(form_html or custom_html)}

    alias = _aliasify(name)
    if custom_html:
        html = custom_html
    else:
        html = _build_landing_page_html(name, form_html=form_html)
        if url:
            html = html.replace("</head>", f'<meta http-equiv="refresh" content="0;url={url}"></head>')
    body = {"name": name, "alias": alias, "isPublished": True, "customHtml": html, "title": name}
    if project_id:
        body["projects"] = [int(project_id)]
    r = _post(base, "/api/pages/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        pg = (r["body"] or {}).get("page") or {}
        new_id = pg.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "alias": alias, "created": True}
    return {"id": None, "error": f"POST /api/pages/new HTTP {r['status']}: {_format_err(r['body'])}"}


# =====================================================================
# stage / form 资产：find-or-create（与 segment/email/page 同一套模式）
# ---------------------------------------------------------------------
# 为什么需要：策略规格声明的终点/阶段规则用的是「名称」（如 "engaged"、"SEG_COLD"），
# 而 Mautic 的 lead.changestage / lead.changelist / form.submit 事件要的是资产 ID。
# 没有这层解析，这些终点只能当审计节点透传，永远落不到 Mautic 画布上。
# =====================================================================
def _bucket_items(res: dict, *keys) -> list:
    """Mautic 各 API 返回形态不一（{"stages": {id:obj}} / {"forms":[...]} / 裸 dict），统一成 list。"""
    if not isinstance(res, dict):
        return []
    bucket = None
    for k in keys:
        if res.get(k):
            bucket = res[k]
            break
    if bucket is None:
        bucket = res
    if isinstance(bucket, dict):
        return [v for v in bucket.values() if isinstance(v, dict)]
    if isinstance(bucket, list):
        return [v for v in bucket if isinstance(v, dict)]
    return []


def ensure_stage(name: str, weight: int = None, env: str = "local", timeout: int = 15) -> dict:
    """按 name 找 stage；找不到就 POST 新建（草稿）。返回 {"id","name","created","error"?}。

    Mautic stage 没有 alias 字段，查重只按 name（精确 + 大小写不敏感）。
    新建时 weight 必填（Mautic stage 排序权重），缺省取现有最大 weight + 1，无现有则从 1 起。
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

    res = _get(base, f"/api/stages?search={urllib.parse.quote(name)}&limit=50", token, timeout)
    items = _bucket_items(res, "stages")
    if items:
        target = str(name).strip().lower()
        for it in items:
            if str(it.get("name") or "").strip().lower() == target:
                return {"id": int(it["id"]), "name": it.get("name"), "created": False}
        # 没搜到就拉全量再比对一次（search 对中文/部分字段不生效）
        res_all = _get(base, "/api/stages?limit=200", token, timeout)
        for it in _bucket_items(res_all, "stages"):
            if str(it.get("name") or "").strip().lower() == target and it.get("id"):
                return {"id": int(it["id"]), "name": it.get("name"), "created": False}
        if weight is None:
            weight = max([int(it.get("weight") or 0) for it in items if it.get("id")] or [0]) + 1

    if weight is None:
        weight = 1
    body = {"name": name, "weight": int(weight), "isPublished": True, "description": ""}
    r = _post(base, "/api/stages/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        st = (r["body"] or {}).get("stage") or {}
        new_id = st.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "created": True}
    return {"id": None, "error": f"POST /api/stages/new HTTP {r['status']}: {_format_err(r['body'])}"}


def ensure_form(name: str, env: str = "local", timeout: int = 15, fields: list = None, project_id: int = None) -> dict:
    """按 name 找 form；找不到就 POST 新建（草稿）。

    fields：表单字段列表（Mautic form field 结构）。缺省为「姓名 + 手机 + 邮箱」
    三字段，覆盖「落地页收集个人信息、提交表单作为流程终点」的常见需求；
    传入 fields=[] 则只建空壳（运营补字段）。
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

    if not fields:
        fields = [
            {"label": "姓名", "alias": "firstname", "type": "text", "isRequired": True,
             "mappedField": "firstname", "mappedObject": "contact", "order": 1},
            {"label": "手机", "alias": "phone", "type": "tel", "isRequired": False,
             "mappedField": "phone", "mappedObject": "contact", "order": 2},
            {"label": "邮箱", "alias": "email", "type": "email", "isRequired": True,
             "mappedField": "email", "mappedObject": "contact", "order": 3},
        ]

    alias = _aliasify(name)
    res = _get(base, f"/api/forms?search={urllib.parse.quote(name)}&limit=50", token, timeout)
    items = _bucket_items(res, "forms")
    if items:
        existing = None
        for it in items:
            if it.get("id") and (str(it.get("name") or "").strip() == str(name).strip()
                                 or it.get("alias") == alias):
                existing = it
                break
        if existing:
            return {"id": int(existing["id"]), "name": existing.get("name"),
                    "alias": existing.get("alias"), "created": False}

    body = {
        "name": name,
        "alias": alias,
        "formType": "standalone",
        "isPublished": True,
        "postAction": "return",
        "postActionProperty": "感谢提交，我们的商务同事会尽快与您联系。",
        "fields": fields,
    }
    if project_id:
        body["projects"] = [int(project_id)]
    r = _post(base, "/api/forms/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        fm = (r["body"] or {}).get("form") or {}
        new_id = fm.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "alias": alias, "created": True}
    return {"id": None, "error": f"POST /api/forms/new HTTP {r['status']}: {_format_err(r['body'])}"}


# =====================================================================
# 聚焦项（Focus）/ 资源（Asset）：find-or-create（与 segment/email/page 同一套模式）
# ---------------------------------------------------------------------
# 这是「策略模型可选输出」的落地层：策略声明 focus_items / assets 时，push() 据此在
# Mautic 端一键创建对应实体。两者都是独立 Mautic 实体（非 campaign 事件图节点）：
#   - Asset  = 可下载营销资源（手册/价目表/白皮书），本实例 AssetBundle 可用 → 真实创建；
#   - Focus  = 浮层 CTA（弹窗/通知条/顶部条），本 Mautic 构建若无 FocusBundle 会 404
#             → ensure_focus_item 内部降级为 skipped 标记，不报错、不阻断 campaign 推送。
# =====================================================================
def ensure_asset(name: str, env: str = "local", timeout: int = 15,
                 url: str = None, title: str = None, language: str = "zh_CN",
                 project_id: int = None) -> dict:
    """按 title 找资源(Asset)；找不到就 POST 新建（草稿）。返回 {"id","title","alias","created","error"?}。

    name：资源名（同时作为 Mautic asset title，缺省用 name）。
    url ：远程资源地址（storage_location=remote，无需上传文件）；为空则只建空壳（运营补文件）。
    Mautic Asset API：POST /api/assets/new，必填 title + alias；远程资源再带 storage_location/remotePath。
    """
    if not name:
        return {"id": None, "error": "name 为空"}
    title = title or name
    alias = _aliasify(name)
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

    res = _get(base, f"/api/assets?search={urllib.parse.quote(title)}&limit=10", token, timeout)
    for it in _bucket_items(res, "assets"):
        if it.get("id") and (str(it.get("title") or "").strip() == title.strip()
                             or it.get("alias") == alias):
            return {"id": int(it["id"]), "title": it.get("title"), "alias": it.get("alias"),
                    "created": False}

    body = {
        "title": title,
        "alias": alias,
        "isPublished": True,
        "language": language,
    }
    # 远程资源：免文件上传，直接给下载链接（最常用场景）；本地文件上传需 multipart，留给运营后台补。
    if url:
        body["storage_location"] = "remote"
        body["remotePath"] = url
    if project_id:
        body["projects"] = [int(project_id)]
    r = _post(base, "/api/assets/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        a = (r["body"] or {}).get("asset") or {}
        new_id = a.get("id")
        if new_id:
            return {"id": int(new_id), "title": title, "alias": alias, "created": True}
    return {"id": None, "error": f"POST /api/assets/new HTTP {r['status']}: {_format_err(r['body'])}"}


def ensure_focus_item(name: str, env: str = "local", timeout: int = 15,
                      focus_type: str = "notification", style: str = "modal",
                      content: str = None, cta_url: str = None,
                      project_id: int = None) -> dict:
    """按 name 找聚焦项(Focus)；找不到就 POST 新建（草稿）。返回 {"id","name","alias","created","skipped"?,"error"?}。

    ⚠️ 防御性实现：本 Mautic 构建可能未启用 FocusBundle（/api/focus/* 会 404）。
    若实例无 FocusBundle，POST 返回 404 / 无 focus 实体，则回退为 skipped 标记
    （不报错、不阻断 campaign 推送），由调用方在 ensure_log 标注「实例未安装 FocusBundle」。

    Mautic Focus API：POST /api/focus/new，字段 name/description/type/style/content/properties。
    type ：notification | popup | modal（聚焦项类型）
    style：modal | notification | top_bar | bottom_bar（展示样式；与 type 共同决定外观）
    """
    if not name:
        return {"id": None, "error": "name 为空"}
    alias = _aliasify(name)
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

    # 先查现有（Focus 列表接口同样依赖 FocusBundle；404 时直接走 skipped 分支）
    try:
        res = _get(base, f"/api/focus?search={urllib.parse.quote(name)}&limit=10", token, timeout)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "skipped": True,
                "reason": f"FocusBundle 可能未安装（查询失败）: {e}"}
    existing = None
    if isinstance(res, dict):
        for it in _bucket_items(res, "focus", "items"):
            if it.get("id") and (str(it.get("name") or "").strip() == name.strip()
                                 or it.get("alias") == alias):
                existing = it
                break
    if existing:
        return {"id": int(existing["id"]), "name": existing.get("name"),
                "alias": existing.get("alias"), "created": False}

    body = {
        "name": name,
        "alias": alias,
        "description": "",
        "type": focus_type,
        "style": style,
        "isPublished": True,
        "content": content or "",
        "properties": {},
    }
    if cta_url:
        body["properties"] = {"cta_url": cta_url}
    r = _post(base, "/api/focus/new", body, token, timeout=timeout)
    if r["status"] in (200, 201):
        f = (r["body"] or {}).get("focus") or (r["body"] or {}).get("item") or {}
        new_id = f.get("id")
        if new_id:
            return {"id": int(new_id), "name": name, "alias": alias, "created": True}
        # 201 但无 focus 实体（极少）：当未安装处理
    # 404 / 无 focus 实体 → 视为实例未安装 FocusBundle，安全降级
    return {"id": None, "skipped": True,
            "reason": f"FocusBundle 可能未安装（POST /api/focus/new HTTP {r['status']}）"}


def ensure_project(name: str, env: str = "local", timeout: int = 60) -> int:
    """按 name 找/建 Mautic project（/api/v2/projects，Basic 认证）。返回 int id 或 None。
    project 与 cockpit program 一一对应（program 生成时建一个，所有资产挂其下）。
    名字含 goal_id 保证唯一；同名复用避免重复建。"""
    if not name:
        return None
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return None
    base = cfg["base_url"]
    auth = _basic_header(cfg)
    if not auth:
        return None
    # 1) 找现有（列全量按 name 精准匹配；PoC 项目数少，分页足够）
    try:
        res = _v2_req("GET", base, "/api/v2/projects?itemsPerPage=200", auth=auth, timeout=timeout)
    except Exception:  # noqa: BLE001
        res = None
    body = (res or {}).get("body") if isinstance(res, dict) else None
    if isinstance(body, dict):
        for m in (body.get("member") or []):
            if isinstance(m, dict) and m.get("id") and m.get("name") == name:
                return int(m["id"])
    # 2) 新建
    r = _v2_req("POST", base, "/api/v2/projects", {"name": name}, auth=auth, timeout=timeout)
    if r.get("status") == 201:
        bid = (r.get("body") or {}).get("id")
        if bid:
            return int(bid)
    return None


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
    读取 Mautic 已存在的资产（email / segment / landingpage / form），供驾驶舱判断
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
        return {"available": False, "emails": [], "segments": [], "pages": [], "forms": []}
    base = cfg["base_url"]
    client_id, client_secret = _oauth_creds(cfg)
    if not client_id or not client_secret:
        return {"available": False, "emails": [], "segments": [], "pages": [], "forms": []}
    try:
        token = _get_token(base, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e), "emails": [], "segments": [], "pages": [], "forms": []}

    out = {"available": True, "emails": [], "segments": [], "pages": [], "forms": []}
    # (输出键, API 路径, 响应中承载资产的键名)
    # 实测 Mautic 7：emails→{"emails":{id:{...}}}；segments→{"lists":{id:{...}}}；pages→{"pages":[{...}]}
    # 全量列表较慢（emails ~18s / segments ~15s），故拉取超时放宽到 45s。
    endpoints = (
        ("emails", "/api/emails?limit=0", "emails"),
        ("segments", "/api/segments?limit=0", "lists"),
        ("pages", "/api/pages?limit=0", "pages"),
        ("forms", "/api/forms?limit=0", "forms"),
    )
    for key, path, bucket_key in endpoints:
        res = _get(base, path, token, timeout=45)
        if res is None:  # 连接失败 → 整体判定为未连接
            return {"available": False, "reason": "连接失败", "emails": [], "segments": [], "pages": [], "forms": []}
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


def invalidate_asset_cache() -> None:
    """推送成功后使资产索引缓存失效，让驾驶舱卡片外链立即解析（否则要等 _ASSET_CACHE_TTL）。

    push() 新建/复用 email/segment/landingpage 后，_mautic_asset_index() 仍可能命中 300s 旧缓存，
    导致刚建出的邮件/落地页 ref 解析不到外链。这里清掉缓存，下次渲染即拉取最新资产列表。
    锁保护；异常静默。"""
    with _ASSET_LOCK:
        _ASSET_CACHE["ts"] = 0.0
        _ASSET_CACHE["data"] = None


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


def _fetch_form_html(base_url: str, form_id, token: str, timeout: int = 60) -> str:
    """取表单的渲染 HTML（cachedHtml）用于内嵌落地页。

    Mautic 表单经 API 保存时即生成 cachedHtml（实测新表单创建后立即可取），
    但个别环境可能缓存未即时生成——故失败时先 PATCH 发布再重试一次。
    任何异常/空值都返回 None（调用方据此决定是否告警，不会抛出）。"""
    try:
        _fobj = _get(base_url, f"/api/forms/{form_id}", token, timeout=timeout)
        _html = (_fobj.get("form") or {}).get("cachedHtml") if isinstance(_fobj, dict) else None
        if _html:
            return _html
        # 兜底：发布后重新拉取
        try:
            _patch(base_url, f"/api/forms/{form_id}/edit", {"isPublished": True}, token, timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        _fobj2 = _get(base_url, f"/api/forms/{form_id}", token, timeout=timeout)
        return (_fobj2.get("form") or {}).get("cachedHtml") if isinstance(_fobj2, dict) else None
    except Exception:  # noqa: BLE001
        return None


def find_existing_campaign(base_url: str, token: str, name: str,
                           project_id: int = None, timeout: int = 60) -> dict | None:
    """查找同名（且与 project 关联，若提供）的已存在 campaign，用于 push 幂等复用。

    返回最优可复用副本的 {id, name, isPublished, events, dup_count}；无匹配返回 None。
    选择策略（规避孤儿/草稿副本被误复用）：已发布 > 事件数多 > id 大（最新）。
    """
    data = _get(base_url, "/api/campaigns?limit=200", token, timeout=timeout)
    if not isinstance(data, dict):
        return None
    campaigns = data.get("campaigns") or {}
    if not isinstance(campaigns, dict):
        return None
    name_matches = []
    for cid, c in campaigns.items():
        if not isinstance(c, dict) or c.get("name") != name:
            continue
        c2 = dict(c)
        c2["id"] = c2.get("id") or cid
        name_matches.append(c2)
    if not name_matches:
        return None
    # 若提供 project_id，优先复用关联到该 project 的副本；无关联副本时回退到任意同名副本
    if project_id is not None:
        proj_hits = []
        for c in name_matches:
            proj_ids = set()
            for p in (c.get("projects") or []):
                proj_ids.add(p.get("id") if isinstance(p, dict) else p)
            try:
                if int(project_id) in proj_ids:
                    proj_hits.append(c)
            except (TypeError, ValueError):
                pass
        if proj_hits:
            name_matches = proj_hits
    matches = name_matches

    def _score(c):
        try:
            _cid = int(c.get("id") or 0)
        except (TypeError, ValueError):
            _cid = 0
        return (1 if c.get("isPublished") else 0, len(c.get("events") or []), _cid)

    matches.sort(key=_score, reverse=True)
    best = matches[0]
    return {
        "id": best.get("id"),
        "name": best.get("name"),
        "isPublished": best.get("isPublished"),
        "events": len(best.get("events") or []),
        "dup_count": len(matches),
    }


def push(proposal: dict, env: str = "local", approved: bool = False, project_id: int = None) -> dict:
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
    # 优先用结构化中文名（活动名-波次意图-票种），缺省回落内部 cid
    goal_name = (proposal.get("campaign") or {}).get("name") or goal_cid
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
            rseg = ensure_segment(seg_name, env=env, timeout=60, project_id=project_id)
            ensure_log.append({"asset": "segment", "name": seg_name, **rseg})
            if rseg.get("id"):
                seg_id = rseg["id"]
                # 已存在(reuse)的 segment 在 POST body 没带 projects → 补关联
                if project_id and not rseg.get("created"):
                    _attach_project(base, "segments", seg_id, project_id, token)
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

    # 0.2 落地页 + 邮件资产 ensure（真实内容，替代 EM_cX_PLACEHOLDER 空壳）
    str_ref = proposal.get("strategy_ref") or {}
    campaign_name = (proposal.get("campaign") or {}).get("name") or goal_cid
    lp_url = (proposal.get("campaign") or {}).get("landing_page_url") or ""
    discount = str_ref.get("discount")

    # 0.2.0 表单（如策略要求落地页+表单）：先建表单，落地页内嵌表单 token。
    # 判断依据：main_endpoint.form 或 strategy_ref.form_ref 任一声明即视为需要。
    _camp_strategy = (proposal.get("campaign") or {}).get("strategy") or {}
    _mep = _camp_strategy.get("main_endpoint") or {}
    _needs_form = bool(
        _mep.get("form") or str_ref.get("form_ref")
        or any((ev.get("type") == "form.submit")
               for ev in (proposal.get("mautic_events") or [])))
    form_id = None
    form_html = None
    if _needs_form:
        # 优先复用编译期 asset_resolver 已按声明名建好的表单（如 FORM_甲A足球赛，
        # 遵循 CSTS「FORM_」命名规范），使其进入 ensure_log 并被推送发布循环自动上线，
        # 与邮件/落地页行为一致；未声明表单名时再回退到「{活动名}-表单」自动命名。
        # 这样避免「编译期建一份 + 推送期又建一份同名不同 id」导致的孤儿草稿。
        _declared_form = str_ref.get("form_ref") or _mep.get("form") or ""
        form_name = _declared_form.strip() or f"{campaign_name}-表单"
        rform = ensure_form(form_name, env=env, timeout=60, project_id=project_id)
        ensure_log.append({"asset": "form", "name": form_name, **rform})
        if rform.get("id"):
            form_id = rform["id"]
            if project_id and not rform.get("created"):
                _attach_project(base, "forms", form_id, project_id, token)
            # 取表单渲染后的 HTML（cachedHtml）直接内嵌进落地页，规避 {form=alias} token 被 Mautic 剥离。
            # cachedHtml 在新建/已存在表单上均已填充（实测新表单创建后立即可取，长度 ~3k）；
            # 加「发布后重试」兜底，防止个别 Mautic 环境缓存未生成导致 form_html 为空、表单被静默丢弃。
            form_html = _fetch_form_html(base, form_id, token, timeout=60)
            if not form_html:
                ensure_log.append({"asset": "form_html_fetch", "warn": "cachedHtml 为空，落地页将不内嵌表单"})

    # 0.2.1 落地页：结构化 HTML + 可选 meta-refresh 跳转；邮件 CTA 指向它
    # 表单型（form.submit 终点）落地页：不注入 meta-refresh 外跳——否则会顶到无效路由
    # （如原 landing_page_url=http://localhost:8080/s/c1-zh，/s/ 是 Mautic 后台前缀→报错），
    # 由内嵌 FORM 承接转化；只有「非表单型且显式给了外部跳转地址」才保留 meta-refresh。
    lp_redirect_url = lp_url if (lp_url and not _needs_form) else ""
    lp_name = f"{campaign_name}-落地页"
    lp_public_url = ""
    rlp = ensure_landing_page(
        lp_name, url=lp_redirect_url, env=env, timeout=60, form_html=form_html, project_id=project_id)
    ensure_log.append({"asset": "landing_page", "name": lp_name, **rlp})
    if rlp.get("id"):
        if project_id and not rlp.get("created"):
            _attach_project(base, "pages", rlp["id"], project_id, token)
        # Mautic 落地页公开 URL：{base}/{alias}（注意：/s/ 是后台(admin)前缀，
        # 公开访问落地页不需要 /s/，否则会落到后台路由返回站点首页而非落地页内容）
        lp_public_url = f"{base}/{rlp.get('alias') or _aliasify(lp_name)}"

    # 0.2.1b 表单终点绑定：把真实 form_id 写回事件图 form.submit 节点，
    # 重新编译出含 forms:[id] 的 Mautic 事件（offline 编译时 form_id 为空、节点被丢弃）。
    # 必须在邮件绑定前完成，避免覆盖 email 真实 id。
    if form_id and isinstance(proposal.get("graph"), list):
        for n in proposal["graph"]:
            if isinstance(n, dict) and n.get("type") in ("form.submit", "decision.form_submit"):
                (n.setdefault("params", {}))["form_id"] = form_id
        try:
            from plan_compiler import to_mautic_events
            _re = to_mautic_events(proposal["graph"], _camp_strategy)
            proposal["mautic_events"] = _re["events"]
            proposal["mautic_canvas"] = _re["canvasSettings"]
        except Exception as _exc:  # noqa: BLE001
            ensure_log.append({"asset": "form_recompile", "error": str(_exc)})

    # 0.2.2 邮件：主 / 提醒各一封（结构化名 + 真实正文 + CTA 指向落地页）
    main_email_name = campaign_name
    followup_email_name = f"{campaign_name}-提醒"
    email_id_cache: dict = {}

    def _resolve_email_id(name: str, subject: str, is_followup: bool):
        if not name:
            return None
        if name in email_id_cache:
            return email_id_cache[name]
        html = _build_email_html(subject, campaign_name, discount, lp_public_url, is_followup)
        rem = ensure_email(name, subject=subject, env=env, list_id=seg_id,
                           custom_html=html, timeout=60, project_id=project_id)
        ensure_log.append({"asset": "email", "name": name, **rem})
        if rem.get("id") and project_id and not rem.get("created"):
            _attach_project(base, "emails", rem["id"], project_id, token)
        email_id_cache[name] = rem.get("id")
        return rem.get("id")

    if isinstance(proposal.get("mautic_events"), list):
        for ev in proposal["mautic_events"]:
            props = ev.get("properties") or {}
            if ev.get("type") == "email.send" and (props.get("email") in (0, None, "")):
                # 主邮件 vs 提醒邮件：用 subject 含「提醒」判定，各建一封独立邮件
                subject = (ev.get("name") or "").replace("发送邮件：", "")
                is_followup = ("提醒" in subject) or ("followup" in subject.lower())
                name = followup_email_name if is_followup else main_email_name
                eid = _resolve_email_id(name, subject, is_followup)
                if eid:
                    props["email"] = eid
            ev["properties"] = props

    # 0.2.3 email.click 决策回填：绑定其父 email.send 的邮件 id。
    # plan_compiler 里 email.click 的 email 取自 strategy.email_ref（占位字符串 → int 失败 → 0），
    # 不回填会导致 Mautic UI 里「决策：是否点击」显示未绑邮件、点击分支不工作。
    if isinstance(proposal.get("mautic_events"), list):
        ev_email = {}
        for ev in proposal["mautic_events"]:
            if ev.get("type") == "email.send":
                ev_email[ev.get("id")] = (ev.get("properties") or {}).get("email")
        for ev in proposal["mautic_events"]:
            if ev.get("type") != "email.click":
                continue
            props = ev.get("properties") or {}
            if props.get("email") in (0, None, ""):
                parent = ev.get("parent")
                pid = parent if not isinstance(parent, dict) else (parent or {}).get("id")
                if pid and ev_email.get(pid):
                    props["email"] = ev_email[pid]
                    ev["properties"] = props

    # 0.2.4 可选：聚焦项（Focus）/ 资源（Asset）实体（策略声明的「可选输出」）
    # 仅当 proposal 含 focus_items / assets 才执行；缺省不影响既有流程、零额外请求。
    # - Asset 实体：本实例 AssetBundle 可用 → 真实 create（远程资源免上传）；
    # - Focus 实体：本 Mautic 构建若无 FocusBundle 会 404 → ensure_focus_item 内部 skipped，
    #   不报错、不阻断 campaign 推送，仅 ensure_log 标注「实例未安装 FocusBundle」。
    _fi_items = proposal.get("focus_items") or []
    _as_items = proposal.get("assets") or []
    if _fi_items or _as_items:
        for fi in _fi_items:
            if not isinstance(fi, dict):
                continue
            fi_name = fi.get("name") or ""
            if not fi_name:
                ensure_log.append({"asset": "focus_item", "warn": "聚焦项缺 name，已跳过"})
                continue
            rfi = ensure_focus_item(
                fi_name, env=env, timeout=60,
                focus_type=fi.get("type", "notification"), style=fi.get("style", "modal"),
                content=fi.get("content"), cta_url=fi.get("cta_url"), project_id=project_id)
            ensure_log.append({"asset": "focus_item", "name": fi_name, **rfi})
        for a in _as_items:
            if not isinstance(a, dict):
                continue
            a_name = a.get("name") or a.get("title") or ""
            if not a_name:
                ensure_log.append({"asset": "asset", "warn": "资源缺 name/title，已跳过"})
                continue
            ra = ensure_asset(
                a_name, env=env, timeout=60, url=a.get("url"),
                title=a.get("title"), language=a.get("language", "zh_CN"),
                project_id=project_id)
            ensure_log.append({"asset": "asset", "name": a_name, **ra})

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

    # 1) 幂等复用：若已存在同名（同 project）campaign，直接复用，不再 POST /campaigns/new 制造副本。
    #    ensure_* 资产已按 name 复用，故「重复推送」唯一会增生副本的就是 campaign 本身。
    reused = False
    existing = find_existing_campaign(base, token, goal_name, project_id=project_id, timeout=60)
    if existing and existing.get("id"):
        new_id = existing["id"]
        reused = True
        steps.append({
            "step": "reuse_existing_campaign",
            "campaign_id": new_id,
            "name": goal_name,
            "isPublished": existing.get("isPublished"),
            "dup_count": existing.get("dup_count"),
            "note": "已存在同名 campaign，复用而非新建，避免重复副本（幂等）",
        })
    else:
        create_body = {"name": goal_name, "isPublished": True}
        if project_id:
            create_body["projects"] = [int(project_id)]
        if proposal.get("mautic_events"):
            create_body["events"] = proposal["mautic_events"]
        if proposal.get("mautic_canvas"):
            create_body["canvasSettings"] = proposal["mautic_canvas"]
        if proposal.get("mautic_lists"):
            create_body["lists"] = proposal["mautic_lists"]
        r1 = _post(base, "/api/campaigns/new", create_body, token, timeout=60)
        steps.append({"step": "create_campaign_with_events", **r1})
        new_id = None
        if isinstance(r1["body"], dict):
            new_id = (r1["body"].get("campaign") or {}).get("id")

    # 2) 审批通过后上线：campaign + 依赖资产（email / landing_page）一并发布
    if new_id and approved:
        publish_log = []
        # 2.1 依赖资产先发布（草稿 → 上线，否则 campaign 上线但引用的是草稿资产）
        for item in ensure_log:
            aid = item.get("id")
            asset = item.get("asset")
            if not aid:
                continue
            if asset == "email":
                r = _patch(base, f"/api/emails/{aid}/edit", {"isPublished": True}, token, timeout=60)
            elif asset == "landing_page":
                r = _patch(base, f"/api/pages/{aid}/edit", {"isPublished": True}, token, timeout=60)
            elif asset == "form":
                # 表单上线：否则公开提交端点 /form/submit?formId=X 会拒绝草稿表单的提交
                r = _patch(base, f"/api/forms/{aid}/edit", {"isPublished": True}, token, timeout=60)
            elif asset == "asset":
                # 资源上线：草稿资源无公开下载页，发布后才可被邮件 CTA 引用
                r = _patch(base, f"/api/assets/{aid}/edit", {"isPublished": True}, token, timeout=60)
            elif asset == "focus_item":
                # 聚焦项上线（仅当实例有 FocusBundle 且已成功创建；skipped 项无 id 已被 continue 过滤）
                r = _patch(base, f"/api/focus/{aid}/edit", {"isPublished": True}, token, timeout=60)
            elif asset == "segment":
                # 联系人来源 segment 必须上线：未发布的 segment 不会吸纳联系人，
                # 会导致 campaign 上线却无人进入流程（功能性失效，而非单纯草稿态）。
                r = _patch(base, f"/api/segments/{aid}/edit", {"isPublished": True}, token, timeout=60)
            else:
                continue
            publish_log.append({"asset": asset, "id": aid, **r})
        # 2.2 campaign 上线
        # Mautic 7：发布用 PATCH /api/campaigns/{id}/edit（POST/404，PUT/500，PATCH 才能正确处理）。
        # 幂等：复用且已发布的副本跳过 PATCH（避免对正常副本做无意义写；
        # 若复用的是未发布副本则仍尝试上线，孤儿副本会 400 但被下方 except 捕获）。
        if reused and existing.get("isPublished"):
            steps.append({"step": "publish_campaign", "skipped": "reused_already_published",
                          "campaign_id": new_id})
        else:
            try:
                r3 = _patch(base, f"/api/campaigns/{new_id}/edit",
                            {"isPublished": True}, token, timeout=60)
                steps.append({"step": "publish_campaign", **r3})
            except Exception as e:  # noqa: BLE001
                steps.append({"step": "publish_campaign", "status": 0, "body": f"网络/连接错误: {e}"})
        steps.append({"step": "publish_assets", "log": publish_log})

    return {
        "dry_run": False, "env": env, "campaign_id": new_id, "reused": reused,
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


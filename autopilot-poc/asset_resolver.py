"""
asset_resolver — 把策略规格里声明的 stage / segment / form「名称或 ref」解析成真实 Mautic 资产 ID
==================================================================================================
背景（为什么单独一层）
----------------------
策略规格（StrategySpec）里，分支终点 / 阶段升降级声明的是**业务名称**，例如：

    {"stage": "engaged"}                  # 阶段名
    {"segment": "SEG_COLD"}               # 分组 ref
    {"form": "FORM_报名"}                 # 表单名

但 Mautic 侧这三个动作要的是**数字 ID**：

    lead.changestage   properties = {"stage": <stage_id>}
    lead.changelist    properties = {"addToLists": [<segment_id>], "removeFromLists": []}
    form.submit        properties = {"forms": [<form_id>]}

没有这层解析，plan_compiler 只能把它们当审计节点透传（`_MAUTIC_TYPE = None`），
于是「终点是阶段/分组/表单」在 Mautic 画布上根本不存在。

设计原则
--------
1. **永不抛异常**：解析失败最多让事件不落 Mautic（退化成改动前的审计行为），
   绝不能因为 Mautic 抖动就让 compile() 挂掉。
2. **离线安全**：拿不到 token / 连不上 → status="unresolved"，不建事件，记 warning。
3. **缺资产自动建草稿**：按用户决策「自动建草稿并记 warning」，新建的资产
   isPublished=False，warning 里写明「已自动建草稿，需运营补内容后上线」。
4. **可注入**：测试与离线场景用 `set_resolver()` 注入假解析器，不碰网络。
5. **进程内缓存**：同一 (kind, ref) 5 分钟内不重复打 Mautic。

用法
----
    from asset_resolver import resolve
    r = resolve("stage", "engaged")
    r.id            # 3 或 None
    r.status        # "reused" / "created" / "unresolved" / ...
    r.warning()     # 需要提示给运营的一行中文；无需提示时返回 None
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# 支持的资产种类 → (Mautic 事件 type, 展示名, 需要的 properties 键名)
ASSET_KINDS = {
    "stage": {"event": "lead.changestage", "label": "阶段", "id_key": "stage_id"},
    "segment": {"event": "lead.changelist", "label": "分组", "id_key": "segment_id"},
    "form": {"event": "form.submit", "label": "表单", "id_key": "form_id"},
}

# 状态
EMPTY = "empty"              # 没声明
ID_REF = "id_ref"            # 声明本身就是数字 ID
INLINE_ID = "inline_id"      # dict 里带了 id
REUSED = "reused"            # 命中已有资产
CREATED = "created"          # 自动新建了草稿
UNRESOLVED = "unresolved"    # 查不到也没建成（Mautic 不可达 / 无凭证 / 建失败）

_CACHE_TTL = 300  # 秒
_CACHE: dict = {}
_LOCK = threading.Lock()

# 全局开关（可用环境变量关掉，便于离线跑批 / 单元测试）
_ENV_ENABLED = os.environ.get("ASSET_RESOLVE", "1").strip().lower() not in ("0", "false", "no", "off")
_ENV_AUTOCREATE = os.environ.get("ASSET_AUTO_CREATE", "1").strip().lower() not in (
    "0", "false", "no", "off")

# 注入的解析器（测试用）：fn(kind, name, allow_create, env) -> dict|None
_RESOLVER_FN = None


@dataclass
class AssetRef:
    """一次资产解析的结果（全部字段都可 JSON 序列化）。"""
    kind: str
    ref: object                      # 规格里声明的原始值
    name: str = ""                   # 规范化后的资产名（用于查重/新建）
    id: Optional[int] = None         # 解析出的 Mautic 资产 ID
    status: str = EMPTY
    created: bool = False
    message: str = ""                # 诊断信息（错误原因等）
    source: str = "declared"         # 解析来源：declared / cache / mautic / injected

    def resolved(self) -> bool:
        return self.id is not None

    def warning(self) -> Optional[str]:
        """需要提示给运营的一行中文；无需提示返回 None。"""
        label = ASSET_KINDS.get(self.kind, {}).get("label", self.kind)
        if self.status == CREATED:
            if self.kind == "form":
                # 表单与邮件/落地页一致：推送上线时由 push() 的 ensure_log 发布循环自动上线，
                # 故编译期只提示「已建草稿」，不再要求运营手动发布。
                return (f"{label}「{self.name}」在 Mautic 不存在，已自动建草稿（id={self.id}）；"
                        f"推送上线时会自动发布（与邮件/落地页一致）")
            return (f"{label}「{self.name}」在 Mautic 不存在，已自动建草稿（id={self.id}）；"
                    f"草稿未上线，需运营补内容后手动发布")
        if self.status == UNRESOLVED:
            why = f"（{self.message}）" if self.message else ""
            return (f"{label}「{self.name}」未解析到 Mautic 资产 ID，该动作不落 Mautic 事件{why}；"
                    f"请在 Mautic 建好同名资产或在规格里直接写 ID")
        return None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "ref": self.ref, "name": self.name, "id": self.id,
            "status": self.status, "created": self.created, "message": self.message,
            "source": self.source,
        }


def _as_int(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    m = re.fullmatch(r"\s*(\d+)\s*", str(v or ""))
    return int(m.group(1)) if m else None


def _split_ref(ref) -> tuple:
    """规格声明值 → (name, inline_id, raw_kind)
    支持：数字 / "12" / "id:12" / {"id":12} / {"ref":"X"} / {"name":"X","id":3} / 纯名字。"""
    if ref is None or ref == "" or ref == [] or ref == {}:
        return "", None, EMPTY
    if isinstance(ref, dict):
        iid = _as_int(ref.get("id") or ref.get("asset_id") or ref.get("mautic_id"))
        nm = ref.get("name") or ref.get("ref") or ref.get("title") or ""
        if not nm and iid is None:
            return "", None, EMPTY
        return str(nm).strip(), iid, (INLINE_ID if iid is not None else "name")
    if isinstance(ref, (list, tuple)):
        ref = ref[0] if ref else ""
    iid = _as_int(ref)
    if iid is not None:
        return str(iid), iid, ID_REF
    s = str(ref).strip()
    m = re.match(r"^(?:id|ID|#)\s*[:：]?\s*(\d+)$", s)
    if m:
        return s, int(m.group(1)), ID_REF
    return s, None, "name"


def set_resolver(fn) -> None:
    """注入解析器（测试 / 离线）：fn(kind, name, allow_create, env) -> dict|None。
    返回的 dict 形如 {"id": 3, "name": "...", "created": bool, "error": "..."}。"""
    global _RESOLVER_FN
    _RESOLVER_FN = fn


def clear_resolver() -> None:
    global _RESOLVER_FN
    _RESOLVER_FN = None


def reset_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _lookup_mautic(kind: str, name: str, allow_create: bool, env: str, timeout: int) -> dict:
    """真的去 Mautic 查/建。返回 mautic_client.ensure_* 的原始 dict；任何异常都兜成 error dict。"""
    try:
        import mautic_client as mc
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"mautic_client 不可用: {e}"}
    try:
        if kind == "stage":
            # allow_create=False → 只查：把 weight 传 0 不影响查重分支，
            # 但为避免误建，这里直接走一个只查路径（ensure_stage 在未命中且无 weight 时会新建）。
            if not allow_create:
                return _find_only(mc, kind, name, env, timeout)
            return mc.ensure_stage(name, env=env, timeout=timeout)
        if kind == "segment":
            if not allow_create:
                return _find_only(mc, kind, name, env, timeout)
            return mc.ensure_segment(name, env=env, timeout=timeout)
        if kind == "form":
            if not allow_create:
                return _find_only(mc, kind, name, env, timeout)
            return mc.ensure_form(name, env=env, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"ensure_{kind} 异常: {e}"}
    return {"id": None, "error": f"不支持的资产类型: {kind}"}


# 只查不建的 API 路径（allow_create=False 时用）
_FIND_PATHS = {"stage": "/api/stages", "segment": "/api/segments", "form": "/api/forms"}
_FIND_BUCKETS = {"stage": "stages", "segment": "lists", "form": "forms"}


def _find_only(mc, kind: str, name: str, env: str, timeout: int) -> dict:
    """只查不建：找不到就返回无 id 的结果（不写任何东西进 Mautic）。"""
    import urllib.parse
    try:
        cfg = mc.load_config(env)
        base = cfg["base_url"]
        cid, sec = mc._oauth_creds(cfg)
        if not cid or not sec:
            return {"id": None, "error": "未配置 OAuth client_id/secret"}
        token = mc._get_token(base, cid, sec)
    except Exception as e:  # noqa: BLE001
        return {"id": None, "error": f"连接 Mautic 失败: {e}"}
    path = _FIND_PATHS.get(kind)
    bucket = _FIND_BUCKETS.get(kind, kind + "s")
    res = mc._get(base, f"{path}?search={urllib.parse.quote(name)}&limit=50", token, timeout)
    items = mc._bucket_items(res, bucket) if hasattr(mc, "_bucket_items") else []
    if kind == "segment":
        hit = mc._find_by_name(items, name) if items else None
    else:
        hit = None
        low = str(name).strip().lower()
        alias = mc._aliasify(name)
        for it in items:
            if not it.get("id"):
                continue
            if str(it.get("name") or "").strip().lower() == low or it.get("alias") == alias:
                hit = it
                break
    if hit:
        return {"id": int(hit["id"]), "name": hit.get("name") or name, "created": False}
    return {"id": None, "error": "Mautic 中不存在同名资产（未自动创建）"}


def resolve(kind: str, ref, env: str = "local", allow_create: Optional[bool] = None,
            timeout: int = 10, use_cache: bool = True) -> AssetRef:
    """把规格声明的 ref 解析成 Mautic 资产 ID。永不抛异常。"""
    if kind not in ASSET_KINDS:
        return AssetRef(kind=kind, ref=ref, name=str(ref or ""), status=UNRESOLVED,
                        message=f"不支持的资产类型: {kind}")
    name, inline_id, raw_kind = _split_ref(ref)
    if raw_kind == EMPTY:
        return AssetRef(kind=kind, ref=ref, status=EMPTY)
    if inline_id is not None:
        return AssetRef(kind=kind, ref=ref, name=name or str(inline_id), id=inline_id,
                        status=(ID_REF if raw_kind == ID_REF else INLINE_ID), source="declared")

    if not _ENV_ENABLED:
        return AssetRef(kind=kind, ref=ref, name=name, status=UNRESOLVED,
                        message="资产解析已关闭（ASSET_RESOLVE=0）")
    if allow_create is None:
        allow_create = _ENV_AUTOCREATE

    key = (kind, name, env, bool(allow_create))
    if use_cache:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and (time.time() - hit[0]) < _CACHE_TTL:
                r = AssetRef(**hit[1])
                r.source = "cache"
                return r

    if _RESOLVER_FN is not None:
        try:
            raw = _RESOLVER_FN(kind, name, allow_create, env) or {}
        except Exception as e:  # noqa: BLE001
            raw = {"id": None, "error": f"注入解析器异常: {e}"}
        src = "injected"
    else:
        raw = _lookup_mautic(kind, name, allow_create, env, timeout)
        src = "mautic"

    if not isinstance(raw, dict):
        raw = {"id": None, "error": f"解析器返回非 dict: {type(raw).__name__}"}
    rid = _as_int(raw.get("id"))
    if rid:
        out = AssetRef(kind=kind, ref=ref, name=str(raw.get("name") or name), id=rid,
                       status=(CREATED if raw.get("created") else REUSED),
                       created=bool(raw.get("created")), source=src)
    else:
        out = AssetRef(kind=kind, ref=ref, name=name, status=UNRESOLVED,
                       message=str(raw.get("error") or "未知原因"), source=src)

    if use_cache:
        with _LOCK:
            _CACHE[key] = (time.time(), out.to_dict())
    return out


def resolve_endpoint(fields: dict, env: str = "local", allow_create: Optional[bool] = None,
                     timeout: int = 10) -> dict:
    """对终点/规则里声明的 stage / segment / form 一次性解析。
    返回 {kind: AssetRef}（只含声明过的种类）。"""
    out = {}
    if not isinstance(fields, dict):
        return out
    for kind in ASSET_KINDS:
        v = fields.get(kind)
        if v in (None, "", [], {}):
            continue
        out[kind] = resolve(kind, v, env=env, allow_create=allow_create, timeout=timeout)
    return out


def summarize(results: dict) -> list:
    """把解析结果压成可写进 proposal 的 dict 列表（供驾驶舱/审批展示）。"""
    return [r.to_dict() for r in (results or {}).values() if isinstance(r, AssetRef)]

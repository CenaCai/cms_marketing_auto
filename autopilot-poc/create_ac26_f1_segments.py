"""
create_ac26_f1_segments.py — 按 tag 条件创建赛事分群（Mautic 7）

背景：Mautic 7 的 /api/segments/new 与 /api/segments/{id}/edit 均**不接受 filters**
（PUT partial 会 500；filters 字段被 form 静默丢弃，回读仍是 a:0:{}）。
故本脚本直连 MariaDB 写 lead_lists.filters（PHP serialize 格式）。

前置：已备份 lead_lists_bak_<ts>（本脚本会再校验备份存在）。

用法：
    python create_ac26_f1_segments.py --dry-run     # 只打印 SQL
    python create_ac26_f1_segments.py --apply       # 真正写入
"""
import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime

MARIADB = r"C:\Program Files\MariaDB 12.3\bin\mariadb.exe"
DB = dict(host="127.0.0.1", port=3306, user="mautic", password="mautic", db="mautic")


# ------------------------------------------------------------------ PHP serialize
def php_serialize(obj) -> str:
    """把 Python 对象序列化成 PHP 的 serialize() 格式（Mautic 的 filters 列是 longtext/PHP序列化）。

    注意两个易错点（本脚本已用 php -r 实测验证，踩过一次）：
      1. **字符串键分号不可省**：`s:4:"glue";` 少一个分号就会在 offset 处解析失败。
      2. **列表索引必须是 i:N; 形式**：`a:1:{i:0;...}`，写成 `{0:...}` 会让
         unserialize 在第一个 offset 直接 false（数组的键是 int 且要带类型前缀）。
    """
    if isinstance(obj, dict):
        n = len(obj)
        parts = []
        for k, v in obj.items():
            # 注意：php_serialize(k) 已经自带结尾分号（如 s:4:"glue";），
            # 这里**不能再加分隔符**，否则得到 s:4:"glue";:s:3:"and"; 而非法。
            parts.append(f"{php_serialize(k)}{php_serialize(v)}")
        return "a:%d:{%s}" % (n, "".join(parts))
    if isinstance(obj, list):
        n = len(obj)
        parts = [f"i:{i};{php_serialize(v)}" for i, v in enumerate(obj)]
        return "a:%d:{%s}" % (n, "".join(parts))
    if isinstance(obj, bool):
        return "b:%d;" % (1 if obj else 0)
    if obj is None:
        return "N;"
    if isinstance(obj, int):
        return "i:%d;" % obj
    if isinstance(obj, float):
        return "d:%s;" % repr(obj)
    if isinstance(obj, str):
        b = obj.encode("utf-8")
        return 's:%d:"%s";' % (len(b), b.decode("utf-8"))
    raise TypeError(f"不支持的类型: {type(obj)}")


# ------------------------------------------------------------------ filter 构造
def tag_filter(tag_name: str, exclude: bool = False, glue: str = "and"):
    """一个「标签」筛选条件。

    object 必须为 'lead'（ListModel::getChoiceFields 里 tags 挂在 lead 下，
    默认的 'behaviors' 取不到 → operator 校验必失败）。
    值字段是 properties.filter（不是顶层的 value）。
    """
    return {
        "glue": glue,
        "object": "lead",
        "type": "tags",
        "operator": "!in" if exclude else "in",
        "field": "tags",
        "properties": {"filter": [tag_name], "display": [tag_name]},
    }


# ------------------------------------------------------------------ 分群定义
# 「未点击」语义：意图标签 ∧ 未打任何触达/转化标签
def build_segments():
    return [
        # ---------- 亚洲杯 2026 ----------
        dict(
            name="SEG_AC26_SPORTS_ALL_NOENGAGE", project="asian_cup_2026",
            note="第1波入口：意图人群 ∧ 未被任何波次触达/转化",
            filters=[tag_filter("intent_sports")]
                    + [tag_filter(t, exclude=True) for t in
                       ("ac26_c1_sent", "ac26_engaged", "ac26_form_submitted", "ac26_converted")],
        ),
        dict(
            name="SEG_AC26_FOOTBALL_ENGAGED", project="asian_cup_2026",
            note="第2波入口：足球细分 ∧ 第1波有互动",
            filters=[tag_filter("intent_sports_Football"), tag_filter("ac26_engaged")],
        ),
        dict(
            name="SEG_AC26_STRONG_INTENT", project="asian_cup_2026",
            note="第2波产出：二次点击判定为强意向",
            filters=[tag_filter("ac26_strong_intent")],
        ),
        dict(
            name="SEG_AC26_SPORTS_ENGAGED", project="asian_cup_2026",
            note="第1波点击分支产出：意图人群 ∧ 第1波已触达并有点击/互动",
            filters=[tag_filter("intent_sports"), tag_filter("ac26_engaged")],
        ),
        dict(
            name="SEG_AC26_NOT_CLICKED", project="asian_cup_2026",
            note="第1波未点击分支产出（用户本次新增）：未点击 → 打标并移入本组，供后续策略承接",
            filters=[tag_filter("intent_sports"), tag_filter("ac26_c1_notclicked")],
        ),
        dict(
            name="SEG_AC26_LEAD_CANDIDATE", project="asian_cup_2026",
            note="第3波可留资池：强意向 或（意图人群且未留资未转化未点击）",
            filters=[tag_filter("ac26_strong_intent", glue="and")]
                    + [tag_filter("intent_sports", glue="or")]
                    + [tag_filter(t, exclude=True) for t in
                       ("ac26_form_submitted", "ac26_converted", "ac26_c1_notclicked")],
        ),
        dict(
            name="SEG_AC26_FORM_NO_CONVERT", project="asian_cup_2026",
            note="第4波转化池：已留资未转化",
            filters=[tag_filter("ac26_form_submitted"), tag_filter("ac26_converted", exclude=True)],
        ),
        dict(
            name="SEG_AC26_NEVER_ENGAGED", project="asian_cup_2026",
            note="挽回池：意图人群 ∧ 全程未互动未留资未转化",
            filters=[tag_filter("intent_sports")]
                    + [tag_filter(t, exclude=True) for t in
                       ("ac26_engaged", "ac26_form_submitted", "ac26_converted", "ac26_c4_sent")],
        ),
        # ---------- F1 2027 ----------
        dict(
            name="SEG_F1_SPORTS_ALL_NOENGAGE", project="f1_2027",
            note="F1 第1波入口：意图人群 ∧ 未触达",
            filters=[tag_filter("intent_sports")]
                    + [tag_filter(t, exclude=True) for t in
                       ("f1_c1_sent", "f1_engaged", "f1_form_submitted", "f1_converted")],
        ),
        dict(
            name="SEG_F1_SPORTS_ENGAGED", project="f1_2027",
            note="F1 第1波产出：有互动（进入第2波）",
            filters=[tag_filter("intent_sports"), tag_filter("f1_engaged")],
        ),
        dict(
            name="SEG_F1_AUTORACING_ENGAGED", project="f1_2027",
            note="F1 第2波入口：赛车细分 ∧ 第1波有互动",
            filters=[tag_filter("intent_sports_AutoRacing"), tag_filter("f1_engaged")],
        ),
        dict(
            name="SEG_F1_STRONG_INTENT", project="f1_2027",
            note="F1 第2波产出：二次点击强意向",
            filters=[tag_filter("f1_strong_intent")],
        ),
        dict(
            name="SEG_F1_EXPERIENCE_POOL", project="f1_2027",
            note="F1 第3波体验培育池",
            filters=[tag_filter("f1_strong_intent")]
                    + [tag_filter("intent_sports_AutoRacing", glue="or")]
                    + [tag_filter(t, exclude=True) for t in
                       ("f1_form_submitted", "f1_converted")],
        ),
        dict(
            name="SEG_F1_LEAD_CANDIDATE", project="f1_2027",
            note="F1 第4波可留资池",
            filters=[tag_filter("f1_experience_confirmed", glue="and")]
                    + [tag_filter("intent_sports", glue="or")]
                    + [tag_filter(t, exclude=True) for t in
                       ("f1_form_submitted", "f1_converted")],
        ),
        dict(
            name="SEG_F1_FORM_NO_CONVERT", project="f1_2027",
            note="F1 第5波转化池：已留资未转化",
            filters=[tag_filter("f1_form_submitted"), tag_filter("f1_converted", exclude=True)],
        ),
        dict(
            name="SEG_F1_NEVER_ENGAGED", project="f1_2027",
            note="F1 挽回池",
            filters=[tag_filter("intent_sports")]
                    + [tag_filter(t, exclude=True) for t in
                       ("f1_engaged", "f1_form_submitted", "f1_converted", "f1_c5_sent")],
        ),
    ]


# ------------------------------------------------------------------ DB 操作
def sql(q: str, raw: bool = False):
    # -N 必须加：否则 mariadb 会输出列名（"id\n131"），.isdigit() 判 False
    # → 把「已存在的分群」误判为不存在 → 每次跑都新建一份同名副本（本脚本真踩过）。
    cmd = [MARIADB, "-h", DB["host"], "-P", str(DB["port"]), "-N",
           "-u", DB["user"], f"-p{DB['password']}", DB["db"], "-e", q]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"SQL 失败: {r.stderr.strip()[:400]}")
    return r.stdout if raw else None


def aliasify(name: str) -> str:
    a = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:50]
    return a


def esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("'", "''")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    ap.add_argument("--only", default="", help="只处理名字包含此串的分群")
    args = ap.parse_args()

    segs = build_segments()
    if args.only:
        segs = [s for s in segs if args.only in s["name"]]

    # 备份存在性校验
    baks = sql("SHOW TABLES LIKE 'lead_lists_bak_%';", raw=True)
    if "lead_lists_bak_" not in baks:
        print("!! 未找到备份表，请先备份再写入"); sys.exit(2)
    print(f"[OK] 检测到备份表: {[l for l in baks.split() if 'bak' in l]}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created, skipped, updated = [], [], []

    for s in segs:
        filters_php = php_serialize(s["filters"])
        alias = aliasify(s["name"])
        exist = sql(f"SELECT id FROM lead_lists WHERE name='{esc(s['name'])}';", raw=True).strip()
        if exist and exist.isdigit():
            sid = int(exist)
            if args.apply:
                sql(f"UPDATE lead_lists SET filters='{esc(filters_php)}', "
                    f"date_modified='{now}' WHERE id={sid};")
            updated.append(sid)
            print(f"  UPDATE {sid:>4}  {s['name']}  filters={len(filters_php)}B  {s['note']}")
        else:
            if args.apply:
                cols = ("name,alias,public_name,filters,is_global,is_preference_center,"
                        "is_published,uuid,date_added,created_by,created_by_user")
                vals = (f"'{esc(s['name'])}','{alias}','{esc(s['name'])}','{esc(filters_php)}',"
                        f"1,0,1,'{uuid.uuid4()}','{now}',1,'自动化营销 [1]'")
                sql(f"INSERT INTO lead_lists ({cols}) VALUES ({vals});")
                row = sql(f"SELECT id FROM lead_lists WHERE name='{esc(s['name'])}';", raw=True).strip()
                sid = int(row) if row.isdigit() else -1
            else:
                sid = -1
            created.append(s["name"])
            print(f"  CREATE  {sid:>4}  {s['name']}  filters={len(filters_php)}B  {s['note']}")

    print(f"\n小结: 新建 {len(created)} · 更新 {len(updated)}")
    if not args.apply:
        print(">>> DRY-RUN，未写入。加 --apply 真正执行。")
    else:
        print(">>> 已写入。")


if __name__ == "__main__":
    main()
"""
auto_feedback.py — 每日定时任务

对 output/ 下所有已生成（即 deploy_result.campaign_id 非空且非 dry_run）的 program campaign，
按 Mautic campaign 事件（email.send / page.hit / form.submit）聚合昨日的
sent / opened / clicked / converted / unsub，并写入 program JSON 的 feedback_auto[date]。

调用：
  python auto_feedback.py                       # 默认昨天
  python auto_feedback.py --date 2026-09-07     # 指定日期
  python auto_feedback.py --gid ucl2028          # 只跑某个 program

依赖：mautic_client.py / config.json 已填 client_id/client_secret。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "output")
sys.path.insert(0, HERE)
from mautic_client import auto_feedback_for_campaign  # noqa: E402


def _iter_programs(gid: str | None):
    if not os.path.isdir(OUT_DIR):
        return
    for fn in sorted(os.listdir(OUT_DIR)):
        if not fn.startswith("program_") or not fn.endswith(".json"):
            continue
        if gid and fn != f"program_{gid}.json":
            continue
        path = os.path.join(OUT_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                p = json.load(f)
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {fn}: 读取失败 {e}")
            continue
        yield path, p


def _yesterday_str() -> str:
    return (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD；默认昨天")
    ap.add_argument("--gid", default=None, help="只处理指定 program (goal_id)")
    args = ap.parse_args()
    date_str = args.date or _yesterday_str()

    total_camps = 0
    updated = 0
    skipped = 0
    for path, p in _iter_programs(args.gid):
        gid = p.get("goal_id", os.path.basename(path))
        for c in p.get("campaigns", []):
            total_camps += 1
            dr = (c.get("proposal") or {}).get("deploy_result") or {}
            mcid = dr.get("campaign_id") if not dr.get("dry_run") else None
            if not mcid:
                skipped += 1
                continue
            try:
                stats = auto_feedback_for_campaign(mcid, date_str)
            except Exception as e:  # noqa: BLE001
                stats = {"_errors": [str(e)]}
            fb_auto = c.setdefault("feedback_auto", {})
            fb_auto[date_str] = {
                "sent": stats.get("sent", 0),
                "opened": stats.get("opened", 0),
                "clicked": stats.get("clicked", 0),
                "converted": stats.get("converted", 0),
                "unsub": stats.get("unsub", 0),
                "conv_rate": stats.get("conv_rate", 0.0),
                "unsub_rate": stats.get("unsub_rate", 0.0),
                "_evidence": stats.get("_evidence", []),
                "_errors": stats.get("_errors", []),
            }
            c["feedback_auto_updated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
            print(f"  [ok] {gid}/{c.get('cid')} mcid={mcid} → "
                  f"sent={fb_auto[date_str]['sent']} opened={fb_auto[date_str]['opened']} "
                  f"clicked={fb_auto[date_str]['clicked']} converted={fb_auto[date_str]['converted']}")
            updated += 1
        # 即使无 campaign 可更新也保存（保持原 JSON 完整）
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)

    print(f"\ndate={date_str} | programs={len(list(_iter_programs(args.gid)))} "
          f"| campaigns_total={total_camps} | updated={updated} | skipped(no_mcid)={skipped}")


if __name__ == "__main__":
    main()

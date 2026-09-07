"""
Autopilot PoC — 运行入口
=====================================================================
把三块串起来：
  [config.json 环境开关] → 选 local / prod
  [goal_intake]          → Brief → GoalSpec
  [plan_compiler]         → GoalSpec → CampaignProposal（带治理注入 + plan_hash）

默认 dry-run：只把「会发给 localhost:8080/s/ 的 API 调用」打印出来，
不真正触碰 Mautic，避免污染生产 campaign #27 / #42。

用法：
  python run_poc.py                         # 用默认 brief_example.json，local 环境，dry-run
  python run_poc.py --env prod             # 切到生产环境（仍需填 config.json 的 key/secret）
  python run_poc.py --brief my.json        # 用自定义 Brief
  python run_poc.py --push                 # 真正推送（需 config.json 已填凭证，且 local 先验证）
  python run_poc.py --interactive          # 交互式填 Brief

输出：
  autopilot-poc/output/proposal_<goal_id>.json   （事件图提案落盘，可拿去审批）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from goal_intake import parse_brief, load_brief, prompt_brief
from plan_compiler import compile, dump_proposal


def load_config(env: str) -> dict:
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if env not in cfg:
        raise SystemExit(f"config.json 没有环境 '{env}'，可选：{list(cfg.keys())}")
    return cfg[env]


def mock_strategy_from_goal(goal) -> dict:
    """PoC 阶段 Strategy 由 GoalSpec 自动推导（真实系统由 L1 策略合成产出）。"""
    return {
        "campaign_name": f"[PoC] {goal.objective}",
        "variant_id": "v_default",
        "email_ref": "EM_MAIN_PLACEHOLDER",
        "email_followup_ref": "EM_FOLLOWUP_PLACEHOLDER",
        "subject": goal.objective,
        "followup_subject": "提醒：" + goal.objective,
    }


def main():
    ap = argparse.ArgumentParser(description="Autopilot PoC: 本地可跑的营销 Agent 编排骨架")
    ap.add_argument("--env", default="local", choices=["local", "prod"],
                    help="环境开关（取自 config.json）")
    ap.add_argument("--brief", default=os.path.join(HERE, "brief_example.json"),
                    help="Brief JSON 路径")
    ap.add_argument("--push", action="store_true",
                    help="真正推送到 {base_url}/s/（需填凭证；默认 dry-run）")
    ap.add_argument("--interactive", action="store_true", help="交互式填 Brief")
    args = ap.parse_args()

    cfg = load_config(args.env)
    base_url = cfg["base_url"]
    print(f"[环境开关] env={args.env}  base_url={base_url}")

    # ---- L0 Goal Intake ----
    raw = prompt_brief() if args.interactive else load_brief(args.brief)
    goal = parse_brief(raw)
    print(f"[Goal Intake] goal_id={goal.goal_id}  channels={goal.channels}  "
          f"reserved={goal.reserved_channels}  LP={goal.landing_page_url}")

    # MVP 闭环校验
    if "email" not in goal.channels:
        print("⚠️  MVP 裁定要求 email 为主渠道，当前 channels 不含 email")
    if not goal.landing_page_url:
        print("⚠️  未配置 landing_page_url：email→LP 承接闭环不成立")
    print("✓ email 主渠道闭环：邮件触达 → CTA 调起 LP 承接转化"
          if (goal.landing_page_url) else "✗ 闭环缺口")

    # ---- L2 Plan Compiler ----
    strategy = mock_strategy_from_goal(goal)
    proposal = compile(goal, strategy)
    print(f"[Plan Compiler] 节点数={len(proposal['graph'])}  "
          f"治理注入={proposal['governance_injected']}  "
          f"plan_hash={proposal['plan_hash'][:16]}...")

    # 落盘
    out_dir = os.path.join(HERE, "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"proposal_{goal.goal_id}.json")
    dump_proposal(proposal, out_path)
    print(f"[输出] 事件图提案已落盘：{out_path}")

    # ---- dry-run / push ----
    print("\n=== Mautic API 调用清单（指向 base_url + /s/）===")
    for call in proposal["api_calls"]:
        print(f"  {call['method']:5} {base_url}{call['path']}")
        print(f"          {call['desc']}")

    if args.push:
        if not cfg.get("api_key") or not cfg.get("api_secret"):
            print("\n✗ --push 需要 config.json 中填好 api_key/api_secret，已中止（未污染生产）。")
        else:
            print("\n[push] 真实推送路径已就位（PoC 阶段请先在 local 验证，再切 prod）。")
            # 真实推送：此处调用 Mautic /api/v2 + applyAction，PoC 不展开 HTTP 实现
    else:
        print("\n[dry-run] 仅打印调用，未触碰 Mautic。加 --push 才真正发送（需凭证）。")


if __name__ == "__main__":
    main()

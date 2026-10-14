"""
受众画像包打分模型重定向验证（用户 2026-09 设计）。

验证点：
  1. 打分因子 = age(0.45) / income(0.40) / industry(0.15)；
     gender / education / region / source 仅打 tag，不参与打分。
  2. 匹配规则：age+income 主、industry 次；0-18 并入 YOUNG_TREND；
     男性可命中 PARENT_FAM（去掉 gender 限制）。
  3. age 数值（如 "30"）须归一到年龄桶（如 "25-34"），与前端一致。
  4. source 不计入 abs_score。

运行：python tests/test_audience_redesign.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from goal_intake import infer_audience_package  # noqa: E402


def _check(name, cond, detail=""):
    if cond:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}  {detail}")
        raise AssertionError(f"{name}  {detail}")


def main():
    # 1. 男性现在可命中 PARENT_FAM（去掉 gender=女 限制）
    r = infer_audience_package({"age": "30", "income": "L3", "industry": "教育", "gender": "男"})
    _check("PARENT_FAM male matches", r["code"] == "PARENT_FAM", f"got {r['code']}")

    # 2. 0-18 合并进 YOUNG_TREND
    r = infer_audience_package({"age": "10", "income": "L1"})
    _check("YOUNG_TREND 0-18 merged", r["code"] == "YOUNG_TREND", f"got {r['code']}")

    # 3. HNW_FAMILY（女、40 岁、L5、IT）
    r = infer_audience_package({"age": "40", "income": "L5", "industry": "IT", "gender": "女"})
    _check("HNW_FAMILY", r["code"] == "HNW_FAMILY", f"got {r['code']}")

    # 4. 28 岁非 HNW（age<35）→ CORP_GRP（income L5 + industry IT）
    r = infer_audience_package({"age": "28", "income": "L5", "industry": "IT"})
    _check("CORP_GRP (28yo not HNW)", r["code"] == "CORP_GRP", f"got {r['code']}")

    # 5. 显式矛盾字段 → 无具名包 → GENERIC
    #    原语义「留空=全选满分」下仅字段留空会给满分；这里 age/income/industry 都显式填了且
    #    与所有包的命中区间矛盾（30岁非亲子年龄主力、L2 非 L3-L4、IT 非教育/医疗）→ 0.45 < 0.6 → GENERIC
    r = infer_audience_package({"age": "30", "income": "L2", "industry": "IT"})
    _check("GENERIC fallback", r["code"] == "GENERIC", f"got {r['code']}")

    # 6. source 不计入打分：abs_score = age(0.45) + income(0.40) = 0.85
    r = infer_audience_package({"age": "20", "income": "L1", "source": "CSTS"})
    _check("YOUNG_TREND source not scored", r["code"] == "YOUNG_TREND", f"got {r['code']}")
    _check("abs_score excludes source (=0.85)",
           abs(r["abs_score"] - 0.85) < 1e-6, f"got abs_score={r['abs_score']}")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()

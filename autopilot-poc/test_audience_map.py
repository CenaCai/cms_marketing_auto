"""
test_audience_map.py — audience_map 单一事实源单元测试（stdlib unittest）
=====================================================================
覆盖：
  ① 6 个包 get_package 全部非空且结构一致
  ② 每包 visual / cta_templates / content_direction / forbidden_phrases 均非空
  ③ content_direction / visual_direction / send_defaults 对 6 包均返回预期结构
  ④ 未知 code（含 None / 空 / 非字符串）回退 GENERIC
  ⑤ thresholds() 返回 threshold == 0.6
  ⑥ 字段缺失时抛 AudienceMapError（不静默返回 None）

运行：
  <python> test_audience_map.py            # 直接跑
  <python> -m unittest test_audience_map -v
"""
from __future__ import annotations

import copy
import json
import os
import unittest

import audience_map as am

EXPECTED_CODES = ["HNW_FAMILY", "YOUNG_TREND", "PARENT_FAM", "CORP_GRP", "DORMANT", "GENERIC"]


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestAudienceMap(unittest.TestCase):
    # ---------- ① 6 包 get_package 非空且结构一致 ----------
    def test_01_packages_complete(self):
        self.assertEqual(am.package_codes(), EXPECTED_CODES)
        shapes = set()
        for code in EXPECTED_CODES:
            pkg = am.get_package(code)
            self.assertTrue(pkg, f"{code} get_package 返回空")
            self.assertIsInstance(pkg, dict)
            self.assertEqual(pkg["code"], code)
            self.assertTrue(pkg.get("label"), f"{code} 缺 label")
            self.assertTrue(pkg.get("label_zh"), f"{code} 缺 label_zh")
            self.assertIn("match", pkg)
            for k in ("code", "label", "label_zh", "match", "strategy"):
                self.assertIn(k, pkg, f"{code} 缺 {k}")
            # 结构一致：必需键集合相同（match_note 是专家表可选说明键，不参与比较）
            shapes.add(tuple(sorted(set(pkg.keys()) - {"match_note"})))
        # 结构一致：所有包对外暴露的键集合相同
        self.assertEqual(len(shapes), 1, f"6 个包 get_package 结构不一致：{shapes}")

    def test_01b_strategy_required_keys(self):
        for code in EXPECTED_CODES:
            st = am.strategy_for(code)
            for k in am.REQUIRED_STRATEGY_KEYS:
                self.assertIn(k, st, f"{code}.strategy 缺 {k}")
                self.assertTrue(st[k], f"{code}.strategy.{k} 为空")
            self.assertIsInstance(st["frequency"], dict)
            self.assertIsNotNone(st["frequency"]["max_per_24h"], f"{code} 缺 max_per_24h")
            self.assertIsNotNone(st["frequency"]["max_per_7d"], f"{code} 缺 max_per_7d")
            self.assertTrue(st["send_window"], f"{code}.send_window 为空")
            self.assertTrue(st["quiet_hours"], f"{code}.quiet_hours 为空")

    # ---------- ② 关键内容字段非空 ----------
    def test_02_content_fields_non_empty(self):
        for code in EXPECTED_CODES:
            st = am.strategy_for(code)
            self.assertTrue(st["visual"], f"{code}.visual 为空")
            self.assertTrue(st["cta_templates"], f"{code}.cta_templates 为空")
            self.assertTrue(st["content_direction"], f"{code}.content_direction 为空")
            self.assertTrue(st["forbidden_phrases"], f"{code}.forbidden_phrases 为空")
            self.assertTrue(st["levers"], f"{code}.levers 为空")
            self.assertTrue(st["tone"], f"{code}.tone 为空")
            self.assertTrue(st["subject_examples"], f"{code}.subject_examples 为空")

    # ---------- ③ 三个方向 API 的返回结构 ----------
    def test_03_content_direction_shape(self):
        want = {"levers", "tone", "forbidden_phrases", "cta_templates",
                "subject_examples", "angles", "claims", "hero_points"}
        for code in EXPECTED_CODES:
            cd = am.content_direction(code)
            self.assertEqual(set(cd.keys()), want, f"{code} content_direction 结构不符")
            for k in ("levers", "forbidden_phrases", "cta_templates",
                      "subject_examples", "angles", "claims", "hero_points"):
                self.assertIsInstance(cd[k], list, f"{code}.{k} 不是 list")
                self.assertTrue(cd[k], f"{code}.{k} 为空")
            self.assertIsInstance(cd["tone"], str)
            self.assertTrue(cd["tone"])

    def test_03b_visual_direction_shape(self):
        want = {"visual", "palette", "design_direction", "imagery"}
        for code in EXPECTED_CODES:
            vd = am.visual_direction(code)
            self.assertEqual(set(vd.keys()), want, f"{code} visual_direction 结构不符")
            self.assertTrue(vd["visual"], f"{code}.visual 为空")
            self.assertTrue(vd["design_direction"], f"{code}.design_direction 为空")
            self.assertTrue(vd["imagery"], f"{code}.imagery 为空")
            self.assertEqual(set(vd["palette"].keys()), {"primary", "secondary", "accent", "bg", "text"},
                             f"{code}.palette 键不全")
            for name, hexv in vd["palette"].items():
                self.assertTrue(hexv.startswith("#") and len(hexv) == 7,
                                f"{code}.palette.{name} 不是 #RRGGBB：{hexv}")

    def test_03c_send_defaults_shape(self):
        for code in EXPECTED_CODES:
            sd = am.send_defaults(code)
            self.assertEqual(set(sd.keys()), {"max_per_24h", "max_per_7d", "quiet_hours", "send_window"})
            self.assertIsInstance(sd["max_per_24h"], int)
            self.assertIsInstance(sd["max_per_7d"], int)
            self.assertIsInstance(sd["quiet_hours"], str)
            self.assertIsInstance(sd["send_window"], list)
            self.assertTrue(sd["send_window"])

    def test_03d_label_for(self):
        self.assertEqual(am.label_for("HNW_FAMILY"), "高净值家庭客")
        self.assertEqual(am.label_for("NOPE"), "通用兜底")

    # ---------- ④ 未知 code 回退 GENERIC ----------
    def test_04_unknown_code_falls_back_to_generic(self):
        for bad in ("NOPE", None, "", "  ", 123, "not_a_code"):
            pkg = am.get_package(bad)
            self.assertEqual(pkg["code"], "GENERIC", f"{bad!r} 未回退 GENERIC")
            self.assertEqual(pkg["label"], "通用兜底")
            self.assertEqual(am.visual_direction(bad), am.visual_direction("GENERIC"))
            self.assertEqual(am.content_direction(bad), am.content_direction("GENERIC"))
            self.assertEqual(am.send_defaults(bad), am.send_defaults("GENERIC"))
        # 大小写/空格容错
        self.assertEqual(am.get_package("hnw_family")["code"], "HNW_FAMILY")
        self.assertEqual(am.get_package(" YOUNG_TREND ")["code"], "YOUNG_TREND")

    def test_04b_require_package_raises(self):
        with self.assertRaises(am.AudienceMapError):
            am.require_package("NOPE")

    # ---------- ⑤ thresholds ----------
    def test_05_thresholds(self):
        th = am.thresholds()
        self.assertEqual(th["threshold"], 0.6)
        self.assertEqual(th["default_weights"]["age"], 0.20)
        self.assertEqual(th["default_weights"]["income"], 0.25)
        self.assertEqual(round(sum(th["default_weights"].values()), 6), 1.0)

    # ---------- ⑥ 字段缺失 → 抛清晰异常（不静默 None） ----------
    def test_06_missing_field_raises(self):
        saved_map, saved_cache = am.MAP_PATH, am._CACHE
        tmp = os.path.join(am.HERE, "_tmp_broken_map.json")
        try:
            good = _read_json(saved_map)
            broken = copy.deepcopy(good)
            broken["packages"][1]["strategy"].pop("content_direction")   # YOUNG_TREND 去掉文案方向
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(broken, f, ensure_ascii=False)
            am.MAP_PATH = tmp
            am.reload_map()
            with self.assertRaises(am.AudienceMapError) as ctx:
                am.validate_packages()
            self.assertIn("content_direction", str(ctx.exception))
            with self.assertRaises(am.AudienceMapError):
                am.content_direction("YOUNG_TREND")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
            am.MAP_PATH = saved_map
            am.reload_map()

    def test_06b_missing_palette_raises(self):
        saved_map = am.MAP_PATH
        tmp = os.path.join(am.HERE, "_tmp_broken_map2.json")
        try:
            good = _read_json(saved_map)
            broken = copy.deepcopy(good)
            broken["packages"][0]["strategy"]["visual"]["palette"].pop("accent")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(broken, f, ensure_ascii=False)
            am.MAP_PATH = tmp
            am.reload_map()
            with self.assertRaises(am.AudienceMapError):
                am.visual_direction("HNW_FAMILY")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
            am.MAP_PATH = saved_map
            am.reload_map()

    def test_06c_broken_file_falls_back(self):
        """文件整体缺失/损坏 → 回退内置兜底，不抛异常。"""
        saved_map = am.MAP_PATH
        try:
            am.MAP_PATH = os.path.join(am.HERE, "_no_such_file.json")
            am.reload_map()
            self.assertEqual(am.package_codes(), ["GENERIC"])
            self.assertEqual(am.get_package("ANY")["label"], "通用兜底")
            self.assertEqual(am.send_defaults("ANY")["quiet_hours"], "22:00-09:00")
            self.assertTrue(am.visual_direction("ANY")["palette"]["primary"])
        finally:
            am.MAP_PATH = saved_map
            am.reload_map()

    # ---------- ⑦ JSON 与专家源表一致性（防误改） ----------
    def test_07_json_matches_expert_source(self):
        src = r"C:/Users/cenacai/.workbuddy/plugins/cache/my-experts/growth-ops/1.0.0/skills/mautic-growth-ops/references/audience-content-map.json"
        if not os.path.exists(src):
            self.skipTest("专家源表不在本机")
        s = _read_json(src)
        d = _read_json(am.MAP_PATH)
        self.assertEqual(s["scoring"], d["scoring"])
        sm = {p["code"]: p for p in s["packages"]}
        dm = {p["code"]: p for p in d["packages"]}
        self.assertEqual(set(sm), set(dm))
        for code, sp in sm.items():
            dp = dm[code]
            self.assertEqual(sp["label_zh"], dp["label_zh"])
            self.assertEqual(sp.get("match"), dp.get("match"))
            for k in ("frequency", "quiet_hours", "send_window", "levers",
                      "forbidden_phrases", "tone", "cta_templates", "subject_examples"):
                self.assertEqual(sp["strategy"][k], dp["strategy"][k], f"{code}.{k} 与专家源表不一致")


if __name__ == "__main__":
    unittest.main(verbosity=2)

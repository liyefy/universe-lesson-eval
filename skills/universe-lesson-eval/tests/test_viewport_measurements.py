"""Real PNG/CLI regression fixtures, deliberately synthetic and never audit evidence."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
from io import BytesIO
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_viewport import REQUIRED_CHECK_IDS, check_viewport, expected_checks, read_image, read_png, validate_assertions
from report_gate import freeze

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKGROUND = (30, 70, 110)
SUBJECT = (250, 245, 180)
CONFIG = {"box_tolerance_px": 2, "center_tolerance_px": 8, "safe_margin_px": 40,
          "edge_background_rgb": [0, 0, 0], "edge_color_tolerance": 18,
          "edge_min_non_background": 0.95, "subject_min_rgb": [245, 235, 150],
          "subject_max_rgb": [255, 255, 255], "subject_min_area_px": 50}


def rect(x, y, width, height):
    return dict(x=x, y=y, width=width, height=height)


def png_chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)


def make_png(width, height, rectangles=(), *, rgba=False, filter_type=0):
    """Encode pixels independently of the decoder; rectangles are physical pixels."""
    channels = 4 if rgba else 3
    rows = []
    previous = bytes(width * channels)
    for y in range(height):
        row = bytearray()
        for x in range(width):
            color = BACKGROUND
            for left, top, right, bottom, fill in rectangles:
                if left <= x < right and top <= y < bottom:
                    color = fill
            row.extend(color)
            if rgba and len(color) == 3:
                row.append(255)
        encoded = bytearray(len(row))
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                prediction = 0
            elif filter_type == 1:
                prediction = left
            elif filter_type == 2:
                prediction = up
            elif filter_type == 3:
                prediction = (left + up) // 2
            else:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                prediction = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
            encoded[index] = (value - prediction) % 256
        rows.append(bytes([filter_type]) + encoded)
        previous = row
    header = struct.pack(">IIBBBBB", width, height, 8, 6 if rgba else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(b"".join(rows))) + png_chunk(b"IEND", b"")


class ViewportMeasurementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan_path, self.raw_path, self.png_path = [self.root / name for name in ("plan.json", "capture.json", "capture.png")]
        self.raw = {"source": "http://localhost/#/modules/synthetic", "build_id": "synthetic-build",
                    "node_id": "n1", "state": "panel-open", "viewport": {"width": 320, "height": 240},
                    "screenshot": "capture.png",
                    "captured_at": datetime.now(timezone.utc).isoformat(), "host": rect(0, 0, 320, 240),
                    "scene": rect(0, 0, 320, 240), "occluders": [{"kind": "panel", "rect": rect(240, 10, 70, 220)}]}
        self.source = self.root / "source.txt"
        self.source.write_text("SYNTHETIC FIXTURE ONLY: full panorama, centered object, 40 CSS px margins.", encoding="utf-8")
        self.plan = {"version": 2, "audit_id": "synthetic-png-check",
                     "scope": {"topic": "synthetic", "version": "fixture", "url": self.raw["source"],
                               "environment": "synthetic fixtures, no real browser", "build_id": self.raw["build_id"],
                               "dimensions": ["viewport"], "coverage": "focused", "visual_contract_version": 1,
                               "viewports": [copy.deepcopy(self.raw["viewport"])]},
                     "sources": [{"id": "fixture", "path": "source.txt", "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}],
                     "rules": [], "inventory": [], "cases": []}
        for index in range(1, 4):
            rule = f"VIEW-0{index}"
            self.plan["rules"].append({"id": rule, "source": "fixture", "version": "synthetic-v1", "applicability": "synthetic pixels"})
            self.plan["cases"].append({"id": f"c{index}", "node": "n1", "rule_id": rule, "title": "synthetic assertion",
                                       "source": "fixture#line1", "source_ids": ["fixture"], "expected": "synthetic expectation",
                                       "critical": False, "allow_not_applicable": False, "dimension": "viewport", "engine": "browser",
                                       "required_evidence": ["code", "blackbox"], "blackbox_method": "visual", "state": self.raw["state"],
                                       "steps": ["read synthetic PNG, not browser evidence"], "viewport": copy.deepcopy(self.raw["viewport"]),
                                       "viewport_assertions": copy.deepcopy(CONFIG)})
        self.plan["inventory"] = [{"node_id": "n1", "required_rules": list(REQUIRED_CHECK_IDS),
                                   "visual_requirements": [{"rule_id": rule, "applicable": True,
                                                            "rationale": "synthetic regression", "source_ids": ["fixture"]}
                                                           for rule in REQUIRED_CHECK_IDS],
                                   "visual_states": [{"state": "panel-open", "panel": "open", "phase": "default"}]}]
        self.png_path.write_bytes(make_png(320, 240, [(100, 90, 140, 130, SUBJECT)]))
        self.save()

    def save(self):
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.raw_path.write_text(json.dumps(self.raw), encoding="utf-8")

    def check(self, rule=2):
        self.save()
        return check_viewport(self.plan_path, f"c{rule}", self.raw_path, self.png_path)

    def test_real_pixels_pass_all_three_rules(self):
        for index in (1, 2, 3):
            with self.subTest(rule=index):
                result, code = self.check(index)
                self.assertEqual(code, 0, result)
                self.assertEqual({check["id"] for check in result["checks"]}, REQUIRED_CHECK_IDS[f"VIEW-0{index}"])
                self.assertEqual(result["measurement"]["available"], rect(0, 0, 240, 240))
                self.assertEqual(result["screenshot"]["sha256"], hashlib.sha256(self.png_path.read_bytes()).hexdigest())
                self.assertEqual(result["measurement_artifact"]["path"], "capture.json")
        self.assertEqual(result["measurement"]["subject"]["width"], 40)

    def test_each_inset_box_edge_fails_independently_of_bright_pixels(self):
        for side, scene in {"top": rect(0, 7, 320, 233), "right": rect(0, 0, 313, 240),
                            "bottom": rect(0, 0, 320, 233), "left": rect(7, 0, 313, 240)}.items():
            with self.subTest(side=side):
                self.raw["scene"] = scene
                result, code = self.check(1)
                self.assertEqual(code, 1, result)
                failed = [check["id"] for check in result["checks"] if not check["passed"]]
                self.assertEqual(failed, [f"box-{side}"])

    def test_four_black_edges_fail_even_with_full_scene_box(self):
        self.png_path.write_bytes(make_png(320, 240, [(0, 0, 320, 240, (0, 0, 0)), (8, 8, 312, 232, BACKGROUND)]))
        result, code = self.check(1)
        self.assertEqual(code, 1, result)
        self.assertEqual({check["id"] for check in result["checks"] if not check["passed"]},
                         {f"pixels-{side}" for side in ("top", "right", "bottom", "left")})

    def test_fullscreen_center_is_wrong_with_panel_open(self):
        self.png_path.write_bytes(make_png(320, 240, [(140, 90, 180, 130, SUBJECT)]))
        result, code = self.check()
        self.assertEqual(code, 1, result)
        self.assertEqual(result["checks"][0]["actual"], 40)
        self.raw["occluders"] = []
        result, code = self.check()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["measurement"]["available"], self.raw["host"])

    def test_bottom_panel_reduces_height_not_horizontal_center(self):
        self.raw["occluders"] = [{"kind": "panel", "rect": rect(0, 170, 320, 70)}]
        self.png_path.write_bytes(make_png(320, 240, [(140, 60, 180, 100, SUBJECT)]))
        for rule in (2, 3):
            result, code = self.check(rule)
            self.assertEqual(code, 0, result)
            self.assertEqual(result["measurement"]["available"], rect(0, 0, 320, 170))

    def test_full_width_bottom_sheet_samples_visible_boundary_not_panel_pixels(self):
        for scale in (1, 2):
            with self.subTest(scale=scale):
                self.raw["occluders"] = [{"kind": "panel", "rect": rect(0, 170.125, 320, 69.875)}]
                panel_start = math.ceil(170.125 * scale - 0.5)
                self.png_path.write_bytes(make_png(320 * scale, 240 * scale,
                                                  [(0, panel_start, 320 * scale, 240 * scale, (0, 0, 0))]))
                result, code = self.check(1)
                self.assertEqual(code, 0, result)
                edges = {edge["side"]: edge for edge in result["measurement"]["edges"]}
                bottom = edges["bottom"]
                self.assertEqual(bottom["boundary"], "available")
                self.assertEqual(bottom["boundary_rect"], rect(0, 0, 320, 170.125))
                self.assertEqual(bottom["reason"], "host_edge_fully_occluded_by_panel")
                self.assertEqual(bottom["panel_rects"], [self.raw["occluders"][0]["rect"]])
                self.assertEqual(bottom["sample_line"], {"coordinate_space": "screenshot_pixels",
                                                        "start": {"x": 0, "y": panel_start - 1},
                                                        "end": {"x": 320 * scale - 1, "y": panel_start - 1}})
                self.assertEqual(bottom["samples"], 320 * scale)
                self.assertEqual(bottom["non_background_fraction"], 1)
                for side in ("top", "left", "right"):
                    self.assertEqual(edges[side]["boundary"], "host")
                    self.assertIsNone(edges[side]["reason"])

    def test_black_strip_at_available_boundary_still_fails(self):
        self.raw["occluders"] = [{"kind": "panel", "rect": rect(0, 170, 320, 70)}]
        self.png_path.write_bytes(make_png(320, 240, [(0, 169, 320, 170, (0, 0, 0)),
                                                     (0, 170, 320, 240, (255, 255, 255))]))
        result, code = self.check(1)
        self.assertEqual(code, 1, result)
        self.assertEqual([row["id"] for row in result["checks"] if not row["passed"]], ["pixels-bottom"])

    def test_scene_inset_hidden_behind_sheet_still_fails_host_box_assertion(self):
        self.raw["occluders"] = [{"kind": "panel", "rect": rect(0, 170, 320, 70)}]
        self.raw["scene"] = rect(0, 0, 320, 180)
        self.png_path.write_bytes(make_png(320, 240, [(0, 170, 320, 240, (0, 0, 0))]))
        result, code = self.check(1)
        self.assertEqual(code, 1, result)
        self.assertEqual([row["id"] for row in result["checks"] if not row["passed"]], ["box-bottom"])
        self.assertEqual(next(row["actual"] for row in result["checks"] if row["id"] == "box-bottom"), 60)

    def test_ui_or_partial_panel_cannot_authorize_moving_edge_samples(self):
        cases = ([{"kind": "ui", "rect": rect(0, 170, 320, 70)}],
                 [{"kind": "panel", "rect": rect(0, 170, 319, 70)},
                  {"kind": "ui", "rect": rect(319, 170, 1, 70)}],
                 [{"kind": "panel", "rect": rect(0, 170, 319, 70)}])
        for occluders in cases:
            with self.subTest(occluders=occluders):
                self.raw["occluders"] = occluders
                result, code = self.check(1)
                self.assertEqual(code, 2, result)
                self.assertIn("bottom host edge", result["diagnostics"][0])

    def test_obscured_available_edge_does_not_search_farther_for_passing_pixels(self):
        self.raw["occluders"] = [{"kind": "panel", "rect": rect(0, 170, 320, 70)},
                                 {"kind": "ui", "rect": rect(0, 169, 320, 1)}]
        result, code = self.check(1)
        self.assertEqual(code, 2, result)
        self.assertIn("bottom available edge", result["diagnostics"][0])

    def test_reported_pixel_runs_retain_ui_exclusion_holes(self):
        self.raw["occluders"] = [{"kind": "panel", "rect": rect(0, 170, 320, 70)},
                                 {"kind": "ui", "rect": rect(100, 160, 20, 10)}]
        result, code = self.check(1)
        self.assertEqual(code, 0, result)
        bottom = next(edge for edge in result["measurement"]["edges"] if edge["side"] == "bottom")
        self.assertEqual(bottom["samples"], 300)
        self.assertEqual(bottom["sample_runs"], [{"start": {"x": 0, "y": 169}, "end": {"x": 99, "y": 169}},
                                                {"start": {"x": 120, "y": 169}, "end": {"x": 319, "y": 169}}])

    def test_safety_margin_uses_subject_pixels_not_canvas(self):
        self.png_path.write_bytes(make_png(320, 240, [(15, 90, 55, 130, SUBJECT)]))
        result, code = self.check(3)
        self.assertEqual(code, 1, result)
        self.assertEqual([row["id"] for row in result["checks"] if not row["passed"]], ["margin-left"])
        self.assertEqual(result["measurement"]["scene"], self.raw["host"])

    def test_css_positions_and_minimum_area_at_double_dpr(self):
        self.png_path.write_bytes(make_png(640, 480, [(200, 180, 280, 260, SUBJECT)]))
        result, code = self.check()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["measurement"]["subject"]["x"], 100)
        self.assertEqual(result["measurement"]["subject"]["area_px"], 1600)
        self.assertEqual(result["screenshot"]["scale_x"], 2)
        self.plan["cases"][1]["viewport_assertions"]["subject_min_area_px"] = 2000
        result, code = self.check()
        self.assertEqual(code, 2, result)
        self.assertIn("not identified", result["diagnostics"][0])

    def test_ui_occluders_mask_pixels_but_do_not_shrink_available_area(self):
        self.raw["occluders"] = [{"kind": "ui", "rect": rect(250, 70, 60, 100), "class": "panel-like-class"}]
        self.png_path.write_bytes(make_png(320, 240, [(140, 90, 180, 130, SUBJECT), (255, 75, 305, 165, SUBJECT)]))
        result, code = self.check()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["measurement"]["available"], self.raw["host"])
        self.assertEqual(result["measurement"]["subject"]["x"], 140)

    def test_missing_small_or_multiple_subjects_are_unverified(self):
        variants = ([], [(100, 90, 104, 94, SUBJECT)],
                    [(40, 90, 80, 130, SUBJECT), (150, 90, 180, 120, SUBJECT)],
                    [(40, 90, 50, 96, SUBJECT), (150, 90, 157, 97, SUBJECT)])
        for shapes in variants:
            with self.subTest(shapes=shapes):
                self.png_path.write_bytes(make_png(320, 240, shapes))
                result, code = self.check()
                self.assertEqual(code, 2, result)
                self.assertEqual(result["status"], "unverified")
                self.assertTrue(result["diagnostics"])

    def test_partially_obscured_subject_is_not_a_false_center_pass(self):
        # The true subject center is x=160, but masking its right half would leave
        # a visible center at x=120, exactly the available-region center.
        self.raw["occluders"].append({"kind": "ui", "rect": rect(140, 80, 100, 60)})
        self.png_path.write_bytes(make_png(320, 240, [(100, 90, 220, 130, SUBJECT)]))
        result, code = self.check()
        self.assertEqual(code, 2, result)
        self.assertIn("occluder", result["diagnostics"][0])

    def test_obscured_edge_and_ambiguous_floating_panel_are_unverified(self):
        for occluder in ({"kind": "ui", "rect": rect(0, 0, 320, 2)},
                         {"kind": "panel", "rect": rect(140, 100, 40, 40)}):
            self.raw["occluders"] = [occluder]
            result, code = self.check(1)
            self.assertEqual(code, 2, result)

    def test_crop_and_corrupt_png_are_unverified(self):
        original = self.png_path.read_bytes()
        corrupt = bytearray(original)
        corrupt[30] ^= 1
        for data in (make_png(319, 210), bytes(corrupt), original[:50], b"not a png"):
            self.png_path.write_bytes(data)
            result, code = self.check()
            self.assertEqual(code, 2, result)
            self.assertEqual(result["status"], "unverified")

    def test_raw_metadata_is_not_replaced_with_plan_values(self):
        for field, value in (("source", "http://localhost/other"), ("build_id", "other-build"),
                             ("state", "other-state"), ("node_id", "other-node"),
                             ("viewport", {"width": 640, "height": 480})):
            with self.subTest(field=field):
                previous = self.raw[field]
                self.raw[field] = value
                result, code = self.check()
                self.assertEqual(code, 2, result)
                self.assertEqual(result[field], value)
                self.assertIn("does not match", result["diagnostics"][0])
                self.raw[field] = previous

    def test_rejects_forged_subject_and_passed_fields(self):
        self.raw.update(subject=rect(100, 90, 40, 40), passed=True, checks=[{"id": "horizontal-center", "passed": True}])
        self.png_path.write_bytes(make_png(320, 240))
        result, code = self.check()
        self.assertEqual(code, 2, result)
        self.assertIsNone(result["measurement"]["subject"])

    def test_capture_must_bind_the_supplied_screenshot(self):
        for value in (None, "other.png", "../outside.png", str(self.png_path)):
            self.raw["screenshot"] = value
            result, code = self.check()
            self.assertEqual(code, 2, result)
            self.assertIn("screenshot", result["diagnostics"][0])

    def test_invalid_raw_geometry_is_unverified(self):
        for value in (True, float("nan"), float("inf"), -1, 0):
            self.raw["host"]["width"] = value
            result, code = self.check()
            self.assertEqual(code, 2, result)
            self.assertIsNone(result["measurement"]["host"])

    def test_invalid_threshold_values_never_bypass_assertions(self):
        for key in ("box_tolerance_px", "center_tolerance_px", "safe_margin_px", "edge_color_tolerance",
                    "edge_min_non_background", "subject_min_area_px"):
            for value in (True, False, float("nan"), float("inf"), "40", None):
                with self.subTest(key=key, value=value):
                    candidate = dict(CONFIG, **{key: value})
                    self.assertTrue(validate_assertions("VIEW-02", candidate))
        for key, value in (("box_tolerance_px", 9999), ("center_tolerance_px", 9999), ("safe_margin_px", 0),
                           ("safe_margin_px", 39), ("edge_min_non_background", 0), ("edge_color_tolerance", 255),
                           ("subject_min_area_px", 0), ("subject_min_rgb", [0, 0, 0]),
                           ("subject_max_rgb", [100, 100, 100]), ("subject_min_rgb", [True, 235, 150])):
            with self.subTest(key=key, value=value):
                self.assertTrue(validate_assertions("VIEW-02", dict(CONFIG, **{key: value})))
        self.assertTrue(validate_assertions("VIEW-02", {"subject_min_area_px": 50}))
        self.assertTrue(validate_assertions("VIEW-02", dict(CONFIG, unexpected=True)))
        self.assertEqual(validate_assertions("VIEW-02", CONFIG), [])

    def test_actual_run_check_records_png_and_raw_inputs(self):
        freeze(self.plan_path, self.root / "lock.json")
        self.raw["captured_at"] = datetime.now(timezone.utc).isoformat()
        self.save()
        run_path = self.root / "run.json"
        completed = subprocess.run([sys.executable, "-B", str(SCRIPTS / "run_check.py"), "--plan", str(self.plan_path),
                                    "--case-id", "c2", "--executor", "synthetic-test", "--out", str(run_path),
                                    "--input", str(self.raw_path), "--input", str(self.png_path), "--",
                                    sys.executable, "-B", str(SCRIPTS / "check_viewport.py"), "--plan", str(self.plan_path),
                                    "--case-id", "c2", "--measurement", str(self.raw_path), "--screenshot", str(self.png_path)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        run = json.loads(run_path.read_text(encoding="utf-8"))
        result = json.loads(run["stdout"])
        self.assertEqual(run["exit_code"], 0)
        self.assertEqual(result["status"], "pass")
        self.assertEqual({row["sha256"] for row in run["inputs"]},
                         {result["screenshot"]["sha256"], result["measurement_artifact"]["sha256"]})

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "optional Pillow is not installed")
    def test_real_jpeg_and_webp_are_decoded_without_rewriting_artifact(self):
        from PIL import Image
        original = self.png_path.read_bytes()
        for image_format, suffix in (("JPEG", "jpg"), ("WEBP", "webp")):
            with self.subTest(image_format=image_format):
                output = BytesIO()
                with Image.open(BytesIO(original)) as image:
                    image.save(output, format=image_format, quality=100, lossless=True, subsampling=0)
                self.png_path = self.root / f"capture.{suffix}"
                self.raw["screenshot"] = self.png_path.name
                captured = output.getvalue()
                self.png_path.write_bytes(captured)
                result, code = self.check()
                self.assertEqual(code, 0, result)
                self.assertEqual(result["screenshot"]["format"], image_format)
                self.assertEqual(self.png_path.read_bytes(), captured)

    def test_exported_expected_thresholds_are_the_ones_actually_used(self):
        for index in (1, 2, 3):
            result, code = self.check(index)
            self.assertEqual(code, 0, result)
            self.assertEqual({row["id"]: row["expected"] for row in result["checks"]},
                             expected_checks(f"VIEW-0{index}", CONFIG))


class PNGReaderTests(unittest.TestCase):
    def test_rgb_rgba_and_all_row_filters_decode_real_pixels(self):
        for rgba in (False, True):
            for filter_type in range(5):
                with self.subTest(rgba=rgba, filter_type=filter_type):
                    image = read_png(make_png(9, 8, [(2, 3, 6, 5, SUBJECT)], rgba=rgba, filter_type=filter_type))
                    self.assertEqual(tuple(image.rgb(3, 4)), SUBJECT)
                    self.assertEqual(tuple(image.rgb(8, 7)), BACKGROUND)

    def test_unsupported_depth_interlace_and_transparency_are_diagnosed(self):
        for depth, color, interlace in ((16, 2, 0), (8, 3, 0), (8, 2, 1)):
            data = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, depth, color, 0, 0, interlace))
            with self.assertRaisesRegex(ValueError, "unsupported PNG"):
                read_png(data)
        with self.assertRaisesRegex(ValueError, "transparent PNG"):
            read_png(make_png(2, 2, [(0, 0, 1, 1, (*SUBJECT, 100))], rgba=True))

    def test_png_is_independent_of_optional_pillow(self):
        with patch.dict(sys.modules, {"PIL": None}):
            self.assertEqual(read_image(make_png(2, 2)).format, "PNG")
            for data in (b"\xff\xd8\xff" + b"synthetic", b"RIFF1234WEBPsynthetic"):
                with self.assertRaisesRegex(ValueError, "requires optional Pillow"):
                    read_image(data)


if __name__ == "__main__":
    unittest.main()

"""Read captured DOM geometry and PNG pixels; never drive or claim to drive a browser.

All coordinates and thresholds are CSS pixels (area thresholds are CSS px squared).
The caller freezes viewport_assertions and passes both artifacts to run_check --input.
Opaque, non-interlaced 8-bit RGB/RGBA PNGs use only the standard library. JPEG/WebP
decoding optionally uses Pillow; screenshots are never rewritten or resampled.
Unsupported or ambiguous measurements exit 2, definite failures 1, complete passes 0.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path, PureWindowsPath
import struct
import zlib

from eval_contract import read_json, require


SIDES = ("top", "right", "bottom", "left")
REQUIRED_CHECK_IDS = {
    "VIEW-01": {f"{kind}-{side}" for kind in ("box", "pixels") for side in SIDES},
    "VIEW-02": {"horizontal-center"},
    "VIEW-03": {f"margin-{side}" for side in SIDES},
}
_REQUIRED_FIELDS = {
    "VIEW-01": {"box_tolerance_px", "edge_background_rgb", "edge_color_tolerance",
                "edge_min_non_background"},
    "VIEW-02": {"center_tolerance_px", "subject_min_rgb", "subject_max_rgb", "subject_min_area_px"},
    "VIEW-03": {"safe_margin_px", "subject_min_rgb", "subject_max_rgb", "subject_min_area_px"},
}
_LIMITS = {
    "box_tolerance_px": (0, 4), "center_tolerance_px": (0, 16),
    "safe_margin_px": (40, 4096), "edge_color_tolerance": (0, 32),
    "edge_min_non_background": (0.9, 1), "subject_min_area_px": (1, 1_000_000),
}
_RGB_FIELDS = {"edge_background_rgb", "subject_min_rgb", "subject_max_rgb"}
_MAX_PIXELS = 32_000_000
_MAX_PNG_BYTES = 64_000_000


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_assertions(rule_id, assertions):
    """Pure field validation for plan freezing; no reads, imports of plan_cases or I/O.

    Bounds prevent vacuous tolerances, including weakening the documented 40 CSS px
    safety floor. RGB thresholds still need a source-backed, view-specific rationale;
    no universal subject color or black-background defect rule is inferred here.
    """
    if rule_id not in _REQUIRED_FIELDS:
        return [f"unsupported viewport rule: {rule_id}"]
    if not isinstance(assertions, dict):
        return ["viewport_assertions must be an object"]
    errors = []
    missing = _REQUIRED_FIELDS[rule_id] - assertions.keys()
    if missing:
        errors.append(f"missing viewport_assertions: {sorted(missing)}")
    unknown = assertions.keys() - (_LIMITS.keys() | _RGB_FIELDS)
    if unknown:
        errors.append(f"unknown viewport_assertions: {sorted(map(str, unknown))}")
    for key, (minimum, maximum) in _LIMITS.items():
        if key in assertions and (not finite_number(assertions[key])
                                  or not minimum <= assertions[key] <= maximum):
            errors.append(f"{key} must be a finite number in [{minimum}, {maximum}]")
    valid_rgb = set()
    for key in _RGB_FIELDS & assertions.keys():
        rgb = assertions[key]
        if not isinstance(rgb, list) or len(rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in rgb):
            errors.append(f"{key} must contain three integer RGB channels in [0, 255]")
        else:
            valid_rgb.add(key)
    if {"subject_min_rgb", "subject_max_rgb"} <= valid_rgb:
        minimum, maximum = assertions["subject_min_rgb"], assertions["subject_max_rgb"]
        if any(low > high for low, high in zip(minimum, maximum)):
            errors.append("subject_min_rgb must not exceed subject_max_rgb")
        if max(minimum) < 32:
            errors.append("subject RGB range is too broad: it must exclude near-black pixels")
    return errors


def expected_checks(rule_id, assertions):
    """Return the frozen numeric thresholds by check ID, without reading artifacts."""
    errors = validate_assertions(rule_id, assertions)
    require(not errors, "; ".join(errors))
    if rule_id == "VIEW-01":
        return {**{f"box-{side}": assertions["box_tolerance_px"] for side in SIDES},
                **{f"pixels-{side}": assertions["edge_min_non_background"] for side in SIDES}}
    if rule_id == "VIEW-02":
        return {"horizontal-center": assertions["center_tolerance_px"]}
    return {f"margin-{side}": assertions["safe_margin_px"] for side in SIDES}


@dataclass
class RasterImage:
    width: int
    height: int
    channels: int
    pixels: bytearray
    format: str = "PNG"

    def rgb(self, x, y):
        offset = (y * self.width + x) * self.channels
        return self.pixels[offset:offset + 3]


def _paeth(left, up, upper_left):
    predictor = left + up - upper_left
    distances = (abs(predictor - left), abs(predictor - up), abs(predictor - upper_left))
    return (left, up, upper_left)[distances.index(min(distances))]


def read_png(data):
    """Decode the actual PNG stream, including CRCs and all five PNG row filters."""
    require(len(data) <= _MAX_PNG_BYTES, "PNG exceeds the supported 64 MB file limit")
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "invalid PNG signature")
    offset, header, ended, idat_closed = 8, None, False, False
    compressed = bytearray()
    while offset < len(data):
        require(offset + 12 <= len(data), "truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        require(offset + 12 + length <= len(data), "truncated PNG chunk payload")
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        require(zlib.crc32(kind + body) & 0xffffffff == crc, f"PNG CRC mismatch in {kind!r}")
        offset += 12 + length
        require(header is not None or kind == b"IHDR", "PNG IHDR must be first")
        if kind == b"IHDR":
            require(header is None and length == 13, "invalid or duplicate PNG IHDR")
            header = struct.unpack(">IIBBBBB", body)
            width, height, depth, color, compression, filtering, interlace = header
            require(width > 0 and height > 0 and width * height <= _MAX_PIXELS,
                    "unsupported PNG dimensions (limit: 32 million pixels)")
            require(depth == 8 and color in (2, 6) and compression == filtering == interlace == 0,
                    "unsupported PNG: require non-interlaced 8-bit RGB or RGBA")
        elif kind == b"IDAT":
            require(not idat_closed, "PNG IDAT chunks must be consecutive")
            compressed.extend(body)
        elif kind == b"IEND":
            require(length == 0 and compressed, "invalid PNG IEND or missing pixel data")
            ended = True
            break
        else:
            if compressed:
                idat_closed = True
            require(kind != b"tRNS", "PNG transparency via tRNS is unsupported")
            require(kind == b"PLTE" or kind[0] & 32, f"unsupported critical PNG chunk: {kind!r}")
    require(header is not None and ended and offset == len(data), "incomplete PNG or data after IEND")
    width, height, _, color, _, _, _ = header
    channels = 3 if color == 2 else 4
    stride = width * channels
    expected_size = (stride + 1) * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(bytes(compressed), expected_size + 1)
    require(len(raw) == expected_size and decoder.eof and not decoder.unused_data
            and not decoder.unconsumed_tail, "invalid PNG compressed pixel length")
    pixels = bytearray(width * height * channels)
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        require(filter_type <= 4, "unsupported PNG row filter")
        row = bytearray(raw[start + 1:start + 1 + stride])
        if filter_type:
            for index in range(stride):
                left = row[index - channels] if index >= channels else 0
                up = previous[index]
                upper_left = previous[index - channels] if index >= channels else 0
                predictor = (left if filter_type == 1 else up if filter_type == 2 else
                             (left + up) // 2 if filter_type == 3 else _paeth(left, up, upper_left))
                row[index] = (row[index] + predictor) & 255
        pixels[y * stride:(y + 1) * stride] = row
        previous = row
    require(channels != 4 or all(alpha == 255 for alpha in pixels[3::4]),
            "transparent PNG cannot establish final rendered colors")
    return RasterImage(width, height, channels, pixels)


def read_image(data):
    """Recognize actual magic bytes. Optional codecs decode, never edit, the capture."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return read_png(data)
    image_format = "JPEG" if data.startswith(b"\xff\xd8\xff") else "WEBP" if (
        data.startswith(b"RIFF") and data[8:12] == b"WEBP") else None
    require(image_format is not None, "unsupported screenshot magic: expected PNG, JPEG or WebP")
    require(len(data) <= _MAX_PNG_BYTES, "screenshot exceeds the supported 64 MB file limit")
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("JPEG/WebP decoding requires optional Pillow; PNG needs only the standard library") from exc
    with Image.open(BytesIO(data)) as decoded:
        require(decoded.format == image_format, "screenshot magic and decoder format disagree")
        require(decoded.width > 0 and decoded.height > 0 and decoded.width * decoded.height <= _MAX_PIXELS,
                "unsupported screenshot dimensions (limit: 32 million pixels)")
        require(getattr(decoded, "n_frames", 1) == 1, "animated screenshot is unsupported")
        require(decoded.getexif().get(274, 1) == 1, "rotated EXIF screenshot orientation is unsupported")
        require(decoded.mode in {"RGB", "RGBA", "L"}, "unsupported screenshot color mode")
        # Expanding grayscale to three equal channels is decoding, not a pixel edit.
        image = decoded.convert("RGB") if decoded.mode == "L" else decoded
        channels = 4 if image.mode == "RGBA" else 3
        pixels = bytearray(image.tobytes())
        require(channels != 4 or all(alpha == 255 for alpha in pixels[3::4]),
                "transparent screenshot cannot establish final rendered colors")
        return RasterImage(image.width, image.height, channels, pixels, image_format)


def rect_fields(value, label):
    require(isinstance(value, dict), f"{label}: rect must be an object")
    require(all(finite_number(value.get(key)) for key in ("x", "y", "width", "height")),
            f"{label}: rect coordinates must be finite numbers")
    require(value["width"] > 0 and value["height"] > 0, f"{label}: rect size must be positive")
    return {key: value[key] for key in ("x", "y", "width", "height")}


def bounds(rect):
    return rect["x"], rect["y"], rect["x"] + rect["width"], rect["y"] + rect["height"]


def intersection(first, second):
    ax, ay, ar, ab = bounds(first)
    bx, by, br, bb = bounds(second)
    x, y, right, bottom = max(ax, bx), max(ay, by), min(ar, br), min(ab, bb)
    if right <= x or bottom <= y:
        return None
    return {"x": x, "y": y, "width": right - x, "height": bottom - y}


def available_rect(host, occluders):
    """Cut the panel's occupied side; choose the largest axis-aligned clear region.

    Floating panels with equally plausible sides are ambiguous, not an excuse to
    assume desktop/right docking. UI rectangles never change the available region.
    """
    hx, hy, hr, hb = bounds(host)
    left, top, right, bottom = hx, hy, hr, hb
    for occluder in occluders:
        if occluder["kind"] != "panel":
            continue
        panel = intersection(host, occluder["rect"])
        if panel is None:
            continue
        px, py, pr, pb = bounds(panel)
        choices = [(max(0, px - hx) * host["height"], "right"),
                   (max(0, hr - pr) * host["height"], "left"),
                   (max(0, py - hy) * host["width"], "bottom"),
                   (max(0, hb - pb) * host["width"], "top")]
        choices.sort(reverse=True)
        require(choices[0][0] > 0 and choices[0][0] > choices[1][0] * 1.05,
                "panel docking side is ambiguous from captured geometry")
        side = choices[0][1]
        if side == "right":
            right = min(right, px)
        elif side == "left":
            left = max(left, pr)
        elif side == "bottom":
            bottom = min(bottom, py)
        else:
            top = max(top, pb)
    require(right > left and bottom > top, "panels leave no measurable rectangular available area")
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def pixel_bounds(rect, image, scale_x, scale_y):
    x, y, right, bottom = bounds(rect)
    # Select pixel centers inside the CSS box, including fractional CSS coordinates.
    return (max(0, math.ceil(x * scale_x - 0.5)), max(0, math.ceil(y * scale_y - 0.5)),
            min(image.width, math.ceil(right * scale_x - 0.5)),
            min(image.height, math.ceil(bottom * scale_y - 0.5)))


def occlusion_mask(image, occluders, scale_x, scale_y):
    mask = bytearray(image.width * image.height)
    for occluder in occluders:
        x, y, right, bottom = pixel_bounds(occluder["rect"], image, scale_x, scale_y)
        if right <= x or bottom <= y:
            continue
        for row in range(y, bottom):
            mask[row * image.width + x:row * image.width + right] = b"\x01" * (right - x)
    return mask


def edge_line(image, rect, side, scale_x, scale_y):
    x, y, right, bottom = pixel_bounds(rect, image, scale_x, scale_y)
    require(right > x and bottom > y, "edge boundary contains no screenshot pixel centers")
    if side in {"top", "bottom"}:
        return [(column, y if side == "top" else bottom - 1) for column in range(x, right)]
    return [(x if side == "left" else right - 1, row) for row in range(y, bottom)]


def panels_covering_edge(host, occluders, side):
    """Prove geometric coverage of the entire host edge using panel rectangles only.

    Merely leaving too few samples, or mixing panel and UI coverage, cannot authorize
    moving a sample line inward. A tiny numerical epsilon only absorbs rect sums.
    """
    hx, hy, hr, hb = bounds(host)
    intervals, panels = [], []
    for occluder in occluders:
        if occluder["kind"] != "panel":
            continue
        panel = intersection(host, occluder["rect"])
        if panel is None:
            continue
        px, py, pr, pb = bounds(panel)
        touches = {"top": py <= hy + 1e-6, "right": pr >= hr - 1e-6,
                   "bottom": pb >= hb - 1e-6, "left": px <= hx + 1e-6}[side]
        if touches:
            intervals.append((px, pr) if side in {"top", "bottom"} else (py, pb))
            panels.append(occluder["rect"])
    start, end = (hx, hr) if side in {"top", "bottom"} else (hy, hb)
    cursor = start
    for left, right in sorted(intervals):
        if left > cursor + 1e-6:
            return []
        cursor = max(cursor, right)
    return panels if cursor >= end - 1e-6 else []


def sample_runs(samples):
    """Compact exact pixel coordinates, retaining holes excluded by DOM occluders."""
    runs = []
    for x, y in samples:
        point = {"x": x, "y": y}
        if runs and abs(x - runs[-1]["end"]["x"]) + abs(y - runs[-1]["end"]["y"]) == 1:
            runs[-1]["end"] = point
        else:
            runs.append({"start": point, "end": point})
    return runs


def measure_edges(image, host, available, occluders, mask, scale_x, scale_y, assertions):
    """Measure visible borders; never claim that pixels behind a panel were observed.

    Full scene-vs-host box assertions remain separate. A completely panel-covered
    host edge may use the nearest same-side available boundary. If that boundary is
    also obscured, the result stays unverified instead of searching for nicer pixels.
    """
    background = assertions["edge_background_rgb"]
    tolerance = assertions["edge_color_tolerance"]
    edges = []
    for side in SIDES:
        boundary, boundary_rect, reason, panels = "host", host, None, []
        line = edge_line(image, host, side, scale_x, scale_y)
        samples = [(column, row) for column, row in line if not mask[row * image.width + column]]
        if not samples:
            panels = panels_covering_edge(host, occluders, side)
            if panels:
                boundary, boundary_rect = "available", available
                reason = "host_edge_fully_occluded_by_panel"
                line = edge_line(image, available, side, scale_x, scale_y)
                samples = [(column, row) for column, row in line if not mask[row * image.width + column]]
        require(len(samples) >= max(16, math.ceil(len(line) * 0.1)),
                f"{side} {boundary} edge has insufficient unoccluded pixel samples")
        non_background = sum(any(abs(channel - expected) > tolerance
                                 for channel, expected in zip(image.rgb(column, row), background))
                             for column, row in samples)
        edges.append({"side": side, "samples": len(samples),
                      "non_background_fraction": non_background / len(samples),
                      "boundary": boundary, "boundary_rect": boundary_rect,
                      "sample_line": {"coordinate_space": "screenshot_pixels",
                                      "start": {"x": line[0][0], "y": line[0][1]},
                                      "end": {"x": line[-1][0], "y": line[-1][1]}},
                      "sample_runs": sample_runs(samples), "reason": reason, "panel_rects": panels})
    return edges


def detect_subject(image, host, mask, scale_x, scale_y, assertions):
    minimum, maximum = assertions["subject_min_rgb"], assertions["subject_max_rgb"]
    x, y, right, bottom = pixel_bounds(host, image, scale_x, scale_y)
    candidates = bytearray(image.width * image.height)
    for row in range(y, bottom):
        for column in range(x, right):
            index = row * image.width + column
            if mask[index]:
                continue
            offset = index * image.channels
            if all(minimum[channel] <= image.pixels[offset + channel] <= maximum[channel] for channel in range(3)):
                candidates[index] = 1
    components = []
    for index in range(len(candidates)):
        if not candidates[index]:
            continue
        stack, count, touches_occluder = [index], 0, False
        candidates[index] = 0
        min_x, min_y, max_x, max_y = image.width, image.height, -1, -1
        while stack:
            current = stack.pop()
            row, column = divmod(current, image.width)
            count += 1
            min_x, min_y = min(min_x, column), min(min_y, row)
            max_x, max_y = max(max_x, column), max(max_y, row)
            # Eight-connectivity preserves diagonal anti-aliased outlines.
            for next_row in range(max(y, row - 1), min(bottom, row + 2)):
                for next_column in range(max(x, column - 1), min(right, column + 2)):
                    neighbor = next_row * image.width + next_column
                    touches_occluder = touches_occluder or bool(mask[neighbor])
                    if candidates[neighbor]:
                        candidates[neighbor] = 0
                        stack.append(neighbor)
        area = count / (scale_x * scale_y)
        # A runner-up just below the minimum may still make the largest component
        # ambiguous. Keep every component that could reach the 25% ambiguity bound.
        if area >= assertions["subject_min_area_px"] * 0.25:
            components.append({"x": min_x / scale_x, "y": min_y / scale_y,
                               "width": (max_x - min_x + 1) / scale_x,
                               "height": (max_y - min_y + 1) / scale_y, "area_px": area,
                               "touches_occluder": touches_occluder})
    require(components, "subject not identified: no RGB component meets subject_min_area_px")
    components.sort(key=lambda component: component["area_px"], reverse=True)
    require(components[0]["area_px"] >= assertions["subject_min_area_px"],
            "subject not identified: no RGB component meets subject_min_area_px")
    require(len(components) == 1 or components[1]["area_px"] < components[0]["area_px"] * 0.25,
            "subject is ambiguous: multiple substantial RGB components")
    require(components[0]["area_px"] <= host["width"] * host["height"] * 0.6,
            "subject RGB range covers most of the host; object identity is unverified")
    require(not components[0]["touches_occluder"],
            "subject touches a DOM occluder; its full projected bounds are unverified")
    return {**components[0], "method": "rgb-largest-connected-component",
            "candidate_count": len(components)}


def artifact_info(path, plan_root):
    path = Path(path).resolve()
    require(path.is_relative_to(plan_root), "measurement and screenshot must be inside the plan directory")
    data = path.read_bytes()
    require(data, f"empty artifact: {path.name}")
    return data, {"path": path.relative_to(plan_root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}


def check_viewport(plan_path, case_id, measurement_path, screenshot_path):
    """Return (JSON result, exit code); metadata always comes from the raw capture."""
    result = {"kind": "viewport-check", "version": 1, "rule_id": None, "node_id": None,
              "state": None, "viewport": None, "source": None, "build_id": None,
              "checks": [], "measurement": {"host": None, "scene": None, "available": None,
                                             "subject": None, "edges": []},
              "screenshot": None, "measurement_artifact": None, "status": "unverified", "diagnostics": []}
    try:
        plan_path = Path(plan_path).resolve()
        plan = read_json(plan_path)
        require(isinstance(plan, dict), "plan must be an object")
        require(type(plan.get("version")) is int and plan["version"] == 2, "viewport checks require a v2 plan")
        cases = [case for case in plan.get("cases", []) if isinstance(case, dict) and case.get("id") == case_id]
        require(len(cases) == 1, "case-id must identify exactly one frozen case")
        case = cases[0]
        rule_id = case.get("rule_id")
        result["rule_id"] = rule_id
        assertions = case.get("viewport_assertions")
        errors = validate_assertions(rule_id, assertions)
        require(not errors, "; ".join(errors))
        _, result["measurement_artifact"] = artifact_info(measurement_path, plan_path.parent)
        image_data, result["screenshot"] = artifact_info(screenshot_path, plan_path.parent)
        raw = read_json(measurement_path)
        require(isinstance(raw, dict), "measurement must be an object")
        screenshot_ref = raw.get("screenshot")
        require(isinstance(screenshot_ref, str) and screenshot_ref.strip(),
                "raw screenshot must name its captured image relative to the plan directory")
        require(not Path(screenshot_ref).is_absolute() and not PureWindowsPath(screenshot_ref).drive
                and (plan_path.parent / screenshot_ref).resolve() == Path(screenshot_path).resolve(),
                "raw screenshot does not match the supplied image")
        for field in ("node_id", "state", "source", "build_id", "captured_at"):
            require(isinstance(raw.get(field), str) and raw[field].strip(), f"raw measurement lacks {field}")
            result[field] = raw[field]
        viewport = raw.get("viewport")
        require(isinstance(viewport, dict) and all(finite_number(viewport.get(field)) and viewport[field] > 0
                                                 for field in ("width", "height")),
                "raw viewport must have finite positive CSS dimensions")
        result["viewport"] = {key: viewport[key] for key in ("width", "height")}
        captured = datetime.fromisoformat(raw["captured_at"].replace("Z", "+00:00"))
        require(captured.utcoffset() is not None, "raw captured_at requires a timezone")
        expected = {"node_id": case.get("node"), "state": case.get("state"),
                    "viewport": case.get("viewport"), "source": case.get("url", plan.get("scope", {}).get("url")),
                    "build_id": plan.get("scope", {}).get("build_id")}
        for field, value in expected.items():
            require(result[field] == value, f"raw {field} does not match the frozen case")
        host, scene = rect_fields(raw.get("host"), "host"), rect_fields(raw.get("scene"), "scene")
        hx, hy, hr, hb = bounds(host)
        require(hx >= 0 and hy >= 0 and hr <= viewport["width"] and hb <= viewport["height"],
                "host extends outside the captured viewport")
        require(isinstance(raw.get("occluders"), list), "raw occluders must be an array, including when empty")
        occluders = []
        for row in raw["occluders"]:
            require(isinstance(row, dict) and row.get("kind") in {"panel", "ui"}, "occluder needs kind panel or ui")
            occluders.append({"kind": row["kind"], "rect": rect_fields(row.get("rect"), "occluder")})
        result["measurement"].update(host=host, scene=scene)
        available = available_rect(host, occluders)
        result["measurement"]["available"] = available
        image = read_image(image_data)
        scale_x, scale_y = image.width / viewport["width"], image.height / viewport["height"]
        require(abs(image.width - viewport["width"] * scale_y) <= 1
                and abs(image.height - viewport["height"] * scale_x) <= 1,
                "screenshot dimensions are not an isotropic full-viewport capture")
        result["screenshot"].update(width=image.width, height=image.height, scale_x=scale_x, scale_y=scale_y,
                                     format=image.format)
        mask = occlusion_mask(image, occluders, scale_x, scale_y)
        thresholds = expected_checks(rule_id, assertions)

        def add_check(check_id, actual, comparison):
            expected_value = thresholds[check_id]
            result["checks"].append({"id": check_id, "passed": comparison(actual, expected_value),
                                     "actual": actual, "expected": expected_value})

        if rule_id == "VIEW-01":
            sx, sy, sr, sb = bounds(scene)
            gaps = {"top": max(0, sy - hy), "right": max(0, hr - sr),
                    "bottom": max(0, hb - sb), "left": max(0, sx - hx)}
            for side in SIDES:
                add_check(f"box-{side}", gaps[side], lambda a, e: a <= e)
            edges = measure_edges(image, host, available, occluders, mask, scale_x, scale_y, assertions)
            result["measurement"]["edges"] = edges
            for edge in edges:
                add_check(f"pixels-{edge['side']}", edge["non_background_fraction"], lambda a, e: a >= e)
        else:
            subject = detect_subject(image, host, mask, scale_x, scale_y, assertions)
            result["measurement"]["subject"] = subject
            if rule_id == "VIEW-02":
                delta = abs(subject["x"] + subject["width"] / 2 - available["x"] - available["width"] / 2)
                add_check("horizontal-center", delta, lambda a, e: a <= e)
            else:
                ax, ay, ar, ab = bounds(available)
                sx, sy, sr, sb = bounds(subject)
                margins = {"top": sy - ay, "right": ar - sr, "bottom": ab - sb, "left": sx - ax}
                for side in SIDES:
                    add_check(f"margin-{side}", margins[side], lambda a, e: a >= e)
        passed = all(check["passed"] for check in result["checks"])
        result["status"] = "pass" if passed else "fail"
        return result, 0 if passed else 1
    except (ValueError, TypeError, KeyError, OSError, OverflowError, struct.error, zlib.error) as exc:
        result["diagnostics"].append(str(exc))
        return result, 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "case-id", "measurement", "screenshot"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    result, exit_code = check_viewport(args.plan, args.case_id, args.measurement, args.screenshot)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

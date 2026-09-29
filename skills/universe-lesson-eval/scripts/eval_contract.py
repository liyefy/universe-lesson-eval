"""Small JSON contracts; structural checks do not attest evidence authenticity."""
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text_fields(obj, names, label):
    require(isinstance(obj, dict), f"{label}: expected object")
    for name in names:
        require(isinstance(obj.get(name), str) and obj[name].strip(),
                f"{label}: missing nonempty {name}")


def string_list(value, label):
    require(isinstance(value, list) and value and
            all(isinstance(item, str) and item.strip() for item in value),
            f"{label}: expected nonempty string array")
    return value


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=unique_object)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def indexed(rows, label, key="id"):
    require(isinstance(rows, list), f"{label}: expected array")
    result = {}
    for row in rows:
        text_fields(row, [key], label)
        require(row[key] not in result, f"{label}: duplicate {key} {row[key]}")
        result[row[key]] = row
    return result


def viewport_fields(viewport, label):
    require(isinstance(viewport, dict), f"{label}: viewport must be an object")
    for dimension in ("width", "height"):
        value = viewport.get(dimension)
        require(type(value) in (int, float) and value > 0
                and (type(value) is int or math.isfinite(value)),
                f"{label}: viewport {dimension} must be finite and positive")


def plan_cases(plan):
    text_fields(plan, ["audit_id"], "plan")
    require(type(plan.get("version")) is int and plan["version"] in {1, 2},
            "plan: version must be 1 or 2")
    text_fields(plan.get("scope"), ["topic", "version", "url", "environment"], "scope")
    nodes = indexed(plan.get("inventory"), "inventory", "node_id")
    cases = indexed(plan.get("cases"), "cases")
    require(nodes and cases, "plan: inventory and cases cannot be empty")
    required, covered = set(), set()
    for node, row in nodes.items():
        rules = string_list(row.get("required_rules"), f"inventory {node}")
        require(len(rules) == len(set(rules)), f"inventory {node}: duplicate rule")
        required.update((node, rule) for rule in rules)
    for case_id, case in cases.items():
        text_fields(case, ["title", "node", "rule_id", "source", "expected"], case_id)
        if "url" in case:
            text_fields(case, ["url"], case_id)
        for key in ("critical", "allow_not_applicable"):
            require(type(case.get(key)) is bool, f"{case_id}: {key} must be boolean")
        if case["allow_not_applicable"]:
            text_fields(case, ["not_applicable_reason"], case_id)
        kinds = string_list(case.get("required_evidence"), case_id)
        allowed = {"code", "blackbox", "analysis"} if plan["version"] == 2 else {"code", "blackbox"}
        require(set(kinds) <= allowed and len(kinds) == len(set(kinds)),
                f"{case_id}: invalid/duplicate evidence kind")
        if "blackbox" in kinds:
            require(case.get("blackbox_method") in {"visual", "interaction", "listening"},
                    f"{case_id}: missing blackbox_method")
            text_fields(case, ["state"], case_id)
            string_list(case.get("steps"), f"{case_id}: planned steps")
            viewport_fields(case.get("viewport"), case_id)
        pair = (case["node"], case["rule_id"])
        require(pair in required, f"{case_id}: node/rule absent from inventory")
        covered.add(pair)
    require(required == covered, f"plan: uncovered node/rule pairs {sorted(required - covered)}")
    if plan["version"] == 2:
        from v2_contract import validate_plan_fields
        validate_plan_fields(plan, cases, nodes)
    return cases

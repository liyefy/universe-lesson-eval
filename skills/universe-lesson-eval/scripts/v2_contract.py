"""Frozen v2 provenance and scope checks; hashes are integrity checks, not signatures."""
from datetime import datetime
import json
from pathlib import Path, PureWindowsPath
import re

from eval_contract import indexed, require, sha256, string_list, text_fields, viewport_fields
from scoring import DIMENSION_BUDGETS


def digest_field(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"{label}: expected lowercase SHA-256")


def timestamp(value, label):
    require(isinstance(value, str) and value.strip(), f"{label}: missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.utcoffset() is not None, f"{label}: timestamp needs timezone")
    return parsed


def contained_file(base, path, label):
    require(isinstance(path, str) and path.strip(), f"{label}: missing path")
    root = Path(base).resolve()
    artifact = (root / path).resolve()
    require(artifact.is_relative_to(root), f"{label}: path escapes evidence root")
    require(artifact.is_file() and artifact.stat().st_size > 0,
            f"{label}: missing/empty artifact {artifact}")
    return artifact


def validate_sources(plan, plan_root):
    for source in plan["sources"]:
        artifact = contained_file(plan_root, source["path"], f"source {source['id']}")
        require(sha256(artifact) == source["sha256"],
                f"source {source['id']}: snapshot SHA-256 changed")


def validate_plan_fields(plan, cases, nodes):
    scope = plan["scope"]
    text_fields(scope, ["build_id", "coverage"], "scope")
    require(scope["coverage"] in {"full", "focused"}, "scope: invalid coverage")
    dimensions = string_list(scope.get("dimensions"), "scope dimensions")
    require(len(dimensions) == len(set(dimensions)) and set(dimensions) <= set(DIMENSION_BUDGETS),
            "scope: unknown/duplicate dimension")
    if scope["coverage"] == "full":
        require(set(dimensions) == set(DIMENSION_BUDGETS), "full scope requires all five dimensions")
    sources = indexed(plan.get("sources"), "sources")
    rules = indexed(plan.get("rules"), "rules")
    require(sources and rules, "v2 plan: sources and rules cannot be empty")
    for source_id, source in sources.items():
        text_fields(source, ["path", "sha256"], f"source {source_id}")
        path = Path(source["path"])
        require(not path.is_absolute() and not PureWindowsPath(source["path"]).drive
                and ".." not in path.parts and ".." not in PureWindowsPath(source["path"]).parts,
                f"source {source_id}: snapshot path must be relative without traversal")
        digest_field(source["sha256"], f"source {source_id}")
    for rule_id, rule in rules.items():
        text_fields(rule, ["source", "version", "applicability"], f"rule {rule_id}")
        require(rule["source"] in sources, f"rule {rule_id}: source is not a frozen source id")
    represented = set()
    for case_id, case in cases.items():
        text_fields(case, ["dimension", "engine"], case_id)
        require(case["dimension"] in dimensions, f"{case_id}: dimension outside frozen scope")
        represented.add(case["dimension"])
        require(case["rule_id"] in rules, f"{case_id}: rule absent from frozen rules")
        source_ids = string_list(case.get("source_ids"), f"{case_id} source_ids")
        require(len(source_ids) == len(set(source_ids)) and set(source_ids) <= set(sources),
                f"{case_id}: unknown/duplicate source id")
        require(rules[case["rule_id"]]["source"] in source_ids,
                f"{case_id}: rule source must be included in source_ids")
        engine, kinds = case["engine"], set(case["required_evidence"])
        require(engine in {"static", "browser", "model"}, f"{case_id}: invalid engine")
        if engine == "model":
            text_fields(case, ["model_reason"], case_id)
            require(kinds & {"blackbox", "analysis"}, f"{case_id}: model judgment cannot use code alone")
        else:
            require("analysis" not in kinds, f"{case_id}: analysis is only for model cases")
            require("code" in kinds, f"{case_id}: deterministic case requires code evidence")
            if engine == "browser":
                require("blackbox" in kinds, f"{case_id}: browser case requires blackbox evidence")
    require(represented == set(dimensions),
            f"scope: dimensions without cases {sorted(set(dimensions) - represented)}")
    for node_id, node in nodes.items():
        require(set(node["required_rules"]) <= set(rules), f"inventory {node_id}: unknown rule")
        if "required_variants" not in node:
            continue
        variants = node["required_variants"]
        require(isinstance(variants, list) and variants,
                f"inventory {node_id}: required_variants must be a nonempty array")
        seen = set()
        for variant in variants:
            text_fields(variant, ["rule_id", "state"], f"inventory {node_id} variant")
            viewport_fields(variant.get("viewport"), f"inventory {node_id} variant")
            require(variant["rule_id"] in node["required_rules"],
                    f"inventory {node_id}: variant rule not required")
            key = (variant["rule_id"], variant["state"],
                   json.dumps(variant["viewport"], sort_keys=True, allow_nan=False))
            require(key not in seen, f"inventory {node_id}: duplicate required variant")
            seen.add(key)
            require(any(case["node"] == node_id and case["rule_id"] == variant["rule_id"]
                        and case.get("state") == variant["state"]
                        and case.get("viewport") == variant["viewport"] for case in cases.values()),
                    f"inventory {node_id}: uncovered state/viewport variant {key}")

"""Frozen v2 provenance and scope checks; hashes are integrity checks, not signatures."""
from datetime import datetime
import json
from pathlib import Path, PureWindowsPath
import re

from eval_contract import indexed, require, sha256, string_list, text_fields, viewport_fields
from scoring import DIMENSION_BUDGETS

VISUAL_RULES = frozenset({"VIEW-01", "VIEW-02", "VIEW-03"})


def source_basis(value, sources, label):
    text_fields(value, ["rationale"], label)
    ids = string_list(value.get("source_ids"), f"{label} source_ids")
    require(len(ids) == len(set(ids)) and set(ids) <= set(sources),
            f"{label}: unknown/duplicate source id")


def visual_requirement(plan, case):
    node = next(row for row in plan["inventory"] if row["node_id"] == case["node"])
    return next((row for row in node.get("visual_requirements", [])
                 if row["rule_id"] == case["rule_id"]), None)


def validate_visual_plan(plan, cases, nodes, sources, rules):
    """Check declared coverage, not whether a human extracted every source node."""
    full = plan["scope"]["coverage"] == "full"
    visual_cases = [case for case in cases.values() if case["rule_id"] in VISUAL_RULES]
    if not full and not visual_cases:
        return
    require(type(plan["scope"].get("visual_contract_version")) is int
            and plan["scope"]["visual_contract_version"] == 1,
            "v2 visual coverage requires scope.visual_contract_version=1; older v2 plans must "
            "freeze a new audit with applicability and runtime evidence, not reuse their old grade")
    viewports = plan["scope"].get("viewports", [])
    require(isinstance(viewports, list), "scope.viewports must be an array")
    sizes = []
    for viewport in viewports:
        viewport_fields(viewport, "scope.viewports")
        sizes.append((viewport["width"], viewport["height"]))
    require(len(sizes) == len(set(sizes)), "scope.viewports contains duplicate dimensions")
    if full:
        require((1024, 768) in sizes, "full visual coverage requires the 1024x768 baseline")
        source_nodes = {node for source in sources.values() for node in source.get("node_ids", [])}
        require(source_nodes, "full visual coverage requires source.node_ids extracted from source snapshots")
        require(source_nodes == set(nodes),
                f"full source/inventory node mismatch: missing={sorted(source_nodes - set(nodes))}, "
                f"extra={sorted(set(nodes) - source_nodes)}")
        for case in cases.values():
            if case["dimension"] != "viewport":
                continue
            requirement = visual_requirement(plan, case)
            if requirement is not None and requirement.get("applicable") is False:
                continue
            require(case["engine"] in {"browser", "model"} and "blackbox" in case["required_evidence"],
                    f"{case['id']}: full viewport conclusions require runtime blackbox evidence; "
                    "static existence and analysis alone are only supporting checks")
    for node_id, node in nodes.items():
        relevant = [case for case in visual_cases if case["node"] == node_id]
        if not full and not relevant:
            continue
        requirements = indexed(node.get("visual_requirements"), f"inventory {node_id} visual_requirements", "rule_id")
        required = VISUAL_RULES if full else {case["rule_id"] for case in relevant}
        require(required <= set(requirements) <= VISUAL_RULES,
                f"inventory {node_id}: explicit VIEW-01/02/03 applicability is missing or unknown")
        require(set(requirements) <= set(node["required_rules"]),
                f"inventory {node_id}: visual requirements must also be required_rules")
        applicable = set()
        for rule_id, requirement in requirements.items():
            label = f"inventory {node_id} {rule_id}"
            require(type(requirement.get("applicable")) is bool, f"{label}: applicable must be boolean")
            source_basis(requirement, sources, label)
            require(rule_id in rules and rules[rule_id]["source"] in requirement["source_ids"],
                    f"{label}: applicability must cite its frozen rule source")
            if full:
                require(any(node_id in sources[source_id].get("node_ids", [])
                            for source_id in requirement["source_ids"]),
                        f"{label}: applicability must cite its course-node source")
            if requirement["applicable"]:
                applicable.add(rule_id)
        states = indexed(node.get("visual_states", []), f"inventory {node_id} visual_states", "state")
        for state, row in states.items():
            require(row.get("panel") in {"open", "closed", "none", "transition"},
                    f"inventory {node_id} {state}: panel must describe the public UI state")
            require(row.get("phase") in {"default", "terminal", "transition"},
                    f"inventory {node_id} {state}: invalid visual phase")
        if applicable:
            require(states, f"inventory {node_id}: applicable visual rules require public visual_states")
            if full:
                phases = {row["phase"] for row in states.values()}
                require("default" in phases, f"inventory {node_id}: missing default visual state")
                exclusions = indexed(node.get("visual_exclusions", []),
                                     f"inventory {node_id} visual_exclusions", "phase")
                require(set(exclusions) <= {"terminal", "transition"},
                        f"inventory {node_id}: only terminal/transition may be excluded")
                for phase, exclusion in exclusions.items():
                    source_basis(exclusion, sources, f"inventory {node_id} {phase} exclusion")
                    require(phase not in phases, f"inventory {node_id}: included phase cannot also be excluded")
                require({"terminal", "transition"} <= phases | set(exclusions),
                        f"inventory {node_id}: freeze terminal/transition states or their source-based exclusions")
                if "VIEW-02" in applicable:
                    require({"open", "closed"} <= {row["panel"] for row in states.values()},
                            f"inventory {node_id}: VIEW-02 requires panel open and closed states")
        for case in relevant:
            requirement = requirements[case["rule_id"]]
            require(case["dimension"] == "viewport", f"{case['id']}: visual rule must use viewport dimension")
            require(set(requirement["source_ids"]) <= set(case["source_ids"]),
                    f"{case['id']}: missing frozen applicability sources")
            if not requirement["applicable"]:
                require(case["allow_not_applicable"]
                        and case.get("not_applicable_reason") == requirement["rationale"],
                        f"{case['id']}: N/A must use the frozen applicability rationale")
                continue
            require(not case["allow_not_applicable"], f"{case['id']}: applicable visual case cannot allow N/A")
            require(case["engine"] == "browser" and {"code", "blackbox"} <= set(case["required_evidence"]),
                    f"{case['id']}: visual propositions require browser code + blackbox; static source checks cannot certify them")
            require(case.get("blackbox_method") == "visual", f"{case['id']}: visual rule requires screenshot observation")
            require(case.get("state") in states, f"{case['id']}: state absent from visual_states")
            require(isinstance(case.get("viewport_assertions"), dict) and case["viewport_assertions"],
                    f"{case['id']}: freeze nonempty viewport_assertions before measuring")
            from check_viewport import validate_assertions
            assertion_errors = validate_assertions(case["rule_id"], case["viewport_assertions"])
            require(not assertion_errors, f"{case['id']}: invalid viewport_assertions: {assertion_errors}")
            if sizes:
                require((case["viewport"]["width"], case["viewport"]["height"]) in sizes,
                        f"{case['id']}: viewport outside scope.viewports")
        if full:
            actual = {(case["rule_id"], case.get("state"), case.get("viewport", {}).get("width"),
                       case.get("viewport", {}).get("height")) for case in relevant}
            expected = {(rule_id, state, width, height) for rule_id in applicable
                        for state in states for width, height in sizes}
            require(expected <= actual,
                    f"inventory {node_id}: uncovered visual state/viewport combinations {sorted(expected - actual)}")


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
        if "node_ids" in source:
            ids = string_list(source["node_ids"], f"source {source_id} node_ids")
            require(len(ids) == len(set(ids)), f"source {source_id}: duplicate node id")
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
    validate_visual_plan(plan, cases, nodes, sources, rules)
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

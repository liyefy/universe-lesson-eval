"""Evidence-bound v2 validation. Content truth and executor identity still require review."""
import hashlib
import json
import math
import os
from pathlib import Path

from eval_contract import indexed, plan_cases, read_json, require, sha256, string_list, text_fields, unique_object, viewport_fields
from scoring import SEVERITY_DEDUCTIONS, derive_score, unavailable_score
from v2_contract import VISUAL_RULES, digest_field, timestamp, validate_sources, visual_requirement

STATUSES = ("pass", "fail", "unverified", "not_applicable")
INVALID_INPUT = (ValueError, TypeError, KeyError, OSError, OverflowError)


class EvidenceUnavailable(ValueError):
    """A claimed pass has no executed observation supporting its proposition."""


def observed(condition, message):
    if not condition:
        raise EvidenceUnavailable(message)


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def measured_rect(value, label):
    observed(isinstance(value, dict) and all(finite_number(value.get(key)) for key in ("x", "y", "width", "height"))
             and value["width"] > 0 and value["height"] > 0, f"{label}: missing finite screen-space rectangle")


def validate_visual_evidence(checked, case, result, plan, base, frozen_at, plan_path):
    """Bind a real check's quantitative output; this cannot attest capture authenticity."""
    if case["rule_id"] not in VISUAL_RULES:
        return
    blackboxes = {entry["path"]: entry for entry in checked if entry["kind"] == "blackbox"}
    runs = [entry["record"] for entry in checked if entry["kind"] == "code"]
    observations = []
    for record in runs:
        try:
            output = json.loads(record["stdout"], object_pairs_hook=unique_object)
        except (ValueError, TypeError):
            continue
        if isinstance(output, dict) and output.get("kind") == "viewport-check":
            observations.append((record, output))
    observed(observations, "visual pass lacks viewport-check measurements; source tokens/classes are not runtime evidence")
    for record, output in observations:
        observed(type(output.get("version")) is int and output["version"] == 1,
                 "viewport-check requires measurement version 1")
        observed(output.get("status") in {"pass", "fail"}, "viewport-check did not reach a measured conclusion")
        if result["status"] == "pass":
            observed(output["status"] == "pass", "viewport-check does not support the reported pass")
        else:
            require(output["status"] == "fail", "visual failure requires a failed viewport-check")
        identities = {"rule_id": case["rule_id"], "node_id": case["node"], "state": case["state"],
                      "viewport": case["viewport"], "source": case.get("url", plan["scope"]["url"]),
                      "build_id": plan["scope"]["build_id"]}
        for key, expected in identities.items():
            require(output.get(key) == expected, f"viewport-check: mismatched {key}")
        inputs = {(Path(record["cwd"]) / item["path"]).resolve(): item["sha256"] for item in record["inputs"]}
        artifacts = {}
        for key in ("screenshot", "measurement_artifact"):
            item = output.get(key)
            observed(isinstance(item, dict) and isinstance(item.get("path"), str)
                     and isinstance(item.get("sha256"), str), f"viewport-check: missing {key} binding")
            artifact = (Path(base).resolve() / item["path"]).resolve()
            require(artifact.is_relative_to(Path(base).resolve()), f"viewport-check {key}: path escapes evidence root")
            observed(artifact.is_file() and artifact.stat().st_size > 0, f"viewport-check: missing {key} artifact")
            require(sha256(artifact) == item["sha256"], f"viewport-check {key}: changed artifact")
            require(inputs.get(artifact) == item["sha256"], f"viewport-check {key}: absent from run_check inputs")
            artifacts[key] = artifact
        screenshot = artifacts["screenshot"]
        observed(screenshot in blackboxes, "viewport-check screenshot must also be the case's blackbox artifact")
        signature = screenshot.read_bytes()[:12]
        image_format = ("PNG" if signature.startswith(b"\x89PNG\r\n\x1a\n") else
                        "JPEG" if signature.startswith(b"\xff\xd8\xff") else
                        "WEBP" if signature.startswith(b"RIFF") and signature[8:12] == b"WEBP" else None)
        observed(image_format, "viewport-check requires the actual screenshot, not a class/DOM text file")
        if "format" in output["screenshot"]:
            require(output["screenshot"]["format"] == image_format, "viewport-check: screenshot format differs from actual bytes")
        raw = read_json(artifacts["measurement_artifact"])
        require(isinstance(raw, dict), "viewport-check raw measurement must be an object")
        require(isinstance(raw.get("screenshot"), str)
                and (Path(base).resolve() / raw["screenshot"]).resolve() == screenshot,
                "raw measurement: screenshot differs from the checked image")
        for key, expected in identities.items():
            if key != "rule_id":
                require(raw.get(key) == expected, f"raw measurement: mismatched {key}")
        raw_captured = timestamp(raw.get("captured_at"), "raw measurement captured_at")
        require(raw_captured >= frozen_at, "raw measurement captured before plan freeze")
        require(raw_captured <= timestamp(record["started_at"], "viewport-check started_at"),
                "raw measurement must be captured before its offline check starts")
        measurements = output.get("measurement")
        observed(isinstance(measurements, dict), "viewport-check: missing measurements")
        measured_rect(measurements.get("host"), "host")
        measured_rect(measurements.get("scene"), "scene")
        if case["rule_id"] == "VIEW-01":
            edges = measurements.get("edges")
            observed(isinstance(edges, list) and len(edges) == 4,
                     "VIEW-01 requires four measured pixel edges as well as the scene box")
            observed({edge.get("side") for edge in edges if isinstance(edge, dict)} == {"top", "right", "bottom", "left"},
                     "VIEW-01 requires top/right/bottom/left pixel samples")
            for edge in edges:
                observed(type(edge.get("samples")) is int and edge["samples"] > 0
                         and finite_number(edge.get("non_background_fraction"))
                         and 0 <= edge["non_background_fraction"] <= 1,
                         "VIEW-01 requires actual pixel sample counts and fractions")
        else:
            measured_rect(measurements.get("available"), "available")
            measured_rect(measurements.get("subject"), "subject")
            observed(isinstance(measurements["subject"].get("method"), str)
                     and measurements["subject"]["method"].strip(), "subject: missing projection measurement method")
        observed(isinstance(output.get("checks"), list), "viewport-check: missing executed assertions")
        assertions = indexed(output["checks"], "viewport-check checks")
        observed(assertions, "viewport-check: no executed assertions")
        from check_viewport import REQUIRED_CHECK_IDS, check_viewport
        observed(set(REQUIRED_CHECK_IDS[case["rule_id"]]) <= set(assertions),
                 "viewport-check: required geometric/pixel assertions were not executed")
        for assertion in assertions.values():
            observed(type(assertion.get("passed")) is bool and "actual" in assertion and "expected" in assertion,
                     "viewport-check: assertions need observed actual, frozen expected and boolean passed")
        recomputed, exit_code = check_viewport(plan_path, case["id"], artifacts["measurement_artifact"], screenshot)
        observed(exit_code != 2, "viewport measurement cannot be reproduced: " + "; ".join(recomputed["diagnostics"]))
        for field in ("checks", "measurement", "status"):
            require(output[field] == recomputed[field],
                    f"viewport-check: {field} differs from recomputed image/geometry and frozen thresholds")
        if result["status"] == "pass":
            observed(all(row["passed"] for row in assertions.values()), "viewport-check contains a failed assertion")
        else:
            require(any(not row["passed"] for row in assertions.values()),
                    "visual failure needs a measured failed assertion")


def executor_identity(value):
    require(isinstance(value, str) and value.strip(), "executor identity must be a nonempty string")
    return value.strip().casefold()


def run_identity(record):
    """Stable command/input identity, excluding per-execution time and output."""
    cwd = Path(record["cwd"]).resolve()

    def normalized(path):
        return os.path.normcase(str((cwd / path).resolve()))

    stdin = record["stdin"]
    return {"command": record["command"], "executable": record["executable"],
            "cwd": os.path.normcase(str(cwd)),
            "inputs": sorted((normalized(item["path"]), item["sha256"]) for item in record["inputs"]),
            "stdin": None if stdin is None else (normalized(stdin["path"]), stdin["sha256"], stdin["text"])}


def validate_evidence(evidence, case, result, report, plan, base, frozen_at):
    text_fields(evidence, ["kind", "path", "observation", "executor", "case_id", "plan_sha256",
                           "build_id", "captured_at", "sha256"], f"{case['id']} evidence")
    kind = evidence["kind"]
    require(kind in {"code", "blackbox", "analysis"}, "unknown evidence kind")
    for field, expected in (("case_id", case["id"]), ("plan_sha256", report["plan_sha256"]),
                            ("build_id", plan["scope"]["build_id"])):
        require(evidence[field] == expected, f"evidence: mismatched {field}")
    if "audit_id" in evidence:
        require(evidence["audit_id"] == report["audit_id"], "evidence: mismatched audit_id")
    digest_field(evidence["sha256"], "evidence sha256")
    artifact = (Path(base).resolve() / evidence["path"]).resolve()
    require(artifact.is_relative_to(Path(base).resolve()), "evidence: path escapes evidence root")
    observed(artifact.is_file() and artifact.stat().st_size > 0, f"missing/empty evidence artifact: {evidence['path']}")
    require(sha256(artifact) == evidence["sha256"], f"evidence SHA-256 changed: {evidence['path']}")
    captured = timestamp(evidence["captured_at"], "evidence captured_at")
    require(captured >= frozen_at, "evidence captured before plan freeze")
    checked = {"kind": kind, "path": artifact, "captured_at": captured,
               "executor": evidence["executor"]}
    if kind == "analysis":
        require(case["engine"] == "model", "analysis evidence is only valid for model cases")
        return checked
    # Preserve the tested run_check v1 record format and its execution-outcome rules.
    from report_gate import evidence_kind
    evidence_kind(evidence, case, {**result, "status": "unverified"} if result["status"] == "pass" else result,
                  report, base, plan["scope"]["url"])
    if kind == "blackbox":
        require("blackbox" in case["required_evidence"], "blackbox channel was not frozen in plan")
        text_fields(evidence, ["state"], "blackbox evidence")
        viewport_fields(evidence.get("viewport"), "blackbox evidence")
        require(evidence["state"] == case["state"], "blackbox state differs from frozen plan")
        require(evidence["viewport"] == case["viewport"], "blackbox viewport differs from frozen plan")
    else:
        record = read_json(artifact)
        if result["status"] == "pass":
            observed(record["outcome"] == "exited" and record["exit_code"] == 0,
                     "code execution did not support pass (timeout, startup error or nonzero exit)")
        started = timestamp(record["started_at"], "code started_at")
        require(started >= frozen_at, "code run started before plan freeze")
        require(captured >= started, "code evidence captured before command started")
        if "build_id" in record:
            require(record["build_id"] == plan["scope"]["build_id"], "code record: mismatched build_id")
        for item in record["inputs"]:
            digest_field(item["sha256"], "command input sha256")
        if record["stdin"] is not None:
            digest_field(record["stdin"]["sha256"], "stdin sha256")
            require(hashlib.sha256(record["stdin"]["text"].encode("utf-8")).hexdigest()
                    == record["stdin"]["sha256"], "stdin text does not match recorded SHA-256")
        checked["started_at"] = started
        checked["run_identity"] = run_identity(record)
        checked["record"] = record
    return checked


def validate_issue(issue, cases, results, report, plan, base, frozen_at, original_evidence, plan_path):
    issue_id = issue["id"]
    text_fields(issue, ["fingerprint", "dimension", "severity", "summary", "actual", "expected", "impact"],
                f"issue {issue_id}")
    case_ids = string_list(issue.get("case_ids"), f"issue {issue_id} case_ids")
    require(len(case_ids) == len(set(case_ids)), f"issue {issue_id}: duplicate case id")
    expected_ids = {case_id for case_id, result in results.items()
                    if result.get("status") == "fail" and result.get("issue_id") == issue_id}
    require(set(case_ids) == expected_ids and set(case_ids) <= set(cases),
            f"issue {issue_id}: case_ids must exactly match its failed results")
    require(all(cases[case_id]["dimension"] == issue["dimension"] for case_id in case_ids),
            f"issue {issue_id}: dimension differs from linked cases")
    require(issue["severity"] in SEVERITY_DEDUCTIONS, f"issue {issue_id}: invalid severity")
    for field, value in (("kind", "product"), ("certainty", "confirmed")):
        if field in issue:
            require(issue[field] == value, f"issue {issue_id}: {field} must be {value}")
    for field in ("topic", "location", "environment", "evidence_summary", "boundary", "record_id", "suggestion"):
        if field in issue:
            text_fields(issue, [field], f"issue {issue_id}")
    if "steps" in issue:
        string_list(issue["steps"], f"issue {issue_id} steps")
    if "code_location" in issue:
        location = issue["code_location"]
        text_fields(location, ["path", "component", "state"], f"issue {issue_id} code_location")
        require(type(location.get("line")) is int and location["line"] > 0,
                f"issue {issue_id}: code_location line must be a positive integer")
    review = issue.get("review")
    text_fields(review, ["method", "reviewer", "reason"], f"issue {issue_id} review")
    require(review.get("confirmed") is True, f"issue {issue_id}: review must confirm the finding")
    require(review["method"] in {"rerun", "independent"}, f"issue {issue_id}: invalid review method")
    if any(cases[case_id]["engine"] == "model" for case_id in case_ids):
        require(review["method"] == "independent", f"issue {issue_id}: model judgment needs independent review")
    original_executors = {executor_identity(results[case_id].get("executor", report["executor"]))
                          for case_id in case_ids}
    originals = [entry for case_id in case_ids for entry in original_evidence.get(case_id, [])]
    original_executors.update(executor_identity(entry["executor"]) for entry in originals)
    if review["method"] == "independent":
        require(executor_identity(review["reviewer"]) not in original_executors,
                f"issue {issue_id}: reviewer is not independent of original result/evidence executors")
    require(isinstance(review.get("evidence"), list) and review["evidence"],
            f"issue {issue_id}: review evidence must be a nonempty array")
    original_paths = {entry["path"] for entry in originals}
    channels = {case_id: set() for case_id in case_ids}
    review_checked = {case_id: [] for case_id in case_ids}
    for evidence in review["evidence"]:
        text_fields(evidence, ["case_id", "executor"], f"issue {issue_id} review evidence")
        case_id = evidence["case_id"]
        require(case_id in channels, f"issue {issue_id}: review evidence for an unrelated case")
        require(evidence["executor"] == review["reviewer"],
                f"issue {issue_id}: review evidence executor must be the reviewer")
        checked = validate_evidence(evidence, cases[case_id], results[case_id], report, plan, base, frozen_at)
        require(checked["path"] not in original_paths,
                f"issue {issue_id}: review cannot reuse an original artifact path")
        prior = original_evidence.get(case_id, [])
        require(prior, f"issue {issue_id}: missing valid original evidence")
        require(checked["captured_at"] > max(entry["captured_at"] for entry in prior),
                f"issue {issue_id}: review capture must be newer than original evidence")
        if review["method"] == "rerun" and checked["kind"] == "code":
            original_runs = [entry for entry in prior if entry["kind"] == "code"]
            require(any(checked["run_identity"] == entry["run_identity"] for entry in original_runs),
                    f"issue {issue_id}: rerun command/cwd/inputs/stdin differ; use independent review for a different check")
            require(checked["started_at"] > max(entry["started_at"] for entry in original_runs),
                    f"issue {issue_id}: rerun must be a new command execution")
        channels[case_id].add(checked["kind"])
        review_checked[case_id].append(checked)
    for case_id in case_ids:
        require(set(cases[case_id]["required_evidence"]) <= channels[case_id],
                f"issue {issue_id}: review lacks required evidence channels for {case_id}")
        validate_visual_evidence(review_checked[case_id], cases[case_id], results[case_id], plan, base, frozen_at, plan_path)


def coverage_summary(plan, cases, results, counts):
    by_dimension = {}
    for name in plan["scope"]["dimensions"]:
        ids = [case_id for case_id, case in cases.items() if case["dimension"] == name]
        row = {status: sum(results.get(case_id, {}).get("status") == status for case_id in ids)
               for status in STATUSES}
        by_dimension[name] = {"expected": len(ids), **row}
    return {"scope": plan["scope"]["coverage"], "dimensions": plan["scope"]["dimensions"],
            "expected": len(cases), "reported": len(results),
            "evaluated": counts["pass"] + counts["fail"], "unverified": counts["unverified"],
            "not_applicable": counts["not_applicable"],
            "ratio": round((counts["pass"] + counts["fail"] + counts["not_applicable"]) / len(cases), 4),
            "by_dimension": by_dimension}


def validate_v2(plan_path, report_path, lock_path):
    errors, counts, coverage = [], dict.fromkeys(STATUSES, 0), {}
    score, hard_findings = unavailable_score(), []
    derived_results, diagnostics = {}, []
    try:
        plan, report, lock = read_json(plan_path), read_json(report_path), read_json(lock_path)
        require(isinstance(plan, dict) and type(plan.get("version")) is int and plan["version"] == 2,
                "v2 plan: version must be 2")
        score["scope"] = plan["scope"].get("coverage") if isinstance(plan.get("scope"), dict) else None
        cases = plan_cases(plan)
        validate_sources(plan, Path(plan_path).resolve().parent)
        text_fields(report, ["audit_id", "executor", "plan_sha256"], "report")
        require(type(report.get("version")) is int and report["version"] == 2
                and isinstance(lock, dict) and type(lock.get("version")) is int and lock["version"] == 2,
                "v2 report/lock: version must be 2")
        require(report["audit_id"] == plan["audit_id"] == lock.get("audit_id"), "audit_id mismatch")
        require(report["plan_sha256"] == lock.get("plan_sha256") == sha256(plan_path), "frozen plan changed")
        frozen_at = timestamp(lock.get("frozen_at"), "lock frozen_at")
        require(not ({"score", "grade", "dimension_scores", "accepted"} & set(report)),
                "v2 report must not supply score/grade/dimension_scores/accepted; gate derives scoring")
        results, issues = indexed(report.get("results"), "results"), indexed(report.get("issues"), "issues")
        missing, extra = set(cases) - set(results), set(results) - set(cases)
        if missing or extra:
            errors.append(f"coverage mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
        base, original_evidence = Path(report_path).resolve().parent, {}
        for case_id, case in cases.items():
            if case_id not in results:
                continue
            result = results[case_id]
            derived = {"id": case_id, "reported_status": result.get("status"),
                       "status": result.get("status"), "reason": result.get("reason"), "diagnostics": []}
            derived_results[case_id] = derived
            try:
                text_fields(result, ["status", "reason"], case_id)
                status = result["status"]
                require(status in STATUSES, f"invalid status {status}")
                if "executor" in result:
                    text_fields(result, ["executor"], case_id)
                if status == "fail":
                    text_fields(result, ["issue_id"], case_id)
                    require(result["issue_id"] in issues, "failed result references a missing issue")
                else:
                    require("issue_id" not in result, "only failed results may reference an issue")
                require(isinstance(result.get("evidence"), list), "evidence must be an array")
                requirement = visual_requirement(plan, case) if case["rule_id"] in VISUAL_RULES else None
                if requirement and not requirement["applicable"]:
                    require(status in {"not_applicable", "unverified"}, "frozen visual N/A cannot be reported as pass/fail")
                checked = []
                for item in result["evidence"]:
                    try:
                        checked.append(validate_evidence(item, case, result, report, plan, base, frozen_at))
                    except EvidenceUnavailable as exc:
                        if status != "pass":
                            raise
                        derived["diagnostics"].append(str(exc))
                original_evidence[case_id] = checked
                kinds = {entry["kind"] for entry in checked}
                if status == "pass":
                    missing_kinds = set(case["required_evidence"]) - kinds
                    if missing_kinds:
                        derived["diagnostics"].append(f"missing planned evidence channels: {sorted(missing_kinds)}")
                    if not derived["diagnostics"]:
                        try:
                            validate_visual_evidence(checked, case, result, plan, base, frozen_at, plan_path)
                        except EvidenceUnavailable as exc:
                            derived["diagnostics"].append(str(exc))
                    if derived["diagnostics"]:
                        derived["status"] = "unverified"
                        derived["reason"] = "原始通过声明缺少运行证据；" + "; ".join(derived["diagnostics"])
                        diagnostics.append({"case_id": case_id, "reported_status": status,
                                            "derived_status": "unverified", "reasons": derived["diagnostics"]})
                elif status == "fail":
                    require(set(case["required_evidence"]) <= kinds,
                            f"{status} lacks planned evidence; use unverified")
                    validate_visual_evidence(checked, case, result, plan, base, frozen_at, plan_path)
                elif status == "not_applicable":
                    require(case["allow_not_applicable"], "not_applicable was not allowed by frozen plan")
            except INVALID_INPUT as exc:
                errors.append(f"{case_id}: {exc}")
            if derived["status"] in counts:
                counts[derived["status"]] += 1
        fingerprints = set()
        for issue_id, issue in issues.items():
            try:
                validate_issue(issue, cases, results, report, plan, base, frozen_at, original_evidence, plan_path)
                fingerprint = issue["fingerprint"].strip().casefold()
                require(fingerprint not in fingerprints, f"issue {issue_id}: duplicate fingerprint")
                fingerprints.add(fingerprint)
            except INVALID_INPUT as exc:
                errors.append(f"issue {issue_id}: {exc}")
        coverage = coverage_summary(plan, cases, derived_results, counts)
        if not errors:
            score = derive_score(plan, derived_results, issues)
            deductions = {item["issue_id"]: item for item in score["deductions"]}
            hard_findings = [{"issue_id": issue_id, "dimension": issues[issue_id]["dimension"],
                              "summary": issues[issue_id]["summary"], "case_ids": issues[issue_id]["case_ids"],
                              "raw_deduction": item["raw"], "applied_deduction": item["applied"]}
                             for issue_id, item in deductions.items() if item["severity"] == "severe"]
    except INVALID_INPUT as exc:
        errors.append(str(exc))
    complete = not errors and not counts["unverified"]
    return {"version": 2, "valid": not errors, "complete": complete,
            "full_certification": complete and score["scope"] == "full" and not counts["fail"] and counts["pass"] > 0,
            "errors": errors, "counts": counts, "coverage": coverage, "score": score,
            "hard_findings": hard_findings, "derived_results": list(derived_results.values()), "diagnostics": diagnostics}

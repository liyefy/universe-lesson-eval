"""Evidence-bound v2 validation. Content truth and executor identity still require review."""
import hashlib
import os
from pathlib import Path

from eval_contract import indexed, plan_cases, read_json, require, sha256, string_list, text_fields, viewport_fields
from scoring import SEVERITY_DEDUCTIONS, derive_score, unavailable_score
from v2_contract import contained_file, digest_field, timestamp, validate_sources

STATUSES = ("pass", "fail", "unverified", "not_applicable")
INVALID_INPUT = (ValueError, TypeError, KeyError, OSError, OverflowError)


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
    artifact = contained_file(base, evidence["path"], "evidence")
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
    evidence_kind(evidence, case, result, report, base, plan["scope"]["url"])
    if kind == "blackbox":
        require("blackbox" in case["required_evidence"], "blackbox channel was not frozen in plan")
        text_fields(evidence, ["state"], "blackbox evidence")
        viewport_fields(evidence.get("viewport"), "blackbox evidence")
        require(evidence["state"] == case["state"], "blackbox state differs from frozen plan")
        require(evidence["viewport"] == case["viewport"], "blackbox viewport differs from frozen plan")
    else:
        record = read_json(artifact)
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
    return checked


def validate_issue(issue, cases, results, report, plan, base, frozen_at, original_evidence):
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
    for case_id in case_ids:
        require(set(cases[case_id]["required_evidence"]) <= channels[case_id],
                f"issue {issue_id}: review lacks required evidence channels for {case_id}")


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
    try:
        plan, report, lock = read_json(plan_path), read_json(report_path), read_json(lock_path)
        require(isinstance(plan, dict) and type(plan.get("version")) is int and plan["version"] == 2,
                "v2 plan: version must be 2")
        cases = plan_cases(plan)
        score["scope"] = plan["scope"]["coverage"]
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
            try:
                text_fields(result, ["status", "reason"], case_id)
                status = result["status"]
                require(status in STATUSES, f"invalid status {status}")
                counts[status] += 1
                if "executor" in result:
                    text_fields(result, ["executor"], case_id)
                if status == "fail":
                    text_fields(result, ["issue_id"], case_id)
                    require(result["issue_id"] in issues, "failed result references a missing issue")
                else:
                    require("issue_id" not in result, "only failed results may reference an issue")
                require(isinstance(result.get("evidence"), list), "evidence must be an array")
                checked = [validate_evidence(item, case, result, report, plan, base, frozen_at)
                           for item in result["evidence"]]
                original_evidence[case_id] = checked
                kinds = {entry["kind"] for entry in checked}
                if status in {"pass", "fail"}:
                    require(set(case["required_evidence"]) <= kinds,
                            f"{status} lacks planned evidence; use unverified")
                elif status == "not_applicable":
                    require(case["allow_not_applicable"], "not_applicable was not allowed by frozen plan")
            except INVALID_INPUT as exc:
                errors.append(f"{case_id}: {exc}")
        fingerprints = set()
        for issue_id, issue in issues.items():
            try:
                validate_issue(issue, cases, results, report, plan, base, frozen_at, original_evidence)
                fingerprint = issue["fingerprint"].strip().casefold()
                require(fingerprint not in fingerprints, f"issue {issue_id}: duplicate fingerprint")
                fingerprints.add(fingerprint)
            except INVALID_INPUT as exc:
                errors.append(f"issue {issue_id}: {exc}")
        coverage = coverage_summary(plan, cases, results, counts)
        if not errors:
            score = derive_score(plan, results, issues)
            deductions = {item["issue_id"]: item for item in score["deductions"]}
            hard_findings = [{"issue_id": issue_id, "dimension": issues[issue_id]["dimension"],
                              "summary": issues[issue_id]["summary"], "case_ids": issues[issue_id]["case_ids"],
                              "raw_deduction": item["raw"], "applied_deduction": item["applied"]}
                             for issue_id, item in deductions.items() if item["severity"] == "severe"]
    except INVALID_INPUT as exc:
        errors.append(str(exc))
    return {"version": 2, "valid": not errors, "complete": not errors and not counts["unverified"],
            "errors": errors, "counts": counts, "coverage": coverage, "score": score,
            "hard_findings": hard_findings}

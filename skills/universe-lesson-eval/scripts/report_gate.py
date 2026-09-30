"""Validate frozen audit evidence: v2 derives scores; v1 retains legacy acceptance."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from eval_contract import indexed, plan_cases, read_json, require, sha256, string_list, text_fields, write_new

STATUSES = ("pass", "fail", "unverified", "not_applicable")


def freeze(plan_path, lock_path):
    plan = read_json(plan_path)
    plan_cases(plan)
    if plan["version"] == 2:
        from v2_contract import validate_sources
        validate_sources(plan, Path(plan_path).resolve().parent)
    lock = {"version": plan["version"], "audit_id": plan["audit_id"], "plan_sha256": sha256(plan_path),
            "frozen_at": datetime.now(timezone.utc).isoformat()}
    write_new(lock_path, lock)
    return lock


def evidence_kind(evidence, case, result, report, base, scope_url):
    text_fields(evidence, ["kind", "path", "observation", "executor"], case["id"])
    executor = evidence["executor"]
    artifact = base / evidence["path"]
    require(artifact.is_file() and artifact.stat().st_size > 0, f"missing/empty evidence: {artifact}")
    kind, status = evidence["kind"], result["status"]
    require(kind in {"code", "blackbox"}, "unknown evidence kind")
    if kind == "code":
        record = read_json(artifact)
        require(isinstance(record, dict) and type(record.get("version")) is int
                and record["version"] == 1 and record.get("kind") == "code",
                "code evidence must be a run_check record")
        for key, expected in (("audit_id", report["audit_id"]), ("plan_sha256", report["plan_sha256"]),
                              ("case_id", case["id"]), ("executor", executor)):
            require(record.get(key) == expected, f"code record: mismatched {key}")
        string_list(record.get("command"), "code command")
        text_fields(record, ["cwd", "started_at", "executable", "encoding"], "code record")
        require(datetime.fromisoformat(record["started_at"]).utcoffset() is not None, "start time needs timezone")
        for field in ("elapsed_seconds", "timeout_seconds"):
            number = record.get(field)
            require(type(number) in (int, float) and math.isfinite(number) and number >= 0,
                    f"invalid command {field}")
        require(all(isinstance(record.get(key), str) for key in ("stdout", "stderr")), "missing command output")
        require(isinstance(record.get("inputs"), list) and "stdin" in record, "missing command inputs")
        for item in record["inputs"]:
            text_fields(item, ["path", "sha256"], "command input")
        require(record["stdin"] is None or isinstance(record["stdin"], dict), "invalid stdin")
        if record["stdin"] is not None:
            text_fields(record["stdin"], ["path", "sha256"], "stdin")
            require(isinstance(record["stdin"].get("text"), str), "missing stdin text")
        require(record.get("outcome") in {"exited", "timeout", "error"}, "invalid command outcome")
        exited = record["outcome"] == "exited"
        require((type(record.get("exit_code")) is int) if exited else record.get("exit_code") is None,
                "invalid command exit code")
        if status in {"pass", "fail"}:
            require(exited, "execution failure/timeout requires unverified, not pass/fail")
        if status == "pass":
            require(record["exit_code"] == 0, "nonzero command cannot support pass")
    else:
        text_fields(evidence, ["source", "method"], "blackbox evidence")
        require(evidence["source"] == case.get("url", scope_url), "blackbox source differs from frozen URL")
        string_list(evidence.get("steps"), "blackbox steps")
        require(evidence["method"] in {"visual", "interaction", "listening"}, "invalid blackbox method")
        if "blackbox" in case["required_evidence"]:
            require(evidence["method"] == case["blackbox_method"], "blackbox method differs from frozen plan")
        if evidence["method"] == "listening":
            require(artifact.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".bmp"},
                    "a screenshot alone cannot establish audible playback")
    return kind


def _validate_v1(plan_path, report_path, lock_path):
    errors, blockers, critical = [], [], []
    counts = dict.fromkeys(STATUSES, 0)
    try:
        plan, report, lock = read_json(plan_path), read_json(report_path), read_json(lock_path)
        cases = plan_cases(plan)
        text_fields(report, ["audit_id", "executor", "plan_sha256"], "report")
        require(type(report.get("version")) is int and report["version"] == 1 and isinstance(lock, dict)
                and type(lock.get("version")) is int and lock["version"] == 1,
                "report/lock: version must be 1")
        require(report["audit_id"] == plan["audit_id"] == lock.get("audit_id"), "audit_id mismatch")
        require(report["plan_sha256"] == lock.get("plan_sha256") == sha256(plan_path), "frozen plan changed")
        results = indexed(report.get("results"), "results")
        require(set(results) == set(cases),
                f"coverage mismatch: missing={sorted(set(cases)-set(results))}, extra={sorted(set(results)-set(cases))}")
        for case_id, case in cases.items():
            result = results[case_id]
            try:
                text_fields(result, ["status", "reason"], case_id)
                status = result["status"]
                require(status in STATUSES, f"invalid status {status}")
                counts[status] += 1
                if status in {"fail", "unverified"}:
                    blockers.append(case_id)
                    if case["critical"]:
                        critical.append(case_id)
                if "executor" in result:
                    text_fields(result, ["executor"], case_id)
                require(isinstance(result.get("evidence"), list), "evidence must be an array")
                kinds = {evidence_kind(item, case, result, report, Path(report_path).resolve().parent, plan["scope"]["url"])
                         for item in result["evidence"]}
                if status in {"pass", "fail"}:
                    require(set(case["required_evidence"]) <= kinds, f"{status} lacks planned evidence; use unverified")
                elif status == "not_applicable":
                    require(case["allow_not_applicable"], "not_applicable was not allowed by frozen plan")
            except (ValueError, TypeError, KeyError, OSError) as exc:
                errors.append(f"{case_id}: {exc}")
                if case_id not in blockers:
                    blockers.append(case_id)
                if case["critical"] and case_id not in critical:
                    critical.append(case_id)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        errors.append(str(exc))
    return {"legacy": True, "valid": not errors, "accepted": not errors and not blockers, "errors": errors,
            "full_certification": False, "compatibility": "v1 legacy acceptance is not v2 visual coverage certification",
            "blocking_cases": blockers, "critical_blockers": critical, "counts": counts}


def validate(plan_path, report_path, lock_path):
    # Select the schema even if one JSON document is broken. The selected validator
    # re-reads inputs and reports every parsing failure instead of concealing it.
    documents = []
    for path in (plan_path, report_path, lock_path):
        try:
            documents.append(read_json(path))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            documents.append({"input_error": str(exc)})
    if any(isinstance(item, dict) and type(item.get("version")) is int and item["version"] == 2
           for item in documents):
        from v2_gate import validate_v2
        return validate_v2(plan_path, report_path, lock_path)
    return _validate_v1(plan_path, report_path, lock_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    freezing = actions.add_parser("freeze")
    freezing.add_argument("plan")
    freezing.add_argument("lock")
    checking = actions.add_parser("check")
    for name in ("plan", "report", "lock"):
        checking.add_argument(name)
    args = parser.parse_args()
    try:
        result = freeze(args.plan, args.lock) if args.action == "freeze" else validate(args.plan, args.report, args.lock)
        finished = result.get("complete", result.get("accepted", False))
        code = 0 if args.action == "freeze" or finished else (1 if result["valid"] else 2)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result, code = {"valid": False, "errors": [str(exc)]}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

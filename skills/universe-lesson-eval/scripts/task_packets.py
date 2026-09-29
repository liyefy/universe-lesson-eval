"""Split a frozen audit into focused packets and merge explicit result shards."""
import argparse
from collections import defaultdict
from pathlib import Path
from eval_contract import indexed, plan_cases, read_json, require, sha256, write_new
from report_gate import validate


def frozen(plan_path, lock_path):
    plan, lock = read_json(plan_path), read_json(lock_path)
    require(isinstance(plan, dict) and plan.get("version") == 2, "task packets require v2")
    require(isinstance(lock, dict) and type(lock.get("version")) is int and lock["version"] == 2,
            "task packets require a v2 lock")
    cases = plan_cases(plan)
    require(lock.get("audit_id") == plan["audit_id"] and lock.get("plan_sha256") == sha256(plan_path),
            "frozen plan mismatch")
    for source in plan["sources"]:
        path = (Path(plan_path).resolve().parent / source["path"]).resolve()
        require(path.is_relative_to(Path(plan_path).resolve().parent), "source escapes plan directory")
        require(sha256(path) == source["sha256"], "frozen source changed")
    return plan, cases


def split(plan_path, lock_path, out_dir, batch_size=6):
    require(type(batch_size) is int and batch_size > 0, "batch_size must be positive")
    plan, cases = frozen(plan_path, lock_path)
    groups = defaultdict(list)
    for case in cases.values():
        groups[(case["engine"], case["rule_id"], case.get("blackbox_method", ""))].append(case)
    packets = []
    for key in sorted(groups):
        rows = groups[key]
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            source_ids = {source for case in batch for source in case["source_ids"]}
            sources = [{**source, "path": str((Path(plan_path).resolve().parent / source["path"]).resolve())}
                       for source in plan["sources"] if source["id"] in source_ids]
            packets.append({"version": 2, "audit_id": plan["audit_id"], "plan_sha256": sha256(plan_path),
                "packet_id": f"packet-{len(packets) + 1:03d}", "engine": key[0], "rule_id": key[1],
                "scope": plan["scope"], "sources": sources,
                "rules": [rule for rule in plan["rules"] if rule["id"] == key[1]],
                "case_ids": [case["id"] for case in batch], "cases": batch,
                "context_policy": "fresh context; relevant basis only; no previous verdicts",
                "browser_access": "serial unless genuinely isolated contexts",
                "output_contract": {"version": 2, "audit_id": plan["audit_id"],
                    "plan_sha256": sha256(plan_path), "executor": "actual executor", "results": [], "issues": []}})
    root = Path(out_dir)
    require(not root.exists(), "packet output directory already exists")
    root.mkdir(parents=True)
    for packet in packets:
        write_new(root / (packet["packet_id"] + ".json"), packet)
    manifest = {"audit_id": plan["audit_id"], "plan_sha256": sha256(plan_path),
                "packets": [{key: packet[key] for key in ("packet_id", "engine", "rule_id", "case_ids")}
                            for packet in packets],
                "dispatch": "scripts run static/browser packets; spawn focused agents only for model packets"}
    write_new(root / "manifest.json", manifest)
    return manifest


def merge(plan_path, lock_path, parts, output, executor, allow_incomplete=False):
    plan, cases = frozen(plan_path, lock_path)
    require(isinstance(executor, str) and executor.strip(), "executor required")
    require(parts, "at least one result shard required")
    rows, issues = {}, {}
    output_root = Path(output).resolve().parent
    output_root.mkdir(parents=True, exist_ok=True)
    for part in parts:
        document = read_json(part)
        require(isinstance(document, dict) and document.get("version") == 2 and document.get("audit_id") == plan["audit_id"]
                and document.get("plan_sha256") == sha256(plan_path), "shard differs from frozen plan")
        shard_rows = indexed(document.get("results"), "shard results")
        shard_issues = indexed(document.get("issues"), "shard issues")
        require(not set(rows).intersection(shard_rows), "duplicate result across shards")
        require(set(shard_rows) <= set(cases), "unknown result in shard")
        require(not set(issues).intersection(shard_issues), "duplicate issue; consolidate explicitly before merge")
        # Artifact paths in every shard are relative to the final report directory,
        # never implicitly rebased to a worker's folder.
        for row in shard_rows.values():
            row.setdefault("executor", document.get("executor"))
        rows.update(shard_rows)
        issues.update(shard_issues)
    missing = sorted(set(cases) - set(rows))
    require(not missing or allow_incomplete, f"missing cases: {missing}; use --allow-incomplete for explicit unverified")
    for key in missing:
        rows[key] = {"id": key, "status": "unverified", "reason": "未收到该检查项的执行结果", "evidence": []}
    report = {"version": 2, "audit_id": plan["audit_id"], "executor": executor,
              "plan_sha256": sha256(plan_path), "results": [rows[key] for key in cases],
              "issues": list(issues.values())}
    write_new(output, report)
    # Invalid merges remain visible for repair; the tool never silently drops an issue.
    return validate(plan_path, output, lock_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    splitting = commands.add_parser("split")
    merging = commands.add_parser("merge")
    for command in (splitting, merging):
        command.add_argument("--plan", required=True)
        command.add_argument("--lock", required=True)
    splitting.add_argument("--out-dir", required=True)
    splitting.add_argument("--batch-size", type=int, default=6)
    merging.add_argument("--part", action="append", required=True)
    merging.add_argument("--out", required=True)
    merging.add_argument("--executor", required=True)
    merging.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "split":
            result = split(args.plan, args.lock, args.out_dir, args.batch_size)
            print(f"Generated {len(result['packets'])} focused packets; no agents spawned.")
            return 0
        result = merge(args.plan, args.lock, args.part, args.out, args.executor, args.allow_incomplete)
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if not result["valid"] else (0 if result["complete"] else 1)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"STOP: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

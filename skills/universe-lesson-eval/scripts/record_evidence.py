"""Bind an existing observed artifact to a v2 case; never manufacture observations."""
import argparse
from datetime import datetime
from pathlib import Path
from eval_contract import plan_cases, read_json, require, sha256, text_fields, write_new


def package(plan_path, case_id, artifact, metadata, report_dir):
    plan = read_json(plan_path)
    require(isinstance(plan, dict) and plan.get("version") == 2, "evidence packaging requires a v2 plan")
    cases = plan_cases(plan)
    require(case_id in cases, "unknown case_id")
    text_fields(metadata, ["kind", "executor", "observation", "build_id", "captured_at"], "observation")
    require(metadata["kind"] in {"code", "blackbox", "analysis"}, "unknown evidence kind")
    require(metadata["build_id"] == plan["scope"]["build_id"], "observed build differs from plan")
    require(datetime.fromisoformat(metadata["captured_at"]).utcoffset() is not None,
            "captured_at needs timezone")
    require(not {"path", "sha256", "case_id", "plan_sha256"}.intersection(metadata),
            "artifact bindings are generated, not supplied in metadata")
    root, path = Path(report_dir).resolve(), Path(artifact).resolve()
    require(path.is_relative_to(root) and path.is_file() and path.stat().st_size > 0,
            "artifact must be a nonempty file inside report directory")
    if metadata["kind"] == "blackbox":
        case = cases[case_id]
        for key in ("state", "viewport"):
            require(metadata.get(key) == case.get(key), f"observed {key} differs from plan")
        require(metadata.get("source") == case.get("url", plan["scope"]["url"]),
                "observed URL differs from plan")
        require(metadata.get("method") == case.get("blackbox_method"), "method differs from plan")
    return {**metadata, "path": path.relative_to(root).as_posix(), "sha256": sha256(path),
            "case_id": case_id, "plan_sha256": sha256(plan_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "case-id", "artifact", "metadata", "report-dir", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        value = package(args.plan, args.case_id, args.artifact, read_json(args.metadata), args.report_dir)
        write_new(args.out, value)
        print(f"Evidence packaged: {args.out}; authenticity requires the actual tool/observer record.")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"STOP: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

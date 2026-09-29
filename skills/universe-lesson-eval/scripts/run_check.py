"""Execute one explicit argv list and save its real inputs/output without a shell."""
import argparse
import codecs
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from eval_contract import plan_cases, read_json, require, sha256


def run(args):
    plan = read_json(args.plan)
    require(args.case_id in plan_cases(plan), "case_id is not in plan")
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    require(command, "provide executable and arguments after --")
    executable = shutil.which(command[0]) or command[0]
    require(Path(executable).suffix.lower() not in {".bat", ".cmd", ".ps1"},
            "use a direct executable, e.g. node.exe plus pnpm.cjs, not a shell wrapper")
    require(Path(executable).stem.lower() not in {"cmd", "powershell", "pwsh", "sh", "bash", "zsh"},
            "shell templates are not accepted; pass executable and argv directly")
    require(math.isfinite(args.timeout) and args.timeout > 0, "timeout must be finite and positive")
    codecs.lookup(args.encoding)
    require(args.executor.strip(), "executor is required")
    cwd = Path(args.cwd).resolve()
    require(cwd.is_dir(), "cwd must be an existing directory")
    stdin = None
    if args.stdin:
        path = Path(args.stdin).resolve()
        stdin = {"path": str(path), "sha256": sha256(path), "text": path.read_bytes().decode("utf-8")}
    record = {"version": 1, "kind": "code", "audit_id": plan["audit_id"],
              "plan_sha256": sha256(args.plan), "case_id": args.case_id, "executor": args.executor,
              "command": command, "executable": str(executable), "cwd": str(cwd),
              "inputs": [{"path": str(Path(path).resolve()), "sha256": sha256(path)} for path in args.input],
              "stdin": stdin, "started_at": datetime.now(timezone.utc).isoformat(),
              "timeout_seconds": args.timeout, "encoding": args.encoding,
              "outcome": "error", "exit_code": None, "stdout": "", "stderr": "", "error": None}
    # Reserve exclusively before execution: an existing run is never overwritten.
    with Path(args.out).open("x", encoding="utf-8", newline="\n") as stream:
        start = time.monotonic()
        try:
            process = subprocess.run([executable, *command[1:]], cwd=cwd, shell=False,
                                     input=stdin["text"].encode("utf-8") if stdin else None,
                                     stdin=subprocess.DEVNULL if stdin is None else None,
                                     capture_output=True, timeout=args.timeout, check=False)
            record.update(outcome="exited", exit_code=process.returncode,
                          stdout=process.stdout.decode(args.encoding, errors="backslashreplace"),
                          stderr=process.stderr.decode(args.encoding, errors="backslashreplace"))
        except subprocess.TimeoutExpired as exc:
            record.update(outcome="timeout", error=f"timeout after {args.timeout} seconds",
                          stdout=(exc.stdout or b"").decode(args.encoding, errors="backslashreplace"),
                          stderr=(exc.stderr or b"").decode(args.encoding, errors="backslashreplace"))
        except OSError as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["elapsed_seconds"] = round(time.monotonic() - start, 6)
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "case-id", "executor", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--stdin")
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        record = run(args)
        print(json.dumps({"record": str(Path(args.out).resolve()), "outcome": record["outcome"],
                          "exit_code": record["exit_code"]}, ensure_ascii=False))
        return 0 if record["outcome"] == "exited" and record["exit_code"] == 0 else 1
    except (ValueError, TypeError, KeyError, LookupError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

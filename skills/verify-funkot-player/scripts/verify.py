#!/usr/bin/env python3
"""Run the existing Funkot browser recipe in disposable committed frontend data."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone


TITLE = "playlist removal keeps Undo and a poll retains the selected occurrence"
INPUTS = ["src", "tests/ui", "index.html", "package.json", "package-lock.json",
          "playwright.config.mjs", "svelte.config.js", "tsconfig.json", "vite.config.ts"]
NOT_RUN = ["native IPC", "disk persistence and restart", "audio", "OS dialogs",
           "Windows WebView2", "Android", "other browser features"]


def port_free():
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 1422))
            return True
        except OSError:
            return False


def judge(report, evidence):
    tests = []

    def visit(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                if spec.get("title") != TITLE or not spec.get("ok"):
                    raise ValueError("Wrong or failed test identity")
                tests.extend(spec.get("tests", []))
            visit(suite.get("suites", []))

    visit(report.get("suites", []))
    if report.get("errors") or sorted(t.get("projectName", "") for t in tests) != ["desktop", "narrow"]:
        raise ValueError("Expected one desktop and one narrow test, without report errors")
    artifacts = []
    for test in tests:
        results = test.get("results", [])
        if test.get("status") != "expected" or len(results) != 1 or results[0].get("status") != "passed":
            raise ValueError("Skipped, retried, or unsuccessful test")
        captures = [a for a in results[0].get("attachments", []) if a.get("name") == "playlist-undo"]
        if len(captures) != 1:
            raise ValueError("Missing unique playlist-undo screenshot")
        path = Path(captures[0]["path"]).resolve()
        if not path.is_relative_to(evidence.resolve()) or not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Screenshot is missing or outside retained evidence")
        artifacts.append(str(path))
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Selected funkot-player checkout; committed frontend inputs only")
    parser.add_argument("--evidence-root", type=Path, required=True, help="Persistent private directory outside source and scratch")
    parser.add_argument("--agent", required=True, help="Actual driving agent identity")
    parser.add_argument("--doctor-only", action="store_true", help="Read inputs and prerequisites; do not launch")
    args = parser.parse_args()
    repo = args.repo.resolve()
    evidence_root = args.evidence_root.resolve()
    if evidence_root.is_relative_to(repo):
        parser.error("Evidence must be outside the selected checkout")
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="funkot-browser-", dir=evidence_root))
    record = {
        "started_at": datetime.now(timezone.utc).isoformat(), "agent": args.agent,
        "repo": str(repo), "evidence": str(evidence), "feature": TITLE,
        "expectations": {"projects": ["desktop", "narrow"], "remove": {"kind": "remove", "id": "night", "entry_id": "a"},
                         "undo": {"kind": "undo_remove", "undo_id": "undo-1"}, "undo_button_after": "absent"},
        "feature_result": "not-run", "not_run": NOT_RUN, "commands": [], "artifacts": [],
        "cleanup": {"ok": False}, "owned": {},
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    result_file = evidence / "result.json"
    scratch = None
    env = os.environ.copy()
    env.pop("TAURI_DEV_HOST", None)
    env.pop("TAURI_ENV_PLATFORM", None)

    def save():
        result_file.write_text(json.dumps(record, indent=2) + "\n")

    def run(argv, cwd):
        index = len(record["commands"])
        log = evidence / f"command-{index}.log"
        entry = {"argv": argv, "cwd": str(cwd), "log": str(log)}
        record["commands"].append(entry)
        save()
        with log.open("wb") as stream:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            entry["process_group"] = process.pid
            save()
            try:
                entry["exit_code"] = process.wait()
            finally:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                process.wait()
        save()
        if entry["exit_code"]:
            raise RuntimeError(f"Command failed; inspect {log.name}")
        return log.read_text()

    try:
        save()
        if not os.sys.platform.startswith("linux") or not all(shutil.which(x) for x in ("git", "node", "npm")):
            raise RuntimeError("Requires Linux process groups, Git, Node.js and npm")
        record["revision"] = run(["git", "rev-parse", "HEAD"], repo).strip()
        record["dirty"] = run(["git", "status", "--porcelain"], repo).splitlines()
        if run(["git", "status", "--porcelain", "--", *INPUTS], repo).strip():
            raise RuntimeError("Commit selected frontend changes before verification")
        record["runtime"] = {"node": run(["node", "--version"], repo).strip(), "npm": run(["npm", "--version"], repo).strip(), "python": os.sys.version}
        for name in INPUTS:
            if not (repo / name).exists():
                raise RuntimeError(f"Missing frontend prerequisite: {name}")
        if not port_free():
            raise RuntimeError("Loopback port 1422 is in use; leave its owner untouched")
        record["archive_argv"] = ["git", "archive", record["revision"], *INPUTS]
        archive = subprocess.check_output(record["archive_argv"], cwd=repo)
        record["input_archive_sha256"] = hashlib.sha256(archive).hexdigest()
        if args.doctor_only:
            record["result"] = "not-run"
        else:
            scratch = Path(tempfile.mkdtemp(prefix="funkot-browser-scratch-"))
            record["owned"] = {"scratch": str(scratch), "endpoint": "http://127.0.0.1:1422/tests/ui/"}
            with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                bundle.extractall(scratch, filter="data")
            record["input_hashes"] = {str(p.relative_to(scratch)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(scratch.rglob("*")) if p.is_file()}
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(scratch / ".browsers")
            env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(evidence / "playwright.json")
            record["environment"] = {k: env[k] for k in ("PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_JSON_OUTPUT_NAME")}
            run(["npm", "ci"], scratch)
            run(["npx", "--no-install", "playwright", "install", "chromium"], scratch)
            run(["node", "--input-type=module", "-e", "import { chromium } from '@playwright/test'; const browser = await chromium.launch(); await browser.close();"], scratch)
            record["feature_result"] = "fail"
            run(["npm", "run", "ui:capture", "--", "tests/ui/queue-ui.spec.mjs", "--grep", TITLE, "--reporter=json", "--output", str(evidence / "results")], scratch)
            record["artifacts"] = judge(json.loads((evidence / "playwright.json").read_text()), evidence)
            record["feature_result"] = "pass"
            record["result"] = "pass"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        record["result"] = "fail" if record["feature_result"] == "fail" else "blocked"
        record["feature_result"] = record["result"]
        record["error"] = str(error)
    finally:
        try:
            if scratch is not None:
                record["cleanup"]["removed_file_bytes"] = sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file())
                removed_file_bytes = record["cleanup"]["removed_file_bytes"]
                shutil.rmtree(scratch)
            else:
                removed_file_bytes = 0
            retained = all(Path(p).is_file() for p in record["artifacts"])
            groups = {c["process_group"] for c in record["commands"] if "process_group" in c}
            remaining = []
            for stat in Path("/proc").glob("[0-9]*/stat"):
                try:
                    fields = stat.read_text().rsplit(")", 1)[1].split()
                    if int(fields[2]) in groups and fields[0] != "Z":
                        remaining.append(int(stat.parent.name))
                except (FileNotFoundError, ProcessLookupError):
                    pass
            record["cleanup"] = {"ok": (scratch is None or port_free()) and retained and not remaining,
                                 "removed_file_bytes": removed_file_bytes,
                                 "remaining_processes": remaining,
                                 "scratch_removed": scratch is None or not scratch.exists(),
                                 "evidence_retained": retained and result_file.exists()}
            if not record["cleanup"]["ok"]:
                record["result"] = "fail"
        except OSError as error:
            record["cleanup"] = {"ok": False, "error": str(error)}
            record["result"] = "fail"
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    print(result_file)
    return {"pass": 0, "fail": 1, "blocked": 2, "not-run": 3}[record["result"]]


if __name__ == "__main__":
    raise SystemExit(main())

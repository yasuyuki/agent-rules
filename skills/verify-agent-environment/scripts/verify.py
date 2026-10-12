import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


RULE_BODY = b"# Synthetic private policy\n\nKeep this project's handwritten inputs intact.\n"
UPDATED_BODY = b"# Synthetic private policy\n\nKeep this project's handwritten inputs intact after update.\n"
SKILL = b"---\nname: environment-proof\ndescription: Inspect synthetic environment proof input.\n---\n# Environment proof\n\nRead reference.txt.\n"
REFERENCE = b"Synthetic source composition evidence.\n"
HANDWRITING = b"---\nname: handwritten\ndescription: Keep this handwritten skill.\n---\n# Handwritten\n"
PREFIXES = (".agents", ".claude", ".grok")
EXIT_CODES = {"pass": 0, "fail": 1, "blocked": 2, "not-run": 3}


class Blocked(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): {"sha256": digest(p.read_bytes()), "mode": p.stat().st_mode & 0o777}
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def expected_files(body):
    files = {"AGENTS.md": body, ".claude/rules/private-example.md": body}
    for prefix in PREFIXES:
        files[f"{prefix}/skills/environment-proof/SKILL.md"] = SKILL
        files[f"{prefix}/skills/environment-proof/reference.txt"] = REFERENCE
    return files


def require(condition, name, record):
    record["assertions"].append({"name": name, "passed": bool(condition)})
    if not condition:
        raise AssertionError(name)


def observe(output, body, record):
    expected = expected_files(body)
    for name, data in expected.items():
        path = output / name
        require(path.is_file() and path.read_bytes() == data, f"exact generated content {name}", record)
    manifest = json.loads((output / ".rulesync-ownership.json").read_text())
    require({f["path"] for f in manifest["files"]} == set(expected), "exact owned file set", record)
    for item in manifest["files"]:
        path = output / item["path"]
        require(item["sha256"] == digest(expected[item["path"]]) and item["mode"] == path.stat().st_mode & 0o777,
                f"ownership matches bytes and mode {item['path']}", record)
    require(not (output / "CLAUDE.md").exists(), "no root CLAUDE.md", record)
    require((output / "note.txt").read_bytes() == b"unrelated note\n", "unrelated note preserved", record)
    require((output / ".agents/skills/handwritten/SKILL.md").read_bytes() == HANDWRITING,
            "handwritten skill preserved", record)


def command(argv, cwd, evidence, record):
    index = len(record["commands"])
    log = evidence / f"command-{index:02}.json"
    item = {"argv": [str(x) for x in argv], "cwd": str(cwd), "artifact": log.name}
    record["commands"].append(item)
    result = subprocess.run(item["argv"], cwd=cwd, capture_output=True, text=True)
    item["returncode"] = result.returncode
    write_json(log, {**item, "stdout": result.stdout, "stderr": result.stderr})
    return result


def doctor(args, evidence, record):
    if platform.system() != "Linux":
        raise Blocked("This recipe has been exercised on Linux only")
    for executable in (args.entry, args.rulesync):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise Blocked(f"Missing executable: {executable}")
    if not shutil.which("git") or not shutil.which("node"):
        raise Blocked("Git and Node.js are required")
    repo = args.environment_repo
    config = repo / "examples/rulesync/placement.json"
    rule = repo / "examples/rulesync/sources/rules/private-example.md"
    if not config.is_file() or not rule.is_file() or config.is_symlink() or rule.is_symlink():
        raise Blocked("A regular synthetic Rulesync config and rule are required")
    value = json.loads(config.read_text())
    if value != {"version": 1, "input_roots": ["sources"], "targets": ["codexcli", "claudecode", "grokcli"],
                 "features": ["rules", "skills"], "output_root": "scratch/project", "global": False}:
        raise Blocked("Synthetic example boundary differs from this proof contract")
    source = rule.read_bytes()
    if source.split(b"---", 2)[-1].lstrip(b"\r\n") != RULE_BODY:
        raise Blocked("Synthetic example policy differs from fixed expectations")
    head = command(["git", "rev-parse", "HEAD"], repo, evidence, record)
    status = command(["git", "status", "--porcelain=v1"], repo, evidence, record)
    if head.returncode or status.returncode:
        raise Blocked("Target must be an identifiable Git checkout")
    record["target"] = {"repo": str(repo), "revision": head.stdout.strip(), "dirty": status.stdout.splitlines()}
    skill = Path(__file__).resolve().parents[1]
    inputs = (config, rule, Path(__file__).resolve(), skill / "SKILL.md", *sorted((skill / "features").glob("*.md")), args.entry, args.rulesync)
    record["inputs"] = {str(p): digest(p.read_bytes()) for p in inputs}
    record["runtime"] = {"python": sys.version, "platform": platform.platform()}
    for name, argv in (("node", ["node", "--version"]), ("git", ["git", "--version"]),
                       ("adapter", [args.entry, "--version"]), ("rulesync", [args.rulesync, "--version"])):
        result = command(argv, repo, evidence, record)
        if result.returncode:
            raise Blocked(f"Cannot identify {name}")
        record["runtime"][name] = result.stdout.strip()
    if int(record["runtime"]["node"].lstrip("v").split(".")[0]) < 22:
        raise Blocked("Node.js 22+ is required")
    if record["runtime"]["rulesync"] != "16.39.1":
        raise Blocked("Target requires Rulesync 16.39.1")
    return config, rule


def drive(args, scratch, evidence, record, config, rule):
    fixture = scratch / "example"
    (fixture / "sources/rules").mkdir(parents=True)
    shutil.copy2(config, fixture / "placement.json")
    copied_rule = fixture / "sources/rules/private-example.md"
    shutil.copy2(rule, copied_rule)
    source_skill = fixture / "sources/skills/environment-proof"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_bytes(SKILL)
    (source_skill / "reference.txt").write_bytes(REFERENCE)
    output = fixture / "scratch/project"
    (output / ".agents/skills/handwritten").mkdir(parents=True)
    (output / ".agents/skills/handwritten/SKILL.md").write_bytes(HANDWRITING)
    (output / "note.txt").write_bytes(b"unrelated note\n")
    write_json(evidence / "expectations.json", {
        "initial": {name: data.decode() for name, data in expected_files(RULE_BODY).items()},
        "updated": {name: data.decode() for name, data in expected_files(UPDATED_BODY).items()},
        "preservation": "Reapply and collision leave output bytes and modes unchanged; original inputs stay unchanged",
        "collision": "Nonzero apply with unchanged output and surviving handwritten skill",
    })
    record["drive_started"] = True

    def operate(operation, succeeds=True, changed=None):
        result = command([args.entry, operation, "--config", fixture / "placement.json", "--rulesync", args.rulesync],
                         fixture, evidence, record)
        require((result.returncode == 0) == succeeds, f"{operation} expected exit success={succeeds}", record)
        if changed is not None:
            require(json.loads(result.stdout) is changed, f"apply changed={changed}", record)
        if not succeeds:
            require("unowned file would be replaced: .agents/skills/handwritten/SKILL.md" in result.stderr,
                    "collision refused for the unowned handwritten skill", record)

    def retain(name):
        shutil.copytree(output, evidence / name)
        return snapshot(output)

    operate("apply", changed=True)
    operate("check")
    observe(output, RULE_BODY, record)
    before = retain("initial")
    operate("apply", changed=False)
    require(snapshot(output) == before, "reapply preserves output bytes and modes", record)
    copied_rule.write_bytes(rule.read_bytes().replace(RULE_BODY, UPDATED_BODY))
    operate("apply", changed=True)
    operate("check")
    observe(output, UPDATED_BODY, record)
    before = retain("updated")
    collision = fixture / "sources/skills/handwritten"
    collision.mkdir()
    (collision / "SKILL.md").write_bytes(HANDWRITING)
    operate("apply", succeeds=False)
    require(retain("rejected") == before, "collision preserves all output bytes and modes", record)
    require(all(digest(Path(p).read_bytes()) == record["inputs"][str(p)] for p in (config, rule)),
            "target source inputs unchanged", record)


def run(args):
    evidence = Path(tempfile.mkdtemp(prefix="environment-proof-", dir=args.evidence_root))
    record = {"run_id": evidence.name, "time": datetime.now(timezone.utc).isoformat(), "agent": args.agent,
              "feature": "rulesync-composition", "entry_point": str(args.entry), "commands": [], "assertions": [],
              "feature_result": "not-run", "drive_started": False,
              "not_run": ["live-placement", "native-discovery", "runtime-launch", "pstack-execution", "push-policy", "necessity-review", "other-hosts"]}
    scratch = None
    write_json(evidence / "result.json", record)
    try:
        config, rule = doctor(args, evidence, record)
        if not args.doctor_only:
            scratch = Path(tempfile.mkdtemp(prefix="environment-proof-scratch-"))
            record["owned_resources"] = [str(scratch)]
            write_json(evidence / "result.json", record)
            drive(args, scratch, evidence, record, config, rule)
            record["feature_result"] = "pass"
    except Blocked as exc:
        record.update(feature_result="blocked", error=str(exc))
    except (OSError, ValueError, AssertionError, KeyError, IndexError) as exc:
        record.update(feature_result="fail" if record["drive_started"] else "blocked", error=str(exc))
    except KeyboardInterrupt:
        record.update(feature_result="fail", error="Run interrupted")
    finally:
        cleanup_error = None
        try:
            if record["feature_result"] == "fail" and scratch is not None:
                output = scratch / "example/scratch/project"
                if output.exists():
                    shutil.copytree(output, evidence / "failed-output")
        except OSError as exc:
            cleanup_error = str(exc)
        artifacts = sorted(p.relative_to(evidence).as_posix() for p in evidence.rglob("*") if p.is_file())
        try:
            if scratch is not None:
                shutil.rmtree(scratch)
        except OSError as exc:
            cleanup_error = str(exc)
        cleanup_ok = cleanup_error is None and (scratch is None or not scratch.exists()) and all((evidence / p).is_file() for p in artifacts)
        record["cleanup"] = {"ok": cleanup_ok, "scratch_removed": scratch is None or not scratch.exists(),
                             "error": cleanup_error, "retained_artifacts": artifacts}
        record["result"] = record["feature_result"] if cleanup_ok else "fail"
        write_json(evidence / "result.json", record)
    print(evidence / "result.json")
    return EXIT_CODES[record["result"]]


def main():
    parser = argparse.ArgumentParser(description="Prove synthetic agent-environment Rulesync composition; never apply live configs.")
    parser.add_argument("--environment-repo", type=Path, required=True)
    parser.add_argument("--entry", type=Path, required=True, help="Installed public agent-rules executable")
    parser.add_argument("--rulesync", type=Path, required=True, help="Installed pinned Rulesync executable")
    parser.add_argument("--evidence-root", type=Path, required=True, help="Existing persistent private parent outside checkout and scratch")
    parser.add_argument("--agent", required=True, help="Actual driving agent identity")
    parser.add_argument("--doctor-only", action="store_true")
    args = parser.parse_args()
    for name in ("environment_repo", "entry", "rulesync", "evidence_root"):
        setattr(args, name, getattr(args, name).expanduser().absolute())
    if not args.evidence_root.is_dir() or args.evidence_root.resolve().is_relative_to(args.environment_repo.resolve()):
        parser.error("Evidence parent must exist outside the target checkout")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

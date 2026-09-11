#!/usr/bin/env python3
"""Drive the public placement CLI against owned disposable inputs; retain proof."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


BLUE = "Use the blue verification value."
GREEN = "Use the green verification value."
LOCAL = "# Local instructions\n\nKeep these hand-written instructions.\n"
SKILL = "---\nname: verification-probe-skill\ndescription: A synthetic verification input\n---\nRead references/note.md.\n"
NOTE = "Synthetic reference: retain these exact bytes.\n"
HAND = {
    "notes.txt": "Unrelated project notes.\n",
    ".codex/skills/hand-written/SKILL.md": "---\nname: hand-written\ndescription: Hand-written fixture\n---\nKeep me.\n",
    ".codex/skills/hand-written/extra.txt": "An unrelated hand-written addition.\n",
}
EXPECTATIONS = {
    "initial": "One blue probe section; source skill/reference copied; marker present; all hand-written bytes retained.",
    "updated": "One green probe section; blue removed; skill/reference and hand-written bytes retained.",
    "check": "Public check exits zero after each successful apply.",
    "collision": "Apply rejects an unmarked skill collision and leaves the output tree byte-identical.",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tree(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()}


def execute_bits(path):
    return None if os.name == "nt" else path.stat().st_mode & 0o111


def reject_links(path, label):
    """Reject a lexical path with a link in any component before reading it."""
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("Linked %s is not an isolated input: %s" % (label, current))
    return path


def command(argv, cwd):
    return subprocess.run(argv, cwd=cwd, text=True, encoding="utf-8",
                          errors="replace", capture_output=True)


def doctor(repo, environment_repo=None):
    repo = reject_links(repo, "public input")
    if sys.version_info < (3, 10):
        raise ValueError("Python 3.10 or newer is required")
    for name in ("bin", "bin/place.py", "placement.json", "rules", "skills"):
        path = repo / name
        if path.is_symlink():
            raise ValueError("Linked public input is not an isolated catalog: " + name)
        valid = path.is_dir() if name in ("bin", "rules", "skills") else path.is_file()
        if not valid:
            raise ValueError("Missing public input: " + name)
    revision = command(["git", "rev-parse", "HEAD"], repo)
    status = command(["git", "status", "--porcelain", "--untracked-files=normal"], repo)
    if revision.returncode or status.returncode:
        raise ValueError("A Git checkout with readable revision and status is required")
    # Do not retain diff contents or unrelated untracked filenames.
    inputs = [repo / "placement.json", *sorted((repo / "bin").glob("*.py"))]
    if any(p.is_symlink() for p in inputs):
        raise ValueError("Linked executable input is not an isolated catalog")
    for folder in ("rules", "skills"):
        for path in sorted((repo / folder).rglob("*")):
            if path.is_symlink():
                raise ValueError("Linked public input is not an isolated catalog: " + str(path.relative_to(repo)))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                inputs.append(path)
    target = {
        "revision": revision.stdout.strip(), "dirty": bool(status.stdout.strip()),
        "inputs_sha256": {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in inputs},
        "helper_sha256": sha(Path(__file__).read_bytes()),
        "python": platform.python_version(), "platform": platform.system(),
        "entry_point": "bin/place.py apply/check --declaration --rules --skills",
    }
    if environment_repo is None:
        return target
    environment_repo = reject_links(environment_repo, "dependency input")
    selected = reject_links(environment_repo / "examples/single-environment/rules/example-private.rule.md", "dependency input")
    if not selected.is_file():
        raise ValueError("Missing environment dependency input: examples/single-environment/rules/example-private.rule.md")
    git_root = command(["git", "rev-parse", "--show-toplevel"], environment_repo)
    revision = command(["git", "rev-parse", "HEAD"], environment_repo)
    status = command(["git", "status", "--porcelain", "--untracked-files=normal"], environment_repo)
    if (git_root.returncode or Path(git_root.stdout.strip()).resolve() != environment_repo.resolve()
            or revision.returncode or status.returncode):
        raise ValueError("Environment dependency must be a Git repository with readable revision and status")
    content = selected.read_bytes()
    target["environment_dependency"] = {
        "revision": revision.stdout.strip(), "dirty": bool(status.stdout.strip()),
        "example_private_sha256": sha(content),
        "selected_rule": "examples/single-environment/rules/example-private.rule.md",
    }
    return target


def fixture(scratch):
    project = scratch / "project"
    project.mkdir()
    home = scratch / "home"
    home.mkdir()
    declaration = scratch / "PLACEMENT.md"
    write(declaration, "\n".join([
        "<!-- BEGIN SITES TSV -->", "```tsv", "id\thost\tuser\thome\treach\tlaunch",
        "local\t%s\tverification\t%s\tlocal\t" % (platform.system(), home.as_posix()), "```", "<!-- END SITES TSV -->",
        "<!-- BEGIN WORKSPACES TSV -->", "```tsv", "id\tsite\tkind\tpath\textra",
        "project\tlocal\tdirect\t%s\t" % project.as_posix(), "```", "<!-- END WORKSPACES TSV -->",
        "<!-- BEGIN LOCATIONS TSV -->", "```tsv",
        "id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind",
        "project-rules\tworkspace\tproject\tcodex\trequired\t\t\t\trules",
        "project-skills\tworkspace\tproject\tcodex\trequired\t\t\t\tskills",
        "```", "<!-- END LOCATIONS TSV -->",
        "<!-- BEGIN EXCEPTIONS TSV -->", "```tsv",
        "artifact\tlocation_id\trequirement\treason", "```", "<!-- END EXCEPTIONS TSV -->", "",
    ]))
    rule = scratch / "inputs/rules/verification-probe.rule.md"
    write(rule, "---\nid: verification-probe\ntitle: Verification probe\nsummary: Synthetic placement proof\n---\n" + BLUE + "\n")
    skills = scratch / "inputs/skills"
    write(skills / "verification-probe-skill/SKILL.md", SKILL)
    write(skills / "verification-probe-skill/references/note.md", NOTE)
    write(project / "AGENTS.md", LOCAL)
    for name, value in HAND.items():
        write(project / name, value)
    return project, declaration, rule, skills


def run(repo, evidence_root=None, doctor_only=False, environment_repo=None, agent="unknown"):
    repo = Path(repo).resolve()
    if evidence_root is not None:
        evidence_root = Path(evidence_root).resolve()
        evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="agent-rules-evidence-", dir=evidence_root))
    result = {
        "run_id": evidence.name, "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked", "feature": "placement", "feature_status": "not-run",
        "agent": agent, "feature_states": {"placement": "not-run", "composition": "not-run", "mirror": "not-run"},
        "expectations": EXPECTATIONS, "commands": [], "assertions": [], "artifacts": [],
        "not_run": ["package CLI", "other file conventions", "native agent loading", "remote placement"],
        "cleanup": {"ok": True, "scratch": None},
    }
    if environment_repo is not None:
        result["expectations"] = {**EXPECTATIONS,
            "composition": "Selected dependency rule composes with the public catalog in initial and updated AGENTS.md.",
            "mirror": "Non-vendored skills mirror byte-for-byte with execute bits; check detects drift and repair restores it."}
    scratch = None

    def record():
        write(evidence / "result.json", json.dumps(result, indent=2) + "\n")

    def assertion(name, expected, observed):
        ok = observed == expected
        result["assertions"].append({"name": name, "expected": expected, "observed": observed, "ok": ok})
        record()
        if not ok:
            raise AssertionError(name)

    def drive(action, *extra_rules):
        argv = [sys.executable, str(repo / "bin/place.py"), action,
                "--declaration", str(declaration), "--rules", str(rule.parent)]
        for extra in extra_rules:
            argv.extend(["--rules", str(extra)])
        argv.extend(["--skills", str(skills)])
        proc = command(argv, scratch)
        result["commands"].append({"argv": argv, "cwd": str(scratch),
                                   "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        record()
        return proc

    def snapshot(label):
        dest = evidence / label
        shutil.copytree(project, dest)
        result["artifacts"].append(label)
        return tree(dest)

    def mirror_snapshot(label):
        dest = evidence / label
        shutil.copytree(mirror, dest)
        result["artifacts"].append(label)
        return tree(dest)

    def inspect(label, body):
        snapshot(label)
        text = (project / "AGENTS.md").read_text(encoding="utf-8") if (project / "AGENTS.md").exists() else ""
        assertion(label + " local instructions", True, text.startswith(LOCAL))
        assertion(label + " section count", 1, text.count("<!-- agent-rules:begin verification-probe -->"))
        expected = "<!-- agent-rules:begin verification-probe -->\n# Verification probe\n\n" + body + "\n<!-- agent-rules:end verification-probe -->"
        assertion(label + " section content", True, expected in text)
        if body == GREEN:
            assertion("old body removed", False, BLUE in text)
        prefix = ".codex/skills/verification-probe-skill/"
        for name, value in {**HAND, prefix + "SKILL.md": SKILL, prefix + "references/note.md": NOTE}.items():
            path = project / name
            assertion(label + " " + name, value, path.read_text(encoding="utf-8") if path.is_file() else None)
        marker = project / prefix / ".agent-skills"
        assertion(label + " ownership marker", True, marker.is_file() and "verification-probe-skill" in marker.read_text(encoding="utf-8"))

    def inspect_composition(label, body):
        inspect(label, body)
        text = (project / "AGENTS.md").read_text(encoding="utf-8")
        expected = ("<!-- agent-rules:begin example-private -->\n# Example private rule\n\n"
                    "This is a synthetic example of a private rule that lives outside the\n"
                    "agent-rules canonical source, in the environment's own `rule_sources`. Real\n"
                    "private rules go in a directory like this one, referenced by an env.json\n"
                    "config's `rule_sources`, and are projected alongside the canonical rules\n"
                    "from `agent_rules_root`.\n<!-- agent-rules:end example-private -->")
        assertion(label + " dependency section", True, expected in text)
        assertion(label + " dependency section count", 1, text.count("<!-- agent-rules:begin example-private -->"))
        assertion(label + " public handoff section", 1, text.count("<!-- agent-rules:begin handoff -->"))

    def mirror_drive(check=False):
        argv = [sys.executable, str(repo / "bin/place.py"), "mirror", "--skills", str(repo / "skills"), "--dest", str(mirror)]
        if check:
            argv.append("--check")
        proc = command(argv, scratch)
        result["commands"].append({"argv": argv, "cwd": str(scratch), "exit_code": proc.returncode,
                                   "stdout": proc.stdout, "stderr": proc.stderr})
        record()
        return proc

    def source_mirror_tree():
        manifest = repo / "skills" / "UPSTREAM.tsv"
        with manifest.open(encoding="utf-8", newline="") as handle:
            vendored = {row["id"] for row in csv.DictReader(handle, delimiter="\t")}
        output = {}
        for skill in sorted((repo / "skills").iterdir()):
            if skill.is_dir() and skill.name not in vendored:
                for path in sorted(skill.rglob("*")):
                    if path.is_file():
                        output[path.relative_to(repo / "skills").as_posix()] = [sha(path.read_bytes()), execute_bits(path)]
        return output

    def assert_mirror(label):
        actual = {}
        root = mirror / "skills"
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    actual[path.relative_to(root).as_posix()] = [sha(path.read_bytes()), execute_bits(path)]
        assertion(label + " non-vendored bytes and execute bits", source_mirror_tree(), actual)
        assertion(label + " root notes retained", "seeded mirror notes\n", (mirror / "notes.txt").read_text(encoding="utf-8"))

    record()  # Expectations exist before the first operation.
    try:
        result["target"] = doctor(repo, environment_repo)
        if doctor_only:
            result["status"] = "not-run"
        else:
            scratch = Path(tempfile.mkdtemp(prefix="agent-rules-drive-"))
            result["cleanup"]["scratch"] = str(scratch)
            project, declaration, rule, skills = fixture(scratch)
            shutil.copytree(scratch / "inputs", evidence / "inputs-initial")
            shutil.copy2(declaration, evidence / "PLACEMENT.md")
            result["artifacts"].extend(["inputs-initial", "PLACEMENT.md"])
            result["feature_status"] = "fail"
            result["status"] = "fail"
            result["feature_states"]["placement"] = "fail"
            assertion("initial apply exit", 0, drive("apply").returncode)
            inspect("initial", BLUE)
            assertion("initial check exit", 0, drive("check").returncode)
            write(rule, rule.read_text(encoding="utf-8").replace(BLUE, GREEN))
            shutil.copy2(rule, evidence / "updated-source.rule.md")
            result["artifacts"].append("updated-source.rule.md")
            assertion("updated apply exit", 0, drive("apply").returncode)
            inspect("updated", GREEN)
            assertion("updated check exit", 0, drive("check").returncode)
            before = tree(project)
            write(skills / "hand-written/SKILL.md", "---\nname: hand-written\ndescription: Conflicting source fixture\n---\nDo not overwrite the hand-written destination.\n")
            shutil.copytree(skills / "hand-written", evidence / "collision-source")
            result["artifacts"].append("collision-source")
            assertion("collision rejected", True, drive("apply").returncode != 0)
            assertion("collision preserves output tree", before, snapshot("collision"))
            result["feature_states"]["placement"] = "pass"
            result["feature_status"] = "pass"
            if environment_repo is not None:
                shutil.rmtree(skills / "hand-written")
                selected = Path(environment_repo).absolute() / "examples/single-environment/rules/example-private.rule.md"
                dependency_rules = scratch / "inputs/dependency-rules"
                before_hash = result["target"]["environment_dependency"]["example_private_sha256"]
                assertion("dependency source hash matches Doctor", before_hash, sha(selected.read_bytes()))
                dependency_rules.mkdir(parents=True)
                shutil.copy2(selected, dependency_rules / selected.name)
                shutil.copy2(selected, evidence / "dependency-example-private.rule.md")
                result["artifacts"].append("dependency-example-private.rule.md")
                result["feature_states"]["composition"] = "fail"
                write(rule, rule.read_text(encoding="utf-8").replace(GREEN, BLUE))
                assertion("composition initial apply exit", 0, drive("apply", dependency_rules).returncode)
                inspect_composition("composition-initial", BLUE)
                assertion("composition initial check exit", 0, drive("check", dependency_rules).returncode)
                write(rule, rule.read_text(encoding="utf-8").replace(BLUE, GREEN))
                assertion("composition updated apply exit", 0, drive("apply", dependency_rules).returncode)
                inspect_composition("composition-updated", GREEN)
                assertion("composition updated check exit", 0, drive("check", dependency_rules).returncode)
                assertion("dependency source hash unchanged after composition", before_hash, sha(selected.read_bytes()))
                result["feature_states"]["composition"] = "pass"

                mirror = scratch / "mirror"
                write(mirror / "notes.txt", "seeded mirror notes\n")
                result["feature_states"]["mirror"] = "fail"
                assertion("mirror initial apply exit", 0, mirror_drive().returncode)
                mirror_snapshot("mirror-initial")
                assert_mirror("mirror initial")
                assertion("mirror initial check exit", 0, mirror_drive(True).returncode)
                assertion("mirror repeated apply exit", 0, mirror_drive().returncode)
                assert_mirror("mirror repeated")
                corrupted = mirror / "skills/verify-agent-rules/SKILL.md"
                write(corrupted, "corrupt mirrored verifier\n")
                before = tree(mirror)
                mirror_snapshot("mirror-corrupt")
                assertion("mirror corruption check rejected", True, mirror_drive(True).returncode != 0)
                assertion("mirror check does not mutate", before, tree(mirror))
                assertion("mirror repair exit", 0, mirror_drive().returncode)
                mirror_snapshot("mirror-repaired")
                assertion("mirror repaired check exit", 0, mirror_drive(True).returncode)
                assert_mirror("mirror repaired")
                assertion("dependency source hash unchanged after mirror", before_hash, sha(selected.read_bytes()))
                assertion("public source hashes unchanged", result["target"]["inputs_sha256"], doctor(repo)["inputs_sha256"])
                result["feature_states"]["mirror"] = "pass"
            result["status"] = "pass"
    except (OSError, ValueError, AssertionError, KeyboardInterrupt) as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        # Preparation errors stay blocked; mismatches after Drive stay fail.
    finally:
        if scratch is not None:
            try:
                shutil.rmtree(scratch)
                result["cleanup"]["ok"] = not scratch.exists()
            except OSError as exc:
                result["cleanup"].update(ok=False, error=str(exc))
        if not result["cleanup"]["ok"]:
            result["status"] = "fail"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        result["evidence_retained"] = all((evidence / item).exists() for item in result["artifacts"])
        if not result["evidence_retained"]:
            result["status"] = "fail"
        if (environment_repo is not None and result["status"] not in ("blocked", "not-run")
                and any(value != "pass" for value in result["feature_states"].values())):
            result["status"] = "fail"
        record()
    return result, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--doctor-only", action="store_true")
    parser.add_argument("--environment-repo", type=Path)
    parser.add_argument("--agent", default="unknown")
    args = parser.parse_args()
    result, evidence = run(args.repo, args.evidence_root, args.doctor_only, args.environment_repo, args.agent)
    print(json.dumps({"status": result["status"], "result": str(evidence / "result.json")}, indent=2))
    return {"pass": 0, "fail": 1, "blocked": 2, "not-run": 3}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())

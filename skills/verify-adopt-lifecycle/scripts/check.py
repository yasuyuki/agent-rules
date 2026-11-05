#!/usr/bin/env python3
"""Model-check AdoptLifecycle.tla and its broken and fixed variants with a pinned TLC."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SPEC = HERE / "AdoptLifecycle.tla"
TLC_VERSION = "1.7.4"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
INVARIANTS = ["InstallResumes", "SwitchResumes", "AdoptedAfterChecks", "AdoptedLeavesNoTask",
              "AdoptedIsLive"]
MAX_FAULTS = 2

# Violations of the current code that are reported, not hidden. Each turns
# into a MISMATCH once its fix lands.
FINDINGS = {
    "InstallResumes": "agent-environment#58",
    "SwitchResumes": "agent-environment#59",
    "AdoptedAfterChecks": "agent-environment#60",
    "AdoptedLeavesNoTask": "agent-environment#60",
}
RUNS = (
    [("none", inv, "finding" if inv in FINDINGS else "pass") for inv in INVARIANTS]
    + [("fixed", inv, "pass") for inv in INVARIANTS]
    + [
        ("apply-trusts-precheck", "AdoptedIsLive", "violated"),
        ("ignore-checks", "AdoptedAfterChecks", "violated"),
    ]
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run_tlc(java: str, jar: Path, out: Path, variant: str, invariant: str) -> tuple[str, str]:
    work = out / f"{variant}-{invariant}"
    work.mkdir()
    (work / "run.cfg").write_text(
        f'SPECIFICATION Spec\nCONSTANTS\n    Mutation = "{variant}"\n    MaxFaults = {MAX_FAULTS}\n'
        f"INVARIANTS\n    TypeOK\n    {invariant}\n", encoding="utf-8", newline="\n")
    shutil.copyfile(SPEC, work / SPEC.name)
    (work / "tmp").mkdir()
    command = [java, "-XX:+UseParallelGC", f"-Djava.io.tmpdir={work / 'tmp'}", "-cp", str(jar),
               "tlc2.TLC", "-workers", "1", "-metadir", str(work / "states"),
               "-config", "run.cfg", SPEC.name]
    result = subprocess.run(command, cwd=work, capture_output=True, encoding="utf-8",
                            errors="replace", stdin=subprocess.DEVNULL)
    text = result.stdout + result.stderr
    (work / "tlc.out").write_text(text, encoding="utf-8", newline="\n")
    states = re.search(r"(\d[\d,]*) distinct states found", text)
    detail = f"{states.group(1)} distinct states" if states else "no state count"
    if "Model checking completed. No error has been found." in text:
        return "pass", detail
    violated = re.search(r"Invariant (\w+) is violated", text)
    if violated and violated.group(1) == invariant:
        return "violated", detail
    if violated:
        return f"violated {violated.group(1)}", detail
    return f"error (exit {result.returncode})", detail


def run_all(java: str, jar: Path, out: Path) -> int:
    mismatches = 0
    for variant, invariant, expected in RUNS:
        actual, detail = run_tlc(java, jar, out, variant, invariant)
        wanted = "violated" if expected == "finding" else expected
        ok = actual == wanted
        mismatches += not ok
        label = "KNOWN FINDING" if ok and expected == "finding" else ("ok" if ok else "MISMATCH")
        issue = f" {FINDINGS[invariant]}" if expected == "finding" else ""
        print(f"{label:13} {variant:22} {invariant:20} expected {expected:8} got {actual} "
              f"({detail}){issue}")
    return 1 if mismatches else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tla2tools", default=os.environ.get("TLA2TOOLS"),
                        help=f"tla2tools.jar {TLC_VERSION}; default $TLA2TOOLS")
    parser.add_argument("--java", default=os.environ.get("JAVA", "java"),
                        help="Java 11+ executable; default $JAVA or java on PATH")
    parser.add_argument("--out", help="new directory that keeps each job's tlc.out; without it outputs are deleted")
    args = parser.parse_args()
    if not args.tla2tools:
        parser.error("pass --tla2tools or set TLA2TOOLS")
    jar = Path(args.tla2tools)
    if not jar.is_file() or sha256(jar) != TLC_SHA256:
        print(f"blocked: {jar} is not tla2tools.jar {TLC_VERSION} (sha256 {TLC_SHA256})", file=sys.stderr)
        return 2
    if args.out:
        out = Path(args.out).resolve()
        out.mkdir(parents=True)
        return run_all(args.java, jar, out)
    with tempfile.TemporaryDirectory(prefix="adopt-lifecycle-tlc-") as temporary:
        return run_all(args.java, jar, Path(temporary))


if __name__ == "__main__":
    sys.exit(main())

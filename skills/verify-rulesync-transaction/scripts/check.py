#!/usr/bin/env python3
"""Model-check RulesyncTransaction.tla and its broken variants with a pinned TLC."""
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
SPEC = HERE / "RulesyncTransaction.tla"
TLC_VERSION = "1.7.4"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
BOUNDS = {"MaxCrashes": 2, "MaxFaults": 1, "MaxUserEdits": 1}

# (variant, invariant, expected). "finding" is a violation of the current code
# that is reported, not hidden; it turns into a mismatch once the code is fixed.
RUNS = [
    ("none", "NoClobber", "pass"),
    ("none", "AllOrNothing", "pass"),
    ("none", "NoStuck", "finding"),
    ("skip-unowned-check", "NoClobber", "violated"),
    ("recover-skip-conflict", "NoClobber", "violated"),
    ("no-journal", "AllOrNothing", "violated"),
    ("proposed-temp-cleanup", "NoStuck", "pass"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run_tlc(java: str, jar: Path, out: Path, variant: str, invariant: str) -> tuple[str, str]:
    name = f"{variant}-{invariant}"
    work = out / name
    work.mkdir()
    constants = "\n".join(f"    {key} = {value}" for key, value in BOUNDS.items())
    (work / "run.cfg").write_text(
        f'SPECIFICATION Spec\nCONSTANTS\n    Mutation = "{variant}"\n{constants}\n'
        f"INVARIANTS\n    TypeOK\n    {invariant}\n", encoding="utf-8", newline="\n")
    shutil.copyfile(SPEC, work / SPEC.name)
    command = [java, "-XX:+UseParallelGC", f"-Djava.io.tmpdir={work / 'tmp'}", "-cp", str(jar),
               "tlc2.TLC", "-workers", "1", "-metadir", str(work / "states"),
               "-config", "run.cfg", SPEC.name]
    (work / "tmp").mkdir()
    result = subprocess.run(command, cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tla2tools", default=os.environ.get("TLA2TOOLS"),
                        help=f"tla2tools.jar {TLC_VERSION}; default $TLA2TOOLS")
    parser.add_argument("--java", default=os.environ.get("JAVA", "java"),
                        help="Java 11+ executable; default $JAVA or java on PATH")
    parser.add_argument("--out", help="new directory for TLC outputs; default a fresh temporary directory")
    args = parser.parse_args()
    if not args.tla2tools:
        parser.error("pass --tla2tools or set TLA2TOOLS")
    jar = Path(args.tla2tools)
    if not jar.is_file() or sha256(jar) != TLC_SHA256:
        print(f"blocked: {jar} is not tla2tools.jar {TLC_VERSION} (sha256 {TLC_SHA256})", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="rulesync-transaction-tlc-"))
    out.mkdir(parents=True, exist_ok=bool(not args.out))
    mismatches = 0
    for variant, invariant, expected in RUNS:
        actual, detail = run_tlc(args.java, jar, out, variant, invariant)
        wanted = "violated" if expected == "finding" else expected
        ok = actual == wanted
        mismatches += not ok
        label = "KNOWN FINDING" if ok and expected == "finding" else ("ok" if ok else "MISMATCH")
        print(f"{label:13} {variant:22} {invariant:13} expected {expected:8} got {actual} ({detail})")
    print(f"outputs: {out}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())

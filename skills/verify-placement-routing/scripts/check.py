#!/usr/bin/env python3
"""Model-check PlacementRouting.tla and its broken variants with a pinned TLC."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SPEC = HERE / "PlacementRouting.tla"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
INVARIANTS = ["PlacementNeverStalls", "NoNewSessionOnDevelopment"]
CONTROLLER = "windows-controller"
MODEL_ENVS = {CONTROLLER, "ubuntu-operator", "ubuntu-26-development"}

# (rule, invariant, expected). "deadlock" is TLC's own check. Use "finding"
# for a violation of the current rule that is reported, not hidden.
FINDINGS: set[tuple[str, str]] = set()
RUNS = (
    [("windows-sessions", inv, "finding" if ("windows-sessions", inv) in FINDINGS else "pass")
     for inv in INVARIANTS + ["deadlock"]]
    + [
        ("by-repo-kind", "PlacementNeverStalls", "violated"),
        ("by-target", "NoNewSessionOnDevelopment", "violated"),
    ]
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_routes(path: Path) -> list[str]:
    """The model's Reach assumes every recorded route starts on windows-controller."""
    envs = json.loads(path.read_text(encoding="utf-8"))["environments"]
    errors = []
    if set(envs) != MODEL_ENVS:
        errors.append(f"route table environments {sorted(envs)} != model {sorted(MODEL_ENVS)}")
    for name, env in envs.items():
        transport = env.get("transport")
        if name == CONTROLLER and transport != []:
            errors.append(f"{name}: transport {transport} is not local")
        if name != CONTROLLER and (not transport or transport[0] not in ("ssh.exe", "wsl.exe")):
            errors.append(f"{name}: transport {transport} does not start on {CONTROLLER}")
    return errors


def run_tlc(java: str, jar: Path, out: Path, rule: str, invariant: str) -> str:
    work = out / f"{rule}-{invariant}"
    work.mkdir()
    lines = ["SPECIFICATION Spec", "CONSTANTS", f'    Rule = "{rule}"', "INVARIANTS", "    TypeOK"]
    if invariant != "deadlock":
        lines.append(f"    {invariant}")
        lines.append("CHECK_DEADLOCK FALSE")
    (work / "run.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    shutil.copyfile(SPEC, work / SPEC.name)
    (work / "tmp").mkdir()
    command = [java, "-XX:+UseParallelGC", f"-Djava.io.tmpdir={work / 'tmp'}", "-cp", str(jar),
               "tlc2.TLC", "-workers", "1", "-metadir", str(work / "states"),
               "-config", "run.cfg", SPEC.name]
    done = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    text = done.stdout + done.stderr
    (work / "tlc.out").write_text(text, encoding="utf-8", newline="\n")
    if "Model checking completed. No error has been found." in text:
        return "pass"
    if f"Invariant {invariant} is violated" in text or (
            invariant == "deadlock" and "Deadlock reached" in text):
        return "violated"
    if "Invariant TypeOK is violated" in text:
        return "type-error"
    return "error"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tla2tools", default=os.environ.get("TLA2TOOLS"),
                        help="tla2tools.jar 1.7.4 (default $TLA2TOOLS)")
    parser.add_argument("--java", default=os.environ.get("JAVA", "java"),
                        help="Java 11+ executable (default $JAVA or java)")
    parser.add_argument("--routes", type=Path,
                        help="agent-environment pstack/environments.json to compare with the model")
    parser.add_argument("--out", type=Path, help="new directory that keeps every TLC run")
    args = parser.parse_args()
    if not args.tla2tools or not Path(args.tla2tools).is_file():
        print("tla2tools.jar not found; pass --tla2tools or set TLA2TOOLS", file=sys.stderr)
        return 2
    jar = Path(args.tla2tools)
    if sha256(jar) != TLC_SHA256:
        print(f"{jar} is not tla2tools.jar 1.7.4 (sha256 mismatch)", file=sys.stderr)
        return 2
    failed = False
    if args.routes:
        errors = check_routes(args.routes)
        for error in errors:
            print(f"MISMATCH routes: {error}")
        if not errors:
            print("ok routes")
        failed |= bool(errors)
    keep = args.out is not None
    if keep:
        args.out.mkdir(parents=True)
    out = args.out if keep else Path(tempfile.mkdtemp(prefix="placement-routing-"))
    try:
        for rule, invariant, expected in RUNS:
            got = run_tlc(args.java, jar, out, rule, invariant)
            want = "violated" if expected == "finding" else expected
            status = "ok" if got == want else "MISMATCH"
            failed |= got != want
            label = "FINDING" if expected == "finding" and got == "violated" else status
            print(f"{label} {rule} {invariant}: expected {expected}, got {got}")
    finally:
        if not keep:
            shutil.rmtree(out, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

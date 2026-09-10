"""Synthetic coverage for the read-only work/environment classifier."""
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("work_classification", ROOT / "bin" / "work_classification.py")
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    placement = root / "placement.md"
    placement.write_text("""<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
local\tLinux\tagent\t/home/agent\tdirect\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\tlocal\tdirect\t/tmp\t
```
<!-- END WORKSPACES TSV -->
""", encoding="utf-8")
    catalog = root / "catalog.json"
    catalog.write_text(json.dumps({"schemaVersion": 1, "sources": {"p": {
        "type": "placement-tsv", "host": "test", "paths": {"default": str(placement)}
    }}, "environments": [
        {"id": "isolated", "purposes": ["normal-development"], "state": "active", "refs": [{"source": "p", "site": "local"}], "entrypoint": None, "agents": [], "capabilities": {
            "source-edit": {"status": "available", "reason": "checked", "evidence": ["fixture"]},
            "tool": {"status": "preparable", "reason": "not installed", "evidence": [], "preparation": "documented setup"},
            "device": {"status": "unavailable", "reason": "no device", "evidence": []},
        }},
        {"id": "outside", "purposes": ["operator"], "state": "active", "refs": [{"source": "p", "site": "local"}], "entrypoint": None, "agents": [], "capabilities": {
            "source-edit": {"status": "available", "reason": "checked", "evidence": []}
        }},
        {"id": "windows", "purposes": ["normal-development"], "state": "active", "refs": [{"source": "p", "site": "local"}], "entrypoint": None, "agents": [], "capabilities": {
            "source-edit": {"status": "available", "reason": "second capable fixture", "evidence": ["fixture"]},
            "device": {"status": "available", "reason": "fixture device", "evidence": ["fixture"]},
            "outside-tool": {"status": "available", "reason": "fixture tool", "evidence": ["fixture"]}
        }},
        {"id": "pending", "purposes": ["normal-development"], "state": "pending", "refs": [{"source": "p", "site": "local"}], "entrypoint": None, "agents": [], "capabilities": {
            "source-edit": {"status": "available", "reason": "fixture", "evidence": []}
        }},
        {"id": "retained", "purposes": ["normal-development"], "state": "retained", "refs": [{"source": "p", "site": "local"}], "entrypoint": None, "agents": [], "capabilities": {
            "source-edit": {"status": "available", "reason": "fixture", "evidence": []}
        }},
    ]}), encoding="utf-8")
    work = root / "work.json"
    def phase(name, requires, *, purpose="normal-development", ids=None, state="ready", mode="normal"):
        return {"id": name, "summary": name, "purpose": purpose, "requires": requires,
                "environment": {"ids": ids or [], "mode": mode}, "executor": {"kind": "agent", "state": state},
                "prerequisites": [], "acceptance": [], "handoffs": []}
    work.write_text(json.dumps({"schemaVersion": 1, "work": [
        {"id": "cases", "reference": "synthetic", "phases": [
            phase("available", ["source-edit"]), phase("preparable", ["tool"]),
            phase("external", ["device"]), phase("unknown", ["missing"]),
            phase("locked", ["source-edit"], ids=["outside"]), phase("hold", ["source-edit"], state="hold"),
            phase("unspecified", ["source-edit"], state="unspecified"), phase("none", ["source-edit"], ids=["outside"]),
            phase("windows", ["device"], ids=["windows"]),
            phase("unknown-external", ["outside-tool"]),
            phase("construct", ["source-edit"], ids=["pending"], mode="construction"),
            phase("retained", ["source-edit"], ids=["retained"]),
        ]},
        {"id": "excluded", "reference": "synthetic old record", "excludedReason": "completed"},
    ]}), encoding="utf-8")
    before = {path: path.read_bytes() for path in (placement, catalog, work)}
    # Classification is read-only: deny process/network activity and confirm
    # every supplied file is byte-identical afterwards.
    with mock.patch.object(classifier.environment_inventory.subprocess, "Popen", side_effect=AssertionError("classification launched")), \
         mock.patch.object(classifier.environment_inventory.os, "system", side_effect=AssertionError("classification launched")), \
         mock.patch("socket.socket.connect", side_effect=AssertionError("classification connected")):
        result = classifier.classify(catalog, work, "isolated")
    assert {path: path.read_bytes() for path in before} == before
    cases = {item["id"]: item for item in result}["cases"]
    phases = {item["id"]: item for item in cases["phases"]}
    assert phases["available"]["classification"] == "available"
    assert {entry["environment"] for entry in phases["available"]["candidates"] if entry["classification"] == "available"} == {"isolated", "windows"}
    assert phases["available"]["proposedEnvironment"] == "isolated"
    assert phases["preparable"]["classification"] == "preparable"
    assert phases["external"]["classification"] == "external-required"
    assert phases["external"]["proposedEnvironment"] == "windows"
    assert phases["unknown"]["classification"] == "insufficient-information"
    assert phases["unknown"]["proposedEnvironment"] is None
    assert phases["unknown-external"]["classification"] == "insufficient-information"
    assert phases["unknown-external"]["proposedEnvironment"] == "windows"
    assert phases["available"]["assessments"][0]["evidence"] == {"source-edit": ["fixture"]}
    assert phases["locked"]["classification"] == "external-required"
    assert phases["hold"]["classification"] == "available"
    assert phases["hold"]["candidates"][0]["readiness"] == "hold"
    assert phases["unspecified"]["candidates"][0]["readiness"] == "unspecified"
    assert phases["none"]["candidates"] == []
    assert phases["construct"]["candidates"][0]["environment"] == "pending"
    assert phases["retained"]["candidates"][0]["environment"] == "retained"
    assert cases["splitRequired"] is True
    assert cases["handover"]
    assert result[1]["excludedReason"] == "completed"
    table = classifier.render_table(result)
    assert "reasons\tpreparation\tunmet conditions" in table
    assert "cases\tavailable\tavailable" in table
    command = [sys.executable, str(ROOT / "bin" / "place.py"), "classify", "--catalog", str(catalog), "--work", str(work), "--prefer-environment", "isolated"]
    table_result = subprocess.run(command, text=True, capture_output=True)
    assert table_result.returncode == 0 and "candidates" in table_result.stdout
    json_result = subprocess.run([*command, "--json"], text=True, capture_output=True)
    assert json_result.returncode == 0 and json.loads(json_result.stdout)[0]["splitRequired"] is True
    assert all(len(row.split("\t")) == len(table.splitlines()[0].split("\t")) for row in table.splitlines())

    # A fresh public checkout must not gain bytecode or any other output from
    # classification, even without PYTHONDONTWRITEBYTECODE in the caller.
    copied = root / "public-copy"
    shutil.copytree(ROOT / "bin", copied / "bin", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "placement.json", copied / "placement.json")
    snapshot = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    clean_command = [sys.executable, str(copied / "bin" / "place.py"), *command[2:], "--json"]
    clean_result = subprocess.run(clean_command, text=True, capture_output=True)
    assert clean_result.returncode == 0, clean_result.stderr
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == snapshot

    incompatible = {"schemaVersion": 1, "work": [{"id": "incompatible", "reference": "fixture", "phases": [phase("only-operator", ["source-edit"], ids=["outside"])]}]}
    work.write_text(json.dumps(incompatible), encoding="utf-8")
    no_preference = classifier.classify(catalog, work)[0]["phases"][0]
    assert no_preference["classification"] == "external-required"
    assert no_preference["proposedEnvironment"] is None

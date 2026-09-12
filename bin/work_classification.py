"""Pure, read-only classification of declared work against an environment catalog.

This module deliberately does not probe, launch, install, transfer, or mutate
anything.  It combines the catalog's declared capabilities with a work JSON
document so a controller can decide which phase needs another environment.
"""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path

_inventory_spec = importlib.util.spec_from_file_location(
    "work_classification_environment_inventory", Path(__file__).with_name("environment_inventory.py")
)
environment_inventory = importlib.util.module_from_spec(_inventory_spec)
_inventory_spec.loader.exec_module(environment_inventory)


EXECUTOR_STATES = {"ready", "hold", "waiting", "unspecified"}
EXECUTOR_KINDS = {"agent", "human", "ci", "external"}


class WorkClassificationError(RuntimeError):
    pass


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=environment_inventory._unique_object)
    except (OSError, json.JSONDecodeError, environment_inventory.CatalogError) as exc:
        raise WorkClassificationError("cannot read work input: %s" % exc) from None


def _strings(value, name, *, allow_empty=True):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise WorkClassificationError("%s must be an array of non-empty strings" % name)
    if not allow_empty and not value:
        raise WorkClassificationError("%s must not be empty" % name)
    return value


def load_work(path):
    document = _read(path)
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise WorkClassificationError("work schemaVersion must be 1")
    items = document.get("work")
    if not isinstance(items, list):
        raise WorkClassificationError("work must be an array")
    ids, result = set(), []
    for item in items:
        if not isinstance(item, dict) or set(item) - {"id", "reference", "phases", "excludedReason"}:
            raise WorkClassificationError("work item has unknown or invalid fields")
        item_id, reference = item.get("id"), item.get("reference")
        if not isinstance(item_id, str) or not item_id or item_id in ids or not isinstance(reference, str) or not reference:
            raise WorkClassificationError("work item needs unique id and reference")
        ids.add(item_id)
        excluded = item.get("excludedReason")
        phases = item.get("phases")
        if excluded is not None:
            if not isinstance(excluded, str) or not excluded or phases is not None:
                raise WorkClassificationError("excluded work item needs excludedReason and no phases")
            result.append({"id": item_id, "reference": reference, "excludedReason": excluded, "phases": []})
            continue
        if not isinstance(phases, list) or not phases:
            raise WorkClassificationError("work item needs non-empty phases")
        phase_ids, parsed = set(), []
        for phase in phases:
            required = {"id", "summary", "purpose", "requires", "executor"}
            optional = {"environment", "prerequisites", "acceptance", "handoffs"}
            if not isinstance(phase, dict) or not required <= set(phase) or set(phase) - required - optional:
                raise WorkClassificationError("phase has missing or unknown fields")
            phase = dict(phase)
            phase.setdefault("environment", {"ids": [], "mode": "normal"})
            phase.setdefault("prerequisites", [])
            phase.setdefault("acceptance", [])
            phase.setdefault("handoffs", [])
            phase_id = phase["id"]
            if not isinstance(phase_id, str) or not phase_id or phase_id in phase_ids:
                raise WorkClassificationError("phase needs unique id")
            phase_ids.add(phase_id)
            if not isinstance(phase["summary"], str) or not phase["summary"]:
                raise WorkClassificationError("phase summary must be a non-empty string")
            if not isinstance(phase["purpose"], str) or phase["purpose"] not in environment_inventory.PURPOSES:
                raise WorkClassificationError("phase has unknown purpose")
            _strings(phase["requires"], "phase requires")
            env = phase["environment"]
            if not isinstance(env, dict) or set(env) - {"ids", "mode"}:
                raise WorkClassificationError("phase environment has invalid fields")
            env.setdefault("ids", [])
            env.setdefault("mode", "normal")
            _strings(env["ids"], "phase environment.ids")
            if not isinstance(env["mode"], str) or env["mode"] not in {"normal", "construction", "repair"}:
                raise WorkClassificationError("phase environment mode is invalid")
            executor = phase["executor"]
            if not isinstance(executor, dict) or set(executor) - {"kind", "state", "required"} or not {"kind", "state"} <= set(executor):
                raise WorkClassificationError("phase executor has invalid fields")
            if not isinstance(executor["kind"], str) or not isinstance(executor["state"], str) or executor["kind"] not in EXECUTOR_KINDS or executor["state"] not in EXECUTOR_STATES or ("required" in executor and type(executor["required"]) is not bool):
                raise WorkClassificationError("phase executor has invalid kind, state, or required")
            for field in ("prerequisites", "acceptance", "handoffs"):
                _strings(phase[field], "phase " + field)
            parsed.append(phase)
        result.append({"id": item_id, "reference": reference, "phases": parsed})
    return result


def _capabilities(environment):
    return environment["capabilities"]


def _readiness(phase, record):
    state = phase["executor"]["state"]
    notes = []
    if state != "ready":
        notes.append("executor is " + state)
    unverified = [ref["source"] for ref in record.get("refs", []) if ref.get("resolution") != "resolved"]
    if unverified:
        notes.append("unverified catalog source: " + ", ".join(unverified))
    if state in {"hold", "waiting", "unspecified"}:
        value = state
    elif unverified:
        value = "unverified"
    else:
        value = "ready"
    return value, notes


def _eligible(phase, record):
    """Return eligibility separately from technical capability assessment."""
    unmet = []
    explicit = record["id"] in phase["environment"]["ids"]
    mode = phase["environment"]["mode"]
    if phase["purpose"] not in record["purposes"]:
        unmet.append("purpose %s is not declared" % phase["purpose"])
    if phase["environment"]["ids"] and not explicit:
        unmet.append("environment is not one of: " + ", ".join(phase["environment"]["ids"]))
    state = record["state"]
    if state == "active":
        pass
    elif state == "pending" and mode in {"construction", "repair"}:
        pass
    elif state == "retained" and explicit:
        pass
    else:
        unmet.append("environment state %s is not eligible for %s mode" % (state, mode))
    return not unmet, unmet


def _evaluate(phase, record):
    caps = _capabilities(record)
    reasons, preparation, unmet, evidence = [], [], [], {}
    eligible, eligibility_unmet = _eligible(phase, record)
    unmet.extend(eligibility_unmet)
    statuses = []
    for capability in phase["requires"]:
        value = caps.get(capability)
        if value is None:
            statuses.append("unknown")
            unmet.append("capability %s is undocumented" % capability)
            continue
        statuses.append(value["status"])
        reasons.append("%s: %s" % (capability, value["reason"]))
        evidence[capability] = value["evidence"]
        if value["status"] == "preparable": preparation.append("%s: %s" % (capability, value["preparation"]))
        elif value["status"] != "available": unmet.append("%s: %s" % (capability, value["reason"]))
    readiness, readiness_notes = _readiness(phase, record)
    unmet.extend(readiness_notes)
    if not eligible or any(status == "unavailable" for status in statuses):
        classification = "external-required"
    elif any(status == "unknown" for status in statuses):
        classification = "insufficient-information"
    elif any(status == "preparable" for status in statuses):
        classification = "preparable"
    else:
        classification = "available"
    return {"environment": record["id"], "eligible": eligible, "candidate": eligible and "unavailable" not in statuses, "classification": classification, "reasons": reasons, "evidence": evidence, "preparation": preparation, "unmetConditions": unmet, "readiness": readiness}


def classify(catalog_path, work_path, prefer_environment=None):
    work = load_work(work_path)
    try:
        catalog, _sources, records = environment_inventory.load_catalog(catalog_path)
    except environment_inventory.CatalogError as exc:
        raise WorkClassificationError(str(exc)) from None
    by_id = {record["id"]: record for record in records}
    if prefer_environment is not None and prefer_environment not in by_id:
        raise WorkClassificationError("unknown preferred environment: " + prefer_environment)
    known_ids = set(by_id)
    for item in work:
        for phase in item["phases"]:
            unknown_ids = set(phase["environment"]["ids"]) - known_ids
            if unknown_ids:
                raise WorkClassificationError("phase names unknown environment: " + ", ".join(sorted(unknown_ids)))
    output = []
    for item in work:
        rendered = {"id": item["id"], "reference": item["reference"]}
        if "excludedReason" in item:
            rendered["excludedReason"] = item["excludedReason"]
            rendered["phases"] = []
            output.append(rendered); continue
        rendered["phases"] = []
        for phase in item["phases"]:
            assessments = [_evaluate(phase, record) for record in records]
            rank = {"available": 0, "preparable": 1, "insufficient-information": 2, "external-required": 3}
            assessments.sort(key=lambda value: (0 if value["environment"] == prefer_environment else 1, rank[value["classification"]], value["environment"]))
            candidates = [value for value in assessments if value["candidate"]]
            feasible_rank = {"available": 0, "preparable": 1}
            feasible = [value for value in candidates if value["classification"] in feasible_rank]
            feasible.sort(key=lambda value: (feasible_rank[value["classification"]], 0 if value["environment"] == prefer_environment else 1, value["environment"]))
            proposed = feasible[0]["environment"] if feasible else None
            preferred = next((value for value in assessments if value["environment"] == prefer_environment), None)
            best = preferred["classification"] if preferred else (assessments[0]["classification"] if assessments else "insufficient-information")
            rendered["phases"].append({"id": phase["id"], "summary": phase["summary"], "purpose": phase["purpose"], "requires": phase["requires"], "environment": phase["environment"], "executor": phase["executor"], "prerequisites": phase["prerequisites"], "acceptance": phase["acceptance"], "handoffs": phase["handoffs"], "preferredEnvironment": prefer_environment, "proposedEnvironment": proposed, "classification": best, "candidates": candidates, "assessments": assessments})
        routes = [(phase["id"], phase["proposedEnvironment"]) for phase in rendered["phases"] if phase["proposedEnvironment"]]
        rendered["splitRequired"] = len({route for _phase, route in routes}) > 1
        rendered["handover"] = [
            {"fromPhase": prior["id"], "toPhase": following["id"], "fromEnvironment": prior["proposedEnvironment"], "toEnvironment": following["proposedEnvironment"], "contents": prior["handoffs"]}
            for prior, following in zip(rendered["phases"], rendered["phases"][1:])
            if prior["proposedEnvironment"] and following["proposedEnvironment"] and prior["proposedEnvironment"] != following["proposedEnvironment"]
        ]
        output.append(rendered)
    return output


def render_table(results):
    lines = ["work\tphase\tclassification\treadiness\tcandidates\treasons\tpreparation\tunmet conditions\tprerequisites\tsplit/handover"]
    for item in results:
        if item.get("excludedReason"):
            lines.append("%s\t-\texcluded\t-\t-\t-\t-\t%s\t-\t-" % (item["id"], item["excludedReason"]))
        for phase in item["phases"]:
            candidates = ", ".join("%s:%s/%s" % (x["environment"], x["classification"], x["readiness"]) for x in phase["candidates"]) or "none"
            selected = {phase["preferredEnvironment"], phase["proposedEnvironment"]}
            values = [value for value in phase["assessments"] if value["environment"] in selected or (value["candidate"] and value["classification"] == "insufficient-information")]
            if not values:
                values = phase["assessments"]
            readiness = ", ".join("%s:%s" % (x["environment"], x["readiness"]) for x in values)
            reasons = "; ".join("%s: %s" % (x["environment"], reason) for x in values for reason in x["reasons"]) or "-"
            preparation = "; ".join("%s: %s" % (x["environment"], value) for x in values for value in x["preparation"]) or "-"
            unmet = "; ".join("%s: %s" % (x["environment"], value) for x in values for value in x["unmetConditions"]) or "-"
            prerequisites = "; ".join(phase["prerequisites"]) or "-"
            handover = "split" if item.get("splitRequired") else "-"
            matching = [entry for entry in item.get("handover", []) if entry["fromPhase"] == phase["id"]]
            if matching:
                handover = "to %s: %s" % (matching[0]["toEnvironment"], "; ".join(matching[0]["contents"]) or "handover required")
            lines.append("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (item["id"], phase["id"], phase["classification"], readiness or "-", candidates, reasons, preparation, unmet, prerequisites, handover))
    return "\n".join(lines)

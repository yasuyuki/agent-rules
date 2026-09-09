"""Bounded lifecycle checks for one environment inventory record.

This module owns no placement data and performs no probes, starts, or repairs.
``place_module`` is deliberately injected so this public helper does not import
the command module which will eventually call it.
"""
from __future__ import annotations

import shutil
import hashlib
import importlib.util
from datetime import datetime
from pathlib import Path

_inventory_spec = importlib.util.spec_from_file_location(
    "environment_inventory", Path(__file__).with_name("environment_inventory.py")
)
environment_inventory = importlib.util.module_from_spec(_inventory_spec)
_inventory_spec.loader.exec_module(environment_inventory)


DEFAULT_SKILL = "maintain-environment-inventory"
DEFAULT_BINDING = "environment-inventory-required"


def _context(value):
    """Accept the stable named form as well as place.load_context's tuple."""
    if isinstance(value, dict):
        required = ("placement", "rules", "sites", "workspaces", "locations", "exceptions", "skills")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError("placement context is missing: " + ", ".join(missing))
        return value
    if isinstance(value, tuple) and len(value) >= 8:
        placement, rules, sites, workspaces, locations, exceptions, _selected, skills = value[:8]
        return {"placement": placement, "rules": rules, "sites": sites, "workspaces": workspaces,
                "locations": locations, "exceptions": exceptions, "skills": skills}
    raise ValueError("placement context must be a mapping or place.load_context tuple")


def _agent_value(reference, sources, placement):
    source = sources.get(reference.get("source"))
    if not source or source.get("unavailable"):
        return None
    field = reference.get("field")
    if source["definition"]["type"] == "json-pointer":
        return source["fields"].get(field)
    site = source["sites"].get(reference.get("site"))
    if not site:
        return None
    if field in site:
        return site[field]
    tool = reference.get("tool")
    if tool in placement["tools"]:
        return placement["tools"][tool]["configHome"]["default"].replace("$HOME", site["home"])
    return None


def _agent_sites(agent, sources):
    """Placement site IDs used by this agent, for narrowly scoped byte checks."""
    result = set()
    for key in ("principal", "configRoot"):
        reference = agent.get(key, {})
        source = sources.get(reference.get("source"), {})
        if source.get("definition", {}).get("type") == "placement-tsv" and reference.get("site"):
            result.add(reference["site"])
    return result


def _artifact_is_required(context, place_module, locations, artifact_id, kind):
    if kind == "skill":
        if artifact_id not in context["skills"]:
            return False
        files, _sections = place_module.expected_writes(
            context["rules"], context["placement"], locations, context["exceptions"],
            context["sites"], context["workspaces"], {artifact_id: context["skills"][artifact_id]},
        )
        return any(path.name == place_module.agent_rules.SKILL_MARKER and path.parent.name == artifact_id for path in files)
    matching = [rule for rule in context["rules"] if rule[0].get("id") == artifact_id]
    if not matching:
        return False
    files, sections = place_module.expected_writes(
        matching, context["placement"], locations, context["exceptions"], context["sites"],
        context["workspaces"], {},
    )
    return bool(files or sections)


def _sha256(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _evidence_errors(evidence, descriptor, skill_id, skill_sha256, binding_sha256, principal, config_root,
                     environment_id, declaration_sha256):
    seen = set()
    for item in evidence:
        if not isinstance(item, dict) or item.get("descriptor") != descriptor:
            continue
        try:
            observed = item.get("observedAt")
            if isinstance(observed, str):
                datetime.fromisoformat(observed.replace("Z", "+00:00"))
            else:
                raise ValueError
        except ValueError:
            continue
        record_path = item.get("record")
        if not isinstance(record_path, str) or not record_path:
            continue
        record = Path(record_path)
        try:
            if not record.is_file() or item.get("recordSha256") != _sha256(record.read_bytes()):
                continue
        except OSError:
            continue
        if (item.get("skillId") != skill_id or not item.get("observedAt") or
                not item.get("condition") or not item.get("record") or
                item.get("applied") is not True or item.get("skillSha256") != skill_sha256 or
                item.get("bindingSha256") != binding_sha256 or item.get("principal") != principal or
                item.get("configRoot") != config_root or item.get("environmentId") != environment_id or
                item.get("declarationSha256") != declaration_sha256):
            continue
        if item.get("session") in {"continuing", "startup"}:
            seen.add(item["session"])
    return ["%s: missing initial skill-reading evidence for %s session" % (descriptor, session)
            for session in ("continuing", "startup") if session not in seen]


def validate_lifecycle(catalog_path, placement_context, environment_id, mode="normal", *,
                       place_module, resolver=shutil.which, current_principal=None,
                       required_skill_id=DEFAULT_SKILL, required_binding_id=DEFAULT_BINDING,
                       session_evidence=None, declaration_path=None, constructing_agent=None):
    """Validate one environment before normal start or construction work.

    Resolver is called only for a local runtime agent and receives its placement
    entrypoint.  A foreign principal is deliberately an error, rather than an
    excuse to inspect the caller's PATH as if it represented that runtime.
    """
    if mode not in {"normal", "construction"}:
        raise ValueError("mode must be 'normal' or 'construction'")
    context = _context(placement_context)
    errors, records = environment_inventory.check_catalog(catalog_path, environment_id=environment_id)
    if errors or not records:
        return errors, records[0] if records else None
    record = records[0]
    state = record["state"]
    if mode == "normal" and state != "active":
        errors.append("%s: normal lifecycle requires active state (found %s)" % (environment_id, state))
    if mode == "construction" and state not in {"pending", "active"}:
        errors.append("%s: construction lifecycle cannot validate state %s" % (environment_id, state))
    evidence = [] if session_evidence is None else session_evidence
    if not isinstance(evidence, list):
        errors.append("%s: sessionEvidence must be an array" % environment_id)
        evidence = []

    _catalog, sources, _all_records = environment_inventory.load_catalog(catalog_path, environment_id=environment_id)
    declaration_sha256 = _sha256(Path(declaration_path).read_bytes()) if declaration_path is not None and Path(declaration_path).is_file() else None
    raw_environment = next(item for item in _catalog["environments"] if item["id"] == environment_id)
    raw_agents = {item["descriptor"]: item for item in raw_environment["agents"]}
    if not record["agents"]:
        errors.append("%s: active lifecycle has no registered agents" % environment_id)
    binding_rules = [rule for rule in context["rules"] if rule[0].get("id") == required_binding_id]
    skill = context["skills"].get(required_skill_id)
    skill_bytes = skill.get("SKILL.md") if isinstance(skill, dict) else None
    binding_bytes = binding_rules[0][1] if binding_rules else None
    if not isinstance(skill_bytes, bytes) or binding_bytes is None:
        # The per-agent placement errors explain which source is absent too.
        skill_sha256 = binding_sha256 = None
    else:
        skill_sha256, binding_sha256 = _sha256(skill_bytes), _sha256(binding_bytes)
    agents_to_check = record["agents"]
    if mode == "construction" and constructing_agent is not None:
        agents_to_check = [agent for agent in record["agents"] if agent["descriptor"] == constructing_agent]
        if not agents_to_check:
            errors.append("%s: constructing agent %s is not registered" % (environment_id, constructing_agent))
    for agent in agents_to_check:
        descriptor = agent["descriptor"]
        raw_agent = raw_agents[descriptor]
        tool = context["placement"]["tools"].get(descriptor)
        if tool is None:
            errors.append("%s: unknown registered agent descriptor %s" % (environment_id, descriptor))
            continue
        principal = agent["principal"]
        config_root = agent["configRoot"]
        if not isinstance(principal, str) or not isinstance(config_root, str):
            errors.append("%s: %s runtime principal or config root is unverified" % (environment_id, descriptor))
            continue
        agent_sites = _agent_sites(raw_agent, sources)
        source = sources.get(raw_agent["principal"].get("source"), {})
        if (raw_agent["principal"].get("source") != raw_agent["configRoot"].get("source") or
                raw_agent["principal"].get("site") != raw_agent["configRoot"].get("site")):
            errors.append("%s: %s principal and config root must share catalog source and site" % (environment_id, descriptor))
            # Do not turn a malformed cross-runtime reference into a local PATH probe.
            return errors, record
        if declaration_path is None:
            errors.append("%s: %s declaration identity is unverified" % (environment_id, descriptor))
            return errors, record
        elif source.get("path") is None or Path(source["path"]).resolve() != Path(declaration_path).resolve():
            errors.append("%s: %s catalog source does not match placement declaration" % (environment_id, descriptor))
            return errors, record
        site = next((context["sites"].get(site_id) for site_id in agent_sites if site_id in context["sites"]), None)
        expected_runtime = {"user": principal, "home": site.get("home") if site else None,
                            "host": site.get("host") if site else None}
        host_matches = (isinstance(current_principal, dict) and
                        (current_principal.get("host") == expected_runtime["host"] or
                         (expected_runtime["host"] == "Linux" and current_principal.get("platform") == "Linux")))
        if (not isinstance(current_principal, dict) or
                any(current_principal.get(key) != value for key, value in expected_runtime.items() if key != "host") or not host_matches or
                current_principal.get("configRoots", {}).get(descriptor) != config_root):
            errors.append("%s: %s runtime principal %r is unverified from current runtime %r" %
                          (environment_id, descriptor, expected_runtime, current_principal))
        elif not resolver(tool["entrypoint"]):
            errors.append("%s: %s CLI does not resolve for runtime principal %s" %
                          (environment_id, descriptor, principal))

        all_locations = context["locations"].values() if isinstance(context["locations"], dict) else context["locations"]
        selected = [location for location in all_locations
                    if location.get("tool") == descriptor and
                    place_module.site_of(location, context["workspaces"]) in agent_sites]
        if not selected:
            errors.append("%s: %s has no declared managed placement location" % (environment_id, descriptor))
            continue
        if not _artifact_is_required(context, place_module, selected, required_skill_id, "skill"):
            errors.append("%s: %s does not require skill %s" % (environment_id, descriptor, required_skill_id))
        if not _artifact_is_required(context, place_module, selected, required_binding_id, "binding"):
            errors.append("%s: %s does not require binding %s" % (environment_id, descriptor, required_binding_id))
        placement_errors, _printed = place_module.check_state(
            context["rules"], context["placement"], selected, context["exceptions"], context["sites"],
            context["workspaces"], context["locations"], context["skills"], check_installed=False,
        )
        errors.extend("%s: %s" % (descriptor, error) for error in placement_errors)
        if state == "active":
            errors.extend(_evidence_errors(evidence, descriptor, required_skill_id, skill_sha256, binding_sha256, principal, config_root, environment_id, declaration_sha256))
    # A supported CLI visible in this runtime is an installation fact.  It must
    # be registered for this environment; no arbitrary filesystem discovery is
    # attempted.
    local_site = next((site for site in context["sites"].values() if isinstance(current_principal, dict) and
                       all(current_principal.get(key) == site.get(key) for key in ("user", "home")) and
                       (current_principal.get("host") == site.get("host") or
                        (site.get("host") == "Linux" and current_principal.get("platform") == "Linux"))), None)
    if local_site and mode == "normal":
        registered = {agent["descriptor"] for agent in record["agents"]}
        for descriptor, tool in context["placement"]["tools"].items():
            if descriptor not in registered and (resolver(tool["entrypoint"]) or place_module.detect_cli(local_site, tool)):
                errors.append("%s: installed supported CLI %s is unregistered" % (environment_id, descriptor))
    return errors, record

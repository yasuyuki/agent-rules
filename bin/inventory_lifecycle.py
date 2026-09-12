"""Bounded lifecycle checks for one environment inventory record.

This module owns no placement data and performs no probes, starts, or repairs.
``place_module`` is deliberately injected so this public helper does not import
the command module which will eventually call it.
"""
from __future__ import annotations

import shutil
import importlib.util
import os
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


def _declared_placement_sites(environment, sources, declaration_path):
    """Return the environment's explicit sites from this declaration only."""
    result = set()
    for reference in environment_inventory._environment_refs(environment):
        if not isinstance(reference, dict):
            continue
        source = sources.get(reference.get("source"), {})
        if (source.get("definition", {}).get("type") != "placement-tsv" or
                source.get("path") is None or
                Path(source["path"]).resolve() != Path(declaration_path).resolve()):
            continue
        site_id = reference.get("site")
        if site_id in source.get("sites", {}):
            result.add(site_id)
    return result


def _managed_config_root(placement, descriptor, site):
    return placement["tools"][descriptor]["configHome"]["default"].replace("$HOME", site["home"])


def _same_path(left, right):
    return isinstance(left, str) and isinstance(right, str) and os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


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


def validate_lifecycle(catalog_path, placement_context, environment_id, mode="readiness", *,
                       place_module, resolver=shutil.which, current_principal=None,
                       required_skill_id=DEFAULT_SKILL, required_binding_id=DEFAULT_BINDING,
                       declaration_path=None, constructing_agent=None, target_agent=None,
                       required_site=None, runtime_state=None):
    """Validate one environment's placement readiness or one normal CLI start.

    Resolver is called only for a local runtime agent and receives its placement
    entrypoint.  A foreign principal is deliberately an error, rather than an
    excuse to inspect the caller's PATH as if it represented that runtime.
    """
    if mode not in {"normal", "readiness", "construction"}:
        raise ValueError("mode must be 'normal', 'readiness', or 'construction'")
    context = _context(placement_context)
    target_only = mode == "normal"
    errors, records = environment_inventory.check_catalog(
        catalog_path, environment_id=environment_id,
        agent_descriptor=target_agent if target_only else None,
        site_id=required_site if target_only else None,
    )
    if errors or not records:
        return errors, records[0] if records else None
    record = records[0]
    state = record["state"]
    if runtime_state is not None:
        if runtime_state not in {'pending', 'active'}:
            raise ValueError('invalid runtime adoption state')
        if state in {'pending', 'active'}:
            state = runtime_state
    if mode == "normal" and state != "active":
        errors.append("%s: normal lifecycle requires active state (found %s)" % (environment_id, state))
    if mode in {"readiness", "construction"} and state not in {"pending", "active"}:
        errors.append("%s: readiness or construction cannot validate state %s" % (environment_id, state))

    _catalog, sources, _all_records = environment_inventory.load_catalog(
        catalog_path, environment_id=environment_id,
        agent_descriptor=target_agent if target_only else None,
        site_id=required_site if target_only else None,
    )
    raw_environment = next(item for item in _catalog["environments"] if item["id"] == environment_id)
    if required_site is not None and required_site not in _declared_placement_sites(
            raw_environment, sources, declaration_path):
        errors.append("%s: selected site %s is not an explicit environment reference" %
                      (environment_id, required_site))
        return errors, record
    raw_agents = {item["descriptor"]: item for item in raw_environment["agents"]}
    if not record["agents"]:
        errors.append("%s: active lifecycle has no registered agents" % environment_id)
    agents_to_check = record["agents"]
    if mode == "normal":
        agents_to_check = [agent for agent in record["agents"] if agent["descriptor"] == target_agent]
        if not agents_to_check:
            errors.append("%s: target agent %s is not registered" % (environment_id, target_agent))
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
        config_source = sources.get(raw_agent["configRoot"].get("source"), {})
        if (raw_agent["principal"].get("source") != raw_agent["configRoot"].get("source") or
                raw_agent["principal"].get("site") != raw_agent["configRoot"].get("site")):
            errors.append("%s: %s principal and config root must share catalog source and site" % (environment_id, descriptor))
            # Do not turn a malformed cross-runtime reference into a local PATH probe.
            return errors, record
        if declaration_path is None:
            errors.append("%s: %s declaration identity is unverified" % (environment_id, descriptor))
            return errors, record
        if source.get("definition", {}).get("type") == "placement-tsv" and (
                source.get("path") is None or Path(source["path"]).resolve() != Path(declaration_path).resolve()):
            errors.append("%s: %s catalog source does not match placement declaration" % (environment_id, descriptor))
            return errors, record
        if source.get("definition", {}).get("type") == "json-pointer" and config_source.get("definition", {}).get("type") == "json-pointer":
            agent_sites = {
                site_id for site_id in _declared_placement_sites(raw_environment, sources, declaration_path)
                if site_id in context["sites"] and context["sites"][site_id].get("user") == principal and
                _same_path(_managed_config_root(context["placement"], descriptor, context["sites"][site_id]), config_root)
            }
            if len(agent_sites) != 1:
                errors.append("%s: %s JSON runtime values do not match one explicitly referenced placement site" %
                              (environment_id, descriptor))
                # The source is foreign to the caller, so never fall through to
                # local CLI discovery after a failed runtime identity check.
                return errors, record
        if len(agent_sites) != 1:
            errors.append("%s: %s runtime values do not identify one declared placement site" %
                          (environment_id, descriptor))
            return errors, record
        site_id = next(iter(agent_sites))
        if required_site is not None and site_id != required_site:
            errors.append("%s: %s references placement site %s, not selected site %s" %
                          (environment_id, descriptor, site_id, required_site))
            continue
        site = context["sites"].get(site_id)
        if site is None:
            errors.append("%s: %s placement site is absent from the active declaration" % (environment_id, descriptor))
            return errors, record
        managed_config_root = _managed_config_root(context["placement"], descriptor, site)
        if not _same_path(config_root, managed_config_root):
            errors.append("%s: %s effective config root %r does not match managed root %r" %
                          (environment_id, descriptor, config_root, managed_config_root))
            return errors, record
        if mode in {"normal", "readiness", "construction"}:
            expected_runtime = {"user": principal, "home": site.get("home") if site else None,
                                "host": site.get("host") if site else None}
            host_matches = (isinstance(current_principal, dict) and
                            (current_principal.get("host") == expected_runtime["host"] or
                             (expected_runtime["host"] == "Linux" and current_principal.get("platform") == "Linux")))
            if (not isinstance(current_principal, dict) or
                    current_principal.get("user") != principal or
                    not _same_path(current_principal.get("home"), expected_runtime["home"]) or not host_matches or
                    not _same_path(current_principal.get("configRoots", {}).get(descriptor), config_root)):
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
    # A supported CLI visible in this runtime is an installation fact.  It must
    # be registered for this environment; no arbitrary filesystem discovery is
    # attempted.
    local_site = next((site for site in context["sites"].values() if isinstance(current_principal, dict) and
                       current_principal.get("user") == site.get("user") and
                       _same_path(current_principal.get("home"), site.get("home")) and
                       (current_principal.get("host") == site.get("host") or
                        (site.get("host") == "Linux" and current_principal.get("platform") == "Linux"))), None)
    if local_site and mode == "readiness":
        registered = {agent["descriptor"] for agent in record["agents"]}
        for descriptor, tool in context["placement"]["tools"].items():
            if descriptor not in registered and (resolver(tool["entrypoint"]) or place_module.detect_cli(local_site, tool)):
                errors.append("%s: installed supported CLI %s is unregistered" % (environment_id, descriptor))
    return errors, record

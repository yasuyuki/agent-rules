"""Read and validate a private environment inventory without owning its data.

The public format deliberately contains references rather than copied machine
settings.  Version 1 accepts placement TSV sources and JSON sources whose
values are selected by JSON Pointer.  It is safe to import this module from a
launcher: ``check_catalog`` performs no writes and probing is opt-in.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path


PURPOSES = {"normal-development", "rule-experiment", "product-development", "operator", "recovery"}
STATES = {"pending", "active", "retained", "retired", "unclassified"}
CAPABILITY_STATES = {"available", "preparable", "unavailable", "unknown"}
TOOL_CONFIG_HOMES = json.loads((Path(__file__).resolve().parents[1] / "placement.json").read_text(encoding="utf-8"))["tools"]


class CatalogError(RuntimeError):
    pass


def validate_capabilities(value, environment_id="?"):
    """Validate optional, declarative capability metadata without probing it."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise CatalogError("environment %s capabilities must be an object" % environment_id)
    result = {}
    for capability_id, item in value.items():
        if not isinstance(capability_id, str) or not capability_id or not isinstance(item, dict) or set(item) - {"status", "reason", "evidence", "preparation"}:
            raise CatalogError("environment %s has invalid capability" % environment_id)
        if not isinstance(item.get("status"), str) or item["status"] not in CAPABILITY_STATES or not isinstance(item.get("reason"), str) or not item["reason"]:
            raise CatalogError("environment %s capability needs status and reason" % environment_id)
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or any(not isinstance(entry, str) or not entry for entry in evidence):
            raise CatalogError("environment %s capability needs evidence strings" % environment_id)
        if "preparation" in item and (not isinstance(item["preparation"], str) or not item["preparation"]):
            raise CatalogError("environment %s capability preparation must be a non-empty string" % environment_id)
        if item["status"] == "preparable" and "preparation" not in item:
            raise CatalogError("environment %s preparable capability needs preparation" % environment_id)
        result[capability_id] = dict(item)
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _tsv(text, name):
    import re
    match = re.search(r"<!-- BEGIN %s TSV -->\s*```tsv\n(.*?)```\s*<!-- END %s TSV -->" % (re.escape(name), re.escape(name)), text, re.S)
    if not match:
        raise CatalogError("missing %s TSV" % name)
    lines = [line.rstrip("\r") for line in match.group(1).splitlines() if line]
    if not lines:
        return []
    fields = lines[0].split("\t")
    result = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) < len(fields):
            values.extend([""] * (len(fields) - len(values)))
        if len(values) != len(fields):
            raise CatalogError("malformed %s TSV row" % name)
        result.append(dict(zip(fields, values)))
    return result


def _pointer(value, pointer):
    if pointer == "":
        return value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise CatalogError("invalid JSON Pointer: %r" % pointer)
    current = value
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, ValueError, TypeError):
            raise CatalogError("JSON Pointer does not resolve: %s" % pointer) from None
    return current


def _parse_source(source_id, source, path, raw):
    kind = source["type"]
    if kind == "placement-tsv":
        site_rows, workspace_rows = _tsv(raw, "SITES"), _tsv(raw, "WORKSPACES")
        if len({x["id"] for x in site_rows}) != len(site_rows) or len({x["id"] for x in workspace_rows}) != len(workspace_rows):
            raise CatalogError("source %s has duplicate placement IDs" % source_id)
        return {"definition": source, "path": path, "sites": {x["id"]: x for x in site_rows}, "workspaces": {x["id"]: x for x in workspace_rows}}
    try:
        document = json.loads(raw, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise CatalogError("source %s is not JSON: %s" % (source_id, exc)) from None
    pointers = source.get("pointers", source.get("fields", {}))
    if not isinstance(pointers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in pointers.items()):
        raise CatalogError("JSON source %s needs string pointers" % source_id)
    if any(any(word in pointer.lower() for word in ("auth", "credential", "secret", "token", "profile", "password")) for pointer in pointers.values()):
        raise CatalogError("JSON source %s pointer may expose authentication data" % source_id)
    fields = {key: _pointer(document, pointer) for key, pointer in pointers.items()}
    if any(not isinstance(value, (str, int, float, bool, type(None))) and not (isinstance(value, list) and all(isinstance(x, (str, int, float, bool, type(None))) for x in value)) for value in fields.values()):
        raise CatalogError("JSON source %s pointer exposes a structured value" % source_id)
    return {"definition": source, "path": path, "document": document, "fields": fields}


def _ssh_probe_config(probe, observer):
    paths = probe.get("configPaths")
    if not isinstance(paths, dict):
        return probe
    path = paths.get(observer, paths.get("default"))
    if not isinstance(path, str) or not Path(path).is_file():
        return None
    allowed = {"hostname", "port", "user", "identityfile", "userknownhostsfile", "identitiesonly", "stricthostkeychecking", "forwardagent", "batchmode", "connecttimeout"}
    values, matched = {}, False
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line: continue
        key, _, value = line.partition(" ")
        key = key.lower()
        value = value.strip()
        if any(character in value for character in ("%", "'", '"', "\\")):
            raise CatalogError("SSH probe config contains unsupported value syntax")
        if key in {"match", "include", "proxycommand", "proxyjump", "localcommand", "remotecommand"}:
            raise CatalogError("SSH probe config contains unsupported %s" % key)
        if key == "host":
            # The probe is deliberately not a general-purpose OpenSSH config
            # interpreter.  Accept only exact repeated blocks for this alias,
            # then apply OpenSSH's first-value-wins rule.  A wildcard, a
            # second alias, or a global directive could select values that our
            # explicit ``ssh -F /dev/null`` invocation would not reproduce.
            target = probe.get("target")
            if not isinstance(target, str) or value.casefold() != target.casefold():
                raise CatalogError("SSH probe config contains unsupported Host pattern")
            matched = True
            continue
        if not matched:
            raise CatalogError("SSH probe config contains unsupported global directive %s" % key)
        if key not in allowed: raise CatalogError("SSH probe config contains unsupported %s" % key)
        values.setdefault(key, value)
    if not matched:
        return None
    result = dict(probe)
    result.update({"target": values.get("hostname", probe.get("target")), "user": values.get("user", probe.get("user")), "port": values.get("port", probe.get("port")), "identityFile": values.get("identityfile", probe.get("identityFile")), "knownHosts": values.get("userknownhostsfile", probe.get("knownHosts")), "connectTimeout": values.get("connecttimeout", probe.get("connectTimeout"))})
    return {key: value for key, value in result.items() if value is not None}


def _explicit_ssh_argv(probe, observer):
    probe = _ssh_probe_config(probe, observer)
    if probe is None:
        return None
    if not isinstance(probe, dict) or probe.get("transport") != "ssh" or not isinstance(probe.get("target"), str) or not probe["target"] or probe["target"].startswith("-"):
        raise CatalogError("source probe needs an explicit non-option SSH target")
    argv = ["ssh", "-F", os.devnull, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", "-o", "ClearAllForwardings=yes", "-o", "PermitLocalCommand=no", "-o", "ControlMaster=no"]
    for key, option in (("user", "User"), ("port", "Port"), ("identityFile", "IdentityFile"), ("knownHosts", "UserKnownHostsFile"), ("connectTimeout", "ConnectTimeout")):
        value = probe.get(key)
        if value is not None:
            if not isinstance(value, (str, int)) or not str(value): raise CatalogError("source probe has invalid %s" % key)
            argv += ["-o", "%s=%s" % (option, value)]
    return argv + ["-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", probe["target"]]


def _sources(catalog_path, catalog, *, probe=False, runner=subprocess.run):
    source_items = catalog.get("sources")
    if not isinstance(source_items, dict) or not source_items:
        raise CatalogError("sources must be a non-empty object keyed by stable ID")
    result = {}
    for source_id, source in source_items.items():
        if not isinstance(source_id, str) or not source_id or not isinstance(source, dict):
            raise CatalogError("invalid source")
        kind = source.get("type")
        host = source.get("host")
        paths = source.get("paths", {})
        if kind not in {"placement-tsv", "json-pointer"} or not isinstance(host, str) or not host or not isinstance(paths, dict):
            raise CatalogError("source %s needs type, source host, and host-keyed paths" % source_id)
        if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
               for key, value in paths.items()):
            raise CatalogError("source %s paths must map host IDs to non-empty strings" % source_id)
        if kind == "json-pointer":
            pointers = source.get("pointers")
            if not isinstance(pointers, dict) or not pointers or any(
                    not isinstance(key, str) or not key or not isinstance(value, str) or not value.startswith("/")
                    for key, value in pointers.items()):
                raise CatalogError("JSON source %s needs explicit named JSON Pointers" % source_id)
        observer = os.environ.get("ENVIRONMENT_INVENTORY_HOST") or ("windows" if os.name == "nt" else "linux")
        path = paths.get(observer, paths.get("default"))
        if not isinstance(path, str):
            remote_path, source_probe = source.get("path"), source.get("probe")
            if probe and isinstance(remote_path, str) and source_probe is not None:
                if not remote_path.startswith("/") or "\x00" in remote_path:
                    raise CatalogError("source %s has invalid remote path" % source_id)
                try:
                    ssh_argv = _explicit_ssh_argv(source_probe, observer)
                    if ssh_argv is None:
                        result[source_id] = {"definition": source, "path": remote_path, "unavailable": "SSH probe config is not locally readable"}
                        continue
                    read = runner(ssh_argv + ["cat -- " + shlex.quote(remote_path)], text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
                except OSError as exc:
                    result[source_id] = {"definition": source, "path": remote_path, "unavailable": "remote source probe unavailable: %s" % exc}
                    continue
                if read.returncode:
                    result[source_id] = {"definition": source, "path": remote_path, "unavailable": "remote source probe failed"}
                    continue
                result[source_id] = _parse_source(source_id, source, remote_path, read.stdout)
                result[source_id]["probed"] = True
                continue
            result[source_id] = {"definition": source, "path": source.get("path"), "unavailable": "no readable path for observer %s" % observer}
            continue
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = catalog_path.parent / file_path
        if not file_path.is_file():
            result[source_id] = {"definition": source, "path": str(file_path), "unavailable": "source is not locally readable"}
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            result[source_id] = {"definition": source, "path": str(file_path), "unavailable": "source read failed: %s" % exc}
            continue
        result[source_id] = _parse_source(source_id, source, str(file_path), raw)
    return result


def _candidate(state, purposes, requested):
    match = not requested or requested in purposes
    if not match:
        return False, "purpose does not match"
    if state == "active": return True, "active purpose match"
    if state == "pending": return False, "pending: construction or repair only"
    if state == "retained": return False, "retained: explicit user selection required"
    return False, "%s environments are not candidates" % state


def _agent_value(reference, sources):
    source = sources[reference["source"]]
    if source.get("unavailable"):
        return None, "unverified: " + source["unavailable"]
    if source["definition"]["type"] == "json-pointer":
        return source["fields"][reference["field"]], "resolved"
    site = source["sites"][reference["site"]]
    if "tool" in reference:
        template = TOOL_CONFIG_HOMES[reference["tool"]]["configHome"]["default"]
        return template.replace("$HOME", site["home"]), "resolved"
    return site[reference["field"]], "resolved"


def _environment_refs(item):
    refs = item.get("refs")
    if refs is None:
        return [{"source": item.get("source"), "site": item.get("site"), "workspace": item.get("workspace"), "fields": item.get("references", {})}]
    return refs


def _referenced_source_ids(environments):
    """Return every source that influences selected catalog environments."""
    source_ids = set()
    for item in environments:
        if not isinstance(item, dict):
            continue
        refs = _environment_refs(item)
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if isinstance(ref, dict) and isinstance(ref.get("source"), str):
                source_ids.add(ref["source"])
        for agent in item.get("agents", []):
            if not isinstance(agent, dict):
                continue
            for key in ("principal", "configRoot"):
                reference = agent.get(key)
                if isinstance(reference, dict) and isinstance(reference.get("source"), str):
                    source_ids.add(reference["source"])
        entrypoint = item.get("entrypoint")
        if isinstance(entrypoint, dict) and isinstance(entrypoint.get("source"), str):
            source_ids.add(entrypoint["source"])
        connection = item.get("connection")
        if isinstance(connection, dict):
            if isinstance(connection.get("source"), str):
                source_ids.add(connection["source"])
            distro = connection.get("distro")
            if isinstance(distro, dict) and isinstance(distro.get("source"), str):
                source_ids.add(distro["source"])
    return source_ids


def load_catalog(path, purpose=None, *, probe=False, runner=subprocess.run, environment_id=None):
    catalog_path = Path(path)
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError("cannot read catalog: %s" % exc) from None
    if not isinstance(catalog, dict) or type(catalog.get("schemaVersion")) is not int or catalog.get("schemaVersion") != 1:
        raise CatalogError("catalog schemaVersion must be 1")
    if purpose is not None and purpose not in PURPOSES:
        raise CatalogError("unknown purpose: %s" % purpose)
    environments = catalog.get("environments")
    if not isinstance(environments, list):
        raise CatalogError("environments must be an array")
    if not isinstance(catalog.get("sources"), dict):
        raise CatalogError("sources must be an object")
    if environment_id is not None:
        environments = [item for item in environments if isinstance(item, dict) and item.get("id") == environment_id]
        if not environments:
            raise CatalogError("unknown environment: %s" % environment_id)
        needed = _referenced_source_ids(environments)
        catalog = dict(catalog)
        catalog["sources"] = {key: value for key, value in catalog["sources"].items() if key in needed}
        catalog["environments"] = environments
    sources = _sources(catalog_path, catalog, probe=probe, runner=runner)
    ids, resolved = set(), []
    for item in environments:
        if not isinstance(item, dict): raise CatalogError("environment must be an object")
        env_id, state, purposes = item.get("id"), item.get("state"), item.get("purposes")
        if not isinstance(env_id, str) or not env_id or env_id in ids: raise CatalogError("environment IDs must be unique and non-empty")
        ids.add(env_id)
        capabilities = validate_capabilities(item.get("capabilities", {}), env_id)
        if state not in STATES: raise CatalogError("environment %s has invalid state" % env_id)
        if not isinstance(purposes, list) or any(x not in PURPOSES for x in purposes) or (not purposes and state != "unclassified"):
            raise CatalogError("environment %s has invalid purposes" % env_id)
        refs = _environment_refs(item)
        if not isinstance(refs, list) or not refs: raise CatalogError("environment %s needs non-empty refs" % env_id)
        resolved_refs = []
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("source") not in sources: raise CatalogError("environment %s names unknown source" % env_id)
            source_id, source = ref["source"], sources[ref["source"]]
            if not isinstance(ref.get("fields", {}), dict): raise CatalogError("environment %s fields must be an object" % env_id)
            site = workspace = None
            if source.get("unavailable"):
                resolved_refs.append({"source": source_id, "sourceHost": source["definition"]["host"], "sourcePath": source["path"], "site": None, "workspace": None, "fields": ref.get("fields", {}), "values": {}, "resolution": "unverified: " + source["unavailable"]})
                continue
            if source["definition"]["type"] == "placement-tsv":
                site_id, workspace_id = ref.get("site"), ref.get("workspace")
                if site_id not in source["sites"]: raise CatalogError("environment %s names unknown site" % env_id)
                site = source["sites"][site_id]
                if workspace_id is not None:
                    if workspace_id not in source["workspaces"] or source["workspaces"][workspace_id].get("site") != site_id: raise CatalogError("environment %s workspace does not belong to site" % env_id)
                    workspace = source["workspaces"][workspace_id]
            else:
                fields = ref.get("fields", {})
                if not isinstance(fields, dict) or any(value not in source["fields"] for value in fields.values()): raise CatalogError("environment %s names unknown JSON field" % env_id)
            fields = ref.get("fields", {})
            values = {name: source["fields"][field] for name, field in fields.items()} if source["definition"]["type"] == "json-pointer" else {}
            all_workspaces = [row for row in source.get("workspaces", {}).values() if site and row.get("site") == site.get("id")]
            resolved_refs.append({"source": source_id, "sourceHost": source["definition"]["host"], "sourcePath": source["path"], "site": site, "workspace": workspace, "siteWorkspaces": all_workspaces, "fields": fields, "values": values, "resolution": "resolved"})
        agents = item.get("agents", [])
        if not isinstance(agents, list): raise CatalogError("environment %s agents must be an array" % env_id)
        for agent in agents:
            if not isinstance(agent, dict) or not isinstance(agent.get("descriptor"), str): raise CatalogError("environment %s has invalid agent descriptor" % env_id)
            for key in ("principal", "configRoot"):
                value = agent.get(key)
                if not isinstance(value, dict) or value.get("source") not in sources: raise CatalogError("environment %s has invalid agent %s reference" % (env_id, key))
                agent_source = sources[value["source"]]
                if "tool" in value and (key != "configRoot" or "field" in value or value["tool"] not in TOOL_CONFIG_HOMES):
                    raise CatalogError("environment %s has invalid derived config root reference" % env_id)
                if agent_source.get("unavailable"):
                    continue
                if agent_source["definition"]["type"] == "json-pointer":
                    if value.get("field") not in agent_source["fields"]: raise CatalogError("environment %s has invalid agent %s reference" % (env_id, key))
                elif value.get("site") not in agent_source["sites"] or not isinstance(value.get("field"), str) or value["field"] not in agent_source["sites"][value["site"]]:
                    # configRoot may be derived from the public tool convention
                    # and the placement site's home; it must never be copied
                    # into the private catalog as a machine-specific value.
                    if not (key == "configRoot" and value.get("site") in agent_source["sites"] and value.get("tool") in TOOL_CONFIG_HOMES):
                        raise CatalogError("environment %s has invalid placement agent %s reference" % (env_id, key))
        entrypoint = item.get("entrypoint")
        if entrypoint is not None:
            if not isinstance(entrypoint, dict) or entrypoint.get("kind") not in {"placement-start", "apparatus"}:
                raise CatalogError("environment %s has invalid entrypoint" % env_id)
            if entrypoint["kind"] == "placement-start":
                entry_source = sources.get(entrypoint.get("source"))
                if not entry_source or not isinstance(entrypoint.get("workspace"), str):
                    raise CatalogError("environment %s has invalid placement entrypoint" % env_id)
                if entry_source.get("unavailable"):
                    entrypoint = dict(entrypoint)
                    entrypoint["resolution"] = "unverified: " + entry_source["unavailable"]
                else:
                    workspace = entry_source.get("workspaces", {}).get(entrypoint["workspace"])
                    ref_sites = {ref["site"]["id"] for ref in resolved_refs if ref["source"] == entrypoint["source"] and ref.get("site")}
                    if workspace is None or workspace.get("site") not in ref_sites:
                        raise CatalogError("environment %s entrypoint workspace is not a referenced site" % env_id)
            if entrypoint["kind"] == "apparatus":
                paths = entrypoint.get("paths")
                if set(entrypoint) != {"kind", "paths"} or not isinstance(paths, dict) or not paths or not all(isinstance(key, str) and isinstance(value, str) and value for key, value in paths.items()):
                    raise CatalogError("environment %s apparatus entrypoint needs host-keyed paths" % env_id)
                observer = os.environ.get("ENVIRONMENT_INVENTORY_HOST") or ("windows" if os.name == "nt" else "linux")
                selected_path = paths.get(observer, paths.get("default"))
                if selected_path is None:
                    entrypoint = {"kind": "apparatus", "path": None, "resolution": "unverified: no path for observer %s" % observer}
                elif not Path(selected_path).is_file():
                    entrypoint = {"kind": "apparatus", "path": selected_path, "resolution": "unverified: entrypoint is not locally readable"}
                else:
                    entrypoint = {"kind": "apparatus", "path": selected_path, "resolution": "resolved"}
        connection = item.get("connection", {})
        if not isinstance(connection, dict): raise CatalogError("environment %s connection must be an object" % env_id)
        if "wslDistro" in connection and (connection.get("transport") != "ssh" or not isinstance(connection["wslDistro"], str) or not connection["wslDistro"]):
            raise CatalogError("environment %s has invalid outer WSL distro" % env_id)
        if connection.get("transport") == "ssh" and "source" in connection:
            connection_source = sources.get(connection["source"])
            source_probe = connection_source["definition"].get("probe") if connection_source else None
            if connection_source is None or not isinstance(source_probe, dict) or source_probe.get("transport") != "ssh":
                raise CatalogError("environment %s SSH connection must reference an SSH source probe" % env_id)
            connection = dict(connection)
            connection["sourceObserved"] = bool(connection_source.get("probed"))
        if connection.get("transport") == "wsl" and isinstance(connection.get("distro"), dict):
            distro_ref = connection["distro"]
            distro_source = sources.get(distro_ref.get("source"))
            if distro_source is None:
                raise CatalogError("environment %s has invalid WSL distro reference" % env_id)
            if distro_source["definition"]["type"] == "json-pointer":
                valid = isinstance(distro_ref.get("field"), str) and distro_ref["field"] in distro_source["definition"].get("pointers", {})
            else:
                if distro_source.get("unavailable"):
                    valid = isinstance(distro_ref.get("site"), str) and isinstance(distro_ref.get("field"), str) and bool(distro_ref["site"]) and bool(distro_ref["field"])
                else:
                    site = distro_source.get("sites", {}).get(distro_ref.get("site"))
                    valid = isinstance(distro_ref.get("field"), str) and isinstance(site, dict) and distro_ref["field"] in site
            if not valid:
                raise CatalogError("environment %s has invalid WSL distro reference" % env_id)
            connection = dict(connection)
            if distro_source.get("unavailable"):
                connection["distro"] = None
                connection["distroResolution"] = "unverified: " + distro_source["unavailable"]
            else:
                connection["distro"], _resolution = _agent_value(distro_ref, sources)
                if not isinstance(connection["distro"], str) or not connection["distro"]:
                    raise CatalogError("environment %s WSL distro reference must resolve to a non-empty string" % env_id)
        descriptors = [agent["descriptor"] for agent in agents]
        if len(descriptors) != len(set(descriptors)) or any(name not in TOOL_CONFIG_HOMES for name in descriptors):
            raise CatalogError("environment %s has duplicate or unknown agent descriptor" % env_id)
        resolved_agents = []
        for agent in agents:
            principal, principal_resolution = _agent_value(agent["principal"], sources)
            config_root, config_resolution = _agent_value(agent["configRoot"], sources)
            resolved_agents.append({"descriptor": agent["descriptor"], "principal": principal, "configRoot": config_root, "resolution": principal_resolution if principal_resolution != "resolved" else config_resolution})
        allowed, reason = _candidate(state, purposes, purpose)
        resolved.append({"id": env_id, "purposes": purposes, "state": state, "candidate": allowed, "candidateReason": reason, "capabilities": capabilities, "refs": resolved_refs, "entrypoint": entrypoint, "connection": connection, "agents": resolved_agents, "observation": {"installed": None, "running": None, "reachable": None, "reason": "unverified: pass --probe for observational state"}})
    return catalog, sources, resolved


def _wsl_names(output):
    # wsl.exe emits UTF-16LE through a pipe, including for non-ASCII names.
    if isinstance(output, bytes):
        output = output.decode("utf-16" if output.startswith((b"\xff\xfe", b"\xfe\xff"))
                               else "utf-16-le" if b"\x00" in output else "utf-8")
    return {line.strip() for line in output.splitlines() if line.strip()}


def probe_records(records, runner=subprocess.run, platform_name=None, report_unregistered=True):
    """Attach observational state. No service/distro is started and SSH is batch-only."""
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    platform_name = platform_name or os.name
    outer_distros = {record["connection"]["wslDistro"] for record in records if record.get("connection", {}).get("wslDistro")}
    declared_wsl = {
        ref["site"].get("host")
        for record in records
        for ref in record.get("refs", [])
        if isinstance(ref.get("site"), dict) and ref["site"].get("reach") == "wsl" and isinstance(ref["site"].get("host"), str)
    }
    declared_wsl.update(
        record.get("connection", {}).get("distro")
        for record in records
        if record.get("connection", {}).get("transport") == "wsl" and isinstance(record.get("connection", {}).get("distro"), str)
    )
    for record in records:
        record["observation"] = {"observedAt": now, "observer": platform_name, "installed": None, "running": None, "reachable": None, "reason": "not probed"}
        connection = record.get("connection") or {}
        transport = connection.get("transport")
        if transport == "wsl" and platform_name == "nt":
            try:
                installed = runner(["wsl.exe", "--list", "--quiet"], capture_output=True, check=False)
                running = runner(["wsl.exe", "--list", "--running", "--quiet"], capture_output=True, check=False)
                installed_names = _wsl_names(installed.stdout) if installed.returncode == 0 else set()
                running_names = _wsl_names(running.stdout) if running.returncode == 0 else set()
            except (OSError, UnicodeError) as exc:
                record["observation"]["reason"] = "WSL probe unavailable: %s" % exc
                continue
            observation = {"reachable": None, "reason": "WSL lists observed" if installed.returncode == 0 else "WSL listing failed"}
            distro = connection.get("distro")
            if installed.returncode == 0 and isinstance(distro, str):
                observation.update({"installed": distro in installed_names, "running": (distro in running_names) if running.returncode == 0 else None, "reachable": None if distro in installed_names else False, "reason": "WSL distro unregistered" if distro not in installed_names else ("WSL running list failed" if running.returncode else "WSL state observed; runtime reachability not probed")})
                if report_unregistered:
                    observation["unregisteredDistros"] = sorted(installed_names - declared_wsl - outer_distros)
            record["observation"].update(observation)
        elif transport == "ssh" and connection.get("sourceObserved"):
            record["observation"].update({"reachable": True, "reason": "reachable through successful source probe"})
        elif transport == "ssh":
            record["observation"]["reason"] = "SSH observation requires a successful referenced source probe"
        else:
            record["observation"]["reason"] = "no supported local observational probe"
    return records


def check_catalog(path, environment_id=None, probe=False, runner=subprocess.run):
    """Return ``(errors, records)`` for callers such as start preflight."""
    try:
        _catalog, sources, records = load_catalog(path, probe=probe, runner=runner, environment_id=environment_id)
    except CatalogError as exc:
        return [str(exc)], []
    errors = []
    all_records = records
    relevant_sources = _referenced_source_ids(_catalog["environments"])
    for source_id in relevant_sources:
        if sources[source_id].get("unavailable"):
            errors.append("unverified source %s: %s" % (source_id, sources[source_id]["unavailable"]))
    for record in records:
        if (record.get("entrypoint") or {}).get("resolution", "resolved") != "resolved":
            errors.append("unverified entrypoint for %s: %s" % (record["id"], record["entrypoint"]["resolution"]))
    # Every declared placement site must have an explicit catalog item. This
    # catches the historical SITES-only omission without guessing its purpose.
    # A targeted preflight validates its target only. Full inventory coverage
    # belongs to an unscoped catalog check, so an unrelated remote does not
    # block a local environment repair or start.
    coverage_sources = sources.items() if environment_id is None else []
    for source_id, source in coverage_sources:
        if source["definition"]["type"] == "placement-tsv" and not source.get("unavailable"):
            covered = {ref["site"]["id"] for record in all_records for ref in record["refs"] if ref["source"] == source_id and ref["site"]}
            for site_id in source["sites"]:
                if site_id not in covered: errors.append("unregistered site: %s/%s" % (source_id, site_id))
        if source["definition"]["type"] == "json-pointer" and not source.get("unavailable"):
            referenced = {field for record in all_records for ref in record["refs"] if ref["source"] == source_id for field in ref.get("fields", {}).values()}
            for field in source["fields"]:
                if field not in referenced:
                    errors.append("unregistered JSON field: %s/%s" % (source_id, field))
    if probe: probe_records(records, runner, report_unregistered=environment_id is None)
    if probe:
        for record in records:
            transport = record.get("connection", {}).get("transport")
            observation = record["observation"]
            failed = (observation.get("installed") is not True or observation.get("running") is None) if transport == "wsl" else (bool(transport) and observation.get("reachable") is not True)
            if failed:
                errors.append("probe unresolved for %s: %s" % (record["id"], record["observation"]["reason"]))
    return errors, records

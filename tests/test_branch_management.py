"""Real-Git regression coverage for the branch-management command.

The command is deliberately exercised through ``place.py`` and Git hooks rather
than importing its implementation: the promises made here are the promises a
checkout receives.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLACE = Path(os.environ.get("AGENT_RULES_PLACE", ROOT / "bin" / "place.py"))


class BranchManagementTests(unittest.TestCase):
    def setUp(self):
        started = time.monotonic()
        self._ci_metrics = {}
        self.temp = tempfile.TemporaryDirectory(prefix="branch management ")
        self.addCleanup(self.cleanup_fixture)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "integration checkout"
        self.command("git", "init", "--bare", "--initial-branch=main", self.remote)
        self.command("git", "clone", self.remote, self.repo)
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "README").write_text("base\n", encoding="utf-8")
        self.git("add", "README")
        self.git("commit", "-m", "base")
        self.git("push", "-u", "origin", "main")
        self.branch("install")
        self._ci_metrics['fixtureSeconds'] = time.monotonic() - started

    def cleanup_fixture(self):
        started = time.monotonic()
        self.temp.cleanup()
        self._ci_metrics['cleanupSeconds'] = time.monotonic() - started

    def command(self, *argv, cwd=None, ok=True, input=None):
        started = time.monotonic()
        result = subprocess.run(argv, cwd=cwd, text=True, input=input,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        kind = 'git' if argv[0] == 'git' else 'cli'
        count, elapsed = kind + 'CommandCount', kind + 'CommandSeconds'
        self._ci_metrics[count] = self._ci_metrics.get(count, 0) + 1
        self._ci_metrics[elapsed] = self._ci_metrics.get(elapsed, 0.0) + time.monotonic() - started
        if ok and result.returncode:
            self.fail("%r failed (%s):\nstdout: %s\nstderr: %s" %
                      (argv, result.returncode, result.stdout, result.stderr))
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def git(self, *argv, **kwargs):
        return self.command("git", "-C", str(self.repo), *argv, **kwargs)

    def branch(self, *argv, repo=None, ok=True):
        repo = self.repo if repo is None else Path(repo)
        remote = ("--remote", "origin") if argv[0] == "install" else ()
        return self.command(sys.executable, str(PLACE), "branch", *argv,
                            "--repo", str(repo), *remote, ok=ok)

    def begin(self, task, mode="new", repo=None, **extra):
        repo = self.repo if repo is None else Path(repo)
        extra.setdefault("request", "request-" + task)
        extra.setdefault("worktree", repo if mode == "adopt" else self.root / (task + " worktree"))
        if mode == "adopt":
            extra.setdefault("base", self.git_at(repo, "rev-parse", "HEAD").stdout.strip())
        argv = ["begin", "--mode", mode, "--task", task]
        for key, value in extra.items():
            argv += ["--" + key.replace("_", "-"), str(value)]
        result = self.branch(*argv, repo=repo)
        return json.loads(result.stdout)

    def git_at(self, repo, *argv, **kwargs):
        return self.command("git", "-C", str(repo), *argv, **kwargs)

    def commit(self, name, contents=None):
        path = self.repo / name
        path.write_text(contents or name + "\n", encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", name)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def integrate(self, task, name=None, contents=None, **extra):
        """Register a topic, commit one file in it and merge it into adopted main."""
        worktree = Path(self.begin(task, branch=task, **extra)["worktree"])
        name = name or task + "-change"
        (worktree / name).write_text(contents or task + "\n", encoding="utf-8")
        self.git_at(worktree, "add", name)
        self.git_at(worktree, "commit", "-m", name)
        self.branch("prepare-merge", "--task", task)
        self.git("merge", "--no-ff", "--no-commit", task)
        self.git("commit", "-m", "merge " + task)
        return worktree

    def publish_remote_topic(self, name, *, base, contents=b"remote topic\n"):
        """Publish a topic without creating its local branch in ``self.repo``."""
        publisher = self.root / (name + " publisher")
        self.command("git", "clone", self.remote, publisher)
        self.git_at(publisher, "config", "user.name", "Publisher")
        self.git_at(publisher, "config", "user.email", "publisher@example.invalid")
        self.git_at(publisher, "switch", "-c", name, base)
        payload = publisher / "payload.bin"
        payload.write_bytes(contents)
        executable = publisher / "run-topic"
        executable.write_text("#!/bin/sh\nprintf remote\\n", encoding="utf-8", newline="\n")
        executable.chmod(0o755)
        self.git_at(publisher, "add", "payload.bin", "run-topic")
        self.git_at(publisher, "commit", "-m", "publish " + name)
        self.git_at(publisher, "push", "origin", "HEAD:refs/heads/" + name)
        return self.git_at(publisher, "rev-parse", "HEAD").stdout.strip()

    def advance_remote_topic(self, name):
        publisher = self.root / (name + " advance publisher")
        self.command("git", "clone", self.remote, publisher)
        self.git_at(publisher, "config", "user.name", "Publisher")
        self.git_at(publisher, "config", "user.email", "publisher@example.invalid")
        self.git_at(publisher, "switch", "-c", name, "origin/" + name)
        (publisher / "advanced").write_text("advanced remote\n", encoding="utf-8")
        self.git_at(publisher, "add", "advanced")
        self.git_at(publisher, "commit", "-m", "advance " + name)
        self.git_at(publisher, "push", "origin", name)
        return self.git_at(publisher, "rev-parse", "HEAD").stdout.strip()

    def remote_begin(self, task, *, branch, worktree, base, repo=None, ok=True, **extra):
        """Invoke the public remote-only adoption entry point exactly once."""
        repo = self.repo if repo is None else Path(repo)
        argv = ["begin", "--mode", "adopt", "--from-remote", "--task", task,
                "--request", extra.pop("request", "request-" + task), "--branch", branch,
                "--worktree", str(worktree), "--base", str(base)]
        for key, value in extra.items():
            argv += ["--" + key.replace("_", "-"), str(value)]
        result = self.branch(*argv, repo=repo, ok=ok)
        return result if not ok else json.loads(result.stdout)

    def test_remote_only_adopt_pins_verified_tip_and_historical_base(self):
        """R1/R2/R10: Q is checked out verbatim while B remains historical."""
        self.begin("integration", "adopt", branch="main", into="main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        # Make the default remote head differ from both B and the topic tip.
        publisher = self.root / "default publisher"
        self.command("git", "clone", self.remote, publisher)
        self.git_at(publisher, "config", "user.name", "Publisher")
        self.git_at(publisher, "config", "user.email", "publisher@example.invalid")
        (publisher / "default-only").write_text("later default\n", encoding="utf-8")
        self.git_at(publisher, "add", "default-only")
        self.git_at(publisher, "commit", "-m", "advance default")
        self.git_at(publisher, "push", "origin", "main")
        default_tip = self.git_at(publisher, "rev-parse", "HEAD").stdout.strip()
        topic_tip = self.publish_remote_topic("remote-topic", base=base, contents=b"\x00topic\r\nbytes\n")
        self.git("fetch", "origin")
        self.assertNotEqual(base, topic_tip)
        self.assertNotEqual(default_tip, topic_tip)
        worktree = self.root / "remote topic worktree"
        result = self.remote_begin("remote-topic", branch="remote-topic", worktree=worktree,
                                   base=base, into="main")
        self.assertEqual(result["base"], base)
        self.assertEqual(result["tip"], topic_tip)
        self.assertEqual(result["request"], "request-remote-topic")
        self.assertEqual(result["depends_on"], None)
        self.assertEqual(self.git("rev-parse", "refs/heads/remote-topic").stdout.strip(), topic_tip)
        self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD").stdout.strip(), topic_tip)
        self.assertEqual(self.git_at(worktree, "config", "--get", "branch.remote-topic.remote").stdout.strip(), "origin")
        self.assertEqual(self.git_at(worktree, "config", "--get", "branch.remote-topic.merge").stdout.strip(),
                         "refs/heads/remote-topic")
        self.assertEqual((worktree / "payload.bin").read_bytes(), b"\x00topic\r\nbytes\n")
        self.assertTrue(os.access(worktree / "run-topic", os.X_OK))
        self.assertEqual(self.git_at(worktree, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()[0], topic_tip)

    def test_remote_only_adopt_rejects_missing_tracking_base_and_collisions_without_mutation(self):
        """R3/R4: validation happens before any branch, path, or state overwrite."""
        self.begin("integration", "adopt", branch="main", into="main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        topic_tip = self.publish_remote_topic("unfetched", base=base)
        before_refs = self.git("show-ref").stdout
        before_state = (self.repo / ".git" / "agent-branches" / "state.json").read_bytes()
        missing_path = self.root / "missing tracking"
        self.remote_begin("missing", branch="unfetched", worktree=missing_path, base=base, ok=False)
        self.assertFalse(missing_path.exists())
        self.assertEqual(self.git("show-ref").stdout, before_refs)
        self.assertEqual((self.repo / ".git" / "agent-branches" / "state.json").read_bytes(), before_state)
        self.git("fetch", "origin")
        state_before_stale = (self.repo / ".git" / "agent-branches" / "state.json").read_bytes()
        q2 = self.advance_remote_topic("unfetched")
        self.remote_begin("stale", branch="unfetched", worktree=self.root / "stale tracking", base=base, ok=False)
        self.assertFalse((self.root / "stale tracking").exists())
        self.assertEqual((self.repo / ".git" / "agent-branches" / "state.json").read_bytes(), state_before_stale)
        self.git("fetch", "origin")
        self.assertEqual(self.git("rev-parse", "origin/unfetched").stdout.strip(), q2)
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        non_ancestor = self.git("commit-tree", tree, "-m", "unrelated base").stdout.strip()
        self.remote_begin("bad-base", branch="unfetched", worktree=self.root / "bad base", base=non_ancestor, ok=False)
        self.remote_begin("noncommit-base", branch="unfetched", worktree=self.root / "noncommit base", base=tree, ok=False)
        existing = self.root / "occupied"
        existing.mkdir()
        (existing / "keep").write_text("keep\n", encoding="utf-8")
        self.remote_begin("occupied", branch="unfetched", worktree=existing, base=base, ok=False)
        self.assertEqual((existing / "keep").read_text(encoding="utf-8"), "keep\n")
        link = self.root / "occupied link"
        link.symlink_to(existing, target_is_directory=True)
        self.remote_begin("linked", branch="unfetched", worktree=link, base=base, ok=False)
        self.assertTrue(link.is_symlink())
        # Fixture setup needs a retained local branch; ordinary ref updates are
        # intentionally rejected by the installed enforcement hook.
        empty_hooks = self.root / "empty hooks"
        empty_hooks.mkdir()
        self.command("git", "-C", str(self.repo), "-c", "core.hooksPath=" + str(empty_hooks),
                     "branch", "unfetched", q2)
        self.remote_begin("existing-branch", branch="unfetched", worktree=self.root / "new path", base=base, ok=False)
        self.assertEqual(self.git("rev-parse", "unfetched").stdout.strip(), q2)

    def test_remote_only_adopt_preserves_dirty_caller_and_does_not_leak_to_other_modes(self):
        """R5/R6: caller contents survive and the flag is not accepted by old modes."""
        self.begin("integration", "adopt", branch="main", into="main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.publish_remote_topic("dirty-safe", base=base)
        self.git("fetch", "origin")
        (self.repo / "README").write_text("staged change\n", encoding="utf-8")
        self.git("add", "README")
        (self.repo / "README").write_text("staged change\nunstaged tail\n", encoding="utf-8")
        (self.repo / "untracked").write_text("untracked\n", encoding="utf-8")
        index_before = self.git("write-tree").stdout.strip()
        status_before = self.git("status", "--porcelain=v1").stdout
        self.remote_begin("dirty-safe", branch="dirty-safe", worktree=self.root / "dirty safe", base=base, into="main")
        self.assertEqual(self.git("write-tree").stdout.strip(), index_before)
        self.assertEqual(self.git("status", "--porcelain=v1").stdout, status_before)
        self.assertEqual((self.repo / "README").read_text(encoding="utf-8"), "staged change\nunstaged tail\n")
        self.assertEqual((self.repo / "untracked").read_text(encoding="utf-8"), "untracked\n")
        self.branch("begin", "--mode", "new", "--from-remote", "--task", "wrong-new",
                    "--request", "fixture", "--branch", "wrong-new", "--worktree", str(self.root / "wrong new"), ok=False)
        self.branch("begin", "--mode", "continue", "--from-remote", "--task", "dirty-safe", ok=False)

    def test_remote_only_adopt_rejects_changed_registered_remote_without_mutation(self):
        """R3: an origin whose registered endpoint changed cannot supply Q."""
        self.begin("integration", "adopt", branch="main", into="main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.publish_remote_topic("wrong-remote", base=base)
        self.git("fetch", "origin")
        before_refs = self.git("show-ref").stdout
        before_index = self.git("write-tree").stdout.strip()
        before_state = (self.repo / ".git" / "agent-branches" / "state.json").read_bytes()
        alternate = self.root / "alternate.git"
        self.command("git", "init", "--bare", alternate)
        self.git("remote", "set-url", "origin", str(alternate))
        target = self.root / "wrong registered remote"
        self.remote_begin("wrong-remote", branch="wrong-remote", worktree=target, base=base, ok=False)
        self.assertFalse(target.exists())
        self.assertEqual(self.git("show-ref").stdout, before_refs)
        self.assertEqual(self.git("write-tree").stdout.strip(), before_index)
        self.assertEqual((self.repo / ".git" / "agent-branches" / "state.json").read_bytes(), before_state)

    def test_remote_only_adopt_rejects_another_tasks_registered_path_without_mutation(self):
        """R4: a path owned by another task is not repurposed for remote work."""
        self.begin("integration", "adopt", branch="main", into="main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        other = Path(self.begin("other", branch="other")["worktree"])
        other_head = self.git_at(other, "rev-parse", "HEAD").stdout.strip()
        (other / "keep").write_text("other task content\n", encoding="utf-8")
        self.publish_remote_topic("remote-path-conflict", base=base)
        self.git("fetch", "origin")
        before_refs = self.git("show-ref").stdout
        before_state = (self.repo / ".git" / "agent-branches" / "state.json").read_bytes()
        self.remote_begin("path-conflict", branch="remote-path-conflict", worktree=other, base=base, ok=False)
        self.assertEqual(self.git_at(other, "rev-parse", "HEAD").stdout.strip(), other_head)
        self.assertEqual((other / "keep").read_text(encoding="utf-8"), "other task content\n")
        self.assertEqual(self.git("show-ref").stdout, before_refs)
        self.assertEqual((self.repo / ".git" / "agent-branches" / "state.json").read_bytes(), before_state)

    def test_remote_only_adopt_preserves_a_dirty_existing_worktree(self):
        """R5: creating Q leaves a different registered checkout entirely intact."""
        self.begin("integration", "adopt", branch="main", into="main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        other = Path(self.begin("existing", branch="existing")["worktree"])
        (other / "README").write_text("staged\n", encoding="utf-8")
        self.git_at(other, "add", "README")
        (other / "README").write_text("staged\nunstaged\n", encoding="utf-8")
        (other / "untracked").write_text("retain\n", encoding="utf-8")
        other_head = self.git_at(other, "rev-parse", "HEAD").stdout.strip()
        other_index = self.git_at(other, "write-tree").stdout.strip()
        other_status = self.git_at(other, "status", "--porcelain=v1").stdout
        self.publish_remote_topic("separate-dirty", base=base)
        self.git("fetch", "origin")
        self.remote_begin("separate-dirty", branch="separate-dirty", worktree=self.root / "separate dirty", base=base)
        self.assertEqual(self.git_at(other, "rev-parse", "HEAD").stdout.strip(), other_head)
        self.assertEqual(self.git_at(other, "write-tree").stdout.strip(), other_index)
        self.assertEqual(self.git_at(other, "status", "--porcelain=v1").stdout, other_status)
        self.assertEqual((other / "README").read_text(encoding="utf-8"), "staged\nunstaged\n")
        self.assertEqual((other / "untracked").read_text(encoding="utf-8"), "retain\n")

    def test_remote_only_adopt_records_non_null_dependency_and_destination(self):
        """The remote entry preserves normal task routing metadata."""
        self.begin("integration", "adopt", branch="main", into="main")
        parent = Path(self.begin("parent", branch="parent")["worktree"])
        (parent / "parent").write_text("parent\n", encoding="utf-8")
        self.git_at(parent, "add", "parent")
        self.git_at(parent, "commit", "-m", "parent")
        parent_tip = self.git_at(parent, "rev-parse", "HEAD").stdout.strip()
        self.git_at(parent, "push", "origin", "parent")
        self.publish_remote_topic("dependent-remote", base=parent_tip)
        self.git("fetch", "origin")
        result = self.remote_begin("dependent-remote", branch="dependent-remote",
                                   worktree=self.root / "dependent remote", base=parent_tip,
                                   request="request-dependent", depends_on="parent", into="parent")
        self.assertEqual(result["request"], "request-dependent")
        self.assertEqual(result["depends_on"], "parent")
        self.assertEqual(result["into"], "parent")

    def test_install_preserves_an_existing_hook_and_detects_tampering(self):
        # Reinstall over a real hook: its args, stdin and exit status must survive.
        legacy = self.root / "legacy checkout"
        self.command("git", "clone", self.remote, legacy)
        original = legacy / ".git" / "hooks" / "prepare-commit-msg"
        original.write_text("#!/bin/sh\nprintf '%s' \"$1\" > legacy-hook-args\n", encoding="utf-8", newline="\n")
        original.chmod(0o755)
        self.branch("install", repo=legacy)
        self.begin("legacy-main", "adopt", repo=legacy, branch="main", into="main")
        self.assertEqual(self.branch("check", repo=legacy).returncode, 0)
        topic = Path(self.begin("legacy-topic", repo=legacy, branch="legacy-topic")["worktree"])
        hook_root = Path(self.git_at(legacy, "config", "--get", "core.hooksPath").stdout.strip())
        hook = hook_root / "prepare-commit-msg"
        message = topic / "message"
        message.write_text("message\n", encoding="utf-8")
        self.git_at(topic, "hook", "run", "prepare-commit-msg", "--", str(message))
        self.assertEqual((topic / "legacy-hook-args").read_text(encoding="utf-8"), str(message))
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.branch("check", repo=legacy, ok=False)

    def test_declare_agent_updates_only_a_registered_source_catalog(self):
        # Inventory consumes the source checkout's managed rules/skills; the
        # installed wheel exposes project commands and branch hooks only. Keep
        # PLACE for branch registration/hooks so their installed form is covered.
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("declaration", branch="declaration")["worktree"])
        declaration = source / "PLACEMENT.md"
        catalog = source / "catalog.json"
        declaration.write_text("""<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
s1\tcontroller\towner\t/tmp/owner\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
w1\ts1\tdirect\t/tmp/owner/work\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
g1\thome\ts1\tgrok\trequired\t\t\t\tskills
g2\thome\ts1\tgrok\trequired\t\t\t\trules
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
<!-- BEGIN INVENTORY TSV -->
```tsv
site\tcatalog\tenvironment
s1\tcatalog.json\tenv
```
<!-- END INVENTORY TSV -->
""", encoding="utf-8")
        catalog.write_text(json.dumps({"schemaVersion": 1,
            "sources": {"p": {"type": "placement-tsv", "host": "test", "paths": {"default": str(declaration)}}},
            "environments": [{"id": "env", "purposes": ["normal-development"], "state": "active",
                "refs": [{"source": "p", "site": "s1", "workspace": "w1"}], "agents": [],
                "unknown": {"keep": True}}], "unknown": ["keep"]}), encoding="utf-8")
        self.git_at(source, "add", "PLACEMENT.md", "catalog.json")
        self.git_at(source, "commit", "-m", "add declaration inputs")
        declaration.write_text(declaration.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        source_dirty = self.command(sys.executable, str(ROOT / "bin" / "place.py"), "inventory", "declare-agent",
                                    "--declaration", str(declaration), "--site", "s1", "--tool", "grok", ok=False)
        self.assertIn("refuse source dirt", source_dirty.stderr)
        self.git_at(source, "checkout", "--", "PLACEMENT.md")
        integration_declaration = self.repo / "default.md"
        integration_catalog = self.repo / "catalog.json"
        integration_declaration.write_bytes(declaration.read_bytes())
        integration_catalog.write_bytes(catalog.read_bytes())
        default_checkout = self.command(sys.executable, str(ROOT / "bin" / "place.py"), "inventory", "declare-agent",
                                        "--declaration", str(integration_declaration), "--site", "s1", "--tool", "grok", ok=False)
        self.assertIn("registered topic checkout", default_checkout.stderr)
        unrelated = source / "unrelated.txt"; unrelated.write_text("keep\n", encoding="utf-8")
        result = self.command(sys.executable, str(ROOT / "bin" / "place.py"), "inventory", "declare-agent",
                              "--declaration", str(declaration), "--site", "s1", "--tool", "grok")
        output = json.loads(result.stdout)
        self.assertTrue(output["changed"])
        self.assertEqual(output["task"], "declaration")
        self.assertEqual(output["catalog"], "catalog.json")
        updated = json.loads(catalog.read_text(encoding="utf-8"))
        self.assertEqual(updated["environments"][0]["state"], "pending")
        self.assertEqual(updated["unknown"], ["keep"])
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep\n")
        repeated = self.command(sys.executable, str(ROOT / "bin" / "place.py"), "inventory", "declare-agent",
                                "--declaration", str(declaration), "--site", "s1", "--tool", "grok")
        self.assertFalse(json.loads(repeated.stdout)["changed"])
        pending_catalog = catalog.read_text(encoding="utf-8")
        invalid = json.loads(pending_catalog); invalid["environments"][0]["agents"] = "invalid"
        catalog.write_text(json.dumps(invalid), encoding="utf-8")
        invalid_catalog = self.command(sys.executable, str(ROOT / "bin" / "place.py"), "inventory", "declare-agent",
                                       "--declaration", str(declaration), "--site", "s1", "--tool", "grok", ok=False)
        self.assertIn("agents", invalid_catalog.stderr)
        catalog.write_text(pending_catalog + " ", encoding="utf-8")
        refused = self.command(sys.executable, str(ROOT / "bin" / "place.py"), "inventory", "declare-agent",
                               "--declaration", str(declaration), "--site", "s1", "--tool", "grok", ok=False)
        self.assertIn("refuse target dirt", refused.stderr)

    def approve_tag(self, name="v1", commit=None, **kwargs):
        commit = commit or self.git("rev-parse", "HEAD").stdout.strip()
        return self.branch("allow-tag-push", "--remote", "origin", "--tag", name,
                           "--commit", commit, "--approval", "user-release-request", **kwargs)

    def preflight(self):
        result = self.command(sys.executable, str(PLACE.with_name("push_preflight.py")),
                              str(self.repo), "--user-intent", "push")
        return json.loads(result.stdout)

    def test_branch_transport_destination_and_shared_preflight(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.repo = Path(self.begin("transport", branch="transport")["worktree"])
        tip = self.commit("transport-change")
        other = self.root / "unregistered.git"
        self.command("git", "clone", "--bare", self.remote, other)
        self.git("remote", "add", "other", str(other))
        before = self.git_at(self.remote, "show-ref").stdout
        other_before = self.git_at(other, "show-ref").stdout
        self.assertEqual(self.preflight()["decision"], "push")
        self.git("push", "other", "HEAD:refs/heads/transport", ok=False)
        self.git("remote", "set-url", "--push", "origin", str(other))
        self.assertNotEqual(self.preflight()["decision"], "push")
        self.git("push", "origin", "HEAD:refs/heads/transport", ok=False)
        self.git("config", "--unset-all", "remote.origin.pushurl")
        self.git("config", "--add", "remote.origin.pushurl", str(self.remote))
        self.git("config", "--add", "remote.origin.pushurl", str(other))
        self.assertNotEqual(self.preflight()["decision"], "push")
        self.git("push", "origin", "HEAD:refs/heads/transport", ok=False)
        self.assertEqual(self.git_at(self.remote, "show-ref").stdout, before)
        self.assertEqual(self.git_at(other, "show-ref").stdout, other_before)
        self.git("config", "--unset-all", "remote.origin.pushurl")
        # Real read/write URL separation to the same local repository, with
        # spaces encoded in the file URI; neither endpoint is a production host.
        self.git("remote", "set-url", "--push", "origin", self.remote.as_uri())
        self.assertEqual(self.preflight()["decision"], "push")
        self.git("push", "origin", "HEAD:refs/heads/transport")
        self.assertEqual(self.git_at(self.remote, "rev-parse", "transport").stdout.strip(), tip)
        self.git("tag", "v-split")
        self.approve_tag("v-split")
        # A stale tag ticket cannot survive even a same-repository URL change.
        self.git("remote", "set-url", "--push", "origin", str(self.remote))
        self.git("push", "origin", "refs/tags/v-split", ok=False)
        self.assertEqual(self.git_at(self.remote, "show-ref", "--tags", ok=False).stdout, "")
        self.git("remote", "set-url", "--push", "origin", self.remote.as_uri())
        self.approve_tag("v-split")
        self.git("push", "origin", "refs/tags/v-split")

    def test_branch_hook_rejects_inconsistent_transport_argument(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.repo = Path(self.begin("transport", branch="transport")["worktree"])
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        row = "HEAD %s refs/heads/transport %s\n" % (tip, "0" * len(tip))
        hook = Path(self.git("config", "--get", "core.hooksPath").stdout.strip()) / "pre-push"
        shell = "sh"
        if os.name == "nt":
            exec_path = Path(self.git("--exec-path").stdout.strip())
            shell = next(str(parent / "usr/bin/sh.exe") for parent in exec_path.parents
                         if (parent / "usr/bin/sh.exe").is_file())
        denied = self.command(shell, hook.as_posix(), "origin", str(self.root / "wrong.git"),
                              cwd=self.repo, input=row, ok=False)
        self.assertIn("push destination differs", denied.stderr)
        self.assertEqual(self.git_at(self.remote, "show-ref", "--verify", "refs/heads/transport", ok=False).stdout, "")

    def test_explicit_new_tag_pushes_preserve_raw_object_and_commit(self):
        self.begin("integration", "adopt", branch="main", into="main")
        commit = self.git("rev-parse", "HEAD").stdout.strip()
        for name, args in (("v-light", ()), ("v-annotated", ("-a", "-m", "Release"))):
            self.git("tag", *args, name)
            self.git("push", "origin", "refs/tags/" + name, ok=False)
            ticket = json.loads(self.approve_tag(name).stdout)
            self.assertEqual(ticket["commit"], commit)
            self.git("push", "origin", "refs/tags/" + name)
            remote = self.git_at(self.remote, "rev-parse", "refs/tags/" + name).stdout.strip()
            self.assertEqual(remote, ticket["object"])
            self.assertEqual(self.git_at(self.remote, "rev-parse", name + "^{commit}").stdout.strip(), commit)
            self.approve_tag(name, ok=False)  # No remote replacement permission.
            self.git("push", "origin", ":refs/tags/" + name, ok=False)
        self.branch("check")

    def test_tag_approval_rejects_noncanonical_or_wrong_commit(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.git("tag", "v1")
        self.approve_tag(commit="HEAD", ok=False)
        self.approve_tag("refs/tags/v1", ok=False)
        self.approve_tag("missing", ok=False)
        self.approve_tag("bad..name", ok=False)
        self.branch("allow-tag-push", "--remote", "origin", "--tag", "v1", "--commit",
                    self.git("rev-parse", "HEAD").stdout.strip(), "--approval", " ", ok=False)
        topic = Path(self.begin("feature", branch="feature")["worktree"])
        (topic / "change").write_text("changed\n", encoding="utf-8")
        self.git_at(topic, "add", "change")
        self.git_at(topic, "commit", "-m", "change")
        self.approve_tag(commit=self.git_at(topic, "rev-parse", "HEAD").stdout.strip(), ok=False)

    def test_tag_batch_rejection_preserves_exact_permission(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.git("tag", "-a", "v1", "-m", "approved annotation")
        raw = self.git("rev-parse", "refs/tags/v1").stdout.strip()
        self.git("tag", "v2")
        self.approve_tag()
        self.git("push", "origin", "refs/tags/v1", "refs/tags/v2", ok=False)
        self.assertEqual(self.git("ls-remote", "--tags", "origin").stdout, "")
        # Even another annotation at the same commit is a different artifact.
        self.git("tag", "-f", "-a", "v1", "-m", "unapproved annotation")
        self.git("push", "origin", "refs/tags/v1", ok=False)
        self.git("update-ref", "refs/tags/v1", raw)
        self.git("push", "origin", "HEAD:refs/tags/v1", ok=False)
        self.git("push", "origin", "refs/tags/v1:refs/tags/renamed", ok=False)
        self.git("push", "origin", "refs/tags/v1")

    def test_tag_destination_is_pinned_at_approval_and_push(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.git("tag", "v1")
        other = self.root / "other.git"
        self.command("git", "clone", "--bare", self.remote, other)
        self.git("remote", "add", "other", str(other))
        self.approve_tag()
        self.git("push", "other", "refs/tags/v1", ok=False)
        self.git("remote", "set-url", "--push", "origin", str(other))
        self.approve_tag(ok=False)
        self.git("push", "origin", "refs/tags/v1", ok=False)
        self.git("config", "--unset-all", "remote.origin.pushurl")
        self.git("config", "--add", "remote.origin.url", str(other))
        self.approve_tag(ok=False)
        self.git("push", "origin", "refs/tags/v1", ok=False)
        self.git("config", "--unset-all", "remote.origin.url")
        self.git("config", "remote.origin.url", str(self.remote))
        raw = self.git("rev-parse", "refs/tags/v1").stdout.strip()
        row = "refs/tags/v1 %s refs/tags/v1 %s\n" % (raw, "0" * len(raw))
        hook = Path(self.git("config", "--get", "core.hooksPath").stdout.strip()) / "pre-push"
        shell = "sh"
        if os.name == "nt":
            exec_path = Path(self.git("--exec-path").stdout.strip())
            shell = next(str(parent / "usr/bin/sh.exe") for parent in exec_path.parents
                         if (parent / "usr/bin/sh.exe").is_file())
        # Exercise the actual hook with an inconsistent transport URL and a
        # duplicate batch, neither of which Git normally emits itself.
        denied = self.command(shell, hook.as_posix(), "origin", str(other), cwd=self.repo, input=row, ok=False)
        self.assertIn("push destination differs", denied.stderr)
        denied = self.command(shell, hook.as_posix(), "origin", str(self.remote), cwd=self.repo, input=row + row, ok=False)
        self.assertIn("duplicate tag push destination", denied.stderr)
        self.git("push", "origin", "refs/tags/v1")
        self.assertEqual(self.git_at(other, "show-ref", "--tags", ok=False).stdout, "")

    def test_failed_transport_consumes_tag_ticket_and_remote_race_cannot_replace(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.git("tag", "-a", "v1", "-m", "release")
        self.approve_tag()
        reject = self.remote / "hooks" / "pre-receive"
        reject.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
        reject.chmod(0o755)
        self.git("push", "origin", "refs/tags/v1", ok=False)
        reject.unlink()
        denied = self.git("push", "origin", "refs/tags/v1", ok=False)
        self.assertIn("tag push needs", denied.stderr)
        self.approve_tag()
        # Another publisher creates the tag after approval. Even an explicit
        # --force cannot spend this ticket to replace the remote tag.
        original = self.git_at(self.remote, "rev-parse", "HEAD").stdout.strip()
        self.git_at(self.remote, "tag", "v1", original)
        self.git("push", "--force", "origin", "refs/tags/v1", ok=False)
        self.git("push", "origin", ":refs/tags/v1", ok=False)
        self.assertEqual(self.git_at(self.remote, "rev-parse", "refs/tags/v1").stdout.strip(), original)

    def test_new_adopt_continue_and_child_ordering(self):
        adopted = self.begin("integration", "adopt", branch="main", into="main")
        self.assertIsInstance(adopted, dict)
        created = self.begin("feature", branch="feature", into="main")
        self.assertIsInstance(created, dict)
        self.branch("begin", "--mode", "continue", "--task", "feature")
        # A child can start before parent integration, but cannot integrate first.
        child = self.begin("child", branch="child", depends_on="feature")
        feature = Path(created["worktree"])
        (feature / "feature-change").write_text("feature\n", encoding="utf-8")
        self.git_at(feature, "add", "feature-change")
        self.git_at(feature, "commit", "-m", "feature-change")
        self.branch("prepare-merge", "--task", "child", ok=False)
        self.branch("prepare-merge", "--task", "feature")
        self.git("merge", "--no-ff", "--no-commit", "feature")
        self.git("commit", "-m", "merge feature")
        child_path = Path(child["worktree"])
        (child_path / "child-change").write_text("child\n", encoding="utf-8")
        self.git_at(child_path, "add", "child-change")
        self.git_at(child_path, "commit", "-m", "child-change")
        self.branch("prepare-merge", "--task", "child")
        self.git("merge", "--no-ff", "--no-commit", "child")
        self.git("commit", "-m", "merge child")
        other = self.root / "other checkout"
        self.command("git", "clone", self.remote, other)
        self.branch("begin", "--mode", "continue", "--task", "feature", "--worktree", str(other), ok=False)

    def test_unregistered_refs_no_verify_and_alternate_index_are_rejected(self):
        self.git("switch", "-c", "unregistered", ok=False)
        (self.repo / "ordinary").write_text("ordinary\n", encoding="utf-8")
        self.git("add", "ordinary")
        # --no-verify must not bypass registration checks.
        self.git("commit", "--allow-empty", "--no-verify", "-m", "bypass", ok=False)
        # A legitimate alternate index is accepted because the hook pins the
        # actual candidate tree.  A changed index after prepare-commit-msg is
        # rejected by the ref transaction.
        registered = self.begin("alternate", branch="alternate")
        checkout = Path(registered["worktree"])
        alternate = self.root / "alternate.index"
        env = {**os.environ, "GIT_INDEX_FILE": str(alternate)}
        (checkout / "alternate").write_text("alternate\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(checkout), "add", "alternate"], env=env, check=True)
        result = subprocess.run(["git", "-C", str(checkout), "commit", "-m", "alternate"],
                                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git_at(checkout, "show", "--format=", "--name-only", "HEAD").stdout.splitlines(),
                         ["README", "alternate"])

    def test_check_catches_wrong_worktree_and_concurrent_worktrees(self):
        self.begin("integration", "adopt", branch="main", into="main")
        self.begin("one", branch="one")
        linked = self.root / "linked checkout"
        self.begin("two", branch="two", worktree=linked)
        checked = self.branch("check", "--json")
        self.assertTrue(json.loads(checked.stdout)["ok"])
        self.assertEqual(self.branch("check", repo=linked).returncode, 0)
        one = self.root / "one worktree"
        (one / "one").write_text("one\n", encoding="utf-8")
        (linked / "two").write_text("two\n", encoding="utf-8")
        for checkout, name in ((one, "one"), (linked, "two")):
            self.git_at(checkout, "add", name)
        processes = [
            subprocess.Popen(["git", "-C", str(checkout), "commit", "-m", name],
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for checkout, name in ((one, "one"), (linked, "two"))
        ]
        completed = [(process, process.communicate()) for process in processes]
        for process, (stdout, stderr) in completed:
            self.assertEqual(process.returncode, 0, stdout + stderr)

    def test_detached_checkout_can_return_only_to_its_registered_tip(self):
        self.begin("integration", "adopt", branch="main", into="main")
        feature = Path(self.begin("feature", branch="feature")["worktree"])
        recorded = self.git_at(feature, "rev-parse", "HEAD").stdout.strip()
        other = Path(self.begin("other", branch="other")["worktree"])
        (other / "other-change").write_text("other\n", encoding="utf-8")
        self.git_at(other, "add", "other-change")
        self.git_at(other, "commit", "-m", "other-change")
        other_tip = self.git_at(other, "rev-parse", "HEAD").stdout.strip()

        # An immutable dependency checkout makes this worktree detached at a
        # different commit.  A normal checkout restores its recorded branch.
        self.git_at(feature, "checkout", "--detach", other_tip)
        self.assertNotEqual(self.branch("check", repo=feature, ok=False).returncode, 0)
        self.git_at(feature, "checkout", "feature")
        self.assertEqual(self.branch("check", repo=feature).returncode, 0)

        self.git_at(feature, "checkout", "--detach", other_tip)
        # A detached worktree cannot move HEAD even to its own recorded tip.
        self.git_at(feature, "checkout", "--detach", recorded, ok=False)
        self.git_at(feature, "checkout", "feature")
        self.assertEqual(self.branch("check", repo=feature).returncode, 0)


    def test_retire_releases_an_integrated_checkout_and_keeps_its_branch(self):
        self.begin("integration", "adopt", branch="main", into="main")
        worktree = self.integrate("source")
        tip = self.git("rev-parse", "refs/heads/source").stdout.strip()
        base = self.git("rev-parse", "refs/heads/source~1").stdout.strip()
        retired = json.loads(self.branch("retire", "--task", "source").stdout)
        self.assertTrue(retired["branch_retained"])
        self.assertFalse(worktree.exists())
        self.assertNotIn(str(worktree), self.git("worktree", "list").stdout)
        checked = json.loads(self.branch("check", "--json").stdout)
        self.assertTrue(checked["ok"], checked)
        self.assertNotIn("source", checked["tasks"])
        self.assertEqual(self.git("rev-parse", "refs/heads/source").stdout.strip(), tip)
        # The branch is retained but unregistered, so its updates are refused.
        tree = self.git("rev-parse", "refs/heads/source^{tree}").stdout.strip()
        outside = self.git("commit-tree", tree, "-p", tip, "-m", "outside").stdout.strip()
        self.git("update-ref", "refs/heads/source", outside, tip, ok=False)
        self.assertEqual(self.git("rev-parse", "refs/heads/source").stdout.strip(), tip)
        # The identifier, branch name and path are free for work again.
        self.git("worktree", "add", str(worktree), "source")
        self.begin("source", "adopt", branch="source", worktree=worktree, base=base)
        self.assertTrue(json.loads(self.branch("check", "--json").stdout)["ok"])

    def test_retire_refuses_unfinished_dependent_and_dirty_work(self):
        self.begin("integration", "adopt", branch="main", into="main")
        live = Path(self.begin("live", branch="live")["worktree"])
        self.assertIn("not integrated", self.branch("retire", "--task", "live", ok=False).stderr)
        self.assertTrue(live.exists())

        parent = self.integrate("parent")
        self.begin("child", branch="child", depends_on="parent")
        self.assertIn("depends on", self.branch("retire", "--task", "parent", ok=False).stderr)
        self.assertTrue(parent.exists())

        untracked = self.integrate("untracked")
        (untracked / "left behind").write_text("keep\n", encoding="utf-8")
        self.assertIn("preserve and inspect",
                      self.branch("retire", "--task", "untracked", ok=False).stderr)
        self.assertTrue((untracked / "left behind").exists())
        (untracked / "left behind").unlink()
        self.branch("retire", "--task", "untracked")

        # Ignored content is exactly what Git cannot restore, and a retired
        # checkout can hold another repository's registered worktree.
        ignored = self.integrate("ignored", name=".gitignore", contents="junk/\n")
        (ignored / "junk").mkdir()
        (ignored / "junk/thing").write_text("thing\n", encoding="utf-8")
        self.assertEqual(self.git_at(ignored, "status", "--porcelain").stdout, "")
        self.assertIn("preserve and inspect",
                      self.branch("retire", "--task", "ignored", ok=False).stderr)
        self.assertTrue((ignored / "junk/thing").exists())

    def test_retire_refuses_the_primary_checkout_and_the_default_branch(self):
        self.begin("integration", "adopt", branch="main", into="main")
        worktree = self.integrate("source")
        self.branch("retire", "--task", "integration", ok=False)
        self.assertTrue((self.repo / "README").exists())
        self.branch("retire", "--task", "source", repo=worktree, ok=False)
        self.assertTrue(worktree.exists())
        self.assertTrue(json.loads(self.branch("check", "--json").stdout)["ok"])

    def test_prepare_merge_requires_the_registered_source_and_allows_no_ff_merge(self):
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "source-change").write_text("source\n", encoding="utf-8")
        self.git_at(source, "add", "source-change")
        self.git_at(source, "commit", "-m", "source-change")
        self.git("merge", "--ff-only", "source", ok=False)
        self.git("reset", "--hard", "HEAD")
        self.git("merge", "--no-ff", "--no-commit", "source")
        self.git("commit", "-m", "unprepared merge", ok=False)
        self.branch("prepare-merge", "--task", "source")
        self.git("commit", "-m", "merge source")

    def test_child_can_merge_into_its_own_registered_parent(self):
        self.begin("integration", "adopt", branch="main", into="main")
        parent = Path(self.begin("parent", branch="parent")["worktree"])
        child = Path(self.begin("child", branch="child", depends_on="parent", into="parent")["worktree"])
        (child / "child-change").write_text("child\n", encoding="utf-8")
        self.git_at(child, "add", "child-change")
        self.git_at(child, "commit", "-m", "child change")
        parent_tip = self.git_at(parent, "rev-parse", "HEAD").stdout.strip()
        child_tip = self.git_at(child, "rev-parse", "HEAD").stdout.strip()
        self.branch("prepare-merge", "--task", "child", ok=False)  # Wrong destination.
        self.branch("prepare-merge", "--task", "child", repo=parent)
        self.git_at(parent, "merge", "--no-ff", "--no-commit", "child")
        self.git_at(parent, "commit", "-m", "merge child into parent")
        self.assertEqual(self.git_at(parent, "show", "-s", "--format=%P", "HEAD").stdout.strip(),
                         parent_tip + " " + child_tip)
        self.branch("check", repo=parent)

    def test_cherry_pick_authorization_is_single_use(self):
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "picked").write_text("one\n", encoding="utf-8")
        self.git_at(source, "add", "picked")
        self.git_at(source, "commit", "-m", "picked")
        sha = self.git_at(source, "rev-parse", "HEAD").stdout.strip()
        (source / "second").write_text("two\n", encoding="utf-8")
        self.git_at(source, "add", "second")
        self.git_at(source, "commit", "-m", "picked again")
        second = self.git_at(source, "rev-parse", "HEAD").stdout.strip()
        refused = Path(self.begin("refused", branch="refused")["worktree"])
        self.git_at(refused, "cherry-pick", sha, ok=False)
        target = Path(self.begin("target", branch="target")["worktree"])
        self.branch("allow-cherry-pick", "--commit", sha, "--approval", "review-123",
                    "--reason", "backport", repo=target)
        # One sequencer invocation commits the permitted first source, then
        # rejects the second while retaining the successful first commit.
        denied = self.git_at(target, "cherry-pick", sha, second, ok=False)
        self.assertIn("cherry-pick", denied.stderr)
        self.assertEqual(self.git_at(target, "log", "-1", "--format=%s").stdout.strip(), "picked")
        self.branch("allow-cherry-pick", "--commit", second, "--approval", "review-124",
                    "--reason", "second backport", repo=target)
        self.git_at(target, "-c", "core.editor=true", "cherry-pick", "--continue")
        replay = self.git_at(target, "cherry-pick", "--keep-redundant-commits", sha, ok=False)
        self.assertIn("cherry-pick", replay.stderr)

    def test_conflicted_pick_keeps_its_exception_until_resolution(self):
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "clash").write_text("source\n", encoding="utf-8")
        self.git_at(source, "add", "clash")
        self.git_at(source, "commit", "-m", "source clash")
        sha = self.git_at(source, "rev-parse", "HEAD").stdout.strip()
        target = Path(self.begin("target", branch="target")["worktree"])
        (target / "clash").write_text("target\n", encoding="utf-8")
        self.git_at(target, "add", "clash")
        self.git_at(target, "commit", "-m", "target clash")
        self.branch("allow-cherry-pick", "--commit", sha, "--approval", "review-conflict",
                    "--reason", "resolve conflict", repo=target)
        self.git_at(target, "cherry-pick", sha, ok=False)
        (target / "clash").write_text("resolved\n", encoding="utf-8")
        self.git_at(target, "add", "clash")
        self.git_at(target, "commit", "-m", "resolve picked conflict")
        self.assertEqual((target / "clash").read_text(encoding="utf-8"), "resolved\n")

    def test_stale_merge_ticket_is_rejected_then_can_be_prepared_again(self):
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "one").write_text("one\n", encoding="utf-8")
        self.git_at(source, "add", "one")
        self.git_at(source, "commit", "-m", "one")
        self.branch("prepare-merge", "--task", "source")
        (source / "two").write_text("two\n", encoding="utf-8")
        self.git_at(source, "add", "two")
        self.git_at(source, "commit", "-m", "two")
        self.git("merge", "--no-ff", "--no-commit", "source")
        self.git("commit", "-m", "stale merge", ok=False)
        self.git("merge", "--abort")
        self.branch("prepare-merge", "--task", "source")
        self.git("merge", "--no-ff", "--no-commit", "source")
        self.git("commit", "-m", "fresh merge")

    def test_continue_sync_imports_only_the_fetched_same_branch_fast_forward(self):
        self.begin("integration", "adopt", branch="main", into="main")
        topic = Path(self.begin("topic", branch="topic")["worktree"])
        publisher = self.root / "publisher"
        self.command("git", "clone", self.remote, publisher)
        self.git_at(publisher, "config", "user.name", "Publisher")
        self.git_at(publisher, "config", "user.email", "publisher@example.invalid")
        self.git_at(publisher, "switch", "-c", "topic", "origin/main")
        (publisher / "remote").write_text("remote\n", encoding="utf-8")
        self.git_at(publisher, "add", "remote")
        self.git_at(publisher, "commit", "-m", "remote topic")
        self.git_at(publisher, "push", "origin", "topic")
        self.git_at(topic, "fetch", "origin")
        self.branch("begin", "--mode", "continue", "--task", "topic", "--sync", repo=topic)
        self.git_at(topic, "merge", "--ff-only", "origin/topic")
        self.branch("begin", "--mode", "continue", "--task", "topic", "--sync", repo=topic, ok=False)

    def test_retries_a_commit_after_the_preserved_hook_rejects_it(self):
        legacy = self.root / "retry legacy"
        self.command("git", "clone", self.remote, legacy)
        self.git_at(legacy, "config", "user.name", "Test User")
        self.git_at(legacy, "config", "user.email", "test@example.invalid")
        original = legacy / ".git" / "hooks" / "prepare-commit-msg"
        original.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
        original.chmod(0o755)
        transaction = legacy / ".git" / "hooks" / "reference-transaction"
        transaction.write_text(
            "#!/bin/sh\n[ \"$1\" = prepared ] && [ -e reject ] && exit 1\nexit 0\n",
            encoding="utf-8", newline="\n",
        )
        transaction.chmod(0o755)
        self.branch("install", repo=legacy)
        self.begin("legacy-main", "adopt", repo=legacy, branch="main", into="main")
        topic = Path(self.begin("retry", repo=legacy, branch="retry")["worktree"])
        (topic / "retry").write_text("retry\n", encoding="utf-8")
        self.git_at(topic, "add", "retry")
        sentinel = topic / "reject"
        sentinel.write_text("reject\n", encoding="utf-8")
        self.git_at(topic, "commit", "-m", "rejected", ok=False)
        sentinel.unlink()
        self.git_at(topic, "commit", "-m", "retried")


if __name__ == "__main__":
    unittest.main()

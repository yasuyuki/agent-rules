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
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLACE = Path(os.environ.get("AGENT_RULES_PLACE", ROOT / "bin" / "place.py"))


class BranchManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="branch management ")
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

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *argv, cwd=None, ok=True, input=None):
        result = subprocess.run(argv, cwd=cwd, text=True, input=input,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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

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

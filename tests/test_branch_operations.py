"""Operation receipts through the installed branch command and real Git."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import importlib.util

from test_branch_management import BranchManagementTests, PLACE


def loaded_management():
    """Load the engine beside the selected place command (source or wheel)."""
    spec = importlib.util.spec_from_file_location("operation_management", PLACE.parent / "branch_management.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationTests(BranchManagementTests):
    def sync_topic(self, task="topic"):
        topic = Path(self.begin(task, branch=task)["worktree"])
        publisher = self.root / ("publisher " + task)
        self.command("git", "clone", self.remote, publisher)
        self.git_at(publisher, "config", "user.name", "Publisher")
        self.git_at(publisher, "config", "user.email", "publisher@example.invalid")
        self.git_at(publisher, "switch", "-c", task, "origin/main")
        (publisher / "remote").write_bytes(b"remote\x00bytes\n")
        self.git_at(publisher, "add", "remote")
        self.git_at(publisher, "commit", "-m", "remote")
        self.git_at(publisher, "push", "origin", task)
        self.git_at(topic, "fetch", "origin")
        return topic

    def prepare_sync(self, topic, ok=True):
        return self.branch("begin", "--mode", "continue", "--task", "topic", "--sync", repo=topic, ok=ok)

    def operation(self, repo, ok=True):
        return self.checked_operation(repo) if ok else json.loads(self.branch("check", "--json", repo=repo, ok=False).stdout)["operations"][-1]

    def test_sync_refusal_preserves_head_index_and_bytes(self):
        topic = self.sync_topic()
        (topic / "staged").write_bytes(b"\x00staged\xff")
        (topic / "staged").chmod(0o755)
        self.git_at(topic, "add", "staged")
        (topic / "README").write_bytes(b"unstaged\x00")
        (topic / "untracked").write_bytes(b"\xffuntracked")
        (topic / "untracked").chmod(0o640)
        index = Path(self.git_at(topic, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip())
        before = (self.git_at(topic, "rev-parse", "HEAD").stdout, index.read_bytes(),
                  (topic / "staged").read_bytes(), (topic / "README").read_bytes(),
                  (topic / "untracked").read_bytes())
        self.prepare_sync(topic, ok=False)
        self.assertEqual(before, (self.git_at(topic, "rev-parse", "HEAD").stdout, index.read_bytes(),
                                  (topic / "staged").read_bytes(), (topic / "README").read_bytes(),
                                  (topic / "untracked").read_bytes()))
        checked = json.loads(self.branch("check", "--json", repo=topic).stdout)
        self.assertEqual(checked["operations"][-1]["before"], checked["operations"][-1]["current"])
        if os.name != "nt":
            self.assertEqual((topic / "staged").stat().st_mode & 0o777, 0o755)
            self.assertEqual((topic / "untracked").stat().st_mode & 0o777, 0o640)

    def test_sync_combines_real_remote_result_and_diagnostic_is_nonwriting(self):
        topic = self.sync_topic()
        self.prepare_sync(topic)
        prepared = self.checked_operation(topic)
        self.assertIn("id", prepared); self.assertIn("before", prepared)
        self.git_at(topic, "merge", "--ff-only", "origin/topic")
        self.assertEqual((topic / "remote").read_bytes(), b"remote\x00bytes\n")
        index = Path(self.git_at(topic, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip())
        before = index.read_bytes()
        completed = self.checked_operation(topic)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(completed["id"], prepared["id"])
        self.assertEqual(completed["before"], prepared["before"])
        self.assertEqual(completed["outcome"], "completed")

    def test_sync_rejects_same_path_and_index_only_contamination(self):
        topic = self.sync_topic()
        self.prepare_sync(topic)
        prepared = self.checked_operation(topic)
        (topic / "README").write_bytes(b"other editor\x00")
        self.git_at(topic, "merge", "--ff-only", "origin/topic", ok=False)
        failed = self.operation(topic, ok=False)
        self.assertEqual(failed["id"], prepared["id"])
        self.assertEqual(failed["before"], prepared["before"])
        self.assertEqual((topic / "README").read_bytes(), b"other editor\x00")
        self.prepare_sync(topic, ok=False)
        target = self.sync_topic("index-topic")
        self.branch("begin", "--mode", "continue", "--task", "index-topic", "--sync", repo=target)
        blob = self.git_at(target, "hash-object", "-w", "--stdin", input="index only").stdout.strip()
        self.git_at(target, "update-index", "--cacheinfo", "100644," + blob + ",README")
        failed = self.operation(target, ok=False)
        self.assertEqual(failed["outcome"], "unknown")

    def test_sync_partial_index_update_keeps_the_original_receipt_for_resume(self):
        topic = self.sync_topic()
        self.prepare_sync(topic)
        prepared = self.checked_operation(topic)
        self.git_at(topic, "read-tree", "-m", "-u", "HEAD", "origin/topic")
        partial = self.operation(topic, ok=False)
        self.assertEqual((partial["id"], partial["before"], partial["outcome"]),
                         (prepared["id"], prepared["before"], "partial-update"))
        self.prepare_sync(topic)
        self.git_at(topic, "merge", "--ff-only", "origin/topic")
        resumed = self.checked_operation(topic)
        self.assertEqual((resumed["id"], resumed["before"], resumed["outcome"]),
                         (prepared["id"], prepared["before"], "completed"))

    def test_pick_conflict_can_resume_only_the_conflicted_path(self):
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "clash").write_bytes(b"source\n")
        self.git_at(source, "add", "clash"); self.git_at(source, "commit", "-m", "source")
        commit = self.git_at(source, "rev-parse", "HEAD").stdout.strip()
        target = Path(self.begin("target", branch="target")["worktree"])
        (target / "clash").write_bytes(b"target\n")
        self.git_at(target, "add", "clash"); self.git_at(target, "commit", "-m", "target")
        self.branch("allow-cherry-pick", "--commit", commit, "--approval", "review", "--reason", "conflict", repo=target)
        self.git_at(target, "cherry-pick", commit, ok=False)
        receipt = self.operation(target, ok=False)
        self.assertEqual(receipt["outcome"], "conflict")
        (target / "unrelated").write_bytes(b"keep\x00")
        self.git_at(target, "add", "unrelated")
        self.branch("allow-cherry-pick", "--commit", commit, "--approval", "review", "--reason", "resume", repo=target, ok=False)
        self.assertEqual((target / "unrelated").read_bytes(), b"keep\x00")

    def test_merge_records_a_real_combined_tree(self):
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("source", branch="source")["worktree"])
        target = self.integrate("target", name="target-only", contents="target\x00\n")
        target_bytes = (target / "target-only").read_bytes()
        (source / "source-only").write_bytes(b"source\x00\n")
        self.git_at(source, "add", "source-only"); self.git_at(source, "commit", "-m", "source")
        self.branch("prepare-merge", "--task", "source")
        receipt = self.checked_operation(self.repo)
        self.git("merge", "--no-ff", "--no-commit", "source")
        self.git("commit", "-m", "merge source")
        self.assertEqual((self.repo / "source-only").read_bytes(), b"source\x00\n")
        self.assertEqual((self.repo / "target-only").read_bytes(), target_bytes)
        completed = self.checked_operation(self.repo)
        self.assertEqual((completed["id"], completed["before"], completed["outcome"]),
                         (receipt["id"], receipt["before"], "completed"))

    def test_merge_rejects_same_source_path_contamination_before_commit(self):
        self.begin("integration", "adopt", branch="main", into="main")
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "shared").write_bytes(b"approved\n")
        self.git_at(source, "add", "shared"); self.git_at(source, "commit", "-m", "approved")
        self.branch("prepare-merge", "--task", "source")
        self.git("merge", "--no-ff", "--no-commit", "source")
        (self.repo / "shared").write_bytes(b"contaminated\x00")
        self.git("add", "shared")
        before = self.git("rev-parse", "HEAD").stdout
        staged = self.git("ls-files", "--stage", "-z").stdout
        denied = self.git("commit", "-m", "contaminated merge", ok=False)
        self.assertIn("expected result", denied.stderr.lower())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertEqual((self.repo / "shared").read_bytes(), b"contaminated\x00")
        self.assertEqual(self.git("ls-files", "--stage", "-z").stdout, staged)
        diagnosis = json.loads(self.branch("check", "--json", ok=False).stdout)["operations"][-1]
        self.assertEqual(diagnosis["outcome"], "unknown")
        self.assertIn("shared", diagnosis["separate_changes"])
        original = (diagnosis["id"], diagnosis["before"])
        self.branch("prepare-merge", "--task", "source", ok=False)
        retried = self.checked_operation(self.repo)
        self.assertEqual((retried["id"], retried["before"]), original)

    def test_ignored_incoming_collision_is_refused_without_overwrite(self):
        topic = Path(self.begin("ignored", branch="ignored")["worktree"])
        publisher = self.root / "ignored publisher"
        self.command("git", "clone", self.remote, publisher)
        self.git_at(publisher, "config", "user.name", "Publisher")
        self.git_at(publisher, "config", "user.email", "publisher@example.invalid")
        self.git_at(publisher, "switch", "-c", "ignored", "origin/main")
        (publisher / "incoming").write_bytes(b"remote\x00")
        self.git_at(publisher, "add", "incoming"); self.git_at(publisher, "commit", "-m", "incoming")
        self.git_at(publisher, "push", "origin", "ignored")
        self.git_at(topic, "fetch", "origin")
        exclude = Path(self.git_at(topic, "rev-parse", "--git-path", "info/exclude").stdout.strip())
        exclude.write_text("incoming\n", encoding="utf-8")
        (topic / "incoming").write_bytes(b"local ignored\x00")
        before = (self.git_at(topic, "rev-parse", "HEAD").stdout, (topic / "incoming").read_bytes())
        result = self.branch("begin", "--mode", "continue", "--task", "ignored", "--sync", repo=topic, ok=False)
        self.assertIn("collision", result.stderr.lower())
        self.assertEqual(before, (self.git_at(topic, "rev-parse", "HEAD").stdout, (topic / "incoming").read_bytes()))

    def test_completed_pick_does_not_mask_a_later_failed_pick(self):
        source = Path(self.begin("source", branch="source")["worktree"])
        (source / "clash").write_bytes(b"source\n")
        self.git_at(source, "add", "clash"); self.git_at(source, "commit", "-m", "source")
        commit = self.git_at(source, "rev-parse", "HEAD").stdout.strip()
        target = Path(self.begin("target", branch="target")["worktree"])
        self.branch("allow-cherry-pick", "--commit", commit, "--approval", "one", "--reason", "first", repo=target)
        self.git_at(target, "cherry-pick", commit)
        receipt = self.checked_operation(target)
        self.assertEqual(receipt["outcome"], "completed")
        # Retain an active sequencer whose source does not match the old receipt.
        (source / "clash").write_bytes(b"second\n")
        self.git_at(source, "add", "clash"); self.git_at(source, "commit", "-m", "second")
        second = self.git_at(source, "rev-parse", "HEAD").stdout.strip()
        (target / "clash").write_bytes(b"local\n")
        self.git_at(target, "add", "clash"); self.git_at(target, "commit", "-m", "local")
        self.git_at(target, "cherry-pick", second, ok=False)
        failed = self.operation(target, ok=False)
        self.assertNotEqual(failed["outcome"], "completed")
        self.assertEqual(failed["id"], receipt["id"])

    def test_crlf_and_binary_sync_preserve_git_identity(self):
        topic = self.sync_topic()
        publisher = self.root / "publisher topic"
        (publisher / "text").write_bytes(b"one\ntwo\n")
        self.git_at(publisher, "add", "text"); self.git_at(publisher, "commit", "-m", "text")
        self.git_at(publisher, "push", "origin", "topic")
        self.git_at(topic, "fetch", "origin"); self.git_at(topic, "config", "core.autocrlf", "true")
        self.prepare_sync(topic); self.git_at(topic, "merge", "--ff-only", "origin/topic")
        self.assertEqual((topic / "remote").read_bytes(), b"remote\x00bytes\n")
        self.assertEqual((topic / "text").read_bytes(), b"one\r\ntwo\r\n")

    def test_check_does_not_run_filters_or_write_state_index_or_worktree(self):
        topic = self.sync_topic()
        self.prepare_sync(topic)
        counter = self.root / "filter-count"
        script = self.root / "count-filter.py"
        script.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('ran')\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
        command = '"' + Path(sys.executable).as_posix() + '" "' + script.as_posix() + '" "' + counter.as_posix() + '"'
        info = Path(self.git_at(topic, "rev-parse", "--path-format=absolute", "--git-path", "info/attributes").stdout.strip())
        info.write_text("README filter=count\n", encoding="utf-8")
        self.git_at(topic, "config", "filter.count.clean", command)
        self.git_at(topic, "config", "filter.count.smudge", command)
        self.git_at(topic, "config", "filter.count.required", "true")
        self.git_at(topic, "hash-object", "--path=README", "--stdin", input="filter probe\n")
        self.assertEqual(counter.read_text(), "ran")  # Prove the fixture can actually run.
        counter.unlink()
        index = Path(self.git_at(topic, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip())
        state = Path(self.git_at(topic, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / "agent-branches/state.json"
        before = (index.read_bytes(), state.read_bytes(), (topic / "README").read_bytes())
        checked = json.loads(self.branch("check", "--json", repo=topic, ok=False).stdout)
        self.assertEqual(checked["operations"][-1]["outcome"], "unknown")
        self.assertIn("README", checked["operations"][-1]["unverified_worktree_paths"])
        self.assertFalse(counter.exists())
        self.assertEqual(before, (index.read_bytes(), state.read_bytes(), (topic / "README").read_bytes()))

    def _interrupt_managed_reference_hook(self, topic, phase, expected_new):
        """Stop at managed-hook entry, before that phase can notify durable state."""
        if os.name == "nt":
            self.skipTest("POSIX process-group signals are unavailable on Windows")
        marker = self.root / ("managed-" + phase)
        site = self.root / "sitecustomize.py"
        site.write_text("import os, pathlib, signal, sys\n"
                        "MARKER = pathlib.Path(" + repr(str(marker)) + ")\n"
                        "PHASE = " + repr(phase) + "\n"
                        "NEW = " + repr(expected_new.encode()) + "\n"
                        "def trace(frame, event, arg):\n"
                        "    data = frame.f_locals.get('data', b'')\n"
                        "    if event == 'line' and frame.f_code.co_name == 'hook' and frame.f_code.co_filename.endswith('branch_management.py') and frame.f_locals.get('name') == 'reference-transaction' and frame.f_locals.get('args') == [PHASE] and NEW in data and b' refs/heads/topic' in data:\n"
                        "        MARKER.write_text(str(os.getpid()))\n"
                        "        os.kill(os.getpid(), signal.SIGSTOP)\n"
                        "    return trace\n"
                        "sys.settrace(trace)\n", encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(self.root) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        child = subprocess.Popen(["git", "-C", str(topic), "merge", "--ff-only", "origin/topic"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            self.assertTrue(marker.exists(), "managed hook did not reach " + phase)
        finally:
            os.killpg(child.pid, signal.SIGKILL)
        out, err = child.communicate(timeout=15)
        self.assertLess(child.returncode, 0, out + err)
        return marker, out, err

    def test_posix_kill_before_prepared_notification_keeps_pending_receipt(self):
        topic = self.sync_topic()
        self.prepare_sync(topic)
        receipt = self.checked_operation(topic)
        old = self.git_at(topic, "rev-parse", "HEAD").stdout.strip()
        source = self.git_at(topic, "rev-parse", "origin/topic").stdout.strip()
        self._interrupt_managed_reference_hook(topic, "prepared", source)
        self.assertEqual(self.git_at(topic, "rev-parse", "HEAD").stdout.strip(), old)
        observed = self.checked_operation(topic)
        self.assertEqual((observed["id"], observed["before"]), (receipt["id"], receipt["before"]))
        self.assertEqual(observed["outcome"], "partial-update")
        self.assertTrue(observed["index_changed"] or observed["worktree_changed"])
        self.assertIsNone(observed["reference_completion"])
        self.assertIsNone(observed["git_exit"])
        self.prepare_sync(topic)
        resumed = self.checked_operation(topic)
        self.assertEqual((resumed["id"], resumed["before"]), (receipt["id"], receipt["before"]))

    def test_posix_kill_before_committed_notification_keeps_visible_ref_and_receipt(self):
        topic = self.sync_topic()
        self.prepare_sync(topic)
        receipt = self.checked_operation(topic)
        old = self.git_at(topic, "rev-parse", "HEAD").stdout.strip()
        source = self.git_at(topic, "rev-parse", "origin/topic").stdout.strip()
        self._interrupt_managed_reference_hook(topic, "committed", source)
        self.assertNotEqual(self.git_at(topic, "rev-parse", "HEAD").stdout.strip(), old)
        observed = self.checked_operation(topic)
        self.assertEqual((observed["id"], observed["before"]), (receipt["id"], receipt["before"]))
        self.assertEqual(observed["reference_completion"], source)
        self.assertEqual(observed["outcome"], "completed")
        self.assertIsNone(observed["git_exit"])
        self.branch("begin", "--mode", "continue", "--task", "topic", repo=topic)
        resumed = json.loads(self.branch("check", "--json", repo=topic).stdout)["operations"][-1]
        self.assertEqual((resumed["id"], resumed["before"]), (receipt["id"], receipt["before"]))
        self.assertEqual(resumed["completed"], source)
        self.assertIsNone(resumed["git_exit"])


class AtomicReceiptTests(unittest.TestCase):
    def test_atomic_fsyncs_file_before_directory_and_does_not_replace_on_file_failure(self):
        management = loaded_management()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            path.write_text("old\n", encoding="utf-8")
            observed = []
            real_fsync = management.os.fsync
            with patch.object(management.os, "fsync", side_effect=lambda fd: (observed.append(fd), real_fsync(fd))[1]):
                management.atomic(path, {"new": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"new": True})
            self.assertGreaterEqual(len(observed), 2 if os.name != "nt" else 1)
            with patch.object(management.os, "fsync", side_effect=OSError("injected fsync failure")):
                with self.assertRaises(OSError):
                    management.atomic(path, {"lost": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"new": True})
            calls = []
            def fail_directory(fd):
                calls.append(fd)
                if len(calls) == 2:
                    raise OSError("injected directory fsync failure")
                return real_fsync(fd)
            if os.name != "nt":
                with patch.object(management.os, "fsync", side_effect=fail_directory):
                    with self.assertRaisesRegex(OSError, "directory fsync"):
                        management.atomic(path, {"durable-after-rename": True})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"durable-after-rename": True})


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite(OperationTests(name) for name in OperationTests.__dict__ if name.startswith("test_"))
    suite.addTests(AtomicReceiptTests(name) for name in AtomicReceiptTests.__dict__ if name.startswith("test_"))
    return suite


if __name__ == "__main__":
    unittest.main()

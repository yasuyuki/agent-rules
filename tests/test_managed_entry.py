"""The standard-name links stay bounded and do not hide vendor executables."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("managed_entry_test", ROOT / "bin" / "managed_entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def executable(path, body="# !/bin/sh\nexit 0\n"):
    path.write_text(body.replace("# !", "#!"), encoding="utf-8")
    path.chmod(0o755)


@unittest.skipIf(os.name == 'nt', 'standard-name installation is POSIX-only')
class ManagedEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.vendor = self.root / "vendor"
        self.managed = self.root / "managed"
        self.vendor.mkdir()
        self.managed.mkdir()
        self.config = self.root / "placement-start.json"
        self.config.write_text("{}", encoding="utf-8")
        executable(self.vendor / "grok")

    def tearDown(self):
        self.temporary.cleanup()

    @property
    def path(self):
        return os.pathsep.join([str(self.managed), str(self.vendor)])

    def test_install_repeat_resolve_updated_vendor_and_remove(self):
        binding = entry.install(self.config, self.managed, ["grok"], path=self.path)
        original = binding.read_bytes()
        self.assertTrue((self.managed / "grok").is_symlink())
        self.assertEqual(entry.install(self.config, self.managed, ["grok"], path=self.path).read_bytes(), original)
        self.assertEqual(Path(entry.resolve_executable("grok", path=self.path)), self.vendor / "grok")
        replacement = self.vendor / "grok-2"
        executable(replacement)
        (self.vendor / "grok").unlink()
        (self.vendor / "grok").symlink_to(replacement.name)
        self.assertEqual(Path(entry.resolve_executable("grok", path=self.path)).resolve(), replacement)
        other = self.managed / "other-cli"
        executable(other)
        entry.remove(self.managed)
        self.assertTrue((self.vendor / "grok").exists())
        self.assertTrue(other.exists())
        self.assertFalse(binding.exists())

    def test_collision_and_malformed_binding_do_not_change_vendor(self):
        collision = self.managed / "grok"
        executable(collision)
        executable(self.vendor / "codex")
        with self.assertRaisesRegex(entry.EntryError, "collision"):
            entry.install(self.config, self.managed, ["grok", "codex"], path=self.path)
        self.assertTrue(collision.exists())
        self.assertFalse((self.managed / "codex").exists())
        self.assertFalse((self.managed / entry.BINDING_NAME).exists())
        collision.unlink()
        binding = self.managed / entry.BINDING_NAME
        binding.write_text("not json", encoding="utf-8")
        with self.assertRaises(entry.EntryError):
            entry.install(self.config, self.managed, ["grok"], path=self.path)
        self.assertEqual(binding.read_text(encoding="utf-8"), "not json")
        with self.assertRaises(entry.EntryError):
            entry.resolve_executable("grok", path=self.path)

    def test_missing_vendor_is_optional_but_relative_path_is_not_saved(self):
        self.assertIsNone(entry.resolve_executable("missing", path=str(self.vendor)))
        entry.install(self.config, self.managed, ["grok"], path=os.pathsep.join([".", str(self.managed), str(self.vendor)]))
        binding = entry.load_binding(self.managed)
        self.assertTrue(all(Path(item).is_absolute() for item in binding["vendor_path"]))
        self.config.unlink()
        # Maintenance resolution remains possible; normal start validates the
        # saved config itself through place.start_config.
        self.assertEqual(Path(entry.resolve_executable("grok", binding=binding)), self.vendor / "grok")

    def test_dispatcher_preserves_quoted_unicode_arguments(self):
        fake_place = self.root / "place.py"
        fake_place.write_text(
            "import json\n"
            "def main(argv, **kwargs):\n"
            " print(json.dumps(argv, ensure_ascii=False))\n"
            " return 0\n", encoding="utf-8")
        document = entry._document(self.managed, self.config, ["grok"], [str(self.vendor)], place=fake_place)
        (self.managed / entry.BINDING_NAME).write_text(json.dumps(document), encoding="utf-8")
        (self.managed / "grok").symlink_to(entry.DISPATCHER)
        result = subprocess.run([str(self.managed / "grok"), "two words", "日本語", "--json"],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["standard-start", "--config", str(self.config), "grok", "--", "two words", "日本語", "--json"])

    def test_changed_link_refuses_remove(self):
        entry.install(self.config, self.managed, ["grok"], path=self.path)
        (self.managed / "grok").unlink()
        (self.managed / "grok").symlink_to(self.vendor / "grok")
        with self.assertRaisesRegex(entry.EntryError, "changed"):
            entry.remove(self.managed)

    def test_reinstall_rebinds_vendor_path_and_adds_owned_tool(self):
        entry.install(self.config, self.managed, ["grok"], path=self.path)
        vendor2 = self.root / "vendor-2"
        vendor2.mkdir()
        executable(vendor2 / "grok")
        executable(vendor2 / "codex")
        path2 = os.pathsep.join([str(self.managed), str(vendor2)])
        entry.install(self.config, self.managed, ["grok", "codex"], path=path2)
        binding = entry.load_binding(self.managed)
        self.assertEqual(binding["tools"], ["grok", "codex"])
        self.assertEqual(binding["vendor_path"], [str(vendor2)])
        self.assertTrue((self.managed / "codex").is_symlink())
        self.assertEqual(Path(entry.resolve_executable("grok", path=path2)), vendor2 / "grok")
        with self.assertRaisesRegex(entry.EntryError, "cannot remove tools"):
            entry.install(self.config, self.managed, ["grok"], path=path2)

    def test_reinstall_from_relocated_public_source_replaces_owned_links(self):
        entry.install(self.config, self.managed, ["grok"], path=self.path)
        source = self.root / "new-public-bin"
        source.mkdir()
        for name in ("managed_entry.py", "managed-cli"):
            shutil.copy2(ROOT / "bin" / name, source / name)
        (source / "place.py").write_text("# relocated public place source\n", encoding="utf-8")
        relocated_spec = importlib.util.spec_from_file_location("relocated_entry", source / "managed_entry.py")
        relocated = importlib.util.module_from_spec(relocated_spec)
        relocated_spec.loader.exec_module(relocated)
        relocated.install(self.config, self.managed, ["grok"], path=self.path)
        binding = relocated.load_binding(self.managed)
        self.assertEqual(Path(binding["dispatcher"]), source / "managed-cli")
        self.assertEqual(Path(binding["place"]), source / "place.py")
        self.assertEqual((self.managed / "grok").resolve(), source / "managed-cli")


if __name__ == "__main__":
    unittest.main()

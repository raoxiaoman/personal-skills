import ast
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = {"develop", "refactor", "migrate-kotlin", "adapt-large-screen", "logging", "maestro", "check-release", "analyze-apk-size", "implement-ui", "analytics"}


class PluginContractsTest(unittest.TestCase):
    def test_manifest_and_entry_names(self):
        manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "forge-android")
        entries = {item.parent.name for item in (ROOT / "skills").glob("*/SKILL.md")}
        self.assertEqual(entries, SKILLS)
        for name in SKILLS:
            text = (ROOT / "skills" / name / "SKILL.md").read_text()
            self.assertTrue(text.startswith("---\n"))
            metadata = text.split("---", 2)[1]
            self.assertRegex(metadata, rf"(?m)^name: {re.escape(name)}$")
            self.assertRegex(metadata, r"(?m)^description: .+")

    def test_develop_routes_to_present_entries(self):
        text = (ROOT / "skills/develop/SKILL.md").read_text()
        for name in SKILLS - {"develop"}:
            self.assertIn("forge-android:" + name, text)
            self.assertIn("../" + name + "/SKILL.md", text)
        self.assertNotIn("尚未纳入本插件", text)
        self.assertNotIn("使用 `logging-conventions`", text)

    def test_local_markdown_links_resolve_inside_plugin(self):
        for name in SKILLS:
            directory = ROOT / "skills" / name
            for path in [directory / "SKILL.md", *directory.glob("references/*.md")]:
                for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                    if "://" in target or target.startswith("#"):
                        continue
                    resolved = (path.parent / target.split("#", 1)[0]).resolve()
                    self.assertTrue(resolved.is_relative_to(ROOT), str(resolved))
                    self.assertTrue(resolved.is_file(), str(resolved))

    def test_specialist_scripts_and_sources_are_portable(self):
        for name in ("migrate-kotlin", "adapt-large-screen", "logging", "maestro", "check-release", "analyze-apk-size", "implement-ui", "analytics"):
            for path in (ROOT / "skills" / name).rglob("*"):
                if path.suffix not in {".py", ".md"}:
                    continue
                data = path.read_bytes()
                self.assertNotIn(b"\r", data, str(path))
                self.assertNotIn(b"/Users/raohui", data, str(path))
                if path.suffix == ".py":
                    ast.parse(data, filename=str(path))
        logging = ROOT / "skills/logging"
        for name in ("temp_logs.py", "watch_android_logcat.py"):
            self.assertTrue((logging / "scripts" / name).is_file())
        self.assertFalse((logging / "tmp").exists())

    def test_specialists_do_not_require_parent_roundtrip(self):
        for name in SKILLS - {"develop", "refactor"}:
            text = (ROOT / "skills" / name / "SKILL.md").read_text()
            self.assertNotIn("先加载 android-development", text)
            self.assertLess(len(text.splitlines()), 160)


if __name__ == "__main__":
    unittest.main()

"""
Validation tests for manifest.json.in (the Ubuntu Touch click package
manifest template). This PR bumped the "version" field from 0.0.2 to
0.1.0; these tests guard the overall structure and the specific
version bump.

Run with:  python3 -m unittest discover -s tests
"""

import json
import os
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANIFEST_PATH = os.path.join(REPO_ROOT, "manifest.json.in")


class ManifestTemplateTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            cls.raw = f.read()
        cls.data = json.loads(cls.raw)

    def test_file_is_valid_json(self):
        # manifest.json.in embeds CMake $ENV{...} placeholders as plain
        # string values, so the template itself must remain valid JSON
        # both before and after CMake's configure_file substitution.
        self.assertIsInstance(self.data, dict)

    def test_required_keys_present(self):
        for key in ("name", "description", "architecture", "title", "hooks",
                    "version", "maintainer", "framework"):
            self.assertIn(key, self.data)

    def test_version_bumped_to_0_1_0(self):
        self.assertEqual(self.data["version"], "0.1.0")

    def test_architecture_and_framework_use_cmake_placeholders(self):
        self.assertEqual(self.data["architecture"], "$ENV{ARCH}")
        self.assertEqual(self.data["framework"], "$ENV{CLICK_FRAMEWORK}")

    def test_hooks_reference_apparmor_and_desktop_files(self):
        hooks = self.data["hooks"]
        self.assertIn("utgpt", hooks)
        self.assertEqual(hooks["utgpt"]["apparmor"], "utgpt.apparmor")
        self.assertEqual(hooks["utgpt"]["desktop"], "utgpt.desktop")

    def test_name_matches_click_package_naming_convention(self):
        # Click package names conventionally use lowercase, dot-separated
        # segments (e.g. "utgpt.surajyadav").
        self.assertRegex(self.data["name"], r"^[a-z0-9]+(\.[a-z0-9]+)+$")


if __name__ == "__main__":
    unittest.main()
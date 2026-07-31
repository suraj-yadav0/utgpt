"""
Tests for manifest.json.in, specifically the version bump made in this PR
(0.0.2 -> 0.1.0).

manifest.json.in is a CMake `configure_file` template (see
CMakeLists.txt: `configure_file(manifest.json.in ... manifest.json)`), so
the raw file is not valid JSON until its $ENV{...} placeholders are
substituted. These tests substitute dummy values the same way CMake would
before validating the resulting JSON structure.
"""

import json
import os
import re
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_TEMPLATE_PATH = os.path.join(ROOT_DIR, "manifest.json.in")


def render_manifest_template(raw_text, arch="armhf", framework="ubuntu-touch-24.04-1.6"):
    rendered = raw_text.replace("$ENV{ARCH}", arch)
    rendered = rendered.replace("$ENV{CLICK_FRAMEWORK}", framework)
    return rendered


class TestManifestJsonTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MANIFEST_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            cls.raw_text = f.read()
        cls.data = json.loads(render_manifest_template(cls.raw_text))

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(MANIFEST_TEMPLATE_PATH))

    def test_renders_to_valid_json(self):
        self.assertIsInstance(self.data, dict)

    def test_version_bumped_to_0_1_0(self):
        self.assertEqual(self.data["version"], "0.1.0")

    def test_version_is_semver_like(self):
        self.assertRegex(self.data["version"], r"^\d+\.\d+\.\d+$")

    def test_required_top_level_keys_present(self):
        for key in ("name", "description", "architecture", "title", "hooks", "version", "maintainer", "framework"):
            self.assertIn(key, self.data)

    def test_hooks_structure_unchanged(self):
        self.assertIn("utgpt", self.data["hooks"])
        self.assertEqual(self.data["hooks"]["utgpt"]["apparmor"], "utgpt.apparmor")
        self.assertEqual(self.data["hooks"]["utgpt"]["desktop"], "utgpt.desktop")

    def test_architecture_and_framework_placeholders_present_in_raw_template(self):
        # Ensures the template still uses CMake substitution variables
        # rather than hard-coded values that would fail on other archs.
        self.assertIn("$ENV{ARCH}", self.raw_text)
        self.assertIn("$ENV{CLICK_FRAMEWORK}", self.raw_text)


if __name__ == "__main__":
    unittest.main()
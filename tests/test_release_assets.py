"""
Validation tests for the release metadata files changed in this PR:

- assets/release_notes.json: the "What's New" content shown by
  qml/components/ReleaseNotesDialog.qml.
- manifest.json.in: the click package manifest template, whose "version"
  field was bumped as part of this PR.
"""

import json
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ReleaseNotesJsonTests(unittest.TestCase):
    def setUp(self):
        path = os.path.join(REPO_ROOT, "assets", "release_notes.json")
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_top_level_required_fields_present(self):
        for key in ("version", "date", "title", "subtitle", "features"):
            self.assertIn(key, self.data)

    def test_version_matches_expected_release(self):
        self.assertEqual(self.data["version"], "0.0.2")

    def test_date_field_has_iso_format(self):
        self.assertRegex(self.data["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_features_is_nonempty_list_of_well_formed_entries(self):
        features = self.data["features"]
        self.assertIsInstance(features, list)
        self.assertGreater(len(features), 0)
        for feature in features:
            self.assertIsInstance(feature, dict)
            for key in ("title", "icon", "description"):
                self.assertIn(key, feature)
                self.assertIsInstance(feature[key], str)
                self.assertTrue(feature[key].strip(), "{0} must not be blank".format(key))

    def test_feature_titles_are_unique(self):
        titles = [f["title"] for f in self.data["features"]]
        self.assertEqual(len(titles), len(set(titles)))

    def test_contains_exactly_the_four_shipped_features(self):
        titles = [f["title"] for f in self.data["features"]]
        self.assertEqual(
            titles,
            [
                "On-Device AI Chat",
                "Web Search Integration",
                "Multi-Session Conversations",
                "Customizable Settings & Theme",
            ],
        )


class ManifestJsonInTests(unittest.TestCase):
    def setUp(self):
        path = os.path.join(REPO_ROOT, "manifest.json.in")
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_is_valid_json_despite_env_placeholders(self):
        # manifest.json.in embeds $ENV{...} placeholders as plain string
        # values; this confirms the file still parses as valid JSON ahead of
        # CMake's configure_file() substitution step.
        self.assertIsInstance(self.data, dict)

    def test_version_bumped_to_0_1_0(self):
        self.assertEqual(self.data["version"], "0.1.0")

    def test_required_fields_present(self):
        for key in ("name", "description", "architecture", "title", "hooks", "version", "maintainer", "framework"):
            self.assertIn(key, self.data)

    def test_placeholder_fields_retain_env_syntax(self):
        self.assertEqual(self.data["architecture"], "$ENV{ARCH}")
        self.assertEqual(self.data["framework"], "$ENV{CLICK_FRAMEWORK}")

    def test_hooks_reference_apparmor_and_desktop_files(self):
        hooks = self.data["hooks"]["utgpt"]
        self.assertEqual(hooks["apparmor"], "utgpt.apparmor")
        self.assertEqual(hooks["desktop"], "utgpt.desktop")


if __name__ == "__main__":
    unittest.main()
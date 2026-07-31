"""
Tests for the assets/release_notes.json data file added in this PR.

These validate the raw asset file independently of backend.py's
get_release_notes() loader (which has its own tests in test_backend.py),
guarding against accidental schema drift or malformed content in the
shipped data file that qml/components/ReleaseNotesDialog.qml relies on.
"""

import json
import os
import re
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_NOTES_PATH = os.path.join(ROOT_DIR, "assets", "release_notes.json")


class TestReleaseNotesAsset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(RELEASE_NOTES_PATH, "r", encoding="utf-8") as f:
            cls.raw_text = f.read()
        cls.data = json.loads(cls.raw_text)

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(RELEASE_NOTES_PATH))

    def test_is_valid_json(self):
        # Would have raised in setUpClass already, but assert explicitly too.
        self.assertIsInstance(self.data, dict)

    def test_top_level_required_keys_present(self):
        for key in ("version", "date", "title", "subtitle", "features"):
            self.assertIn(key, self.data)

    def test_version_matches_expected_value(self):
        self.assertEqual(self.data["version"], "0.0.2")

    def test_date_is_iso_formatted(self):
        self.assertRegex(self.data["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_title_and_subtitle_are_non_empty_strings(self):
        self.assertIsInstance(self.data["title"], str)
        self.assertTrue(self.data["title"].strip())
        self.assertIsInstance(self.data["subtitle"], str)
        self.assertTrue(self.data["subtitle"].strip())

    def test_features_is_a_non_empty_list(self):
        self.assertIsInstance(self.data["features"], list)
        self.assertGreater(len(self.data["features"]), 0)

    def test_each_feature_has_required_fields(self):
        for feature in self.data["features"]:
            self.assertIsInstance(feature, dict)
            for key in ("title", "icon", "description"):
                self.assertIn(key, feature)
                self.assertIsInstance(feature[key], str)
                self.assertTrue(feature[key].strip(), "{0} must not be empty".format(key))

    def test_feature_titles_are_unique(self):
        titles = [f["title"] for f in self.data["features"]]
        self.assertEqual(len(titles), len(set(titles)))

    def test_expected_feature_set_matches_shipped_content(self):
        # Regression guard for this PR's specific payload; update
        # deliberately if the release notes content is intentionally
        # revised in a future PR.
        expected_titles = {
            "On-Device AI Chat",
            "Web Search Integration",
            "Multi-Session Conversations",
            "Customizable Settings & Theme",
        }
        actual_titles = {f["title"] for f in self.data["features"]}
        self.assertEqual(actual_titles, expected_titles)

    def test_no_trailing_or_leading_whitespace_issues_in_raw_file(self):
        # Sanity check that the file parses cleanly with UTF-8 and has no
        # stray control characters that would break JSON parsers.
        self.assertNotIn("\ufeff", self.raw_text)  # no BOM


if __name__ == "__main__":
    unittest.main()
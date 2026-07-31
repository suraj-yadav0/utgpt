"""
Schema/content validation tests for assets/release_notes.json.

This file is new in this pull request and is consumed at runtime by
backend.get_release_notes() (see backend/backend.py) and rendered by
qml/components/ReleaseNotesDialog.qml. These tests guard against
accidental structural regressions (missing keys, wrong types, empty
required fields) that would otherwise only surface at runtime in the UI.

Run with:  python3 -m unittest discover -s tests
"""

import json
import os
import re
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RELEASE_NOTES_PATH = os.path.join(REPO_ROOT, "assets", "release_notes.json")


class ReleaseNotesAssetTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue_ = unittest.TestCase.assertTrue
        with open(RELEASE_NOTES_PATH, "r", encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(RELEASE_NOTES_PATH))

    def test_top_level_is_object(self):
        self.assertIsInstance(self.data, dict)

    def test_required_top_level_keys_present(self):
        for key in ("version", "date", "title", "subtitle", "features"):
            self.assertIn(key, self.data)

    def test_version_is_non_empty_semver_like_string(self):
        version = self.data["version"]
        self.assertIsInstance(version, str)
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_date_matches_iso_format(self):
        date = self.data["date"]
        self.assertIsInstance(date, str)
        self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")

    def test_title_and_subtitle_are_non_empty_strings(self):
        self.assertIsInstance(self.data["title"], str)
        self.assertTrue(self.data["title"].strip())
        self.assertIsInstance(self.data["subtitle"], str)
        self.assertTrue(self.data["subtitle"].strip())

    def test_features_is_non_empty_list(self):
        features = self.data["features"]
        self.assertIsInstance(features, list)
        self.assertGreater(len(features), 0)

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

    def test_matches_backend_default_fallback_shape(self):
        # backend.get_release_notes() falls back to a default dict with the
        # same top-level keys when this file is missing/corrupt. Ensure the
        # real file conforms to that same shape (same key set at minimum).
        default_keys = {"version", "date", "title", "subtitle", "features"}
        self.assertTrue(default_keys.issubset(self.data.keys()))


if __name__ == "__main__":
    unittest.main()
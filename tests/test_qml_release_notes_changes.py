"""
Static/structural tests for the "release notes" QML changes introduced in
this pull request:

  * qml/Main.qml
  * qml/components/ReleaseNotesDialog.qml
  * qml/pages/SettingsPage.qml

No Qt/QML runtime (qmlscene, qmllint, PyOtherSide, a display server, etc.)
is available in this environment, so a full behavioral/UI test is not
feasible here. Instead these tests perform source-level verification
(balanced braces as a coarse syntax sanity check, plus targeted regex
assertions on the specific properties/functions/signals/bindings added by
this PR) to guard against accidental regressions when the QML files are
edited in the future.

Run with:  python3 -m unittest discover -s tests
"""

import os
import re
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_QML_PATH = os.path.join(REPO_ROOT, "qml", "Main.qml")
RELEASE_NOTES_DIALOG_PATH = os.path.join(REPO_ROOT, "qml", "components", "ReleaseNotesDialog.qml")
SETTINGS_PAGE_PATH = os.path.join(REPO_ROOT, "qml", "pages", "SettingsPage.qml")


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def assert_balanced_braces(text):
    return text.count("{") == text.count("}")


class MainQmlTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(MAIN_QML_PATH)

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(MAIN_QML_PATH))

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "Main.qml has unbalanced braces")

    def test_app_settings_declares_last_seen_version_property(self):
        self.assertRegex(self.text, r'property\s+string\s+lastSeenVersion\s*:\s*""')

    def test_root_declares_current_version_and_release_notes_data_properties(self):
        self.assertRegex(self.text, r'property\s+string\s+currentVersion\s*:\s*""')
        self.assertRegex(self.text, r'property\s+var\s+releaseNotesData\s*:\s*null')

    def test_show_release_notes_function_defined(self):
        match = re.search(
            r"function\s+showReleaseNotes\s*\(\s*\)\s*\{(.*?)\n\s*\}",
            self.text,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "showReleaseNotes() function not found")
        body = match.group(1)
        self.assertIn("if (root.releaseNotesData)", body)
        self.assertIn("PopupUtils.open(releaseNotesDialogComponent, root", body)
        self.assertIn('"releaseNotesData": root.releaseNotesData', body)

    def test_release_notes_dialog_component_registered(self):
        match = re.search(
            r"Component\s*\{\s*id:\s*releaseNotesDialogComponent\s*(.*?)\}",
            self.text,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "releaseNotesDialogComponent Component not found")
        self.assertIn("ReleaseNotesDialog", match.group(1))

    def test_initialize_callback_stores_version_and_release_notes(self):
        self.assertIn('root.currentVersion = result.version || ""', self.text)
        self.assertIn("root.releaseNotesData = result.releaseNotes || null", self.text)

    def test_initialize_callback_shows_release_notes_on_version_change(self):
        pattern = (
            r"if\s*\(root\.releaseNotesData\s*&&\s*root\.releaseNotesData\.version\s*&&\s*"
            r"appSettings\.lastSeenVersion\s*!==\s*root\.releaseNotesData\.version\)\s*\{"
            r"\s*showReleaseNotes\(\)\s*"
            r"appSettings\.lastSeenVersion\s*=\s*root\.releaseNotesData\.version"
        )
        self.assertRegex(self.text, pattern)

    def test_settings_page_show_release_notes_signal_wired_to_root(self):
        self.assertRegex(self.text, r"onShowReleaseNotes:\s*root\.showReleaseNotes\(\)")


class ReleaseNotesDialogQmlTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(RELEASE_NOTES_DIALOG_PATH)

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(RELEASE_NOTES_DIALOG_PATH))

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "ReleaseNotesDialog.qml has unbalanced braces")

    def test_is_a_dialog_with_release_notes_data_property(self):
        self.assertIsNotNone(re.search(r"^Dialog\s*\{", self.text, re.MULTILINE))
        self.assertRegex(self.text, r'property\s+var\s+releaseNotesData\s*:\s*null')

    def test_title_falls_back_when_no_release_notes_data(self):
        self.assertIn(
            'title: (releaseNotesData && releaseNotesData.title) ? releaseNotesData.title : i18n.tr("What\'s New")',
            self.text,
        )

    def test_version_badge_only_visible_when_version_present(self):
        self.assertIn(
            "visible: !!(dialog.releaseNotesData && dialog.releaseNotesData.version)",
            self.text,
        )

    def test_features_repeater_defaults_to_empty_list(self):
        self.assertIn(
            "model: (dialog.releaseNotesData && dialog.releaseNotesData.features) ? dialog.releaseNotesData.features : []",
            self.text,
        )

    def test_feature_delegate_has_safe_fallbacks_for_missing_fields(self):
        self.assertIn('name: modelData.icon || "info"', self.text)
        self.assertIn('text: modelData.title || ""', self.text)
        self.assertIn('text: modelData.description || ""', self.text)

    def test_close_button_closes_dialog(self):
        self.assertRegex(self.text, r'text:\s*i18n\.tr\("Got It!"\)')
        self.assertIn("onClicked: PopupUtils.close(dialog)", self.text)


class SettingsPageQmlTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(SETTINGS_PAGE_PATH)

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(SETTINGS_PAGE_PATH))

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "SettingsPage.qml has unbalanced braces")

    def test_show_release_notes_signal_declared(self):
        self.assertRegex(self.text, r"signal\s+showReleaseNotes\s*\(\s*\)")

    def test_release_notes_list_item_present(self):
        self.assertRegex(
            self.text,
            r'ListElement\s*\{\s*title:\s*"What\'s New & Release Notes";\s*icon:\s*"info";\s*section:\s*"releasenotes"\s*\}',
        )

    def test_release_notes_click_handler_emits_signal_instead_of_switching_section(self):
        match = re.search(
            r'onClicked:\s*\{(.*?)\n\s*\}\s*\}\s*\}\s*\n\s*\}',
            self.text,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "onClicked handler block not found")
        body = match.group(1)
        self.assertIn('if (model.section === "releasenotes")', body)
        self.assertIn("settingsPage.showReleaseNotes()", body)
        self.assertIn("settingsPage.currentSection = model.section", body)


if __name__ == "__main__":
    unittest.main()
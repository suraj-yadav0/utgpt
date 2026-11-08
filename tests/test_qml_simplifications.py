"""
Static verification tests for Ponytail frontend simplifications in QML files.
"""

import os
import re
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_QML_PATH = os.path.join(REPO_ROOT, "qml", "Main.qml")
CHAT_PAGE_PATH = os.path.join(REPO_ROOT, "qml", "pages", "ChatPage.qml")
SETTINGS_PAGE_PATH = os.path.join(REPO_ROOT, "qml", "pages", "SettingsPage.qml")
DOWNLOAD_PAGE_PATH = os.path.join(REPO_ROOT, "qml", "pages", "DownloadPage.qml")


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def assert_balanced_braces(text):
    return text.count("{") == text.count("}")


class MainQmlSimplificationsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(MAIN_QML_PATH)

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "Main.qml has unbalanced braces")

    def test_settings_property_aliases_present(self):
        aliases = [
            "selectedModel",
            "temperature",
            "maxTokens",
            "threads",
            "ctxSize",
            "flashAttn",
            "kvCache",
            "themeMode",
            "webSearchEnabled",
            "webSearchMode",
        ]
        for prop in aliases:
            pattern = rf"property\s+alias\s+{prop}\s*:\s*appSettings\.{prop}"
            self.assertRegex(self.text, pattern, f"Missing property alias for {prop}")

    def test_redundant_sync_handlers_removed(self):
        redundant_handlers = [
            r"onSelectedModelChanged\s*:\s*appSettings\.selectedModel\s*=\s*selectedModel",
            r"onTemperatureChanged\s*:\s*appSettings\.temperature\s*=\s*temperature",
            r"onMaxTokensChanged\s*:\s*appSettings\.maxTokens\s*=\s*maxTokens",
            r"onThreadsChanged\s*:\s*appSettings\.threads\s*=\s*threads",
            r"onCtxSizeChanged\s*:\s*appSettings\.ctxSize\s*=\s*ctxSize",
            r"onFlashAttnChanged\s*:\s*appSettings\.flashAttn\s*=\s*flashAttn",
            r"onKvCacheChanged\s*:\s*appSettings\.kvCache\s*=\s*kvCache",
            r"onWebSearchEnabledChanged\s*:\s*appSettings\.webSearchEnabled\s*=\s*webSearchEnabled",
        ]
        for handler in redundant_handlers:
            self.assertNotRegex(self.text, handler, f"Found redundant handler {handler}")

    def test_theme_mode_changed_triggers_update_theme(self):
        self.assertRegex(self.text, r"onThemeModeChanged\s*:\s*updateTheme\(\)")

    def test_sidebar_overlay_has_no_manual_dragging(self):
        overlay_match = re.search(
            r"Rectangle\s*\{\s*id:\s*sidebarOverlay(.*?)\n\s*\}",
            self.text,
            re.DOTALL,
        )
        self.assertIsNotNone(overlay_match, "sidebarOverlay Rectangle not found")
        overlay_body = overlay_match.group(1)
        self.assertNotIn("isDragging", overlay_body)
        self.assertNotIn("deltaX", overlay_body)
        self.assertIn("onClicked: root.sidebarOpen = false", overlay_body)


class ChatPageSimplificationsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(CHAT_PAGE_PATH)

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "ChatPage.qml has unbalanced braces")

    def test_build_history_context_defined(self):
        self.assertIn("function buildHistoryContext()", self.text)

    def test_save_assistant_response_defined(self):
        self.assertIn("function saveAssistantResponse(text)", self.text)

    def test_helpers_used_in_operations(self):
        self.assertIn("saveAssistantResponse(lastItem.text)", self.text)
        self.assertIn("var history = buildHistoryContext()", self.text)

    def test_sources_chip_flow_present(self):
        self.assertIn("id: sourcesContainer", self.text)
        self.assertIn("parsedSources", self.text)
        self.assertIn("Qt.openUrlExternally(modelData.url)", self.text)

    def test_web_search_status_dynamic_binding(self):
        self.assertIn("property string webSearchStatusText", self.text)
        self.assertIn("text: chatPage.webSearchStatusText", self.text)
        self.assertIn("chatPage.activeSources = data.payload.sources", self.text)

    def test_web_search_3way_mode_toggle(self):
        self.assertIn("property string webSearchMode", self.text)
        self.assertIn('i18n.tr("Web Auto")', self.text)
        self.assertIn('i18n.tr("Web On")', self.text)
        self.assertIn('i18n.tr("Web Off")', self.text)


class SettingsPageSimplificationsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(SETTINGS_PAGE_PATH)

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "SettingsPage.qml has unbalanced braces")

    def test_inference_engine_status_event_handled(self):
        self.assertIn('data.event === "inference_engine_status"', self.text)
        self.assertIn("settingsPage.engineStatus = data.payload.status", self.text)

    def test_status_timer_polling_removed(self):
        self.assertNotIn("id: statusTimer", self.text)


class DownloadPageSimplificationsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(DOWNLOAD_PAGE_PATH)

    def test_braces_are_balanced(self):
        self.assertTrue(assert_balanced_braces(self.text), "DownloadPage.qml has unbalanced braces")

    def test_leading_actions_kept(self):
        self.assertRegex(self.text, r"leadingActions:\s*model\.ready\s*\?\s*deleteActions\s*:\s*null")

    def test_trailing_actions_and_redundant_action_blocks_removed(self):
        self.assertNotIn("trailingActions:", self.text)
        self.assertNotIn("id: downloadActions", self.text)
        self.assertNotIn("id: downloadingActions", self.text)
        self.assertNotIn("id: pausedActions", self.text)


if __name__ == "__main__":
    unittest.main()

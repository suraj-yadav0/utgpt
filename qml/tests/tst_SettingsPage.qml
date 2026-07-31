/*
 * tst_SettingsPage.qml
 *
 * QtTest unit tests for the parts of qml/pages/SettingsPage.qml that were
 * added in this PR: the new `showReleaseNotes()` signal used to notify
 * Main.qml that the "What's New & Release Notes" menu entry was tapped.
 *
 * Note: the actual routing decision (tapping the "releasenotes" row calls
 * showReleaseNotes() instead of setting currentSection) lives inline in a
 * delegate MouseArea.onClicked handler inside a virtualized ListView with
 * no objectName/alias exposed for test hooks, and the row's on-screen
 * position depends on PageHeader layout height. Simulating a real tap
 * reliably would require assumptions about internal layout that cannot be
 * verified without a live Qt/Lomiri runtime, so that interaction path is
 * intentionally left for manual/QA verification. These tests instead
 * cover the new signal's presence/behavior and default page state, which
 * are directly part of the public QML API surface changed by this PR.
 *
 * Run with qmltestrunner inside a clickable/Lomiri devel container.
 */

import QtQuick 2.7
import QtTest 1.1
import "../pages"

Item {
    id: root
    width: 400
    height: 800

    readonly property color themeColor: "#5C0A1A"
    readonly property bool isDark: false
    readonly property color bgColor: "#f5f5f7"
    readonly property color cardColor: "#FFFFFF"
    readonly property color cardBorderColor: "#E2E8F0"
    readonly property color primaryTextColor: "#1E293B"
    readonly property color secondaryTextColor: "#64748B"
    readonly property color tertiaryTextColor: "#94A3B8"
    readonly property color bodyTextColor: "#475569"
    readonly property color themeTextColor: themeColor
    property var availableModels: []
    property var modelCatalog: []
    function refreshModels() {}

    Component {
        id: settingsPageComponent
        SettingsPage {}
    }

    TestCase {
        id: testCase
        name: "SettingsPageReleaseNotesTests"
        when: windowShown

        SignalSpy {
            id: showReleaseNotesSpy
            signalName: "showReleaseNotes"
        }

        SignalSpy {
            id: toggleSidebarSpy
            signalName: "toggleSidebar"
        }

        function init() {
            showReleaseNotesSpy.clear()
            showReleaseNotesSpy.target = null
            toggleSidebarSpy.clear()
            toggleSidebarSpy.target = null
        }

        function test_showReleaseNotes_signal_is_defined() {
            var page = createTemporaryObject(settingsPageComponent, root)
            verify(page !== null)
            showReleaseNotesSpy.target = page
            verify(showReleaseNotesSpy.valid)
        }

        function test_showReleaseNotes_signal_emits_when_invoked() {
            var page = createTemporaryObject(settingsPageComponent, root)
            showReleaseNotesSpy.target = page

            page.showReleaseNotes()

            compare(showReleaseNotesSpy.count, 1)
        }

        function test_showReleaseNotes_does_not_change_currentSection() {
            var page = createTemporaryObject(settingsPageComponent, root)
            compare(page.currentSection, "")

            page.showReleaseNotes()

            compare(page.currentSection, "")
        }

        function test_default_currentSection_is_empty() {
            var page = createTemporaryObject(settingsPageComponent, root)
            compare(page.currentSection, "")
        }

        function test_page_constructs_successfully_with_new_signal_present() {
            var page = createTemporaryObject(settingsPageComponent, root)
            verify(page !== null)
            // toggleSidebar existed before this PR; showReleaseNotes is new.
            // Both must coexist without error.
            toggleSidebarSpy.target = page
            verify(toggleSidebarSpy.valid)
            page.toggleSidebar()
            compare(toggleSidebarSpy.count, 1)
        }
    }
}
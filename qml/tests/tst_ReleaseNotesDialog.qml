/*
 * tst_ReleaseNotesDialog.qml
 *
 * QtTest unit tests for qml/components/ReleaseNotesDialog.qml, added in
 * this PR. Run with qmltestrunner (e.g. `qmltestrunner -input qml/tests`)
 * inside a clickable/Lomiri devel container where the
 * "Lomiri.Components"/"Lomiri.Components.Popups" plugins are available.
 *
 * ReleaseNotesDialog.qml references `root.<property>` for theming (e.g.
 * root.themeColor, root.isDark, ...). This mirrors how the component is
 * used in production: it is only ever instantiated as a (grand)child of
 * Main.qml, whose top-level id is "root". QML resolves such unqualified
 * ids by walking up the context chain to the context that created the
 * object, so declaring our own `id: root` here with the same properties
 * lets the dialog be exercised standalone, exactly like the rest of the
 * codebase's components (see ChatPage.qml, SettingsPage.qml, etc., which
 * all rely on the same pattern).
 */

import QtQuick 2.7
import QtTest 1.1
import "../components"

Item {
    id: root
    width: 400
    height: 800

    readonly property color themeColor: "#5C0A1A"
    readonly property bool isDark: false
    readonly property color cardBorderColor: "#E2E8F0"
    readonly property color secondaryTextColor: "#64748B"
    readonly property color primaryTextColor: "#1E293B"
    readonly property color bodyTextColor: "#475569"
    readonly property color themeTextColor: themeColor

    property var sampleReleaseNotes: ({
        "version": "0.0.2",
        "date": "2026-07-26",
        "title": "What's New in UTGPT",
        "subtitle": "Version 0.0.2 Release Notes",
        "features": [
            { "title": "Feature One", "icon": "message", "description": "Desc one" },
            { "title": "Feature Two", "icon": "settings", "description": "Desc two" }
        ]
    })

    Component {
        id: dialogComponent
        ReleaseNotesDialog {}
    }

    TestCase {
        id: testCase
        name: "ReleaseNotesDialogTests"
        when: windowShown

        function test_title_defaults_to_generic_whats_new_when_no_data() {
            var dialog = createTemporaryObject(dialogComponent, root)
            verify(dialog !== null)
            compare(dialog.releaseNotesData, null)
            compare(dialog.title, "What's New")
        }

        function test_title_uses_release_notes_title_when_provided() {
            var dialog = createTemporaryObject(dialogComponent, root, {
                releaseNotesData: root.sampleReleaseNotes
            })
            compare(dialog.title, "What's New in UTGPT")
        }

        function test_title_falls_back_when_release_notes_has_no_title_field() {
            var dialog = createTemporaryObject(dialogComponent, root, {
                releaseNotesData: { "version": "1.0.0", "features": [] }
            })
            compare(dialog.title, "What's New")
        }

        function test_title_updates_reactively_when_data_changes_after_creation() {
            var dialog = createTemporaryObject(dialogComponent, root)
            compare(dialog.title, "What's New")

            dialog.releaseNotesData = root.sampleReleaseNotes
            compare(dialog.title, "What's New in UTGPT")

            dialog.releaseNotesData = null
            compare(dialog.title, "What's New")
        }

        function test_creation_does_not_fail_with_missing_features_field() {
            var dialog = createTemporaryObject(dialogComponent, root, {
                releaseNotesData: { "version": "1.0.0", "title": "No Features Here" }
            })
            verify(dialog !== null)
            compare(dialog.title, "No Features Here")
        }

        function test_creation_does_not_fail_with_empty_features_list() {
            var dialog = createTemporaryObject(dialogComponent, root, {
                releaseNotesData: { "version": "1.0.0", "title": "Empty Features", "features": [] }
            })
            verify(dialog !== null)
            compare(dialog.title, "Empty Features")
        }

        function test_release_notes_data_property_round_trips() {
            var dialog = createTemporaryObject(dialogComponent, root, {
                releaseNotesData: root.sampleReleaseNotes
            })
            compare(dialog.releaseNotesData.version, "0.0.2")
            compare(dialog.releaseNotesData.features.length, 2)
            compare(dialog.releaseNotesData.features[0].title, "Feature One")
        }
    }
}
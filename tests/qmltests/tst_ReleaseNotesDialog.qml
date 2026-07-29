/*
 * tst_ReleaseNotesDialog.qml
 *
 * Qt Quick Test coverage for qml/components/ReleaseNotesDialog.qml, the
 * popup introduced in this PR to present "What's New" release notes.
 *
 * Run with: qmltestrunner -input tests/qmltests
 *
 * ReleaseNotesDialog.qml is normally opened via PopupUtils.open(component,
 * root, ...) from qml/Main.qml, and reads a handful of theme colors from
 * that ancestor "root" (MainView) context. To keep this test self-contained
 * and independent of the full application/window stack, the component is
 * instantiated directly (Component.createObject) as a child of a minimal
 * stand-in Item that exposes the same "root.*" properties the dialog reads.
 */
import QtQuick 2.7
import QtTest 1.2
import Lomiri.Components 1.3
import "../../qml/components"

Item {
    id: root
    width: units.gu(50)
    height: units.gu(80)

    // Minimal stand-in for the ancestor "root" (qml/Main.qml MainView)
    // properties that ReleaseNotesDialog.qml reads for styling.
    readonly property color themeColor: "#5C0A1A"
    readonly property bool isDark: false
    readonly property color themeTextColor: themeColor
    readonly property color cardBorderColor: "#E2E8F0"
    readonly property color primaryTextColor: "#1E293B"
    readonly property color secondaryTextColor: "#64748B"
    readonly property color bodyTextColor: "#475569"

    Component {
        id: dialogComponent
        ReleaseNotesDialog {}
    }

    // Recursively collects every non-empty "text" property found in the
    // visual tree rooted at "item" (Labels, etc.), used to assert on
    // rendered content without relying on internal ids/objectNames.
    function collectTexts(item, out) {
        if (item === null || item === undefined) {
            return;
        }
        if (typeof item.text === "string" && item.text.length > 0) {
            out.push(item.text);
        }
        var kids = item.children;
        if (kids) {
            for (var i = 0; i < kids.length; i++) {
                collectTexts(kids[i], out);
            }
        }
    }

    TestCase {
        id: testCase
        name: "ReleaseNotesDialogTests"
        when: windowShown

        property var dialog: null

        function cleanup() {
            if (dialog !== null) {
                dialog.destroy();
                dialog = null;
            }
        }

        function test_defaultTitleWhenNoReleaseNotesData() {
            dialog = dialogComponent.createObject(root, { "releaseNotesData": null });
            verify(dialog !== null);
            compare(dialog.title, "What's New");
        }

        function test_titleUsesReleaseNotesDataTitle() {
            var data = { "title": "Custom Release Title", "version": "9.9.9", "subtitle": "Sub", "features": [] };
            dialog = dialogComponent.createObject(root, { "releaseNotesData": data });
            compare(dialog.title, "Custom Release Title");
        }

        function test_titleFallsBackWhenTitleFieldMissing() {
            var data = { "version": "1.0.0", "subtitle": "Sub", "features": [] };
            dialog = dialogComponent.createObject(root, { "releaseNotesData": data });
            compare(dialog.title, "What's New");
        }

        function test_versionBadgeTextIncludesVersion() {
            var data = { "title": "T", "version": "4.5.6", "subtitle": "S", "features": [] };
            dialog = dialogComponent.createObject(root, { "releaseNotesData": data });
            wait(50);
            var texts = [];
            collectTexts(dialog, texts);
            verify(texts.indexOf("v4.5.6") !== -1);
        }

        function test_featureContentIsRendered() {
            var data = {
                "title": "T",
                "version": "1.2.3",
                "subtitle": "S",
                "features": [
                    { "title": "Feature Alpha", "icon": "message", "description": "Alpha description text" },
                    { "title": "Feature Beta", "icon": "settings", "description": "Beta description text" }
                ]
            };
            dialog = dialogComponent.createObject(root, { "releaseNotesData": data });
            wait(50);
            var texts = [];
            collectTexts(dialog, texts);
            verify(texts.indexOf("Feature Alpha") !== -1);
            verify(texts.indexOf("Alpha description text") !== -1);
            verify(texts.indexOf("Feature Beta") !== -1);
            verify(texts.indexOf("Beta description text") !== -1);
        }

        function test_emptyFeaturesRendersNoFeatureItems() {
            var data = { "title": "T", "version": "1.0.0", "subtitle": "S", "features": [] };
            dialog = dialogComponent.createObject(root, { "releaseNotesData": data });
            wait(50);
            var texts = [];
            collectTexts(dialog, texts);
            compare(texts.indexOf("Feature Alpha"), -1);
        }

        function test_missingFeaturesFieldDoesNotThrow() {
            // Negative/boundary case: releaseNotesData present but without a
            // "features" array at all (falls back to the Repeater's []
            // default model instead of crashing).
            var data = { "title": "T", "version": "1.0.0", "subtitle": "S" };
            dialog = dialogComponent.createObject(root, { "releaseNotesData": data });
            verify(dialog !== null);
            compare(dialog.title, "T");
        }
    }
}
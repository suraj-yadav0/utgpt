/*
 * tst_Main.qml
 *
 * QtTest coverage for the release-notes wiring added to qml/Main.qml in
 * this PR: the new `currentVersion`/`releaseNotesData` properties and the
 * `showReleaseNotes()` function, populated from the (also new)
 * "version"/"releaseNotes" fields returned by backend.initialize().
 *
 * This is necessarily an integration-style test rather than a pure unit
 * test: Main.qml is the application's MainView and bootstraps the real
 * Python backend (io.thp.pyotherside) in Component.onCompleted, so
 * instantiating it here exercises the real backend.py (which is safe -
 * backend.initialize() only reads local files/checks binaries, it does
 * not perform network requests). It must be run with qmltestrunner inside
 * a clickable/Lomiri devel container where the "io.thp.pyotherside" and
 * "Lomiri.Components" plugins are installed, the same environment the
 * app itself requires to run.
 */

import QtQuick 2.7
import QtTest 1.1
import ".."

Item {
    id: testRoot
    width: 480
    height: 800

    Component {
        id: mainComponent
        Main {}
    }

    TestCase {
        id: testCase
        name: "MainReleaseNotesWiringTests"
        when: windowShown

        function test_currentVersion_and_releaseNotesData_start_empty_before_backend_ready() {
            var app = createTemporaryObject(mainComponent, testRoot)
            verify(app !== null)
            // The backend.initialize() round-trip via python.call() is
            // asynchronous, so immediately after construction (before any
            // event-loop iteration has let the callback fire) these must
            // still hold their declared defaults.
            compare(app.currentVersion, "")
            compare(app.releaseNotesData, null)
        }

        function test_showReleaseNotes_is_a_safe_noop_when_no_release_notes_loaded() {
            var app = createTemporaryObject(mainComponent, testRoot)
            // Should not throw/crash even though releaseNotesData is null.
            app.showReleaseNotes()
            compare(app.releaseNotesData, null)
        }

        function test_backend_initialize_populates_version_and_release_notes() {
            var app = createTemporaryObject(mainComponent, testRoot)

            tryCompare(app, "backendReady", true, 10000)

            verify(app.currentVersion.length > 0)
            verify(app.releaseNotesData !== null)
            verify(app.releaseNotesData.features !== undefined)
        }

        function test_showReleaseNotes_does_not_crash_once_release_notes_are_loaded() {
            var app = createTemporaryObject(mainComponent, testRoot)
            tryCompare(app, "backendReady", true, 10000)

            // By this point the app may have already auto-shown the
            // dialog once (lastSeenVersion mismatch); calling it again
            // manually must still be safe.
            app.showReleaseNotes()
        }
    }
}
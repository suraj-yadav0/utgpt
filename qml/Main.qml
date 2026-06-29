/*
 * Main.qml
 *
 * Boots the PyOtherSide backend, displays a simple loading and error overlay,
 * and wires the chat, model download, and settings pages together via tabs.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import io.thp.pyotherside 1.4
import Qt.labs.settings 1.0

MainView {
    id: root
    objectName: "mainView"
    applicationName: "utgpt.surajyadav"
    automaticOrientation: true
    anchorToKeyboard: true

    width: units.gu(45)
    height: units.gu(75)

    Settings {
        id: appSettings
        category: "General"
        property string selectedModel: ""
        property real temperature: 0.7
        property int maxTokens: 512
        property int threads: 4
        property int ctxSize: 2048
        property string flashAttn: "auto"
    }

    property bool backendReady: false
    property string backendError: ""
    property int currentTabIndex: 0
    property string selectedModel: appSettings.selectedModel
    property var availableModels: []
    property real temperature: appSettings.temperature
    property int maxTokens: appSettings.maxTokens
    property int threads: appSettings.threads
    property int ctxSize: appSettings.ctxSize
    property string flashAttn: appSettings.flashAttn
    property bool sidebarOpen: false
    property var modelCatalog: []
    property var currentSessionId: null
    property var chatSessions: []

    onSelectedModelChanged: appSettings.selectedModel = selectedModel
    onTemperatureChanged: appSettings.temperature = temperature
    onMaxTokensChanged: appSettings.maxTokens = maxTokens
    onThreadsChanged: appSettings.threads = threads
    onCtxSizeChanged: appSettings.ctxSize = ctxSize
    onFlashAttnChanged: appSettings.flashAttn = flashAttn

    onWidthChanged: {
        sidebarOpen = (width >= units.gu(60))
    }

    onBackendReadyChanged: {
        if (backendReady) {
            refreshModels()
            loadCatalog()
            refreshSessions()
            // Start with a new chat on startup
            root.currentSessionId = null
            chatPage.startNewChat()
        }
    }

    function loadCatalog() {
        if (!backendReady) return;
        python.call("backend.fetch_model_catalog", [], function(result) {
            if (result && result.length > 0) {
                root.modelCatalog = result
            }
        })
    }

    onCurrentTabIndexChanged: {
        refreshModels()
    }

    function refreshModels() {
        if (!backendReady) return;
        python.call("backend.list_models", [], function(result) {
            root.availableModels = result || []
            if (root.availableModels.length === 0) {
                root.selectedModel = ""
                return
            }

            var selectedIndex = root.availableModels.indexOf(root.selectedModel)
            if (selectedIndex < 0) {
                root.selectedModel = root.availableModels[0]
            }
        })
    }

    function refreshSessions() {
        if (!backendReady) return;
        python.call("backend.get_sessions", [], function(result) {
            root.chatSessions = result || []
        })
    }

    function deleteSession(sessionId) {
        python.call("backend.delete_session", [sessionId], function(ok) {
            if (ok) {
                if (root.currentSessionId === sessionId) {
                    // Try to load the next/latest session
                    python.call("backend.get_latest_session_id", [], function(latestId) {
                        if (latestId) {
                            root.currentSessionId = latestId
                            chatPage.loadHistory(latestId)
                        } else {
                            root.currentSessionId = null
                            chatPage.loadHistory(null)
                        }
                        refreshSessions()
                    })
                } else {
                    refreshSessions()
                }
            }
        })
    }

    function startNewChat() {
        root.currentSessionId = null
        chatPage.startNewChat()
        root.currentTabIndex = 0
        if (root.width < units.gu(60)) {
            root.sidebarOpen = false
        }
    }

    function showError(message) {
        backendError = message
        PopupUtils.open(errorDialogComponent, root, { "message": message })
    }

    Python {
        id: python

        onError: function(traceback) {
            root.showError(traceback)
        }

        Component.onCompleted: {
            addImportPath(Qt.resolvedUrl("../backend"))
            importModule("backend", function() {
                python.call("backend.initialize", [], function() {
                    root.backendReady = true
                })
            })
        }
    }

    function tabButtonColor(index) {
        return currentTabIndex === index ? "#E95420" : "#d7d7d7"
    }

    Component {
        id: errorDialogComponent

        Dialog {
            id: dialog
            property string message: ""

            title: i18n.tr("Backend Error")

            Label {
                width: parent ? parent.width : undefined
                wrapMode: Text.Wrap
                text: dialog.message
            }

            Button {
                text: i18n.tr("OK")
                onClicked: PopupUtils.close(dialog)
            }
        }
    }

    ColumnLayout {
        id: mainLayout
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.left: parent.left
        anchors.leftMargin: (root.width < units.gu(60)) ? 0 : (root.sidebarOpen ? sidebar.width : 0)
        visible: root.backendReady
        spacing: 0

        Behavior on anchors.leftMargin {
            NumberAnimation { duration: 200; easing.type: Easing.OutQuad }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ChatPage {
                id: chatPage
                anchors.fill: parent
                visible: root.currentTabIndex === 0
                python: python
                backendReady: root.backendReady
                model: root.selectedModel
                temperature: root.temperature
                maxTokens: root.maxTokens
                threads: root.threads
                ctxSize: root.ctxSize
                flashAttn: root.flashAttn
                onToggleSidebar: root.sidebarOpen = !root.sidebarOpen
            }

            DownloadPage {
                id: downloadPage
                anchors.fill: parent
                visible: root.currentTabIndex === 1
                python: python
                backendReady: root.backendReady
                onToggleSidebar: root.sidebarOpen = !root.sidebarOpen
            }

            SettingsPage {
                id: settingsPage
                anchors.fill: parent
                visible: root.currentTabIndex === 2
                python: python
                backendReady: root.backendReady
                selectedModel: root.selectedModel
                temperature: root.temperature
                maxTokens: root.maxTokens
                threads: root.threads
                ctxSize: root.ctxSize
                flashAttn: root.flashAttn
                onSelectedModelChanged: root.selectedModel = selectedModel
                onTemperatureChanged: root.temperature = temperature
                onMaxTokensChanged: root.maxTokens = maxTokens
                onThreadsChanged: root.threads = threads
                onCtxSizeChanged: root.ctxSize = ctxSize
                onFlashAttnChanged: root.flashAttn = flashAttn
                onClearChat: chatPage.clearHistory()
                onToggleSidebar: root.sidebarOpen = !root.sidebarOpen
            }
        }
    }

    // MouseArea at the left edge to open the sidebar on swipe right (on mobile only)
    MouseArea {
        id: leftSwipeArea
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: units.gu(2)
        z: 98 // Just below the sidebar and overlay

        // Active on mobile when sidebar is closed
        enabled: root.backendReady && (root.width < units.gu(60)) && !root.sidebarOpen

        property real startX: 0
        property bool isDragging: false

        onPressed: {
            startX = mouse.x
            isDragging = true
        }

        onPositionChanged: {
            if (!isDragging) return
            var deltaX = mouse.x - startX
            if (deltaX > units.gu(4)) {
                root.sidebarOpen = true
                isDragging = false
            }
        }

        onReleased: {
            isDragging = false
        }
    }

    // Semi-transparent overlay to close sidebar on mobile when tapping/swiping outside
    Rectangle {
        id: sidebarOverlay
        anchors.fill: parent
        color: "black"
        opacity: 0.4
        z: 99
        visible: (root.width < units.gu(60)) && root.sidebarOpen

        MouseArea {
            anchors.fill: parent
            onClicked: root.sidebarOpen = false

            // Detect swipe left to close
            property real startX: 0
            property bool isDragging: false

            onPressed: {
                startX = mouse.x
                isDragging = true
            }

            onPositionChanged: {
                if (!isDragging) return
                var deltaX = mouse.x - startX
                if (deltaX < -units.gu(4)) {
                    root.sidebarOpen = false
                    isDragging = false
                }
            }

            onReleased: {
                isDragging = false
            }
        }
    }

    // Sidebar on the left
    Rectangle {
        id: sidebar
        z: 100
        height: parent.height
        width: units.gu(30)
        color: "#FFFFFF" // Clean white background

        x: root.sidebarOpen ? 0 : -width
        Behavior on x {
            NumberAnimation { duration: 200; easing.type: Easing.OutQuad }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 0
            spacing: 0

            // Header/Logo
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: units.gu(8)
                color: "#E95420" // Primary orange

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: units.gu(2)
                    anchors.rightMargin: units.gu(2)
                    spacing: units.gu(1.5)

                    Label {
                        text: i18n.tr("Chat History")
                        color: "white"
                        font.bold: true
                        fontSize: "large"
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                    }

                    // "+" button to start a new chat
                    Rectangle {
                        width: units.gu(4)
                        height: units.gu(4)
                        radius: units.gu(0.5)
                        color: "transparent"
                        Layout.alignment: Qt.AlignVCenter

                        Icon {
                            anchors.centerIn: parent
                            name: "add"
                            width: units.gu(2.4)
                            height: units.gu(2.4)
                            color: "white"
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            onEntered: parent.color = "rgba(255,255,255,0.15)"
                            onExited: parent.color = "transparent"
                            onClicked: {
                                root.startNewChat()
                            }
                        }
                    }
                }
            }

            // Slim elegant divider
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: "#E2E8F0"
            }

            // Sessions List
            ListView {
                id: sessionsListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.chatSessions
                spacing: 0

                delegate: Rectangle {
                    width: sessionsListView.width
                    height: units.gu(6.5)
                    color: root.currentSessionId === modelData.id ? "#FFF5F0" : "#FFFFFF"

                    // Orange indicator pill on the left
                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: units.gu(0.4)
                        color: "#E95420"
                        visible: root.currentSessionId === modelData.id
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: units.gu(1.5)
                        anchors.rightMargin: units.gu(1.5)
                        spacing: units.gu(1)

                        Icon {
                            name: "message"
                            width: units.gu(2.2)
                            height: units.gu(2.2)
                            color: root.currentSessionId === modelData.id ? "#E95420" : "#64748B"
                            Layout.alignment: Qt.AlignVCenter
                        }

                        // Session title label
                        Label {
                            text: modelData.title
                            color: root.currentSessionId === modelData.id ? "#E95420" : "#475569"
                            font.bold: root.currentSessionId === modelData.id
                            fontSize: "medium"
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            Layout.alignment: Qt.AlignVCenter
                        }

                        // Trash button to delete session
                        Rectangle {
                            width: units.gu(3.5)
                            height: units.gu(3.5)
                            radius: units.gu(0.5)
                            color: "transparent"
                            Layout.alignment: Qt.AlignVCenter

                            Icon {
                                anchors.centerIn: parent
                                name: "delete"
                                width: units.gu(1.8)
                                height: units.gu(1.8)
                                color: "#94A3B8"
                            }

                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                onEntered: parent.color = "#FEE2E2"
                                onExited: parent.color = "transparent"
                                onClicked: {
                                    root.deleteSession(modelData.id)
                                }
                            }
                        }
                    }

                    // Bottom separator line
                    Rectangle {
                        anchors.bottom: parent.bottom
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: units.gu(1.5)
                        anchors.rightMargin: units.gu(1.5)
                        height: 1
                        color: "#E2E8F0"
                    }

                    MouseArea {
                        anchors.fill: parent
                        propagateComposedEvents: true
                        onClicked: {
                            root.currentSessionId = modelData.id
                            root.currentTabIndex = 0 // Go to Chat Page
                            chatPage.loadHistory(modelData.id)
                            if (root.width < units.gu(60)) {
                                root.sidebarOpen = false
                            }
                        }
                    }
                }
            }

            // Footer
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: units.gu(6)
                color: "#F8F9FA"

                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: "#E2E8F0"
                }

                Label {
                    anchors.centerIn: parent
                    text: "v0.1.0"
                    color: "#94A3B8"
                    fontSize: "x-small"
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: !root.backendReady
        color: "#f5f5f5"

        Column {
            anchors.centerIn: parent
            spacing: units.gu(2)

            ActivityIndicator {
                anchors.horizontalCenter: parent.horizontalCenter
                running: !root.backendReady
            }

            Label {
                text: i18n.tr("Loading Python backend...")
            }
        }
    }
}

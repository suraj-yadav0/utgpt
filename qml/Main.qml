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

MainView {
    id: root
    objectName: "mainView"
    applicationName: "utgpt.surajyadav"
    automaticOrientation: true
    anchorToKeyboard: true

    width: units.gu(45)
    height: units.gu(75)

    property bool backendReady: false
    property string backendError: ""
    property int currentTabIndex: 0
    property string selectedModel: ""
    property var availableModels: []
    property real temperature: 0.7
    property int maxTokens: 200
    property bool sidebarOpen: false

    onWidthChanged: {
        sidebarOpen = (width >= units.gu(60))
    }

    onBackendReadyChanged: {
        if (backendReady) {
            refreshModels()
        }
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
        anchors.left: (root.width < units.gu(60)) ? parent.left : sidebar.right
        visible: root.backendReady
        spacing: 0

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
                onSelectedModelChanged: root.selectedModel = selectedModel
                onTemperatureChanged: root.temperature = temperature
                onMaxTokensChanged: root.maxTokens = maxTokens
                onClearChat: chatPage.clearHistory()
                onToggleSidebar: root.sidebarOpen = !root.sidebarOpen
            }
        }
    }

    // Semi-transparent overlay to close sidebar on mobile when tapping outside
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
        }
    }

    // Sidebar on the left
    Rectangle {
        id: sidebar
        z: 100
        height: parent.height
        width: units.gu(26)
        color: "#1E1E24" // Sleek dark charcoal/slate gray

        x: (root.width < units.gu(60)) ? (root.sidebarOpen ? 0 : -width) : 0
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
                color: "transparent"

                RowLayout {
                    anchors.centerIn: parent
                    spacing: units.gu(1.5)

                    Image {
                        source: Qt.resolvedUrl("../assets/logo.png")
                        Layout.preferredWidth: units.gu(4)
                        Layout.preferredHeight: units.gu(4)
                        fillMode: Image.PreserveAspectFit
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Label {
                        text: "UTGPT"
                        color: "white"
                        font.bold: true
                        fontSize: "large"
                        Layout.alignment: Qt.AlignVCenter
                    }
                }
            }

            // Slim elegant divider
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: "#2D2D35"
            }

            // Navigation Tabs
            Column {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: units.gu(2)
                spacing: units.gu(0.8)

                // Chat Tab
                Rectangle {
                    width: parent.width - units.gu(2)
                    height: units.gu(5.5)
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: root.currentTabIndex === 0 ? "#2D2D35" : "transparent"
                    radius: units.gu(0.8)

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: units.gu(1.5)
                        spacing: units.gu(1.5)

                        Icon {
                            name: "message"
                            width: units.gu(2.2)
                            height: units.gu(2.2)
                            color: root.currentTabIndex === 0 ? "#E95420" : "#8A8A8F"
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Label {
                            text: i18n.tr("Chat")
                            color: root.currentTabIndex === 0 ? "white" : "#BDC3C7"
                            font.bold: root.currentTabIndex === 0
                            fontSize: "medium"
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }

                    // Orange indicator pill on the left
                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: units.gu(0.4)
                        height: units.gu(3)
                        color: "#E95420"
                        visible: root.currentTabIndex === 0
                        radius: width / 2
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.currentTabIndex = 0
                            if (root.width < units.gu(60)) {
                                root.sidebarOpen = false
                            }
                        }
                    }
                }

                // Models Tab
                Rectangle {
                    width: parent.width - units.gu(2)
                    height: units.gu(5.5)
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: root.currentTabIndex === 1 ? "#2D2D35" : "transparent"
                    radius: units.gu(0.8)

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: units.gu(1.5)
                        spacing: units.gu(1.5)

                        Icon {
                            name: "package-x-generic-symbolic"
                            width: units.gu(2.2)
                            height: units.gu(2.2)
                            color: root.currentTabIndex === 1 ? "#E95420" : "#8A8A8F"
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Label {
                            text: i18n.tr("Models")
                            color: root.currentTabIndex === 1 ? "white" : "#BDC3C7"
                            font.bold: root.currentTabIndex === 1
                            fontSize: "medium"
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }

                    // Orange indicator pill on the left
                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: units.gu(0.4)
                        height: units.gu(3)
                        color: "#E95420"
                        visible: root.currentTabIndex === 1
                        radius: width / 2
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.currentTabIndex = 1
                            if (root.width < units.gu(60)) {
                                root.sidebarOpen = false
                            }
                        }
                    }
                }

                // Settings Tab
                Rectangle {
                    width: parent.width - units.gu(2)
                    height: units.gu(5.5)
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: root.currentTabIndex === 2 ? "#2D2D35" : "transparent"
                    radius: units.gu(0.8)

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: units.gu(1.5)
                        spacing: units.gu(1.5)

                        Icon {
                            name: "settings"
                            width: units.gu(2.2)
                            height: units.gu(2.2)
                            color: root.currentTabIndex === 2 ? "#E95420" : "#8A8A8F"
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Label {
                            text: i18n.tr("Settings")
                            color: root.currentTabIndex === 2 ? "white" : "#BDC3C7"
                            font.bold: root.currentTabIndex === 2
                            fontSize: "medium"
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }

                    // Orange indicator pill on the left
                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: units.gu(0.4)
                        height: units.gu(3)
                        color: "#E95420"
                        visible: root.currentTabIndex === 2
                        radius: width / 2
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.currentTabIndex = 2
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
                color: "transparent"

                Label {
                    anchors.centerIn: parent
                    text: "v0.1.0"
                    color: "#5C5C64"
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

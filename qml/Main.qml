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

    width: units.gu(45)
    height: units.gu(75)

    property bool backendReady: false
    property string backendError: ""
    property int currentTabIndex: 0
    property string selectedModel: ""
    property real temperature: 0.7
    property int maxTokens: 200

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
                python.call("initialize", [], function() {
                    root.backendReady = true
                })
            })
        }
    }

    function tabButtonColor(index) {
        return currentTabIndex === index ? LomiriColors.orange : "#d7d7d7"
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
        anchors.fill: parent
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
                model: root.selectedModel
                temperature: root.temperature
                maxTokens: root.maxTokens
            }

            DownloadPage {
                id: downloadPage
                anchors.fill: parent
                visible: root.currentTabIndex === 1
                python: python
            }

            SettingsPage {
                id: settingsPage
                anchors.fill: parent
                visible: root.currentTabIndex === 2
                python: python
                selectedModel: root.selectedModel
                temperature: root.temperature
                maxTokens: root.maxTokens
                onSelectedModelChanged: root.selectedModel = selectedModel
                onTemperatureChanged: root.temperature = temperature
                onMaxTokensChanged: root.maxTokens = maxTokens
                onClearChat: chatPage.clearHistory()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(8)
            color: "#efefef"
            border.color: "#d0d0d0"

            RowLayout {
                anchors.fill: parent
                anchors.margins: units.gu(1)
                spacing: units.gu(1)

                Button {
                    Layout.fillWidth: true
                    text: i18n.tr("Chat")
                    color: root.tabButtonColor(0)
                    onClicked: root.currentTabIndex = 0
                }

                Button {
                    Layout.fillWidth: true
                    text: i18n.tr("Models")
                    color: root.tabButtonColor(1)
                    onClicked: root.currentTabIndex = 1
                }

                Button {
                    Layout.fillWidth: true
                    text: i18n.tr("Settings")
                    color: root.tabButtonColor(2)
                    onClicked: root.currentTabIndex = 2
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

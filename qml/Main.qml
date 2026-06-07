/*
 * Main.qml
 *
 * Boots the PyOtherSide backend, displays a simple loading and error overlay,
 * and wires the chat, model download, and settings pages together via tabs.
 */

import QtQuick 2.7
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

    Tabs {
        id: tabs
        anchors.fill: parent
        visible: root.backendReady

        Tab {
            title: i18n.tr("Chat")
            iconSource: "image://theme/message"
            page: ChatPage {
                id: chatPage
                title: i18n.tr("Chat")
                python: python
                model: settingsPage.selectedModel
                temperature: settingsPage.temperature
                maxTokens: settingsPage.maxTokens
            }
        }

        Tab {
            title: i18n.tr("Models")
            iconSource: "image://theme/download"
            page: DownloadPage {
                title: i18n.tr("Download Models")
                python: python
            }
        }

        Tab {
            title: i18n.tr("Settings")
            iconSource: "image://theme/settings"
            page: SettingsPage {
                id: settingsPage
                title: i18n.tr("Settings")
                python: python
                onClearChat: chatPage.clearHistory()
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

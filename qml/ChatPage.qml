/*
 * ChatPage.qml
 *
 * Renders the main UTGPT conversation screen, streams inference text into the
 * latest assistant bubble, and exposes clearHistory() for Settings-driven reset.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import QtQuick.Controls 2.2 as QQC2

Page {
    id: chatPage
    signal toggleSidebar()

    header: PageHeader {
        id: chatHeader
        title: i18n.tr("Chat")
        leadingActionBar.numberOfSlots: 1
        leadingActionBar.actions: [
            Action {
                iconName: "navigation-menu"
                text: i18n.tr("Menu")
                visible: chatPage.width < units.gu(60)
                onTriggered: chatPage.toggleSidebar()
            }
        ]
    }

    property var python
    property bool backendReady: false
    property string model: ""
    property real temperature: 0.7
    property int maxTokens: 200
    property bool isResponding: false
    property string pendingRequestId: ""

    function clearHistory() {
        messageModel.clear()
        composer.text = ""
        isResponding = false
        pendingRequestId = ""
    }

    function scrollToBottom() {
        if (messageModel.count > 0) {
            messageList.positionViewAtEnd()
        }
    }

    function appendAssistantText(chunk) {
        if (messageModel.count === 0) {
            return
        }

        var lastIndex = messageModel.count - 1
        var currentText = messageModel.get(lastIndex).text
        if (currentText === "...") {
            messageModel.setProperty(lastIndex, "text", chunk)
        } else {
            messageModel.setProperty(lastIndex, "text", currentText + chunk)
        }
        scrollToBottom()
    }

    function finishResponse(ok, errorMessage) {
        isResponding = false

        if (!ok && messageModel.count > 0) {
            var lastIndex = messageModel.count - 1
            var currentText = messageModel.get(lastIndex).text
            var fallback = errorMessage && errorMessage.length > 0 ? errorMessage : "The model stopped unexpectedly."
            if (currentText === "...") {
                messageModel.setProperty(lastIndex, "text", fallback)
            } else {
                messageModel.setProperty(lastIndex, "text", currentText + "\n" + fallback)
            }
        }
    }

    function sendMessage() {
        var trimmed = composer.text.trim()
        if (!trimmed || isResponding) {
            return
        }

        if (!model) {
            messageModel.append({ "role": "assistant", "text": "Select a model in Settings before chatting." })
            composer.text = ""
            scrollToBottom()
            return
        }

        messageModel.append({ "role": "user", "text": trimmed })
        messageModel.append({ "role": "assistant", "text": "..." })
        composer.text = ""
        isResponding = true
        pendingRequestId = "chat-" + Date.now()
        scrollToBottom()

        python.call(
            "backend.run_inference",
            [model, trimmed, temperature, maxTokens, pendingRequestId, pendingRequestId],
            function(result) {
                if (result === false && isResponding) {
                    var lastIndex = messageModel.count - 1
                    if (lastIndex >= 0 && messageModel.get(lastIndex).text === "...") {
                        finishResponse(false, "Unable to start inference.")
                    }
                }
            }
        )
    }

    ListModel {
        id: messageModel
        onCountChanged: chatPage.scrollToBottom()
    }

    Connections {
        target: python

        function onReceived(result) {
            console.log("QML_LOG: ChatPage received result type:", typeof result, "JSON:", JSON.stringify(result), "pendingRequestId:", pendingRequestId)
            
            // PyOtherSide received signal passes arguments wrapped in a JavaScript array
            var data = (result && result.length > 0) ? result[0] : null
            if (!data || !data.event || !data.payload) {
                return
            }

            if (data.payload.requestId !== pendingRequestId) {
                console.log("QML_LOG: Request ID mismatch: " + data.payload.requestId + " != " + pendingRequestId)
                return
            }

            if (data.event === "inference_token") {
                chatPage.appendAssistantText(data.payload.text)
            } else if (data.event === "inference_done") {
                chatPage.finishResponse(data.payload.ok, data.payload.error)
                pendingRequestId = ""
            }
        }
    }

    Connections {
        target: Qt.inputMethod
        function onVisibleChanged() {
            if (Qt.inputMethod.visible) {
                scrollTimer.start()
            }
        }
    }

    Timer {
        id: scrollTimer
        interval: 150
        repeat: false
        onTriggered: chatPage.scrollToBottom()
    }

    Rectangle {
        anchors.fill: parent
        color: "#f5f5f7"
        z: -1
    }

    ColumnLayout {
        anchors.top: chatHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: units.gu(1.5)
        spacing: units.gu(1)

        // Model Selection Bar
        Rectangle {
            id: modelSelectionBar
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(6.5)
            color: "#FFFFFF"
            border.color: "#E2E8F0"
            border.width: 1
            radius: units.gu(1.5)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: units.gu(1.5)
                anchors.rightMargin: units.gu(1.5)
                spacing: units.gu(1.5)

                // Brand/Warning Icon
                Rectangle {
                    width: units.gu(3.5)
                    height: units.gu(3.5)
                    radius: units.gu(1)
                    color: root.availableModels.length > 0 ? "#FFEBE6" : "#FFF5F5"
                    Layout.alignment: Qt.AlignVCenter

                    Icon {
                        anchors.centerIn: parent
                        name: root.availableModels.length > 0 ? "message" : "dialog-warning"
                        width: units.gu(2.2)
                        height: units.gu(2.2)
                        color: root.availableModels.length > 0 ? "#E95420" : "#E53E3E"
                    }
                }

                // If models are available, show the ComboBox to switch
                RowLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    visible: root.availableModels.length > 0
                    spacing: units.gu(1)

                    Label {
                        text: i18n.tr("Model:")
                        font.bold: true
                        color: "#4A5568"
                        fontSize: "small"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    QQC2.ComboBox {
                        id: chatModelSelector
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        model: root.availableModels
                        currentIndex: root.availableModels.indexOf(root.selectedModel)

                        onActivated: {
                            if (currentIndex >= 0 && currentIndex < root.availableModels.length) {
                                root.selectedModel = root.availableModels[currentIndex]
                            }
                        }
                    }
                }

                // If no models downloaded, show helper text to download one
                RowLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    visible: root.availableModels.length === 0
                    spacing: units.gu(1)

                    Label {
                        Layout.fillWidth: true
                        text: i18n.tr("No models downloaded - tap to download one")
                        color: "#E53E3E"
                        font.bold: true
                        fontSize: "small"
                        elide: Text.ElideRight
                    }

                    Label {
                        text: "\u2192" // Right arrow
                        color: "#E53E3E"
                        fontSize: "small"
                        Layout.alignment: Qt.AlignVCenter
                    }
                }
            }

            // Clicking when no models are available redirects to the Models tab
            MouseArea {
                anchors.fill: parent
                enabled: root.availableModels.length === 0
                onClicked: {
                    root.currentTabIndex = 1 // Go to Models tab
                }
            }
        }

        ListView {
            id: messageList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: units.gu(1.5)
            model: messageModel
            onHeightChanged: chatPage.scrollToBottom()

            delegate: Item {
                width: messageList.width
                height: Math.max(units.gu(4.5), bubble.height) + units.gu(1.5)

                // Avatar bubble
                Rectangle {
                    id: avatar
                    width: units.gu(4)
                    height: units.gu(4)
                    radius: width / 2
                    color: model.role === "user" ? "#FFEBE6" : "#E2E8F0"
                    anchors.top: parent.top
                    anchors.topMargin: units.gu(0.5)
                    anchors.left: model.role === "assistant" ? parent.left : undefined
                    anchors.right: model.role === "user" ? parent.right : undefined

                    Label {
                        anchors.centerIn: parent
                        text: model.role === "user" ? "U" : "AI"
                        color: model.role === "user" ? "#E95420" : "#4A5568"
                        font.bold: true
                        fontSize: "small"
                    }
                }

                // Message bubble
                Rectangle {
                    id: bubble
                    anchors {
                        top: parent.top
                        topMargin: units.gu(0.5)
                        left: model.role === "assistant" ? avatar.right : undefined
                        right: model.role === "user" ? avatar.left : undefined
                        leftMargin: model.role === "assistant" ? units.gu(1) : undefined
                        rightMargin: model.role === "user" ? units.gu(1) : undefined
                    }
                    width: Math.min(messageText.implicitWidth + units.gu(3.5), messageList.width * 0.76)
                    height: messageText.implicitHeight + units.gu(2)
                    radius: units.gu(1.5)
                    color: model.role === "user" ? "#E95420" : "#FFFFFF"
                    border.color: model.role === "user" ? "transparent" : "#E2E8F0"
                    border.width: model.role === "user" ? 0 : 1

                    Label {
                        id: messageText
                        anchors.fill: parent
                        anchors.margins: units.gu(1)
                        text: model.text
                        wrapMode: Text.Wrap
                        color: model.role === "user" ? "#FFFFFF" : "#1E293B"
                    }
                }
            }
        }

        // Welcome placeholder View
        Column {
            id: welcomeView
            anchors.centerIn: parent
            width: parent.width - units.gu(6)
            spacing: units.gu(2)
            visible: messageModel.count === 0

            Rectangle {
                width: units.gu(8)
                height: units.gu(8)
                radius: units.gu(2)
                color: "#FFEBE6"
                anchors.horizontalCenter: parent.horizontalCenter

                Icon {
                    anchors.centerIn: parent
                    name: "message"
                    width: units.gu(4)
                    height: units.gu(4)
                    color: "#E95420"
                }
            }

            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: i18n.tr("Welcome to UTGPT")
                font.bold: true
                fontSize: "large"
                color: "#1E293B"
            }

            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: i18n.tr("Ask anything! Choose a model above or type a message to start the conversation.")
                color: "#64748B"
                fontSize: "small"
            }

            Column {
                width: parent.width
                spacing: units.gu(1)

                Label {
                    text: i18n.tr("Try asking:")
                    color: "#94A3B8"
                    fontSize: "x-small"
                    font.bold: true
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Button {
                    width: parent.width
                    text: i18n.tr("What is Ubuntu Touch?")
                    color: "#F1F5F9"
                    onClicked: {
                        composer.text = text
                        chatPage.sendMessage()
                    }
                }

                Button {
                    width: parent.width
                    text: i18n.tr("Explain QML in simple terms")
                    color: "#F1F5F9"
                    onClicked: {
                        composer.text = text
                        chatPage.sendMessage()
                    }
                }
            }
        }

        // Input card row
        Rectangle {
            id: inputCard
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(7.5)
            color: "#FFFFFF"
            border.color: "#E2E8F0"
            border.width: 1
            radius: units.gu(1.5)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: units.gu(1.5)
                anchors.rightMargin: units.gu(1.5)
                spacing: units.gu(1)

                TextField {
                    id: composer
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    placeholderText: i18n.tr("Type a message...")
                    enabled: !chatPage.isResponding
                    onAccepted: chatPage.sendMessage()
                }

                Button {
                    id: sendButton
                    Layout.preferredWidth: units.gu(10)
                    Layout.preferredHeight: units.gu(5)
                    Layout.alignment: Qt.AlignVCenter
                    text: chatPage.isResponding ? i18n.tr("...") : i18n.tr("Send")
                    color: (chatPage.isResponding || !composer.text || composer.text.trim().length === 0) ? "#E2E8F0" : "#E95420"
                    enabled: !chatPage.isResponding && composer.text && composer.text.trim().length > 0
                    onClicked: chatPage.sendMessage()
                }
            }
        }
    }
}

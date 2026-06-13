/*
 * ChatPage.qml
 *
 * Renders the main UTGPT conversation screen, streams inference text into the
 * latest assistant bubble, and exposes clearHistory() for Settings-driven reset.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3

Page {
    id: chatPage
    title: i18n.tr("Chat")

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
            if (!result || !result.event || !result.payload) {
                return
            }

            if (result.payload.requestId !== pendingRequestId) {
                console.log("QML_LOG: Request ID mismatch: " + result.payload.requestId + " != " + pendingRequestId)
                return
            }

            if (result.event === "inference_token") {
                chatPage.appendAssistantText(result.payload.text)
            } else if (result.event === "inference_done") {
                chatPage.finishResponse(result.payload.ok, result.payload.error)
                pendingRequestId = ""
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: units.gu(2)
        spacing: units.gu(1)

        ListView {
            id: messageList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: units.gu(1)
            model: messageModel

            delegate: Item {
                width: messageList.width
                height: bubble.implicitHeight + units.gu(1)

                Rectangle {
                    id: bubble
                    anchors {
                        top: parent.top
                        right: model.role === "user" ? parent.right : undefined
                        left: model.role === "assistant" ? parent.left : undefined
                    }
                    width: Math.min(messageText.implicitWidth + units.gu(4), messageList.width * 0.78)
                    implicitHeight: messageText.implicitHeight + units.gu(2.5)
                    radius: units.gu(1.2)
                    color: model.role === "user" ? "#19B6EE" : "#2a2a2a"

                    Label {
                        id: messageText
                        anchors.fill: parent
                        anchors.margins: units.gu(1.2)
                        text: model.text
                        wrapMode: Text.Wrap
                        color: "white"
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: units.gu(1)

            TextField {
                id: composer
                Layout.fillWidth: true
                placeholderText: i18n.tr("Type a message...")
                enabled: !chatPage.isResponding
                onAccepted: chatPage.sendMessage()
            }

            Button {
                id: sendButton
                text: chatPage.isResponding ? i18n.tr("Waiting...") : i18n.tr("Send")
                enabled: !chatPage.isResponding
                onClicked: chatPage.sendMessage()
            }
        }
    }
}

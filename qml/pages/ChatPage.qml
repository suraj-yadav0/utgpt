/*
 * ChatPage.qml
 *
 * Renders the main UTGPT conversation screen, streams inference text into the
 * latest assistant bubble, and exposes clearHistory() for Settings-driven reset.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import QtQuick.Controls 2.2 as QQC2
import "../components"

Page {
    id: chatPage
    signal toggleSidebar()

    header: PageHeader {
        id: chatHeader
        title: i18n.tr("Chat")
        StyleHints {
            backgroundColor: root.themeColor
            foregroundColor: "white"
        }
        leadingActionBar.numberOfSlots: 1
        leadingActionBar.actions: [
            Action {
                iconName: "navigation-menu"
                text: i18n.tr("Menu")
                visible: true
                onTriggered: chatPage.toggleSidebar()
            }
        ]
        NavigationRow {
            anchors.right: parent.right
            anchors.rightMargin: units.gu(1.5)
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    property var python
    property bool backendReady: false
    property string model: ""
    property real temperature: 0.7
    property int maxTokens: 512
    property int threads: 4
    property int ctxSize: 2048
    property string flashAttn: "auto"
    property string kvCache: "f16"
    property bool webSearchEnabled: false
    property bool isResponding: false
    property string pendingRequestId: ""
    property bool userStopped: false

    ListModel {
        id: attachedDocsModel
    }

    onBackendReadyChanged: {
        if (backendReady) {
            docPickerLoader.source = root.isDesktop ? "../components/DesktopFilePicker.qml" : "../components/LomiriFilePicker.qml"
            picturePickerLoader.source = root.isDesktop ? "../components/DesktopFilePicker.qml" : "../components/LomiriPicturePicker.qml"
        }
    }

    function loadSessionDocuments(sessionId) {
        attachedDocsModel.clear()
        if (!backendReady) return;
        python.call("backend.get_session_documents", [sessionId || ""], function(result) {
            attachedDocsModel.clear()
            if (result && result.length > 0) {
                for (var i = 0; i < result.length; i++) {
                    attachedDocsModel.append({
                        "id": result[i].id,
                        "filename": result[i].filename,
                        "filePath": result[i].file_path,
                        "fileSize": result[i].file_size,
                        "charCount": result[i].char_count,
                        "chunkCount": result[i].chunk_count || 1,
                        "fileType": result[i].file_type || "document",
                        "isImage": !!result[i].is_image
                    })
                }
            }
        })
    }

    function attachDocument(fileUrl, onComplete) {
        if (!fileUrl) {
            if (onComplete) onComplete();
            return;
        }
        python.call("backend.attach_document", [fileUrl, root.currentSessionId || ""], function(result) {
            if (onComplete) {
                onComplete();
            }
            if (result) {
                if (result.session_id && root.currentSessionId !== result.session_id) {
                    root.currentSessionId = result.session_id
                    root.refreshSessions()
                }
                loadSessionDocuments(root.currentSessionId)
                if (result.is_image) {
                    if (result.ocr_success && result.ocr_chars > 0) {
                        root.showNotification(
                            i18n.tr("Image OCR Complete"),
                            i18n.tr("Recognized %1 characters from '%2'").arg(result.ocr_chars).arg(result.filename)
                        )
                    } else if (result.ocr_downloading) {
                        root.showNotification(
                            i18n.tr("Setting up OCR Engine"),
                            i18n.tr("Downloading Tesseract OCR engine in background. Please wait a moment and try again.")
                        )
                    } else {
                        root.showNotification(
                            i18n.tr("Image Attached"),
                            i18n.tr("Attached image '%1'").arg(result.filename)
                        )
                    }
                } else {
                    root.showNotification(
                        i18n.tr("Document Attached"),
                        i18n.tr("Successfully attached and indexed '%1' (%2 chunks)").arg(result.filename).arg(result.chunk_count)
                    )
                }
            }
        })
    }

    function removeDocument(documentId, modelIndex) {
        if (!documentId) return;
        python.call("backend.delete_session_document", [documentId], function(ok) {
            if (ok && modelIndex >= 0 && modelIndex < attachedDocsModel.count) {
                attachedDocsModel.remove(modelIndex)
            }
        })
    }

    function loadHistory(sessionId) {
        if (root.debugMode) {
            console.log("QML_LOG: loadHistory called with sessionId:", sessionId, "stack:", new Error().stack)
        }
        loadSessionDocuments(sessionId)
        if (sessionId === null || sessionId === undefined) {
            messageModel.clear()
            return
        }
        python.call("backend.load_chat_history", [sessionId], function(result) {
            messageModel.clear()
            if (result && result.length > 0) {
                for (var i = 0; i < result.length; i++) {
                    messageModel.append({ "role": result[i].role, "text": result[i].text })
                }
            }
            scrollToBottom()
        })
    }

    function stopInference() {
        if (!isResponding) return;
        userStopped = true
        python.call("backend.stop_all_inference", [])
    }

    function stopAndSaveCurrentResponse() {
        if (!isResponding) return;
        if (root.debugMode) {
            console.log("QML_LOG: stopAndSaveCurrentResponse called for session:", root.currentSessionId)
        }
        python.call("backend.stop_all_inference", [])
        if (messageModel.count > 0) {
            var lastIndex = messageModel.count - 1
            var lastItem = messageModel.get(lastIndex)
            if (lastItem.role === "assistant" && lastItem.text !== "Thinking" && !lastItem.text.startsWith("Thinking") && lastItem.text !== "...") {
                python.call("backend.add_chat_message", ["assistant", lastItem.text, root.currentSessionId || ""])
            }
        }
        isResponding = false
        pendingRequestId = ""
        userStopped = false
    }

    function startNewChat() {
        messageModel.clear()
        attachedDocsModel.clear()
        composer.text = ""
        isResponding = false
        pendingRequestId = ""
    }

    function clearHistory() {
        messageModel.clear()
        attachedDocsModel.clear()
        composer.text = ""
        isResponding = false
        pendingRequestId = ""
        python.call("backend.clear_chat_history", [], function() {
            root.currentSessionId = null
            root.refreshSessions()
        })
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
        if (currentText === "..." || currentText.startsWith("Thinking")) {
            currentText = ""
        }
        var newText = currentText + chunk

        // Format reasoning blocks cleanly for markdown/text display
        newText = newText.replace(/<think>\s*/gi, "*Thinking Process:*\n\n")
                         .replace(/\s*<\/think>\s*/gi, "\n\n---\n\n")
                         .replace(/<\|im_end\|>/gi, "")
                         .replace(/<\/im_end>/gi, "")
                         .replace(/<\|im_start\|>/gi, "")
                         .replace(/<end_of_turn>/gi, "")
                         .replace(/<start_of_turn>/gi, "")
                         .replace(/<\|end\|>/gi, "")
                         .replace(/<\|eot_id\|>/gi, "")
                         .replace(/<\|start_header_id\|>/gi, "")
                         .replace(/\[end of text\]/gi, "")

        messageModel.setProperty(lastIndex, "text", newText)
        scrollToBottom()
    }

    function finishResponse(ok, errorMessage) {
        isResponding = false

        if (!ok && messageModel.count > 0) {
            var lastIndex = messageModel.count - 1
            var currentText = messageModel.get(lastIndex).text
            var fallback = userStopped ? i18n.tr("Generation stopped by user.") : (errorMessage && errorMessage.length > 0 ? errorMessage : "The model stopped unexpectedly.")
            if (currentText === "..." || currentText.startsWith("Thinking")) {
                messageModel.setProperty(lastIndex, "text", fallback)
            } else if (userStopped) {
                // Keep the generated text, do not append crash message
            } else {
                messageModel.setProperty(lastIndex, "text", currentText + "\n" + fallback)
            }
        }

        // Save generated assistant response to database
        if (messageModel.count > 0) {
            var lastIndex = messageModel.count - 1
            var lastItem = messageModel.get(lastIndex)
            if (lastItem.role === "assistant" && lastItem.text !== "Thinking" && !lastItem.text.startsWith("Thinking") && lastItem.text !== "...") {
                python.call("backend.add_chat_message", ["assistant", lastItem.text, root.currentSessionId || ""])
            }
        }

        userStopped = false
    }

    function regenerateResponse(idx) {
        if (isResponding) return;
        if (idx < 0 || idx >= messageModel.count) return;
        if (messageModel.get(idx).role !== "user") return;

        if (!model) {
            messageModel.append({ "role": "assistant", "text": i18n.tr("Select a model in Settings before chatting.") })
            scrollToBottom()
            return
        }

        // 1. Truncate UI model to only keep up to the user message at idx
        while (messageModel.count > idx + 1) {
            messageModel.remove(messageModel.count - 1)
        }

        // 2. Truncate SQLite database
        if (root.currentSessionId) {
            python.call("backend.truncate_session_messages", [root.currentSessionId, idx + 1])
        }

        // 3. Build history context
        var history = []
        for (var i = 0; i < messageModel.count; i++) {
            var item = messageModel.get(i)
            if (item.role === "user" || (item.role === "assistant" && item.text !== "Thinking" && !item.text.startsWith("Thinking") && item.text !== "...")) {
                history.push({ "role": item.role, "content": item.text })
            }
        }

        // 4. Start response generation
        messageModel.append({ "role": "assistant", "text": "Thinking" })
        isResponding = true
        pendingRequestId = "chat-" + Date.now()
        scrollToBottom()

        python.call(
            "backend.run_inference",
            [model, history, temperature, maxTokens, threads, ctxSize, flashAttn, kvCache, webSearchEnabled, pendingRequestId, pendingRequestId],
            function(result) {
                if (result === false && isResponding) {
                    var lastIndex = messageModel.count - 1
                    if (lastIndex >= 0 && (messageModel.get(lastIndex).text === "..." || messageModel.get(lastIndex).text.startsWith("Thinking"))) {
                        finishResponse(false, i18n.tr("Unable to start inference."))
                    }
                }
            }
        )
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

        // Build history array of previous messages to pass as context
        var history = []
        for (var i = 0; i < messageModel.count; i++) {
            var item = messageModel.get(i)
            // Filter out system warnings or thinking states
            if (item.role === "user" || (item.role === "assistant" && item.text !== "Thinking" && !item.text.startsWith("Thinking" ) && item.text !== "...")) {
                history.push({ "role": item.role, "content": item.text })
            }
        }
        history.push({ "role": "user", "content": trimmed })

        // Save user message to database
        python.call("backend.add_chat_message", ["user", trimmed, root.currentSessionId || ""], function(newSessionId) {
            if (newSessionId && root.currentSessionId !== newSessionId) {
                root.currentSessionId = newSessionId
                root.refreshSessions()
            }
        })

        messageModel.append({ "role": "user", "text": trimmed })
        messageModel.append({ "role": "assistant", "text": "Thinking" })
        composer.text = ""
        isResponding = true
        pendingRequestId = "chat-" + Date.now()
        scrollToBottom()

        python.call(
            "backend.run_inference",
            [model, history, temperature, maxTokens, threads, ctxSize, flashAttn, kvCache, webSearchEnabled, pendingRequestId, pendingRequestId],
            function(result) {
                if (result === false && isResponding) {
                    var lastIndex = messageModel.count - 1
                    if (lastIndex >= 0 && (messageModel.get(lastIndex).text === "..." || messageModel.get(lastIndex).text.startsWith("Thinking"))) {
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
            if (root.debugMode) {
                console.log("QML_LOG: ChatPage received result type:", typeof result, "JSON:", JSON.stringify(result), "pendingRequestId:", pendingRequestId)
            }
            
            // PyOtherSide received signal passes arguments wrapped in a JavaScript array
            var data = (result && result.length > 0) ? result[0] : null
            if (!data || !data.event || !data.payload) {
                return
            }

            if (data.payload.requestId !== pendingRequestId) {
                if (root.debugMode) {
                    console.log("QML_LOG: Request ID mismatch: " + data.payload.requestId + " != " + pendingRequestId)
                }
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

    Timer {
        id: thinkingTimer
        interval: 400
        repeat: true
        running: chatPage.isResponding && messageModel.count > 0 && 
                 (messageModel.get(messageModel.count - 1).text.startsWith("Thinking") || 
                  messageModel.get(messageModel.count - 1).text === "...")
        
        property int step: 0

        onTriggered: {
            if (messageModel.count === 0) return
            var lastIndex = messageModel.count - 1
            step = (step + 1) % 4
            var dots = ""
            if (step === 1) dots = "."
            else if (step === 2) dots = ".."
            else if (step === 3) dots = "..."
            messageModel.setProperty(lastIndex, "text", i18n.tr("Thinking") + dots)
        }

        onRunningChanged: {
            if (running) {
                step = 0
                if (messageModel.count > 0) {
                    messageModel.setProperty(messageModel.count - 1, "text", i18n.tr("Thinking"))
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: root.bgColor
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
            color: root.cardColor
            border.color: root.cardBorderColor
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
                    color: root.availableModels.length > 0 ? root.themeBgLight : (root.isDark ? "#4C1D1D" : "#FFF5F5")
                    Layout.alignment: Qt.AlignVCenter

                    Icon {
                        anchors.centerIn: parent
                        name: root.availableModels.length > 0 ? "message" : "dialog-warning"
                        width: units.gu(2.2)
                        height: units.gu(2.2)
                        color: root.availableModels.length > 0 ? root.themeTextColor : "#E53E3E"
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
                        color: root.bodyTextColor
                        fontSize: "small"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    StyledComboBox {
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

                    Rectangle {
                        id: webSearchBtn
                        width: units.gu(7.5)
                        height: units.gu(3.6)
                        radius: units.gu(1)
                        color: chatPage.webSearchEnabled ? (root.isDark ? "#1E2D2A" : "#E6FFFA") : (root.isDark ? "#2D2D2D" : "#EDF2F7")
                        border.color: chatPage.webSearchEnabled ? "#319795" : root.cardBorderColor
                        border.width: 1
                        Layout.alignment: Qt.AlignVCenter

                        RowLayout {
                            anchors.centerIn: parent
                            spacing: units.gu(0.5)

                            Icon {
                                name: "stock_internet"
                                width: units.gu(1.8)
                                height: units.gu(1.8)
                                color: chatPage.webSearchEnabled ? "#319795" : root.secondaryTextColor
                            }

                            Label {
                                text: i18n.tr("Web")
                                fontSize: "x-small"
                                font.bold: true
                                color: chatPage.webSearchEnabled ? "#319795" : root.secondaryTextColor
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: chatPage.webSearchEnabled = !chatPage.webSearchEnabled
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
                height: Math.max(units.gu(4.5), bubbleContainer.height) + units.gu(1.5)

                // Avatar bubble
                Rectangle {
                    id: avatar
                    width: units.gu(4)
                    height: units.gu(4)
                    radius: width / 2
                    color: model.role === "user" ? root.themeBgLight : (root.isDark ? "#2D2D2D" : "#E2E8F0")
                    anchors.top: parent.top
                    anchors.topMargin: units.gu(0.5)
                    anchors.left: model.role === "assistant" ? parent.left : undefined
                    anchors.right: model.role === "user" ? parent.right : undefined

                    Label {
                        anchors.centerIn: parent
                        text: model.role === "user" ? "U" : "AI"
                        color: model.role === "user" ? root.themeTextColor : root.bodyTextColor
                        font.bold: true
                        fontSize: "small"
                    }
                }

                // Message container holding bubble and actions
                Column {
                    id: bubbleContainer
                    anchors {
                        top: parent.top
                        topMargin: units.gu(0.5)
                        left: model.role === "assistant" ? avatar.right : undefined
                        right: model.role === "user" ? avatar.left : undefined
                        leftMargin: model.role === "assistant" ? units.gu(1) : undefined
                        rightMargin: model.role === "user" ? units.gu(1) : undefined
                    }
                    spacing: units.gu(0.6)

                    // Message bubble
                    Rectangle {
                        id: bubble
                        width: Math.min(messageText.implicitWidth + units.gu(3.5), messageList.width * 0.76)
                        height: messageText.implicitHeight + units.gu(2)
                        radius: units.gu(1.5)
                        color: model.role === "user" ? root.themeColor : root.assistantBubbleColor
                        border.color: model.role === "user" ? "transparent" : root.assistantBubbleBorderColor
                        border.width: model.role === "user" ? 0 : 1

                        Label {
                            id: messageText
                            anchors.fill: parent
                            anchors.margins: units.gu(1)
                            text: model.text
                            wrapMode: Text.Wrap
                            textFormat: model.role === "assistant" ? (typeof Text.MarkdownText !== "undefined" ? Text.MarkdownText : Text.AutoText) : Text.PlainText
                            color: model.role === "user" ? "#FFFFFF" : root.assistantBubbleTextColor
                        }
                    }

                    // Copy action button
                    RowLayout {
                        visible: model.role === "assistant" && model.text !== "Thinking" && !model.text.startsWith("Thinking") && model.text !== "..."
                        spacing: units.gu(1)

                        Rectangle {
                            id: copyBtn
                            width: units.gu(9)
                            height: units.gu(3)
                            radius: units.gu(0.6)
                            color: isCopied ? (root.isDark ? "#1E2D2A" : "#E6FFFA") : root.cardColor
                            border.color: isCopied ? "#319795" : root.cardBorderColor
                            border.width: 1

                            property bool isCopied: false

                            Timer {
                                id: copiedTimer
                                interval: 2000
                                onTriggered: copyBtn.isCopied = false
                            }

                            RowLayout {
                                anchors.centerIn: parent
                                spacing: units.gu(0.5)

                                Icon {
                                    name: copyBtn.isCopied ? "ok" : "edit-copy"
                                    width: units.gu(1.6)
                                    height: units.gu(1.6)
                                    color: copyBtn.isCopied ? (root.isDark ? "#4FD1C5" : "#319795") : root.bodyTextColor
                                }

                                Label {
                                    text: copyBtn.isCopied ? i18n.tr("Copied!") : i18n.tr("Copy")
                                    color: copyBtn.isCopied ? (root.isDark ? "#4FD1C5" : "#319795") : root.bodyTextColor
                                    fontSize: "x-small"
                                    font.bold: true
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    Clipboard.push(model.text)
                                    copyBtn.isCopied = true
                                    copiedTimer.restart()
                                }
                            }
                        }
                    }

                    // Redo action button
                    RowLayout {
                        visible: model.role === "user" && !chatPage.isResponding
                        spacing: units.gu(1)
                        anchors.right: parent.right

                        Rectangle {
                            id: redoBtn
                            width: units.gu(9)
                            height: units.gu(3)
                            radius: units.gu(0.6)
                            color: root.cardColor
                            border.color: root.cardBorderColor
                            border.width: 1

                            RowLayout {
                                anchors.centerIn: parent
                                spacing: units.gu(0.5)

                                Icon {
                                    name: "reload"
                                    width: units.gu(1.6)
                                    height: units.gu(1.6)
                                    color: root.bodyTextColor
                                }

                                Label {
                                    text: i18n.tr("Redo")
                                    color: root.bodyTextColor
                                    fontSize: "x-small"
                                    font.bold: true
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    chatPage.regenerateResponse(index)
                                }
                            }
                        }
                    }
                }
            }
        }



        Component {
            id: attachmentChoiceDialogComponent
            AttachmentChoiceDialog {
                onCameraRequested: {
                    if (picturePickerLoader.item) {
                        picturePickerLoader.item.openCamera()
                    }
                }
                onGalleryRequested: {
                    if (picturePickerLoader.item) {
                        picturePickerLoader.item.openGallery()
                    }
                }
                onDocPickerRequested: {
                    if (docPickerLoader.item) {
                        docPickerLoader.item.open()
                    }
                }
            }
        }

        // Attached documents chip container
        Rectangle {
            id: attachedDocsBar
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(4.5)
            visible: attachedDocsModel.count > 0
            color: "transparent"

            RowLayout {
                anchors.fill: parent
                spacing: units.gu(1)

                ListView {
                    id: attachedDocsView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    orientation: ListView.Horizontal
                    spacing: units.gu(1)
                    clip: true
                    model: attachedDocsModel

                    delegate: Rectangle {
                        width: docChipRow.implicitWidth + units.gu(2)
                        height: units.gu(4)
                        radius: units.gu(1)
                        color: root.isDark ? "#262626" : "#E2E8F0"
                        border.color: root.themeColor
                        border.width: 1

                        RowLayout {
                            id: docChipRow
                            anchors.centerIn: parent
                            spacing: units.gu(0.6)

                            Icon {
                                name: model.isImage ? "camera-app" : "document-open"
                                width: units.gu(1.8)
                                height: units.gu(1.8)
                                color: root.themeTextColor
                            }

                            Label {
                                text: model.filename
                                fontSize: "x-small"
                                font.bold: true
                                color: root.primaryTextColor
                                elide: Text.ElideRight
                                maximumLineCount: 1
                            }

                            Label {
                                text: model.isImage ? (model.charCount > 0 ? ("(" + model.charCount + " chars OCR)") : "(Image)") : ("(" + model.chunkCount + " chunks)")
                                fontSize: "x-small"
                                color: root.secondaryTextColor
                            }

                            Rectangle {
                                width: units.gu(2.4)
                                height: units.gu(2.4)
                                radius: width / 2
                                color: "transparent"

                                Icon {
                                    anchors.centerIn: parent
                                    name: "close"
                                    width: units.gu(1.4)
                                    height: units.gu(1.4)
                                    color: "#C7162B"
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: {
                                        chatPage.removeDocument(model.id, index)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Input card row
        Rectangle {
            id: inputCard
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(7.5)
            color: root.cardColor
            border.color: root.cardBorderColor
            border.width: 1
            radius: units.gu(1.5)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: units.gu(1.5)
                anchors.rightMargin: units.gu(1.5)
                spacing: units.gu(1)

                Button {
                    id: attachButton
                    Layout.preferredWidth: units.gu(4.5)
                    Layout.preferredHeight: units.gu(4.5)
                    Layout.alignment: Qt.AlignVCenter
                    color: root.isDark ? "#2D2D2D" : "#E2E8F0"
                    enabled: !chatPage.isResponding

                    Icon {
                        anchors.centerIn: parent
                        name: "attachment"
                        width: units.gu(2.2)
                        height: units.gu(2.2)
                        color: attachButton.enabled ? root.primaryTextColor : root.secondaryTextColor
                    }

                    onClicked: {
                        PopupUtils.open(attachmentChoiceDialogComponent, root)
                    }
                }

                TextField {
                    id: composer
                    Layout.fillWidth: true
                    Layout.preferredHeight: units.gu(4.5)
                    Layout.alignment: Qt.AlignVCenter
                    placeholderText: attachedDocsModel.count > 0 ? i18n.tr("Ask about attached documents or images...") : i18n.tr("Type a message...")
                    enabled: !chatPage.isResponding
                    onAccepted: chatPage.sendMessage()
                }

                Button {
                    id: sendButton
                    Layout.preferredWidth: units.gu(4.5)
                    Layout.preferredHeight: units.gu(4.5)
                    Layout.alignment: Qt.AlignVCenter
                    color: chatPage.isResponding ? "#C7162B" : ((!composer.text || composer.text.trim().length === 0) ? (root.isDark ? "#2D2D2D" : "#E2E8F0") : root.themeColor)
                    enabled: chatPage.isResponding || (composer.text && composer.text.trim().length > 0)

                    Icon {
                        anchors.centerIn: parent
                        name: chatPage.isResponding ? "media-playback-stop" : "send"
                        width: units.gu(2.4)
                        height: units.gu(2.4)
                        color: sendButton.enabled ? "white" : (root.isDark ? "#4A5568" : "#94A3B8")
                    }

                    onClicked: {
                        if (chatPage.isResponding) {
                            chatPage.stopInference()
                        } else {
                            chatPage.sendMessage()
                        }
                    }
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
            color: root.themeBgLight
            anchors.horizontalCenter: parent.horizontalCenter

            Icon {
                anchors.centerIn: parent
                name: "message"
                width: units.gu(4)
                height: units.gu(4)
                color: root.themeTextColor
            }
        }

        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: i18n.tr("Welcome to UTGPT")
            font.bold: true
            fontSize: "large"
            color: root.primaryTextColor
        }

        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: i18n.tr("Ask anything! Choose a model above or type a message to start the conversation.")
            color: root.secondaryTextColor
            fontSize: "small"
        }

        Column {
            width: parent.width
            spacing: units.gu(1)

            Label {
                text: i18n.tr("Try asking:")
                color: root.tertiaryTextColor
                fontSize: "x-small"
                font.bold: true
                anchors.horizontalCenter: parent.horizontalCenter
            }

            GridLayout {
                width: parent.width
                columns: 2
                rowSpacing: units.gu(1)
                columnSpacing: units.gu(1)

                Button {
                    id: q1
                    Layout.fillWidth: true
                    text: i18n.tr("What is Ubuntu Touch?")
                    color: root.tryAskingButtonColor
                    onClicked: {
                        composer.text = q1.text
                        chatPage.sendMessage()
                    }
                }

                Button {
                    id: q2
                    Layout.fillWidth: true
                    text: i18n.tr("Tell me a joke!")
                    color: root.tryAskingButtonColor
                    onClicked: {
                        composer.text = q2.text
                        chatPage.sendMessage()
                    }
                }

                Button {
                    id: q3
                    Layout.fillWidth: true
                    text: i18n.tr("A fun recipe in 10 minutes")
                    color: root.tryAskingButtonColor
                    onClicked: {
                        composer.text = q3.text
                        chatPage.sendMessage()
                    }
                }

                Button {
                    id: q4
                    Layout.fillWidth: true
                    text: i18n.tr("2 min story")
                    color: root.tryAskingButtonColor
                    onClicked: {
                        composer.text = q4.text
                        chatPage.sendMessage()
                    }
                }
            }
        }
    }

    Loader {
        id: docPickerLoader
        anchors.fill: parent
        z: 1000
        onLoaded: {
            if (item) {
                if (item.hasOwnProperty("title")) {
                    item.title = i18n.tr("Select Document File")
                }
                if (item.hasOwnProperty("nameFilters")) {
                    item.nameFilters = [
                        "Document files (*.txt *.md *.pdf *.json *.csv *.py *.js *.c *.cpp *.qml *.html *.xml *.yaml *.yml)",
                        "All files (*)"
                    ]
                }
                item.fileSelected.connect(function(fileUrl) {
                    chatPage.attachDocument(fileUrl, function() {
                        if (item && item.hasOwnProperty("finalizeTransfer")) {
                            item.finalizeTransfer()
                        }
                    })
                })
            }
        }
    }

    Loader {
        id: picturePickerLoader
        anchors.fill: parent
        z: 1000
        onLoaded: {
            if (item) {
                if (item.hasOwnProperty("title")) {
                    item.title = i18n.tr("Select or Capture Image")
                }
                if (item.hasOwnProperty("nameFilters")) {
                    item.nameFilters = [
                        "Image files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif *.svg)",
                        "All files (*)"
                    ]
                }
                item.fileSelected.connect(function(fileUrl) {
                    chatPage.attachDocument(fileUrl, function() {
                        if (item && item.hasOwnProperty("finalizeTransfer")) {
                            item.finalizeTransfer()
                        }
                    })
                })
            }
        }
    }

}

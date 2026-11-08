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
    property bool webSearchEnabled: true
    property string webSearchMode: "auto"
    property bool webSearchActive: false
    property string webSearchStatusText: i18n.tr("Searching the web for latest info...")
    property var activeSources: []
    property bool isResponding: false
    property string pendingRequestId: ""
    property bool userStopped: false

    onWebSearchEnabledChanged: {
        if (!webSearchEnabled && webSearchMode !== "off") {
            webSearchMode = "off"
        } else if (webSearchEnabled && webSearchMode === "off") {
            webSearchMode = "auto"
        }
    }
    onWebSearchModeChanged: {
        webSearchEnabled = (webSearchMode !== "off")
    }

    function loadHistory(sessionId) {
        if (root.debugMode) {
            console.log("QML_LOG: loadHistory called with sessionId:", sessionId, "stack:", new Error().stack)
        }
        if (sessionId === null || sessionId === undefined) {
            messageModel.clear()
            return
        }
        python.call("backend.load_chat_history", [sessionId], function(result) {
            messageModel.clear()
            if (result && result.length > 0) {
                for (var i = 0; i < result.length; i++) {
                    messageModel.append({ "role": result[i].role, "text": result[i].text, "sources": result[i].sources || "" })
                }
            }
            scrollToBottom()
        })
    }

    function stopInference() {
        if (!isResponding) return;
        userStopped = true
        webSearchActive = false
        python.call("backend.stop_all_inference", [])
    }

    function buildHistoryContext() {
        var history = []
        for (var i = 0; i < messageModel.count; i++) {
            var item = messageModel.get(i)
            var txt = (item.text || "").trim()
            if (item.role === "user") {
                history.push({ "role": "user", "content": txt })
            } else if (item.role === "assistant" && txt && !txt.startsWith("Thinking") && !txt.startsWith(i18n.tr("Thinking")) && txt !== "...") {
                history.push({ "role": "assistant", "content": txt })
            }
        }
        return history
    }

    function saveAssistantResponse(text) {
        if (!text) return
        var clean = text.trim()
        if (clean && !clean.startsWith("Thinking") && !clean.startsWith(i18n.tr("Thinking")) && clean !== "..." && clean !== "Generation stopped by user.") {
            var sourcesJson = (activeSources && activeSources.length > 0) ? JSON.stringify(activeSources) : ""
            if (arguments.length > 1 && arguments[1]) {
                sourcesJson = arguments[1]
            }
            python.call("backend.add_chat_message", ["assistant", clean, root.currentSessionId || "", sourcesJson])
        }
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
            if (lastItem.role === "assistant") {
                if (activeSources && activeSources.length > 0) {
                    messageModel.setProperty(lastIndex, "sources", JSON.stringify(activeSources))
                }
                saveAssistantResponse(lastItem.text)
            }
        }
        isResponding = false
        pendingRequestId = ""
        userStopped = false
        webSearchActive = false
        activeSources = []
    }

    function startNewChat() {
        messageModel.clear()
        composer.text = ""
        isResponding = false
        pendingRequestId = ""
        webSearchActive = false
        activeSources = []
    }

    function clearHistory() {
        messageModel.clear()
        composer.text = ""
        isResponding = false
        pendingRequestId = ""
        webSearchActive = false
        activeSources = []
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

        thinkingTimer.stop()

        var lastIndex = messageModel.count - 1
        var currentText = messageModel.get(lastIndex).text
        if (currentText === "..." || currentText.startsWith("Thinking") || currentText.startsWith(i18n.tr("Thinking"))) {
            currentText = ""
        }

        var text = chunk
        if (text.indexOf("<think>") >= 0 || text.indexOf("</think>") >= 0) {
            text = text.replace(/<think>\s*/gi, "*Thinking Process:*\n\n")
                       .replace(/\s*<\/think>\s*/gi, "\n\n---\n\n")
        }

        messageModel.setProperty(lastIndex, "text", currentText + text)
        scrollToBottom()
    }

    function finishResponse(ok, errorMessage) {
        isResponding = false
        webSearchActive = false

        var stoppedText = i18n.tr("Generation stopped by user.")
        if (!ok && messageModel.count > 0) {
            var lastIndex = messageModel.count - 1
            var currentText = messageModel.get(lastIndex).text
            var fallback = userStopped ? stoppedText : (errorMessage && errorMessage.length > 0 ? errorMessage : "The model stopped unexpectedly.")
            if (currentText === "..." || currentText.startsWith("Thinking") || currentText.startsWith(i18n.tr("Thinking"))) {
                messageModel.setProperty(lastIndex, "text", fallback)
            } else if (userStopped) {
                // Keep the generated text, do not append crash message
            } else {
                messageModel.setProperty(lastIndex, "text", currentText + "\n" + fallback)
            }
        }

        // Clean up stop tokens and normalize reasoning tags once generation ends
        if (messageModel.count > 0) {
            var lastIndex = messageModel.count - 1
            var itemText = messageModel.get(lastIndex).text
            if (itemText !== "..." && !itemText.startsWith("Thinking") && !itemText.startsWith(i18n.tr("Thinking")) &&
                itemText !== stoppedText && itemText !== "Generation stopped by user.") {
                var cleanedText = itemText.replace(/<think>\s*/gi, "*Thinking Process:*\n\n")
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
                if (cleanedText !== itemText) {
                    messageModel.setProperty(lastIndex, "text", cleanedText)
                }
            }
        }

        // Save generated assistant response to database
        if (messageModel.count > 0 && !userStopped) {
            var lastIndex = messageModel.count - 1
            var lastItem = messageModel.get(lastIndex)
            if (lastItem.role === "assistant" && lastItem.text !== stoppedText) {
                if (activeSources && activeSources.length > 0) {
                    messageModel.setProperty(lastIndex, "sources", JSON.stringify(activeSources))
                }
                saveAssistantResponse(lastItem.text)
            }
        }

        activeSources = []
        userStopped = false
    }

    function regenerateResponse(idx) {
        if (isResponding) return;
        if (idx < 0 || idx >= messageModel.count) return;
        if (messageModel.get(idx).role !== "user") return;

        if (!model) {
            messageModel.append({ "role": "assistant", "text": i18n.tr("Select a model in Settings before chatting."), "sources": "" })
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
        var history = buildHistoryContext()

        // 4. Start response generation
        activeSources = []
        webSearchStatusText = i18n.tr("Searching the web for latest info...")
        messageModel.append({ "role": "assistant", "text": "Thinking", "sources": "" })
        isResponding = true
        pendingRequestId = "chat-" + Date.now()
        scrollToBottom()

        python.call(
            "backend.run_inference",
            [model, history, temperature, maxTokens, threads, ctxSize, flashAttn, kvCache, webSearchMode, pendingRequestId, pendingRequestId],
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
            messageModel.append({ "role": "assistant", "text": "Select a model in Settings before chatting.", "sources": "" })
            composer.text = ""
            scrollToBottom()
            return
        }

        // Build history array of previous messages to pass as context
        var history = buildHistoryContext()
        history.push({ "role": "user", "content": trimmed })

        // Save user message to database
        python.call("backend.add_chat_message", ["user", trimmed, root.currentSessionId || ""], function(newSessionId) {
            if (newSessionId && root.currentSessionId !== newSessionId) {
                root.currentSessionId = newSessionId
                root.refreshSessions()
            }
        })

        activeSources = []
        webSearchStatusText = i18n.tr("Searching the web for latest info...")
        messageModel.append({ "role": "user", "text": trimmed, "sources": "" })
        messageModel.append({ "role": "assistant", "text": "Thinking", "sources": "" })
        composer.text = ""
        isResponding = true
        pendingRequestId = "chat-" + Date.now()
        scrollToBottom()

        python.call(
            "backend.run_inference",
            [model, history, temperature, maxTokens, threads, ctxSize, flashAttn, kvCache, webSearchMode, pendingRequestId, pendingRequestId],
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
            } else if (data.event === "web_search_status") {
                if (data.payload.phase === "started") {
                    chatPage.webSearchActive = true
                    var q = data.payload.query || ""
                    chatPage.webSearchStatusText = q ? (i18n.tr("Searching: \"") + q + "\"...") : i18n.tr("Searching the web for latest info...")
                } else if (data.payload.phase === "found") {
                    var count = data.payload.count || 0
                    chatPage.webSearchStatusText = i18n.tr("Found ") + count + i18n.tr(" sources, generating response...")
                } else if (data.payload.phase === "finished") {
                    chatPage.webSearchActive = false
                }
            } else if (data.event === "web_search_sources") {
                chatPage.activeSources = data.payload.sources || []
            } else if (data.event === "inference_done") {
                chatPage.webSearchActive = false
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
            var currentText = messageModel.get(lastIndex).text
            if (!currentText || (!currentText.startsWith("Thinking") && !currentText.startsWith(i18n.tr("Thinking")) && currentText !== "...")) {
                thinkingTimer.stop()
                return
            }
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
                        enabled: !chatPage.isResponding
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
                        width: units.gu(9.2)
                        height: units.gu(3.6)
                        radius: units.gu(1)
                        color: {
                            if (chatPage.webSearchMode === "on") return root.isDark ? "#1E2D2A" : "#E6FFFA"
                            if (chatPage.webSearchMode === "auto") return root.isDark ? "#233330" : "#EDFAF7"
                            return root.isDark ? "#2D2D2D" : "#EDF2F7"
                        }
                        border.color: chatPage.webSearchMode === "off" ? root.cardBorderColor : "#319795"
                        border.width: 1
                        Layout.alignment: Qt.AlignVCenter

                        RowLayout {
                            anchors.centerIn: parent
                            spacing: units.gu(0.4)

                            Icon {
                                name: "stock_website"
                                width: units.gu(1.6)
                                height: units.gu(1.6)
                                color: chatPage.webSearchMode === "off" ? root.secondaryTextColor : "#319795"
                            }

                            Label {
                                text: {
                                    if (chatPage.webSearchMode === "on") return i18n.tr("Web On")
                                    if (chatPage.webSearchMode === "auto") return i18n.tr("Web Auto")
                                    return i18n.tr("Web Off")
                                }
                                fontSize: "x-small"
                                font.bold: true
                                color: chatPage.webSearchMode === "off" ? root.secondaryTextColor : "#319795"
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                if (chatPage.webSearchMode === "auto") {
                                    chatPage.webSearchMode = "on"
                                } else if (chatPage.webSearchMode === "on") {
                                    chatPage.webSearchMode = "off"
                                } else {
                                    chatPage.webSearchMode = "auto"
                                }
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
                            textFormat: model.role === "assistant" ? (typeof Text.MarkdownText !== "undefined" ? Text.MarkdownText : Text.PlainText) : Text.PlainText
                            color: model.role === "user" ? "#FFFFFF" : root.assistantBubbleTextColor
                        }
                    }

                    // Web Search Sources Chips
                    Flow {
                        id: sourcesContainer
                        width: Math.min(messageText.implicitWidth + units.gu(3.5), messageList.width * 0.76)
                        spacing: units.gu(0.8)
                        visible: model.role === "assistant" && model.sources && model.sources !== "" && model.sources !== "[]"

                        property var parsedSources: {
                            if (!model.sources) return []
                            try {
                                var res = JSON.parse(model.sources)
                                return Array.isArray(res) ? res : []
                            } catch (e) {
                                return []
                            }
                        }

                        Repeater {
                            model: sourcesContainer.parsedSources

                            Rectangle {
                                height: units.gu(3.2)
                                width: Math.min(chipRow.implicitWidth + units.gu(1.6), sourcesContainer.width)
                                radius: units.gu(0.8)
                                color: chipMouse.pressed ? (root.isDark ? "#2C3E3B" : "#D4F5EC") : (root.isDark ? "#1E2D2A" : "#E6FFFA")
                                border.color: "#319795"
                                border.width: 1

                                RowLayout {
                                    id: chipRow
                                    anchors.fill: parent
                                    anchors.leftMargin: units.gu(0.8)
                                    anchors.rightMargin: units.gu(0.8)
                                    spacing: units.gu(0.5)

                                    Icon {
                                        name: "stock_website"
                                        width: units.gu(1.5)
                                        height: units.gu(1.5)
                                        color: "#319795"
                                        Layout.alignment: Qt.AlignVCenter
                                    }

                                    Label {
                                        text: modelData.title || modelData.url || ""
                                        color: root.isDark ? "#4FD1C5" : "#234E52"
                                        fontSize: "x-small"
                                        font.bold: true
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignVCenter
                                    }
                                }

                                MouseArea {
                                    id: chipMouse
                                    anchors.fill: parent
                                    onClicked: {
                                        if (modelData.url) {
                                            Qt.openUrlExternally(modelData.url)
                                        }
                                    }
                                }
                            }
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



        // Transient web-search status pill (never saved to chat history)
        Rectangle {
            id: webSearchStatus
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(4)
            visible: chatPage.webSearchActive
            color: root.isDark ? "#1E2D2A" : "#E6FFFA"
            border.color: "#319795"
            border.width: 1
            radius: units.gu(1)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: units.gu(1.5)
                anchors.rightMargin: units.gu(1.5)
                spacing: units.gu(1)

                ActivityIndicator {
                    running: webSearchStatus.visible
                    width: units.gu(2)
                    height: units.gu(2)
                    Layout.alignment: Qt.AlignVCenter
                }

                Label {
                    text: chatPage.webSearchStatusText
                    color: "#319795"
                    fontSize: "small"
                    font.italic: true
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    elide: Text.ElideRight
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

                TextField {
                    id: composer
                    Layout.fillWidth: true
                    Layout.preferredHeight: units.gu(4.5)
                    Layout.alignment: Qt.AlignVCenter
                    placeholderText: i18n.tr("Type a message...")
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

                    property real lastClickTime: 0

                    Icon {
                        anchors.centerIn: parent
                        name: chatPage.isResponding ? "media-playback-stop" : "send"
                        width: units.gu(2.4)
                        height: units.gu(2.4)
                        color: sendButton.enabled ? "white" : (root.isDark ? "#4A5568" : "#94A3B8")
                    }

                    onClicked: {
                        var now = Date.now()
                        if (now - lastClickTime < 400) {
                            return
                        }
                        lastClickTime = now

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

}

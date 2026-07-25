/*
 * SettingsPage.qml
 *
 * Exposes the active model selector, generation controls, free-storage status,
 * and a clearChat signal that Main.qml forwards to the chat page.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import QtQuick.Controls 2.2 as QQC2
import Lomiri.Components 1.3
import "../components"

Page {
    id: settingsPage
    signal toggleSidebar()
    signal showReleaseNotes()

    property string currentSection: ""
    property string themeMode: "system"


    header: PageHeader {
        id: settingsHeader
        title: settingsPage.currentSection === "" ? i18n.tr("Settings") :
               settingsPage.currentSection === "model" ? i18n.tr("Active Model") :
               settingsPage.currentSection === "engine" ? i18n.tr("Inference Engine") :
               settingsPage.currentSection === "generation" ? i18n.tr("Generation Settings") :
               settingsPage.currentSection === "performance" ? i18n.tr("Performance Settings") :
               settingsPage.currentSection === "theme" ? i18n.tr("Theme") :
               settingsPage.currentSection === "websearch" ? i18n.tr("Web Search") : i18n.tr("Storage & History")

        StyleHints {
            backgroundColor: root.themeColor
            foregroundColor: "white"
        }
        leadingActionBar.numberOfSlots: 1
        leadingActionBar.actions: [
            Action {
                iconName: settingsPage.currentSection === "" ? "navigation-menu" : "back"
                text: settingsPage.currentSection === "" ? i18n.tr("Menu") : i18n.tr("Back")
                visible: true
                onTriggered: {
                    if (settingsPage.currentSection === "") {
                        settingsPage.toggleSidebar()
                    } else {
                        settingsPage.currentSection = ""
                    }
                }
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
    property string selectedModel: ""
    property string engineStatus: "checking"
    property string engineError: ""
    
    onSelectedModelChanged: {
        var info = getModelInfo(selectedModel)
        var limit = info ? info.maxContext : 2048
        if (maxTokens > limit) {
            maxTokens = limit
        }
    }

    property real temperature: 0.7
    property int maxTokens: 512
    property int threads: 4
    property int ctxSize: 2048
    property string flashAttn: "auto"
    property string kvCache: "f16"
    property bool webSearchEnabled: false
    property string freeStorage: i18n.tr("Checking storage...")
    property var availableModels: root.availableModels

    signal clearChat()

    function refreshModels() {
        root.refreshModels()
    }

    function refreshStorage() {
        python.call("backend.get_free_storage", [], function(result) {
            freeStorage = result || i18n.tr("Storage unavailable")
        })
    }

    function refreshEngineStatus() {
        if (!backendReady) return;
        python.call("backend.get_inference_engine_status", [], function(result) {
            if (result) {
                engineStatus = result.status
                engineError = result.error
            }
        })
    }

    Timer {
        id: statusTimer
        interval: 1000
        repeat: true
        running: engineStatus === "downloading"
        onTriggered: refreshEngineStatus()
    }

    function snapTemperature(value) {
        return Math.round(value * 10) / 10
    }

    function snapMaxTokens(value) {
        if (value <= 200) {
            return Math.round(value / 10) * 10
        } else if (value <= 1000) {
            return Math.round(value / 50) * 50
        } else if (value <= 10000) {
            return Math.round(value / 500) * 500
        } else {
            return Math.round(value / 5000) * 5000
        }
    }

    function getModelInfo(filename) {
        if (!filename) return null;
        var fn = filename.toLowerCase();
        
        // Search in root.modelCatalog first
        if (root.modelCatalog) {
            for (var i = 0; i < root.modelCatalog.length; i++) {
                var item = root.modelCatalog[i];
                if (item.filename && item.filename.toLowerCase() === fn) {
                    return item;
                }
            }
        }
        
        // Fallback for custom or legacy filenames
        if (fn.indexOf("smollm2") >= 0) {
            return {
                name: "SmolLM2-1.7B",
                developer: "Hugging Face",
                size: "~1.0 GB",
                context: "8,192 tokens",
                maxContext: 8192,
                quant: "Q4_K_M (4-bit)",
                usage: "Fast general chat, low resource devices"
            };
        } else if (fn.indexOf("qwen") >= 0) {
            return {
                name: "Qwen2.5-1.5B",
                developer: "Alibaba Group",
                size: "~1.0 GB",
                context: "32,768 tokens",
                maxContext: 32768,
                quant: "Q4_K_M (4-bit)",
                usage: "Excellent multilingual capabilities, coding & reasoning"
            };
        } else if (fn.indexOf("llama-3.2-1b") >= 0) {
            return {
                name: "Llama-3.2-1B",
                developer: "Meta",
                size: "~800 MB",
                context: "128,000 tokens",
                maxContext: 128000,
                quant: "Q4_K_M (4-bit)",
                usage: "Ultra-fast assistant, agentic tasks, long contexts"
            };
        } else if (fn.indexOf("llama-3.2-3b") >= 0) {
            return {
                name: "Llama-3.2-3B",
                developer: "Meta",
                size: "~2.0 GB",
                context: "128,000 tokens",
                maxContext: 128000,
                quant: "Q4_K_M (4-bit)",
                usage: "Smart general assistant, high quality logic & reasoning"
            };
        } else if (fn.indexOf("gemma") >= 0) {
            return {
                name: "Gemma-2-2B",
                developer: "Google",
                size: "~1.7 GB",
                context: "8,192 tokens",
                maxContext: 8192,
                quant: "Q4_K_M (4-bit)",
                usage: "Lightweight high-quality chatting, instruction following"
            };
        } else if (fn.indexOf("phi-3") >= 0) {
            return {
                name: "Phi-3-mini-4K",
                developer: "Microsoft",
                size: "~2.2 GB",
                context: "4,096 tokens",
                maxContext: 4096,
                quant: "Q4_K_M (4-bit)",
                usage: "Reasoning, logical tasks, math and coding"
            };
        } else if (fn.indexOf("tinyllama") >= 0) {
            return {
                name: "TinyLlama-1.1B",
                developer: "TinyLlama Project",
                size: "~700 MB",
                context: "2,048 tokens",
                maxContext: 2048,
                quant: "Q4_K_M (4-bit)",
                usage: "Extremely fast, simple chats on low-spec hardware"
            };
        }
        return {
            name: filename,
            developer: "Unknown",
            size: "Unknown",
            context: "Unknown",
            maxContext: 2048,
            quant: "GGUF",
            usage: "General inference"
        };
    }

    onBackendReadyChanged: {
        if (backendReady) {
            refreshModels()
            refreshStorage()
            refreshEngineStatus()
        }
    }

    onVisibleChanged: {
        if (visible) {
            if (backendReady) {
                refreshModels()
                refreshStorage()
                refreshEngineStatus()
            }
        } else {
            currentSection = ""
        }
    }

    Rectangle {
        anchors.fill: parent
        color: root.bgColor
        z: -1
    }

    Flickable {
        anchors.top: settingsHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        contentWidth: width
        contentHeight: settingsColumn.height + units.gu(4)
        clip: true

        Column {
            id: settingsColumn
            width: parent.width - units.gu(4)
            anchors {
                left: parent.left
                right: parent.right
                top: parent.top
                margins: units.gu(2)
            }
            spacing: units.gu(2)

            // MAIN SETTINGS LIST
            StyledListView {
                id: listMenuContainer
                width: parent.width
                expandToContent: true
                visible: settingsPage.currentSection === ""

                model: ListModel {
                    ListElement { title: "Active Model"; icon: "message"; section: "model" }
                    ListElement { title: "Inference Engine"; icon: "info"; section: "engine" }
                    ListElement { title: "Generation Settings"; icon: "settings"; section: "generation" }
                    ListElement { title: "Performance Settings"; icon: "reload"; section: "performance" }
                    ListElement { title: "Theme"; icon: "preferences-desktop-display-symbolic"; section: "theme" }
                    ListElement { title: "Web Search"; icon: "stock_internet"; section: "websearch" }
                    ListElement { title: "Storage & History"; icon: "delete"; section: "storage" }
                    ListElement { title: "What's New & Release Notes"; icon: "info"; section: "releasenotes" }
                }


                delegate: Item {
                    width: listMenuContainer.width
                    height: units.gu(7.5)

                    Rectangle {
                        anchors.fill: parent
                        color: mouseArea.pressed ? (root.isDark ? "#2A2A2A" : "#E2E8F0") : (mouseArea.containsMouse ? (root.isDark ? "#242424" : "#F1F5F9") : "transparent")
                        Behavior on color { ColorAnimation { duration: 100 } }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: units.gu(2)
                        anchors.rightMargin: units.gu(2)
                        spacing: units.gu(2)

                        Icon {
                            name: model.icon
                            width: units.gu(2.6)
                            height: units.gu(2.6)
                            color: root.themeTextColor
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Label {
                            text: i18n.tr(model.title)
                            color: root.primaryTextColor
                            font.bold: true
                            fontSize: "medium"
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Icon {
                            name: "next"
                            width: units.gu(2.0)
                            height: units.gu(2.0)
                            color: root.secondaryTextColor
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: units.gu(6.6)
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: root.isDark ? "#2D2D2D" : "#E2E8F0"
                        visible: index < 6
                    }

                    MouseArea {
                        id: mouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (model.section === "releasenotes") {
                                settingsPage.showReleaseNotes()
                            } else {
                                settingsPage.currentSection = model.section
                            }
                        }
                    }
                }
            }

            // Card 1: Active Model
            Rectangle {
                width: parent.width
                height: activeModelColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "model"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: activeModelColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1)

                    Label {
                        text: i18n.tr("Active Model")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    Label {
                        text: i18n.tr("No models downloaded yet")
                        visible: settingsPage.availableModels.length === 0
                        color: root.secondaryTextColor
                        fontSize: "small"
                    }

                    StyledComboBox {
                        id: modelSelector
                        width: parent.width
                        visible: settingsPage.availableModels.length > 0
                        model: settingsPage.availableModels
                        currentIndex: settingsPage.availableModels.indexOf(settingsPage.selectedModel)

                        onActivated: {
                            if (currentIndex >= 0 && currentIndex < settingsPage.availableModels.length) {
                                settingsPage.selectedModel = settingsPage.availableModels[currentIndex]
                            }
                        }
                    }
                }
            }

            // Card 1b: Model Specifications
            Rectangle {
                width: parent.width
                height: modelSpecsColumn.implicitHeight + units.gu(3)
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)
                visible: settingsPage.currentSection === "model" && settingsPage.selectedModel !== ""

                Column {
                    id: modelSpecsColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.2)

                    Label {
                        text: i18n.tr("Model Specifications")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    GridLayout {
                        columns: 2
                        width: parent.width
                        columnSpacing: units.gu(2)
                        rowSpacing: units.gu(0.8)
                        
                        property var info: settingsPage.getModelInfo(settingsPage.selectedModel)

                        Label {
                            text: i18n.tr("Model Name:")
                            color: root.secondaryTextColor
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.name : ""
                            color: root.primaryTextColor
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Developer:")
                            color: root.secondaryTextColor
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.developer : ""
                            color: root.primaryTextColor
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("File Size:")
                            color: root.secondaryTextColor
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.size : ""
                            color: root.primaryTextColor
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Context Window:")
                            color: root.secondaryTextColor
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.context : ""
                            color: root.primaryTextColor
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Quantization:")
                            color: root.secondaryTextColor
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.quant : ""
                            color: root.primaryTextColor
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Recommended For:")
                            color: root.secondaryTextColor
                            fontSize: "small"
                            font.bold: true
                            Layout.alignment: Qt.AlignTop
                        }
                        Label {
                            text: parent.info ? parent.info.usage : ""
                            color: root.primaryTextColor
                            fontSize: "small"
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            // Card: Inference Engine Status
            Rectangle {
                width: parent.width
                height: engineStatusColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "engine"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: engineStatusColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.5)

                    Label {
                        text: i18n.tr("Inference Engine")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    RowLayout {
                        width: parent.width
                        spacing: units.gu(1)

                        Rectangle {
                            width: units.gu(1.2)
                            height: units.gu(1.2)
                            radius: height / 2
                            color: engineStatus === "ready" ? "#22C55E" : (engineStatus === "downloading" ? "#3B82F6" : "#EF4444")
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Label {
                            text: {
                                if (engineStatus === "ready") return i18n.tr("Ready");
                                if (engineStatus === "downloading") return i18n.tr("Downloading...");
                                if (engineStatus === "error") return i18n.tr("Error");
                                return i18n.tr("Not Downloaded");
                            }
                            font.bold: true
                            color: root.bodyTextColor
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Button {
                            text: engineStatus === "error" ? i18n.tr("Retry") : i18n.tr("Download")
                            visible: engineStatus !== "ready" && engineStatus !== "downloading"
                            color: root.themeColor
                            onClicked: {
                                python.call("backend.start_inference_engine_download", [], function(success) {
                                    refreshEngineStatus()
                                })
                            }
                        }
                        
                        ActivityIndicator {
                            running: engineStatus === "downloading"
                            visible: engineStatus === "downloading"
                            width: units.gu(2)
                            height: units.gu(2)
                        }
                    }

                    Label {
                        text: engineError
                        color: "#EF4444"
                        fontSize: "small"
                        wrapMode: Text.Wrap
                        width: parent.width
                        visible: engineStatus === "error" && engineError !== ""
                    }

                    Label {
                        text: i18n.tr("Required to run local .gguf models on your device.")
                        color: root.secondaryTextColor
                        fontSize: "x-small"
                        wrapMode: Text.Wrap
                        width: parent.width
                        visible: engineStatus !== "ready"
                    }
                }
            }

            // Card 2: Generation Settings
            Rectangle {
                width: parent.width
                height: genSettingsColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "generation"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: genSettingsColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.5)

                    Label {
                        text: i18n.tr("Generation Settings")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    Label {
                        text: i18n.tr("Temperature") + ": " + settingsPage.temperature.toFixed(1)
                        color: root.bodyTextColor
                        fontSize: "small"
                    }

                    Slider {
                        id: temperatureSlider
                        width: parent.width
                        minimumValue: 0.1
                        maximumValue: 1.0
                        value: settingsPage.temperature
                        live: true

                        onValueChanged: {
                            var snapped = settingsPage.snapTemperature(value)
                            if (Math.abs(snapped - value) > 0.001) {
                                value = snapped
                                return
                            }
                            settingsPage.temperature = snapped
                        }
                    }

                    Label {
                        text: i18n.tr("Max response length") + ": " + settingsPage.maxTokens + i18n.tr(" tokens")
                        color: root.bodyTextColor
                        fontSize: "small"
                    }

                    Slider {
                        id: maxTokensSlider
                        width: parent.width
                        minimumValue: 50
                        maximumValue: {
                            var info = settingsPage.getModelInfo(settingsPage.selectedModel)
                            return info ? info.maxContext : 2048
                        }
                        value: settingsPage.maxTokens
                        live: true

                        onValueChanged: {
                            var snapped = settingsPage.snapMaxTokens(value)
                            if (Math.abs(snapped - value) > 0.001) {
                                value = snapped
                                return
                            }
                            settingsPage.maxTokens = snapped
                        }
                    }
                }
            }

            // Card 2b: Performance Settings
            Rectangle {
                width: parent.width
                height: perfSettingsColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "performance"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: perfSettingsColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.5)

                    Label {
                        text: i18n.tr("Performance Settings")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    Label {
                        text: i18n.tr("CPU Threads") + ": " + settingsPage.threads
                        color: root.bodyTextColor
                        fontSize: "small"
                    }

                    Slider {
                        id: threadsSlider
                        width: parent.width
                        minimumValue: 1
                        maximumValue: 8
                        value: settingsPage.threads
                        live: true

                        onValueChanged: {
                            var snapped = Math.round(value)
                            if (snapped !== value) {
                                value = snapped
                                return
                            }
                            settingsPage.threads = snapped
                        }
                    }
                    
                    Label {
                        text: i18n.tr("Recommended: 4 threads on octa-core devices to avoid overheating and thermal throttling.")
                        color: root.tertiaryTextColor
                        fontSize: "x-small"
                        wrapMode: Text.Wrap
                        width: parent.width
                    }

                    Label {
                        text: i18n.tr("Context Size Limit")
                        color: root.bodyTextColor
                        fontSize: "small"
                    }

                    StyledComboBox {
                        id: ctxSelector
                        width: parent.width
                        model: ["512", "1024", "2048", "4096", "8192"]
                        currentIndex: {
                            var idx = model.indexOf(settingsPage.ctxSize.toString())
                            return idx >= 0 ? idx : 2 // Default to 2048
                        }
                        onActivated: {
                            settingsPage.ctxSize = parseInt(model[currentIndex])
                        }
                    }

                    Label {
                        text: i18n.tr("Flash Attention")
                        color: root.bodyTextColor
                        fontSize: "small"
                    }

                    StyledComboBox {
                        id: faSelector
                        width: parent.width
                        model: ["auto", "on", "off"]
                        currentIndex: model.indexOf(settingsPage.flashAttn) >= 0 ? model.indexOf(settingsPage.flashAttn) : 0
                        onActivated: {
                            settingsPage.flashAttn = model[currentIndex]
                        }
                    }

                    Label {
                        text: i18n.tr("KV Cache Quantization")
                        color: root.bodyTextColor
                        fontSize: "small"
                    }

                    StyledComboBox {
                        id: kvSelector
                        width: parent.width
                        model: ["f16", "q8_0", "q4_0"]
                        currentIndex: model.indexOf(settingsPage.kvCache) >= 0 ? model.indexOf(settingsPage.kvCache) : 0
                        onActivated: {
                            settingsPage.kvCache = model[currentIndex]
                        }
                    }

                    Label {
                        text: i18n.tr("Recommended: q8_0 or q4_0 to significantly reduce memory transfer and speed up token generation on mobile CPUs.")
                        color: root.tertiaryTextColor
                        fontSize: "x-small"
                        wrapMode: Text.Wrap
                        width: parent.width
                    }
                }
            }

            // Card: Theme Settings
            Rectangle {
                width: parent.width
                height: themeSettingsColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "theme"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: themeSettingsColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.5)

                    Label {
                        text: i18n.tr("Theme Mode")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    StyledComboBox {
                        id: themeSelector
                        width: parent.width
                        model: [i18n.tr("System"), i18n.tr("Light"), i18n.tr("Dark")]
                        currentIndex: {
                            if (settingsPage.themeMode === "light") return 1;
                            if (settingsPage.themeMode === "dark") return 2;
                            return 0; // "system"
                        }
                        onActivated: {
                            if (currentIndex === 1) {
                                settingsPage.themeMode = "light"
                            } else if (currentIndex === 2) {
                                settingsPage.themeMode = "dark"
                            } else {
                                settingsPage.themeMode = "system"
                            }
                        }
                    }
                }
            }

            // Card: Web Search Settings
            Rectangle {
                width: parent.width
                height: webSearchColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "websearch"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: webSearchColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.5)

                    Label {
                        text: i18n.tr("Web Search Integration")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    RowLayout {
                        width: parent.width
                        spacing: units.gu(1)

                        Label {
                            text: i18n.tr("Enable Web Search by default")
                            color: root.bodyTextColor
                            fontSize: "small"
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                        }

                        CheckBox {
                            checked: settingsPage.webSearchEnabled
                            onCheckedChanged: settingsPage.webSearchEnabled = checked
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }

                    Label {
                        text: i18n.tr("Allows models to access real-time information via privacy-focused DuckDuckGo Lite search. Search snippets will be automatically injected into your prompt.")
                        color: root.tertiaryTextColor
                        fontSize: "x-small"
                        wrapMode: Text.Wrap
                        width: parent.width
                    }
                }
            }

            // Card 3: Storage
            Rectangle {
                width: parent.width
                height: storageColumn.implicitHeight + units.gu(3)
                visible: settingsPage.currentSection === "storage"
                color: root.cardColor
                border.color: root.cardBorderColor
                border.width: 1
                radius: units.gu(1.5)

                Column {
                    id: storageColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1)

                    Label {
                        text: i18n.tr("Storage")
                        font.bold: true
                        color: root.primaryTextColor
                    }

                    Label {
                        text: settingsPage.freeStorage
                        color: root.bodyTextColor
                        fontSize: "small"
                    }
                }
            }


            Button {
                width: parent.width
                visible: settingsPage.currentSection === "storage"
                text: i18n.tr("Clear chat history")
                color: "#C7162B"
                onClicked: settingsPage.clearChat()
            }
        }
    }
}

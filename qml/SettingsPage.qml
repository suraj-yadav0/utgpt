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

Page {
    id: settingsPage
    signal toggleSidebar()

    header: PageHeader {
        id: settingsHeader
        title: i18n.tr("Settings")
        leadingActionBar.numberOfSlots: 1
        leadingActionBar.actions: [
            Action {
                iconName: "navigation-menu"
                text: i18n.tr("Menu")
                visible: settingsPage.width < units.gu(60)
                onTriggered: settingsPage.toggleSidebar()
            }
        ]
    }

    property var python
    property bool backendReady: false
    property string selectedModel: ""
    
    onSelectedModelChanged: {
        var info = getModelInfo(selectedModel)
        var limit = info ? info.maxContext : 2048
        if (maxTokens > limit) {
            maxTokens = limit
        }
    }

    property real temperature: 0.7
    property int maxTokens: 512
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
        }
    }

    onVisibleChanged: {
        if (visible && backendReady) {
            refreshModels()
            refreshStorage()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#f5f5f7"
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

            // Card 1: Active Model
            Rectangle {
                width: parent.width
                height: activeModelColumn.implicitHeight + units.gu(3)
                color: "#FFFFFF"
                border.color: "#E2E8F0"
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
                        color: "#1E293B"
                    }

                    Label {
                        text: i18n.tr("No models downloaded yet")
                        visible: settingsPage.availableModels.length === 0
                        color: "#64748B"
                        fontSize: "small"
                    }

                    QQC2.ComboBox {
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
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1
                radius: units.gu(1.5)
                visible: settingsPage.selectedModel !== ""

                Column {
                    id: modelSpecsColumn
                    anchors.fill: parent
                    anchors.margins: units.gu(1.5)
                    spacing: units.gu(1.2)

                    Label {
                        text: i18n.tr("Model Specifications")
                        font.bold: true
                        color: "#1E293B"
                    }

                    GridLayout {
                        columns: 2
                        width: parent.width
                        columnSpacing: units.gu(2)
                        rowSpacing: units.gu(0.8)
                        
                        property var info: settingsPage.getModelInfo(settingsPage.selectedModel)

                        Label {
                            text: i18n.tr("Model Name:")
                            color: "#64748B"
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.name : ""
                            color: "#1E293B"
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Developer:")
                            color: "#64748B"
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.developer : ""
                            color: "#1E293B"
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("File Size:")
                            color: "#64748B"
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.size : ""
                            color: "#1E293B"
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Context Window:")
                            color: "#64748B"
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.context : ""
                            color: "#1E293B"
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Quantization:")
                            color: "#64748B"
                            fontSize: "small"
                            font.bold: true
                        }
                        Label {
                            text: parent.info ? parent.info.quant : ""
                            color: "#1E293B"
                            fontSize: "small"
                        }

                        Label {
                            text: i18n.tr("Recommended For:")
                            color: "#64748B"
                            fontSize: "small"
                            font.bold: true
                            Layout.alignment: Qt.AlignTop
                        }
                        Label {
                            text: parent.info ? parent.info.usage : ""
                            color: "#1E293B"
                            fontSize: "small"
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            // Card 2: Generation Settings
            Rectangle {
                width: parent.width
                height: genSettingsColumn.implicitHeight + units.gu(3)
                color: "#FFFFFF"
                border.color: "#E2E8F0"
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
                        color: "#1E293B"
                    }

                    Label {
                        text: i18n.tr("Temperature") + ": " + settingsPage.temperature.toFixed(1)
                        color: "#475569"
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
                        color: "#475569"
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

            // Card 3: Storage
            Rectangle {
                width: parent.width
                height: storageColumn.implicitHeight + units.gu(3)
                color: "#FFFFFF"
                border.color: "#E2E8F0"
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
                        color: "#1E293B"
                    }

                    Label {
                        text: settingsPage.freeStorage
                        color: "#475569"
                        fontSize: "small"
                    }
                }
            }


            Button {
                width: parent.width
                text: i18n.tr("Clear chat history")
                color: "#C7162B"
                onClicked: settingsPage.clearChat()
            }
        }
    }
}

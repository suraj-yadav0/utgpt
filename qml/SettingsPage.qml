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
    title: i18n.tr("Settings")

    property var python
    property bool backendReady: false
    property string selectedModel: ""
    property real temperature: 0.7
    property int maxTokens: 200
    property string freeStorage: i18n.tr("Checking storage...")
    property var availableModels: []

    signal clearChat()

    function refreshModels() {
        python.call("backend.list_models", [], function(result) {
            availableModels = result || []
            if (availableModels.length === 0) {
                selectedModel = ""
                modelSelector.currentIndex = -1
                return
            }

            var selectedIndex = availableModels.indexOf(selectedModel)
            if (selectedIndex < 0) {
                selectedIndex = 0
            }

            modelSelector.currentIndex = selectedIndex
            selectedModel = availableModels[selectedIndex]
        })
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
        return Math.round(value / 10) * 10
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

    Flickable {
        anchors.fill: parent
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
            spacing: units.gu(3)

            Column {
                width: parent.width
                spacing: units.gu(1)

                Label {
                    text: i18n.tr("Active Model")
                    font.bold: true
                }

                Label {
                    text: i18n.tr("No models downloaded yet")
                    visible: settingsPage.availableModels.length === 0
                    color: "#5c5c5c"
                }

                QQC2.ComboBox {
                    id: modelSelector
                    width: parent.width
                    visible: settingsPage.availableModels.length > 0
                    model: settingsPage.availableModels

                    onActivated: {
                        if (currentIndex >= 0 && currentIndex < settingsPage.availableModels.length) {
                            settingsPage.selectedModel = settingsPage.availableModels[currentIndex]
                        }
                    }
                }
            }

            Column {
                width: parent.width
                spacing: units.gu(1.5)

                Label {
                    text: i18n.tr("Generation Settings")
                    font.bold: true
                }

                Label {
                    text: i18n.tr("Temperature") + ": " + settingsPage.temperature.toFixed(1)
                }

                Slider {
                    id: temperatureSlider
                    width: parent.width
                    minimumValue: 0.1
                    maximumValue: 1.0
                    value: 0.7
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
                }

                Slider {
                    id: maxTokensSlider
                    width: parent.width
                    minimumValue: 50
                    maximumValue: 400
                    value: 200
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

            Column {
                width: parent.width
                spacing: units.gu(1)

                Label {
                    text: i18n.tr("Storage")
                    font.bold: true
                }

                Label {
                    text: settingsPage.freeStorage
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

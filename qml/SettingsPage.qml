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
    property real temperature: 0.7
    property int maxTokens: 200
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
                        maximumValue: 400
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

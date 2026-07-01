/*
 * DownloadPage.qml
 *
 * Shows the built-in UTGPT model catalog, starts GGUF downloads through the
 * Python backend, and reflects progress/ready state for each model card.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3

Page {
    id: downloadPage
    signal toggleSidebar()

    header: PageHeader {
        id: downloadHeader
        title: i18n.tr("Download Models")
        leadingActionBar.numberOfSlots: 1
        leadingActionBar.actions: [
            Action {
                iconName: "navigation-menu"
                text: i18n.tr("Menu")
                visible: true
                onTriggered: downloadPage.toggleSidebar()
            }
        ]
        trailingActionBar.numberOfSlots: 3
        trailingActionBar.actions: [
            Action {
                iconName: "message"
                text: i18n.tr("Chat")
                onTriggered: root.currentTabIndex = 0
            },
            Action {
                iconName: "package-x-generic-symbolic"
                text: i18n.tr("Models")
                onTriggered: root.currentTabIndex = 1
            },
            Action {
                iconName: "settings"
                text: i18n.tr("Settings")
                onTriggered: root.currentTabIndex = 2
            }
        ]
    }

    property var python
    property bool backendReady: false

    function updateDownloadStates(states) {
        for (var row = 0; row < modelsList.count; row++) {
            var item = modelsList.get(row)
            var state = states[item.filename]
            
            if (state) {
                if (state.status === "ready") {
                    modelsList.setProperty(row, "ready", true)
                    modelsList.setProperty(row, "downloading", false)
                    modelsList.setProperty(row, "paused", false)
                    modelsList.setProperty(row, "progress", 1.0)
                } else if (state.status === "downloading") {
                    modelsList.setProperty(row, "ready", false)
                    modelsList.setProperty(row, "downloading", true)
                    modelsList.setProperty(row, "paused", false)
                    if (state.requestId) {
                        modelsList.setProperty(row, "requestId", state.requestId)
                    }
                } else if (state.status === "paused") {
                    modelsList.setProperty(row, "ready", false)
                    modelsList.setProperty(row, "downloading", false)
                    modelsList.setProperty(row, "paused", true)
                    if (state.requestId) {
                        modelsList.setProperty(row, "requestId", state.requestId)
                    }
                }
            } else {
                modelsList.setProperty(row, "ready", false)
                modelsList.setProperty(row, "downloading", false)
                modelsList.setProperty(row, "paused", false)
                modelsList.setProperty(row, "progress", 0.0)
            }
        }
    }

    function refreshDownloadedModels() {
        python.call("backend.get_download_states", [], function(result) {
            downloadPage.updateDownloadStates(result || {})
        })
    }

    function startDownload(index) {
        var item = modelsList.get(index)
        var requestId = "download-" + index + "-" + Date.now()

        modelsList.setProperty(index, "requestId", requestId)
        modelsList.setProperty(index, "downloading", true)
        modelsList.setProperty(index, "paused", false)
        modelsList.setProperty(index, "ready", false)
        modelsList.setProperty(index, "progress", 0.0)

        python.call("backend.download_model", [item.name, item.url, requestId])
    }

    function pauseDownload(index) {
        var item = modelsList.get(index)
        if (item.requestId) {
            python.call("backend.pause_download", [item.requestId], function(result) {
                if (result) {
                    modelsList.setProperty(index, "downloading", false)
                    modelsList.setProperty(index, "paused", true)
                }
            })
        }
    }

    function resumeDownload(index) {
        var item = modelsList.get(index)
        if (!item.requestId) {
            var requestId = "download-" + index + "-" + Date.now()
            modelsList.setProperty(index, "requestId", requestId)
        }
        modelsList.setProperty(index, "downloading", true)
        modelsList.setProperty(index, "paused", false)
        python.call("backend.download_model", [item.name, item.url, item.requestId])
    }

    function cancelDownload(index) {
        var item = modelsList.get(index)
        if (item.requestId) {
            python.call("backend.cancel_download", [item.requestId])
        }
        python.call("backend.clear_partial_download", [item.filename], function(result) {
            modelsList.setProperty(index, "downloading", false)
            modelsList.setProperty(index, "paused", false)
            modelsList.setProperty(index, "progress", 0.0)
            modelsList.setProperty(index, "requestId", "")
            downloadPage.refreshDownloadedModels()
            root.refreshModels()
        })
    }

    function deleteModel(index) {
        var item = modelsList.get(index)
        python.call("backend.delete_model", [item.filename], function(result) {
            downloadPage.refreshDownloadedModels()
            root.refreshModels()
        })
    }


    ListModel {
        id: modelsList
    }

    Connections {
        target: python

        function onReceived(result) {
            console.log("QML_LOG: DownloadPage received result type:", typeof result, "JSON:", JSON.stringify(result))
            
            // PyOtherSide received signal passes arguments wrapped in a JavaScript array
            var data = (result && result.length > 0) ? result[0] : null
            if (!data || !data.event || !data.payload) {
                return
            }

            for (var index = 0; index < modelsList.count; index++) {
                var item = modelsList.get(index)
                if (item.requestId !== data.payload.requestId) {
                    continue
                }

                if (data.event === "download_progress") {
                    modelsList.setProperty(index, "progress", data.payload.progress)
                    modelsList.setProperty(index, "downloading", true)
                    modelsList.setProperty(index, "paused", false)
                } else if (data.event === "download_paused") {
                    modelsList.setProperty(index, "progress", data.payload.progress)
                    modelsList.setProperty(index, "downloading", false)
                    modelsList.setProperty(index, "paused", true)
                } else if (data.event === "download_complete") {
                    modelsList.setProperty(index, "progress", 1.0)
                    modelsList.setProperty(index, "downloading", false)
                    modelsList.setProperty(index, "paused", false)
                    modelsList.setProperty(index, "ready", true)
                    root.refreshModels()
                } else if (data.event === "download_error") {
                    modelsList.setProperty(index, "downloading", false)
                    modelsList.setProperty(index, "paused", false)
                    modelsList.setProperty(index, "progress", 0.0)
                }
                break
            }
        }
    }

    function populateModelsFromCatalog() {
        if (!root.modelCatalog || root.modelCatalog.length === 0) return;
        modelsList.clear();
        
        var filterText = "";
        try {
            if (typeof searchInput !== "undefined" && searchInput) {
                filterText = searchInput.text.toLowerCase().trim();
            }
        } catch(e) {}

        for (var i = 0; i < root.modelCatalog.length; i++) {
            var item = root.modelCatalog[i];
            
            if (filterText.length > 0) {
                var nameMatch = (item.name && item.name.toLowerCase().indexOf(filterText) >= 0);
                var descMatch = (item.description && item.description.toLowerCase().indexOf(filterText) >= 0);
                var devMatch = (item.developer && item.developer.toLowerCase().indexOf(filterText) >= 0);
                var usageMatch = (item.usage && item.usage.toLowerCase().indexOf(filterText) >= 0);
                
                if (!nameMatch && !descMatch && !devMatch && !usageMatch) {
                    continue;
                }
            }

            modelsList.append({
                name: item.name,
                filename: item.filename,
                size: item.size,
                description: item.description,
                url: item.url,
                progress: 0.0,
                downloading: false,
                paused: false,
                ready: false,
                requestId: "",
                compatibility: item.compatibility || "yellow",
                compatibilityText: item.compatibilityText || i18n.tr("Runs Fine")
            });
        }
        refreshDownloadedModels();
    }

    onBackendReadyChanged: {
        if (backendReady) {
            populateModelsFromCatalog()
        }
    }
    
    onVisibleChanged: {
        if (visible && backendReady) {
            populateModelsFromCatalog()
        }
    }

    Connections {
        target: root
        function onModelCatalogChanged() {
            populateModelsFromCatalog()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#f5f5f7"
        z: -1
    }

    Flickable {
        anchors.top: downloadHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        contentWidth: width
        contentHeight: cardsColumn.height + units.gu(4)
        clip: true

        Column {
            id: cardsColumn
            width: parent.width - (units.gu(4))
            anchors {
                left: parent.left
                right: parent.right
                top: parent.top
                margins: units.gu(2)
            }
            spacing: units.gu(2)

            // Search Bar Card
            Rectangle {
                width: parent.width
                height: units.gu(6.5)
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1
                radius: units.gu(1.5)

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: units.gu(1.5)
                    anchors.rightMargin: units.gu(1.5)
                    spacing: units.gu(1.5)

                    Icon {
                        name: "search"
                        width: units.gu(2.2)
                        height: units.gu(2.2)
                        color: "#94A3B8"
                    }

                    TextField {
                        id: searchInput
                        Layout.fillWidth: true
                        placeholderText: i18n.tr("Search models...")
                        hasClearButton: true
                        
                        onTextChanged: {
                            downloadPage.populateModelsFromCatalog()
                        }
                    }
                }
            }

            Repeater {
                model: modelsList

                delegate: Rectangle {
                    width: cardsColumn.width
                    color: "#FFFFFF"
                    border.color: "#E2E8F0"
                    radius: units.gu(1.5)
                    implicitHeight: cardLayout.implicitHeight + units.gu(3)

                    ColumnLayout {
                        id: cardLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: units.gu(2)
                        anchors.rightMargin: units.gu(2)
                        anchors.topMargin: units.gu(1.5)
                        spacing: units.gu(1)

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: units.gu(1)

                            Label {
                                text: model.name
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Rectangle {
                                height: units.gu(2.4)
                                implicitWidth: compatRow.implicitWidth + units.gu(1.6)
                                radius: units.gu(0.4)
                                color: {
                                    if (model.compatibility === "green") return "#e8f5e9"
                                    if (model.compatibility === "yellow") return "#fffde7"
                                    return "#ffebee"
                                }
                                border.width: 1
                                border.color: {
                                    if (model.compatibility === "green") return "#81c784"
                                    if (model.compatibility === "yellow") return "#fff176"
                                    return "#e57373"
                                }

                                RowLayout {
                                    id: compatRow
                                    anchors.centerIn: parent
                                    spacing: units.gu(0.5)

                                    Icon {
                                        name: {
                                            if (model.compatibility === "green") return "ok"
                                            if (model.compatibility === "yellow") return "info"
                                            return "warning"
                                        }
                                        width: units.gu(1.4)
                                        height: units.gu(1.4)
                                        color: {
                                            if (model.compatibility === "green") return "#2e7d32"
                                            if (model.compatibility === "yellow") return "#f57f17"
                                            return "#c62828"
                                        }
                                    }

                                    Label {
                                        id: compatLabel
                                        text: model.compatibilityText
                                        fontSize: "small"
                                        color: {
                                            if (model.compatibility === "green") return "#2e7d32"
                                            if (model.compatibility === "yellow") return "#f57f17"
                                            return "#c62828"
                                        }
                                    }
                                }
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: model.name + "  - " + model.size + " - " + model.description
                            color: "#5c5c5c"
                        }

                        ProgressBar {
                            Layout.fillWidth: true
                            minimumValue: 0
                            maximumValue: 1
                            value: model.progress
                            visible: model.downloading || model.paused
                        }

                        Label {
                            text: {
                                if (model.paused) {
                                    return i18n.tr("Paused: ") + Math.round(model.progress * 100) + "%"
                                }
                                if (model.progress === 0.0) {
                                    return i18n.tr("Connecting...")
                                }
                                return i18n.tr("Downloading: ") + Math.round(model.progress * 100) + "%"
                            }
                            visible: model.downloading || model.paused
                            color: "#5c5c5c"
                            fontSize: "small"
                        }

                        RowLayout {
                            spacing: units.gu(1)
                            visible: model.ready

                            RowLayout {
                                spacing: units.gu(0.5)
                                Layout.alignment: Qt.AlignVCenter

                                Icon {
                                    name: "ok"
                                    width: units.gu(1.8)
                                    height: units.gu(1.8)
                                    color: "#2e7d32"
                                    Layout.alignment: Qt.AlignVCenter
                                }

                                Label {
                                    text: i18n.tr("Ready")
                                    color: "#2e7d32"
                                    Layout.alignment: Qt.AlignVCenter
                                }
                            }

                            Button {
                                text: i18n.tr("Delete")
                                color: "#C7162B"
                                onClicked: downloadPage.deleteModel(index)
                            }
                        }

                        RowLayout {
                            spacing: units.gu(1)
                            visible: model.downloading || model.paused

                            Button {
                                text: model.paused ? i18n.tr("Resume") : i18n.tr("Pause")
                                onClicked: {
                                    if (model.paused) {
                                        downloadPage.resumeDownload(index)
                                    } else {
                                        downloadPage.pauseDownload(index)
                                    }
                                }
                            }

                            Button {
                                text: i18n.tr("Cancel")
                                color: "#C7162B"
                                onClicked: downloadPage.cancelDownload(index)
                            }
                        }

                        Button {
                            text: i18n.tr("Download")
                            visible: !model.downloading && !model.ready && !model.paused
                            onClicked: downloadPage.startDownload(index)
                        }
                    }
                }
            }
        }
    }
}

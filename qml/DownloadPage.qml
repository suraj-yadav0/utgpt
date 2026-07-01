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
        NavigationRow {
            anchors.right: parent.right
            anchors.rightMargin: units.gu(1.5)
            anchors.verticalCenter: parent.verticalCenter
        }
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
        color: "#FFFFFF"
        z: -1
    }

    ColumnLayout {
        anchors.top: downloadHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: units.gu(1.5)
        spacing: units.gu(1.5)

        // Search Bar Card
        Rectangle {
            id: searchBarCard
            Layout.fillWidth: true
            Layout.leftMargin: units.gu(1.5)
            Layout.rightMargin: units.gu(1.5)
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

        ListView {
            id: modelsListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 0
            model: modelsList

            delegate: ListItem {
                id: modelListItem
                width: modelsListView.width
                height: cardLayout.implicitHeight + units.gu(4.0)
                highlightColor: "transparent"
                divider.visible: true

                leadingActions: model.ready ? deleteActions : null
                trailingActions: {
                    if (model.ready) return null;
                    if (model.downloading) return downloadingActions;
                    if (model.paused) return pausedActions;
                    return downloadActions;
                }

                ListItemActions {
                    id: deleteActions
                    actions: [
                        Action {
                            iconName: "delete"
                            text: i18n.tr("Delete")
                            onTriggered: downloadPage.deleteModel(index)
                        }
                    ]
                }

                ListItemActions {
                    id: downloadActions
                    actions: [
                        Action {
                            iconSource: "../assets/Download.svg"
                            text: i18n.tr("Download")
                            onTriggered: downloadPage.startDownload(index)
                        }
                    ]
                }

                ListItemActions {
                    id: downloadingActions
                    actions: [
                        Action {
                            iconName: "media-playback-pause"
                            text: i18n.tr("Pause")
                            onTriggered: downloadPage.pauseDownload(index)
                        },
                        Action {
                            iconName: "cancel"
                            text: i18n.tr("Cancel")
                            onTriggered: downloadPage.cancelDownload(index)
                        }
                    ]
                }

                ListItemActions {
                    id: pausedActions
                    actions: [
                        Action {
                            iconName: "media-playback-start"
                            text: i18n.tr("Resume")
                            onTriggered: downloadPage.resumeDownload(index)
                        },
                        Action {
                            iconName: "cancel"
                            text: i18n.tr("Cancel")
                            onTriggered: downloadPage.cancelDownload(index)
                        }
                    ]
                }

                RowLayout {
                    id: cardLayout
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: units.gu(1.5)
                    anchors.rightMargin: units.gu(1.5)
                    anchors.topMargin: units.gu(2.0)
                    spacing: units.gu(1.5)

                    // Text & Status Info Column
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: units.gu(0.5)

                        RowLayout {
                            spacing: units.gu(1)

                            // Compatibility Blinker / status circle
                            Rectangle {
                                width: units.gu(1.2)
                                height: units.gu(1.2)
                                radius: width / 2
                                color: {
                                    if (model.compatibility === "green") return "#2ECC71"
                                    if (model.compatibility === "yellow") return "#F1C40F"
                                    return "#E74C3C"
                                }
                                visible: true
                                Layout.alignment: Qt.AlignVCenter

                                SequentialAnimation on opacity {
                                    loops: Animation.Infinite
                                    PropertyAnimation { to: 0.3; duration: 2000; easing.type: Easing.InOutQuad }
                                    PropertyAnimation { to: 1.0; duration: 2000; easing.type: Easing.InOutQuad }
                                }
                            }

                            Label {
                                text: model.name
                                font.bold: true
                                color: "#1E293B"
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: model.size + " - " + model.description
                            color: "#64748B"
                            fontSize: "small"
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
                            color: "#475569"
                            fontSize: "small"
                        }
                    }

                    // Trailing Action/State Indicator Icon
                    Icon {
                        name: {
                            if (model.ready) return "ok"
                            if (model.downloading) return "media-playback-pause"
                            if (model.paused) return "media-playback-start"
                            return ""
                        }
                        source: {
                            if (model.ready || model.downloading || model.paused) return ""
                            return "../assets/Download.svg"
                        }
                        width: units.gu(2.2)
                        height: units.gu(2.2)
                        color: model.ready ? "#2ECC71" : (model.downloading ? "#E95420" : "#5C5C5C")
                        Layout.alignment: Qt.AlignVCenter

                        SequentialAnimation on opacity {
                            running: model.downloading
                            loops: Animation.Infinite
                            PropertyAnimation { to: 0.4; duration: 800; easing.type: Easing.InOutQuad }
                            PropertyAnimation { to: 1.0; duration: 800; easing.type: Easing.InOutQuad }
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                if (model.ready) {
                                    // Already ready
                                } else if (model.downloading) {
                                    downloadPage.pauseDownload(index)
                                } else if (model.paused) {
                                    downloadPage.resumeDownload(index)
                                } else {
                                    downloadPage.startDownload(index)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/*
 * DownloadPage.qml
 *
 * Shows the built-in UTGPT model catalog, starts GGUF downloads through the
 * Python backend, and reflects progress/ready state for each model card.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import "../components"

Page {
    id: downloadPage
    signal toggleSidebar()

    header: PageHeader {
        id: downloadHeader
        title: i18n.tr("Download Models")
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

    function importModel(fileUrl) {
        python.call("backend.import_local_model", [fileUrl])
    }


    ListModel {
        id: modelsList
    }

    Connections {
        target: python

        function onReceived(result) {
            if (root.debugMode) {
                console.log("QML_LOG: DownloadPage received result type:", typeof result, "JSON:", JSON.stringify(result))
            }
            
            // PyOtherSide received signal passes arguments wrapped in a JavaScript array
            var data = (result && result.length > 0) ? result[0] : null
            if (!data || !data.event || !data.payload) {
                return
            }

            if (data.event === "import_start") {
                importOverlay.visible = true
                importFilenameLabel.text = data.payload.filename
                importProgressBar.value = 0
                importProgressLabel.text = "0%"
                return
            } else if (data.event === "import_progress") {
                importOverlay.visible = true
                importProgressBar.value = data.payload.progress
                importProgressLabel.text = data.payload.progress + "%"
                return
            } else if (data.event === "import_complete") {
                importOverlay.visible = false
                if (pickerLoader.item && typeof pickerLoader.item.finalizeTransfer === "function") {
                    pickerLoader.item.finalizeTransfer()
                }
                root.refreshModels()
                root.showNotification(i18n.tr("Import Successful"), i18n.tr("Successfully imported ") + data.payload.filename + i18n.tr(". You can now select it as the Active Model in Settings."))
                return
            } else if (data.event === "import_error") {
                importOverlay.visible = false
                if (pickerLoader.item && typeof pickerLoader.item.finalizeTransfer === "function") {
                    pickerLoader.item.finalizeTransfer()
                }
                root.showError(i18n.tr("Failed to import model: ") + data.payload.error)
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
            if (root.isDesktop) {
                console.log("QML_LOG: Backend ready. Running on desktop, loading DesktopFilePicker...")
                pickerLoader.source = "../components/DesktopFilePicker.qml"
            } else {
                console.log("QML_LOG: Backend ready. Running on device, loading LomiriFilePicker...")
                pickerLoader.source = "../components/LomiriFilePicker.qml"
            }
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
        color: root.bgColor
        z: -1
    }

    ColumnLayout {
        anchors.top: downloadHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: units.gu(1.5)
        spacing: units.gu(1.5)

        // Import Local GGUF Card
        Rectangle {
            id: importLocalCard
            Layout.fillWidth: true
            Layout.leftMargin: units.gu(1.5)
            Layout.rightMargin: units.gu(1.5)
            Layout.preferredHeight: units.gu(12.5)
            color: root.isDark ? "#1A1A1A" : "#F8FAFC"
            border.color: root.cardBorderColor
            border.width: 1
            radius: units.gu(1.5)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: units.gu(2)
                anchors.rightMargin: units.gu(2)
                spacing: units.gu(1.5)

                Icon {
                    name: "document-open"
                    width: units.gu(2.8)
                    height: units.gu(2.8)
                    color: root.themeColor
                    Layout.alignment: Qt.AlignVCenter
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: units.gu(0.5)
                    Layout.alignment: Qt.AlignVCenter

                    Label {
                        text: i18n.tr("Import Local Model")
                        font.bold: true
                        color: root.primaryTextColor
                    }
                    Label {
                        text: i18n.tr("Load a .gguf file from your Downloads folder")
                        color: root.secondaryTextColor
                        fontSize: "small"
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        spacing: units.gu(0.5)
                        Layout.fillWidth: true
                        Icon {
                            name: "info"
                            width: units.gu(1.6)
                            height: units.gu(1.6)
                            color: "#D97706"
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Label {
                            text: i18n.tr("Use Instruct/Chat models. Avoid Base/autocompletion models.")
                            color: "#D97706"
                            fontSize: "x-small"
                            font.bold: true
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }
                }

                Button {
                    text: i18n.tr("Import GGUF")
                    color: root.themeColor
                    Layout.alignment: Qt.AlignVCenter
                    onClicked: {
                        if (pickerLoader.item) {
                            pickerLoader.item.open()
                        } else {
                            pickerLoader.source = "../components/LomiriFilePicker.qml"
                        }
                    }
                }
            }
        }

        // Search Bar Card
        Rectangle {
            id: searchBarCard
            Layout.fillWidth: true
            Layout.leftMargin: units.gu(1.5)
            Layout.rightMargin: units.gu(1.5)
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

                Icon {
                    name: "search"
                    width: units.gu(2.2)
                    height: units.gu(2.2)
                    color: root.tertiaryTextColor
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

        StyledListView {
            id: modelsListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: units.gu(1.5)
            Layout.rightMargin: units.gu(1.5)
            Layout.bottomMargin: units.gu(1.5)
            expandToContent: false
            model: modelsList

            delegate: ListItem {
                id: modelListItem
                width: parent.width
                implicitHeight: cardLayout.implicitHeight + units.gu(4.0)
                highlightColor: "transparent"
                divider.visible: index < modelsList.count - 1

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
                            iconSource: "../../assets/Download.svg"
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
                    x: units.gu(1.5)
                    y: units.gu(2.0)
                    width: parent.width - units.gu(3.0)
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
                                color: root.primaryTextColor
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: model.size + " - " + model.description
                            color: root.secondaryTextColor
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
                            color: root.bodyTextColor
                            fontSize: "small"
                        }
                    }

                    // Trailing Action/State Indicator Icon
                    Icon {
                        name: {
                            if (model.ready) return "ok"
                            if (model.downloading) return "media-playback-pause"
                            if (model.paused) return "media-playback-start"
                            return "next"
                        }
                        width: units.gu(2.2)
                        height: units.gu(2.2)
                        color: model.ready ? "#2ECC71" : (model.downloading ? root.themeTextColor : root.tertiaryTextColor)
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

    Loader {
        id: pickerLoader
        anchors.fill: parent
        onStatusChanged: {
            if (status === Loader.Error) {
                if (source.toString().indexOf("LomiriFilePicker.qml") >= 0) {
                    console.log("Failed to load Lomiri picker, trying Desktop picker...")
                    source = "../components/DesktopFilePicker.qml"
                } else {
                    console.log("Failed to load Desktop picker as well.")
                }
            }
        }
        
        onLoaded: {
            if (item) {
                item.fileSelected.connect(function(fileUrl) {
                    downloadPage.importModel(fileUrl)
                })
            }
        }
    }

    // Import Progress Overlay
    Rectangle {
        id: importOverlay
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.5)
        visible: false
        z: 1000

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.AllButtons
            onClicked: {}
        }

        Rectangle {
            anchors.centerIn: parent
            width: parent.width - units.gu(8)
            height: units.gu(18)
            color: root.cardColor
            radius: units.gu(1.5)
            border.color: root.cardBorderColor
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: units.gu(2)
                spacing: units.gu(1.5)

                Label {
                    text: i18n.tr("Importing Model...")
                    font.bold: true
                    fontSize: "large"
                    color: root.primaryTextColor
                    Layout.alignment: Qt.AlignHCenter
                }

                Label {
                    id: importFilenameLabel
                    text: ""
                    fontSize: "small"
                    color: root.secondaryTextColor
                    Layout.alignment: Qt.AlignHCenter
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                }

                ProgressBar {
                    id: importProgressBar
                    Layout.fillWidth: true
                    minimumValue: 0
                    maximumValue: 100
                    value: 0
                }

                Label {
                    id: importProgressLabel
                    text: "0%"
                    color: root.bodyTextColor
                    Layout.alignment: Qt.AlignHCenter
                }
            }
        }
    }


}

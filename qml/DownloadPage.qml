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
    title: i18n.tr("Download Models")

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
        })
    }

    function deleteModel(index) {
        var item = modelsList.get(index)
        python.call("backend.delete_model", [item.filename], function(result) {
            downloadPage.refreshDownloadedModels()
        })
    }


    ListModel {
        id: modelsList

        ListElement {
            name: "SmolLM2-1.7B"
            filename: "smollm2-1.7b-instruct-q4_k_m.gguf"
            size: "~1 GB"
            description: "Fast general chat"
            url: "https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF/resolve/main/smollm2-1.7b-instruct-q4_k_m.gguf"
            progress: 0.0
            downloading: false
            paused: false
            ready: false
            requestId: ""
        }
        ListElement {
            name: "Qwen2.5-1.5B"
            filename: "qwen2.5-1.5b-instruct-q4_k_m.gguf"
            size: "~1 GB"
            description: "Great multilingual"
            url: "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
            progress: 0.0
            downloading: false
            paused: false
            ready: false
            requestId: ""
        }
        ListElement {
            name: "TinyLlama-1.1B"
            filename: "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            size: "~700 MB"
            description: "Fastest, basic"
            url: "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            progress: 0.0
            downloading: false
            paused: false
            ready: false
            requestId: ""
        }
    }

    Connections {
        target: python

        function onReceived(data) {
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
                } else if (data.event === "download_error") {
                    modelsList.setProperty(index, "downloading", false)
                    modelsList.setProperty(index, "paused", false)
                    modelsList.setProperty(index, "progress", 0.0)
                }
                break
            }
        }
    }

    onBackendReadyChanged: if (backendReady) refreshDownloadedModels()
    onVisibleChanged: if (visible && backendReady) refreshDownloadedModels()

    Flickable {
        anchors.fill: parent
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

            Repeater {
                model: modelsList

                delegate: Rectangle {
                    width: cardsColumn.width
                    color: "#f7f7f7"
                    border.color: "#d7d7d7"
                    radius: units.gu(1)
                    implicitHeight: cardLayout.implicitHeight + units.gu(3)

                    ColumnLayout {
                        id: cardLayout
                        anchors.fill: parent
                        anchors.margins: units.gu(1.5)
                        spacing: units.gu(1)

                        Label {
                            text: model.name
                            font.bold: true
                            Layout.fillWidth: true
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

                            Label {
                                text: "\u2713 Ready"
                                color: "#2e7d32"
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

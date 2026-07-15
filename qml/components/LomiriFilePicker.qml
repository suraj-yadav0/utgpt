/*
 * LomiriFilePicker.qml
 *
 * Implements the native Ubuntu Touch/Lomiri file picking via Content Hub.
 * This file is loaded dynamically to avoid QML import errors on non-Lomiri desktops.
 */

import QtQuick 2.7
import Lomiri.Content 1.3

Item {
    id: pickerItem
    anchors.fill: parent
    signal fileSelected(string fileUrl)

    property var activeTransfer: null

    // Model to query available document sources
    ContentPeerModel {
        id: docSources
        contentType: ContentType.Documents
        handler: ContentHandler.Source
    }

    // Default fallback file manager peer
    ContentPeer {
        id: defaultFileManagerPeer
        appId: "com.ubuntu.filemanager"
        contentType: ContentType.Documents
        handler: ContentHandler.Source
    }

    ContentPeerPicker {
        id: peerPicker
        anchors.fill: parent
        contentType: ContentType.Documents
        handler: ContentHandler.Source
        visible: false

        onPeerSelected: {
            console.log("QML_LOG: LomiriFilePicker peer selected: " + peer.appId)
            activeTransfer = peer.request()
            peerPicker.visible = false
        }

        onCancelPressed: {
            console.log("QML_LOG: LomiriFilePicker peer picker cancelled by user.")
            peerPicker.visible = false
        }
    }

    // Shows system transfer overlay when transfer is active
    ContentTransferHint {
        anchors.fill: parent
        activeTransfer: pickerItem.activeTransfer
    }

    Connections {
        target: activeTransfer
        onStateChanged: {
            if (activeTransfer) {
                console.log("QML_LOG: LomiriFilePicker transfer state changed: " + activeTransfer.state)
                if (activeTransfer.state === ContentTransfer.Charged) {
                    var items = activeTransfer.items
                    if (items && items.length > 0) {
                        var itemUrl = items[0].url.toString()
                        console.log("QML_LOG: LomiriFilePicker received file url: " + itemUrl)
                        pickerItem.fileSelected(itemUrl)
                    }
                } else if (activeTransfer.state === ContentTransfer.Aborted) {
                    console.log("QML_LOG: LomiriFilePicker transfer aborted/cancelled.")
                    activeTransfer = null
                }
            }
        }
    }

    function finalizeTransfer() {
        if (activeTransfer) {
            console.log("QML_LOG: Finalizing Lomiri Content Hub transfer")
            if (activeTransfer.state === ContentTransfer.Charged) {
                activeTransfer.state = ContentTransfer.Collected
                activeTransfer.finalize()
            }
            activeTransfer = null
        }
    }

    function open() {
        var foundPeer = null
        if (docSources && docSources.peers) {
            for (var i = 0; i < docSources.peers.length; i++) {
                var p = docSources.peers[i]
                var appId = p.appId || ""
                var name = p.name || ""
                console.log("QML_LOG: LomiriFilePicker found peer: appId=" + appId + ", name=" + name)
                if (appId.indexOf("filemanager") !== -1 || 
                    appId.indexOf("file-manager") !== -1 || 
                    name.toLowerCase().indexOf("file manager") !== -1 ||
                    name.toLowerCase().indexOf("files") !== -1) {
                    foundPeer = p
                    break
                }
            }
        }

        if (foundPeer) {
            console.log("QML_LOG: LomiriFilePicker launching file manager directly: " + foundPeer.appId)
            activeTransfer = foundPeer.request()
        } else {
            // Fallback: if we didn't find any file manager, but peers list is populated,
            // show the peer picker. Otherwise try default file manager peer directly.
            if (docSources && docSources.peers && docSources.peers.length > 0) {
                console.log("QML_LOG: LomiriFilePicker no file manager found in loaded list. Showing peer picker.")
                peerPicker.visible = true
            } else {
                console.log("QML_LOG: LomiriFilePicker peers list empty/loading. Launching default file manager directly.")
                activeTransfer = defaultFileManagerPeer.request()
            }
        }
    }
}

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
    // Same single-fire guard as the picture picker: ignore repeat
    // Charged notifications for one transfer so a doc is never attached twice.
    property bool _handled: false

    function _startTransfer(t) {
        _handled = false
        activeTransfer = t
    }

    function _emitChargedItems() {
        if (!activeTransfer || _handled) return
        if (activeTransfer.state !== ContentTransfer.Charged) return
        var items = activeTransfer.items
        if (!items || items.length === 0) return
        _handled = true
        var seen = {}
        for (var i = 0; i < items.length; i++) {
            try {
                var itemUrl = items[i].url.toString()
                if (!itemUrl || seen[itemUrl]) continue
                seen[itemUrl] = true
                console.log("QML_LOG: LomiriFilePicker received file url: " + itemUrl)
                pickerItem.fileSelected(itemUrl)
            } catch (e) {
                console.log("QML_LOG: LomiriFilePicker skipping bad item: " + e)
            }
        }
    }

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
            _startTransfer(peer.request())
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
                    _emitChargedItems()
                } else if (activeTransfer.state === ContentTransfer.Aborted) {
                    console.log("QML_LOG: LomiriFilePicker transfer aborted/cancelled.")
                    _handled = false
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
            _handled = false
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
            _startTransfer(foundPeer.request())
        } else {
            // Fallback: if we didn't find any file manager, but peers list is populated,
            // show the peer picker. Otherwise try default file manager peer directly.
            if (docSources && docSources.peers && docSources.peers.length > 0) {
                console.log("QML_LOG: LomiriFilePicker no file manager found in loaded list. Showing peer picker.")
                peerPicker.visible = true
            } else {
                console.log("QML_LOG: LomiriFilePicker peers list empty/loading. Launching default file manager directly.")
                _startTransfer(defaultFileManagerPeer.request())
            }
        }
    }
}

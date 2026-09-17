/*
 * LomiriPicturePicker.qml
 *
 * Implements native Ubuntu Touch/Lomiri picture picking and camera capture via Content Hub.
 * This file is loaded dynamically to avoid QML import errors on non-Lomiri desktops.
 */

import QtQuick 2.7
import Lomiri.Content 1.3

Item {
    id: pickerItem
    anchors.fill: parent
    signal fileSelected(string fileUrl)

    property var activeTransfer: null
    // Single-fire guard: the transfer stays Charged until QML finalizes it,
    // and stateChanged can re-fire in that window. Without this the same
    // image is emitted twice, attaching the previous pick again.
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
                console.log("QML_LOG: LomiriPicturePicker received image url: " + itemUrl)
                pickerItem.fileSelected(itemUrl)
            } catch (e) {
                console.log("QML_LOG: LomiriPicturePicker skipping bad item: " + e)
            }
        }
    }

    // Model to query available picture sources (Gallery, Camera, etc.)
    ContentPeerModel {
        id: pictureSources
        contentType: ContentType.Pictures
        handler: ContentHandler.Source
    }

    // Default fallback peers for gallery and camera
    ContentPeer {
        id: defaultGalleryPeer
        appId: "com.ubuntu.gallery"
        contentType: ContentType.Pictures
        handler: ContentHandler.Source
    }

    ContentPeer {
        id: defaultCameraPeer
        appId: "com.ubuntu.camera"
        contentType: ContentType.Pictures
        handler: ContentHandler.Source
    }

    ContentPeerPicker {
        id: peerPicker
        anchors.fill: parent
        contentType: ContentType.Pictures
        handler: ContentHandler.Source
        visible: false

        onPeerSelected: {
            console.log("QML_LOG: LomiriPicturePicker peer selected: " + peer.appId)
            _startTransfer(peer.request())
            peerPicker.visible = false
        }

        onCancelPressed: {
            console.log("QML_LOG: LomiriPicturePicker cancelled by user.")
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
                console.log("QML_LOG: LomiriPicturePicker transfer state changed: " + activeTransfer.state)
                if (activeTransfer.state === ContentTransfer.Charged) {
                    _emitChargedItems()
                } else if (activeTransfer.state === ContentTransfer.Aborted) {
                    console.log("QML_LOG: LomiriPicturePicker transfer aborted/cancelled.")
                    _handled = false
                    activeTransfer = null
                }
            }
        }
    }

    function finalizeTransfer() {
        if (activeTransfer) {
            console.log("QML_LOG: Finalizing Lomiri Content Hub picture transfer")
            if (activeTransfer.state === ContentTransfer.Charged) {
                activeTransfer.state = ContentTransfer.Collected
                activeTransfer.finalize()
            }
            _handled = false
            activeTransfer = null
        }
    }

    function openCamera() {
        var foundPeer = null
        if (pictureSources && pictureSources.peers) {
            for (var i = 0; i < pictureSources.peers.length; i++) {
                var p = pictureSources.peers[i]
                var appId = (p.appId || "").toLowerCase()
                var name = (p.name || "").toLowerCase()
                if (appId.indexOf("camera") !== -1 || name.indexOf("camera") !== -1) {
                    foundPeer = p
                    break
                }
            }
        }
        if (foundPeer) {
            console.log("QML_LOG: LomiriPicturePicker launching camera directly: " + foundPeer.appId)
            _startTransfer(foundPeer.request())
        } else {
            console.log("QML_LOG: LomiriPicturePicker launching default camera peer directly.")
            _startTransfer(defaultCameraPeer.request())
        }
    }

    function openGallery() {
        var foundPeer = null
        if (pictureSources && pictureSources.peers) {
            for (var i = 0; i < pictureSources.peers.length; i++) {
                var p = pictureSources.peers[i]
                var appId = (p.appId || "").toLowerCase()
                var name = (p.name || "").toLowerCase()
                if (appId.indexOf("gallery") !== -1 || name.indexOf("gallery") !== -1 || name.indexOf("photos") !== -1) {
                    foundPeer = p
                    break
                }
            }
        }
        if (foundPeer) {
            console.log("QML_LOG: LomiriPicturePicker launching gallery directly: " + foundPeer.appId)
            _startTransfer(foundPeer.request())
        } else {
            console.log("QML_LOG: LomiriPicturePicker launching default gallery peer directly.")
            _startTransfer(defaultGalleryPeer.request())
        }
    }

    function open() {
        if (pictureSources && pictureSources.peers && pictureSources.peers.length > 0) {
            peerPicker.visible = true
        } else {
            openGallery()
        }
    }
}

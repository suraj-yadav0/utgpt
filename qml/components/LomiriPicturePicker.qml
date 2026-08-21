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
            activeTransfer = peer.request()
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
                    var items = activeTransfer.items
                    if (items && items.length > 0) {
                        var itemUrl = items[0].url.toString()
                        console.log("QML_LOG: LomiriPicturePicker received image url: " + itemUrl)
                        pickerItem.fileSelected(itemUrl)
                    }
                } else if (activeTransfer.state === ContentTransfer.Aborted) {
                    console.log("QML_LOG: LomiriPicturePicker transfer aborted/cancelled.")
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
            activeTransfer = foundPeer.request()
        } else {
            console.log("QML_LOG: LomiriPicturePicker launching default camera peer directly.")
            activeTransfer = defaultCameraPeer.request()
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
            activeTransfer = foundPeer.request()
        } else {
            console.log("QML_LOG: LomiriPicturePicker launching default gallery peer directly.")
            activeTransfer = defaultGalleryPeer.request()
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

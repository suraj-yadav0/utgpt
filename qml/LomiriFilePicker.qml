/*
 * LomiriFilePicker.qml
 *
 * Implements the native Ubuntu Touch/Lomiri file picking via Content Hub.
 * This file is loaded dynamically to avoid QML import errors on non-Lomiri desktops.
 */

import QtQuick 2.7
import Lomiri.Content 1.1

Item {
    id: pickerItem
    signal fileSelected(string fileUrl)

    property var activeTransfer: null

    ContentPeerPicker {
        id: peerPicker
        contentType: ContentType.All
        handler: ContentHandler.Source
        visible: false

        onPeerSelected: {
            activeTransfer = peer.request()
            peerPicker.visible = false
        }
    }

    Connections {
        target: activeTransfer
        onStateChanged: {
            if (activeTransfer && activeTransfer.state === ContentTransfer.Charged) {
                var items = activeTransfer.items
                if (items && items.length > 0) {
                    var itemUrl = items[0].url.toString()
                    pickerItem.fileSelected(itemUrl)
                }
            }
        }
    }

    function open() {
        peerPicker.visible = true
    }
}

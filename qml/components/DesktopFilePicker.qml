/*
 * DesktopFilePicker.qml
 *
 * Implements the standard desktop file dialog for development/testing environments.
 */

import QtQuick 2.7
import QtQuick.Dialogs 1.2

Item {
    id: pickerItem
    signal fileSelected(string fileUrl)

    property string title: "Select File"
    property var nameFilters: [ "All files (*)" ]

    FileDialog {
        id: fileDialog
        title: pickerItem.title
        folder: shortcuts.home
        nameFilters: pickerItem.nameFilters
        onAccepted: {
            pickerItem.fileSelected(fileDialog.fileUrl.toString())
        }
    }

    function open() {
        fileDialog.open()
    }

    function openCamera() {
        fileDialog.open()
    }

    function openGallery() {
        fileDialog.open()
    }
}

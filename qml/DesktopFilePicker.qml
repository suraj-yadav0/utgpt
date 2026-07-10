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

    FileDialog {
        id: fileDialog
        title: "Select GGUF Model File"
        folder: shortcuts.download
        nameFilters: [ "GGUF files (*.gguf)" ]
        onAccepted: {
            pickerItem.fileSelected(fileDialog.fileUrl.toString())
        }
    }

    function open() {
        fileDialog.open()
    }
}

/*
 * AttachmentChoiceDialog.qml
 *
 * Modal dialog for choosing between Camera OCR, Gallery Image OCR, and Document RAG.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

Dialog {
    id: dialog
    title: i18n.tr("Add Attachment")

    signal cameraRequested()
    signal galleryRequested()
    signal docPickerRequested()

    ColumnLayout {
        width: parent ? parent.width : units.gu(38)
        spacing: units.gu(1.2)

        // Option 1: Take Photo with Camera
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(6.8)
            radius: units.gu(1)
            color: root.isDark ? "#262626" : "#F8FAFC"
            border.color: root.themeColor
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.margins: units.gu(1)
                spacing: units.gu(1.2)

                Rectangle {
                    width: units.gu(4.2)
                    height: units.gu(4.2)
                    radius: units.gu(0.8)
                    color: root.themeBgLight

                    Icon {
                        anchors.centerIn: parent
                        name: "camera-app"
                        width: units.gu(2.4)
                        height: units.gu(2.4)
                        color: root.themeTextColor
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: units.gu(0.2)

                    Label {
                        text: i18n.tr("Take Photo (Camera)")
                        font.bold: true
                        color: root.primaryTextColor
                        fontSize: "small"
                    }

                    Label {
                        text: i18n.tr("Capture a new photo and extract text via OCR")
                        color: root.secondaryTextColor
                        fontSize: "x-small"
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    PopupUtils.close(dialog)
                    dialog.cameraRequested()
                }
            }
        }

        // Option 2: Pick from Gallery
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(6.8)
            radius: units.gu(1)
            color: root.isDark ? "#262626" : "#F8FAFC"
            border.color: root.themeColor
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.margins: units.gu(1)
                spacing: units.gu(1.2)

                Rectangle {
                    width: units.gu(4.2)
                    height: units.gu(4.2)
                    radius: units.gu(0.8)
                    color: root.themeBgLight

                    Icon {
                        anchors.centerIn: parent
                        name: "image"
                        width: units.gu(2.4)
                        height: units.gu(2.4)
                        color: root.themeTextColor
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: units.gu(0.2)

                    Label {
                        text: i18n.tr("Pick from Gallery")
                        font.bold: true
                        color: root.primaryTextColor
                        fontSize: "small"
                    }

                    Label {
                        text: i18n.tr("Choose an image to translate or extract text")
                        color: root.secondaryTextColor
                        fontSize: "x-small"
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    PopupUtils.close(dialog)
                    dialog.galleryRequested()
                }
            }
        }

        // Option 3: Document RAG
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(6.8)
            radius: units.gu(1)
            color: root.isDark ? "#262626" : "#F8FAFC"
            border.color: root.cardBorderColor
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.margins: units.gu(1)
                spacing: units.gu(1.2)

                Rectangle {
                    width: units.gu(4.2)
                    height: units.gu(4.2)
                    radius: units.gu(0.8)
                    color: root.isDark ? "#333333" : "#E2E8F0"

                    Icon {
                        anchors.centerIn: parent
                        name: "document"
                        width: units.gu(2.4)
                        height: units.gu(2.4)
                        color: root.primaryTextColor
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: units.gu(0.2)

                    Label {
                        text: i18n.tr("Attach Document")
                        font.bold: true
                        color: root.primaryTextColor
                        fontSize: "small"
                    }

                    Label {
                        text: i18n.tr("Index PDF, TXT, MD, CSV, or code files for RAG search")
                        color: root.secondaryTextColor
                        fontSize: "x-small"
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    PopupUtils.close(dialog)
                    dialog.docPickerRequested()
                }
            }
        }

        Button {
            Layout.fillWidth: true
            text: i18n.tr("Cancel")
            onClicked: PopupUtils.close(dialog)
        }
    }
}

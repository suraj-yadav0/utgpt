/*
 * AttachmentChoiceDialog.qml
 *
 * Modal dialog for choosing between Camera OCR, Gallery Image OCR, and Document RAG.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import "../js/ChatUtils.js" as ChatUtils

Dialog {
    id: dialog
    title: i18n.tr("Add Attachment")

    signal cameraRequested()
    signal galleryRequested()
    signal docPickerRequested()

    // Experimental gates, bound by ChatPage. Hidden options are not offered.
    property bool imagesEnabled: true
    property bool docsEnabled: true

    function choose(action) {
        PopupUtils.close(dialog)
        if (action === "camera") {
            dialog.cameraRequested()
        } else if (action === "gallery") {
            dialog.galleryRequested()
        } else {
            dialog.docPickerRequested()
        }
    }

    function buildModel() {
        var defs = {
            "camera": {
                icon: "camera-app",
                title: i18n.tr("Take Photo"),
                sub: i18n.tr("Capture a new photo and extract text via OCR")
            },
            "gallery": {
                icon: "stock_image",
                title: i18n.tr("Pick from Gallery"),
                sub: i18n.tr("Choose an image to translate or extract text")
            },
            "document": {
                icon: "document-open",
                title: i18n.tr("Attach Document"),
                sub: i18n.tr("Index PDF, TXT, MD, CSV, or code files for search")
            }
        };
        var actions = ChatUtils.attachmentActions(imagesEnabled, docsEnabled);
        var out = [];
        for (var i = 0; i < actions.length; i++) {
            var d = defs[actions[i]];
            out.push({ icon: d.icon, title: d.title, sub: d.sub, action: actions[i] });
        }
        return out;
    }

    ColumnLayout {
        width: parent ? parent.width : units.gu(38)
        spacing: units.gu(1)

        Repeater {
            model: buildModel()

            delegate: Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(units.gu(7.2), optionRow.implicitHeight + units.gu(2.2))
                radius: units.gu(1.2)
                color: rowMouse.pressed ? root.themeBgLight : root.cardColor
                border.color: rowMouse.pressed || rowMouse.containsMouse ? root.themeTextColor : root.cardBorderColor
                border.width: 1

                Behavior on color { ColorAnimation { duration: 120 } }

                RowLayout {
                    id: optionRow
                    anchors.fill: parent
                    anchors.margins: units.gu(1.2)
                    spacing: units.gu(1.2)

                    Rectangle {
                        width: units.gu(4.4)
                        height: units.gu(4.4)
                        radius: units.gu(1)
                        color: root.themeBgLight
                        Layout.alignment: Qt.AlignVCenter

                        Icon {
                            anchors.centerIn: parent
                            name: modelData.icon
                            width: units.gu(2.4)
                            height: units.gu(2.4)
                            color: root.themeTextColor
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        spacing: units.gu(0.3)

                        Label {
                            text: modelData.title
                            font.bold: true
                            color: root.primaryTextColor
                            fontSize: "small"
                            Layout.fillWidth: true
                        }

                        Label {
                            text: modelData.sub
                            color: root.secondaryTextColor
                            fontSize: "x-small"
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }

                    Icon {
                        name: "next"
                        width: units.gu(1.8)
                        height: units.gu(1.8)
                        color: root.tertiaryTextColor
                        Layout.alignment: Qt.AlignVCenter
                    }
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: dialog.choose(modelData.action)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: units.gu(4.5)
            radius: units.gu(1.2)
            color: cancelMouse.pressed ? root.themeBgLight : "transparent"

            Label {
                anchors.centerIn: parent
                text: i18n.tr("Cancel")
                color: root.secondaryTextColor
                fontSize: "small"
            }

            MouseArea {
                id: cancelMouse
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: PopupUtils.close(dialog)
            }
        }
    }
}

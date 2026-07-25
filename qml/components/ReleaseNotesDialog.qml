/*
 * ReleaseNotesDialog.qml
 *
 * Popup dialog displaying the Release Notes and "What's New" features
 * for newly installed or updated application releases.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

Dialog {
    id: dialog
    property var releaseNotesData: null

    title: (releaseNotesData && releaseNotesData.title) ? releaseNotesData.title : i18n.tr("What's New")

    ColumnLayout {
        width: parent ? parent.width : units.gu(40)
        spacing: units.gu(1.5)

        // Subtitle / Version tag header badge
        RowLayout {
            Layout.fillWidth: true
            spacing: units.gu(1)
            visible: !!(dialog.releaseNotesData && dialog.releaseNotesData.version)

            Rectangle {
                color: root.themeColor
                radius: units.gu(0.5)
                implicitWidth: versionLabel.implicitWidth + units.gu(1.5)
                implicitHeight: versionLabel.implicitHeight + units.gu(0.6)

                Label {
                    id: versionLabel
                    anchors.centerIn: parent
                    text: dialog.releaseNotesData ? ("v" + dialog.releaseNotesData.version) : ""
                    color: "#FFFFFF"
                    font.bold: true
                    fontSize: "small"
                }
            }

            Label {
                text: (dialog.releaseNotesData && dialog.releaseNotesData.subtitle) ? dialog.releaseNotesData.subtitle : i18n.tr("Release Highlights")
                color: root.secondaryTextColor
                fontSize: "small"
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }

        // Feature items list
        Flickable {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(featuresColumn.implicitHeight, units.gu(32))
            contentHeight: featuresColumn.implicitHeight
            clip: true

            ColumnLayout {
                id: featuresColumn
                width: parent.width
                spacing: units.gu(1.5)

                Repeater {
                    model: (dialog.releaseNotesData && dialog.releaseNotesData.features) ? dialog.releaseNotesData.features : []

                    delegate: Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: itemRow.implicitHeight + units.gu(2)
                        color: root.isDark ? "#222222" : "#F8F9FA"
                        border.color: root.cardBorderColor
                        border.width: 1
                        radius: units.gu(1)

                        RowLayout {
                            id: itemRow
                            anchors.fill: parent
                            anchors.margins: units.gu(1)
                            spacing: units.gu(1.5)

                            Rectangle {
                                Layout.alignment: Qt.AlignTop
                                width: units.gu(3.5)
                                height: units.gu(3.5)
                                radius: units.gu(1.75)
                                color: Qt.rgba(root.themeColor.r, root.themeColor.g, root.themeColor.b, 0.15)

                                Icon {
                                    anchors.centerIn: parent
                                    width: units.gu(2)
                                    height: units.gu(2)
                                    name: modelData.icon || "info"
                                    color: root.themeTextColor
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: units.gu(0.3)

                                Label {
                                    text: modelData.title || ""
                                    font.bold: true
                                    color: root.primaryTextColor
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }

                                Label {
                                    text: modelData.description || ""
                                    color: root.bodyTextColor
                                    fontSize: "small"
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }
            }
        }

        // Close action button
        Button {
            text: i18n.tr("Got It!")
            color: root.themeColor
            Layout.fillWidth: true
            onClicked: PopupUtils.close(dialog)
        }
    }
}

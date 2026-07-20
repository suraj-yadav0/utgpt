/*
 * StyledComboBox.qml
 *
 * A custom-styled ComboBox that conforms to the app's light/dark mode palette.
 * Bypasses platform-specific ComboBox popup orientation/rotation bugs on desktop.
 */

import QtQuick 2.7
import Lomiri.Components 1.3
import QtQuick.Controls 2.2 as QQC2

QQC2.ComboBox {
    id: control

    activeFocusOnTab: true

    contentItem: QQC2.Label {
        leftPadding: units.gu(1.5)
        rightPadding: control.indicator ? control.indicator.width + control.spacing : units.gu(1.5)
        text: control.displayText
        color: root.primaryTextColor
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        implicitHeight: units.gu(4.5)
        color: root.cardColor
        border.color: control.activeFocus ? root.themeTextColor : root.cardBorderColor
        border.width: 1
        radius: units.gu(0.8)
    }

    indicator: Icon {
        x: control.width - width - units.gu(1.5)
        y: (control.height - height) / 2
        name: "down"
        width: units.gu(2.2)
        height: units.gu(2.2)
        color: root.secondaryTextColor
    }

    delegate: QQC2.ItemDelegate {
        width: control.width
        contentItem: QQC2.Label {
            text: control.textRole ? (modelData[control.textRole] || modelData) : modelData
            color: control.highlightedIndex === index ? (root.isDark ? "#FF8093" : root.themeColor) : root.primaryTextColor
            font.bold: control.currentIndex === index
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: control.highlightedIndex === index ? root.themeBgLight : "transparent"
        }
    }

    popup: QQC2.Popup {
        y: control.height + units.gu(0.5)
        width: control.width
        implicitHeight: Math.min(units.gu(25), contentItem.implicitHeight)
        padding: units.gu(0.5)

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex

            QQC2.ScrollIndicator.vertical: QQC2.ScrollIndicator { }
        }

        background: Rectangle {
            color: root.cardColor
            border.color: root.cardBorderColor
            border.width: 1
            radius: units.gu(1)
        }
    }
}

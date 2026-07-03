/*
 * NavigationRow.qml
 *
 * A reusable page header navigation action row with premium active highlights
 * and hover states.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3

Row {
    id: navRow
    spacing: units.gu(1)

    // Chat Action
    Rectangle {
        width: units.gu(4)
        height: units.gu(4)
        radius: units.gu(0.8)
        color: {
            if (root.currentTabIndex === 0) return root.themeBgLight
            if (chatMouse.containsMouse) return "#F1F5F9"
            return "transparent"
        }

        Icon {
            anchors.centerIn: parent
            name: "message"
            width: units.gu(2.4)
            height: units.gu(2.4)
            color: root.currentTabIndex === 0 ? root.themeColor : "#5C5C5C"
        }

        MouseArea {
            id: chatMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.currentTabIndex = 0
        }
    }

    // Models Action
    Rectangle {
        width: units.gu(4)
        height: units.gu(4)
        radius: units.gu(0.8)
        color: {
            if (root.currentTabIndex === 1) return root.themeBgLight
            if (modelsMouse.containsMouse) return "#F1F5F9"
            return "transparent"
        }

        Icon {
            anchors.centerIn: parent
            name: "package-x-generic-symbolic"
            width: units.gu(2.4)
            height: units.gu(2.4)
            color: root.currentTabIndex === 1 ? root.themeColor : "#5C5C5C"
        }

        MouseArea {
            id: modelsMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.currentTabIndex = 1
        }
    }

    // Settings Action
    Rectangle {
        width: units.gu(4)
        height: units.gu(4)
        radius: units.gu(0.8)
        color: {
            if (root.currentTabIndex === 2) return root.themeBgLight
            if (settingsMouse.containsMouse) return "#F1F5F9"
            return "transparent"
        }

        Icon {
            anchors.centerIn: parent
            name: "settings"
            width: units.gu(2.4)
            height: units.gu(2.4)
            color: root.currentTabIndex === 2 ? root.themeColor : "#5C5C5C"
        }

        MouseArea {
            id: settingsMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.currentTabIndex = 2
        }
    }
}

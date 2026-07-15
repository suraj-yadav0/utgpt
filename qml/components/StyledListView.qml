/*
 * StyledListView.qml
 *
 * Reusable list view component styled with rounded corners, borders, and clipping.
 * Can either expand to content height (useful inside parent Flickables) or scroll internally.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3

Rectangle {
    id: control
    color: root.cardColor
    border.color: root.cardBorderColor
    border.width: 1
    radius: units.gu(1.5)
    clip: true

    property alias model: listView.model
    property alias delegate: listView.delegate
    property alias currentIndex: listView.currentIndex
    property alias interactive: listView.interactive
    
    property bool expandToContent: false
    height: expandToContent ? listView.contentHeight : undefined

    ListView {
        id: listView
        anchors.fill: parent
        spacing: 0
        clip: true
        interactive: !control.expandToContent
    }
}

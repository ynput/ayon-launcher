import QtQuick 2.15
import "."

Item {
    id: spinner
    implicitWidth: 18
    implicitHeight: 18
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "transparent"
        border.width: 2
        border.color: Theme.outlineVariant
    }
    Item {
        anchors.fill: parent
        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: Theme.primary
            anchors.horizontalCenter: parent.horizontalCenter
            y: -1
        }
        RotationAnimator on rotation {
            from: 0
            to: 360
            duration: 900
            loops: Animation.Infinite
            running: spinner.visible
        }
    }
}

import QtQuick 2.15

Item {
    id: spinner
    implicitWidth: 22
    implicitHeight: 22
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "transparent"
        border.width: 2
        border.color: "#354c4b"
    }
    Item {
        anchors.fill: parent
        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: "#a0e5d5"
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

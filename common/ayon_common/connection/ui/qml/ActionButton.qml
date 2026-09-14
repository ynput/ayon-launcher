import QtQuick 2.15
import QtQuick.Templates 2.15 as T

T.Button {
    id: control
    property bool primary: false
    implicitWidth: Math.max(120, contentItem.implicitWidth + 40)
    implicitHeight: 48
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text

    contentItem: Text {
        text: control.text
        font.pixelSize: 14
        font.weight: Font.DemiBold
        color: !control.enabled ? "#727b86"
             : control.primary ? "#122020" : "#ecf0f3"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 8
        color: !control.enabled ? "#252b31"
             : control.primary ? (control.down ? "#7bc6bc" : control.hovered ? "#baf2e5" : "#a0e5d5")
             : control.down ? "#303840" : control.hovered ? "#282f37" : "#20262d"
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#a0e5d5"
                    : control.primary && control.enabled ? "transparent" : "#37404a"
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}

import QtQuick 2.15
import QtQuick.Templates 2.15 as T

T.TextField {
    id: control
    implicitWidth: 320
    implicitHeight: 48
    leftPadding: 14
    rightPadding: 14
    topPadding: 12
    bottomPadding: 12
    color: enabled ? "#edf2f4" : "#9ca6b2"
    font.pixelSize: 14
    selectionColor: "#a0e5d5"
    selectedTextColor: "#122020"
    selectByMouse: true
    persistentSelection: false
    verticalAlignment: TextInput.AlignVCenter
    placeholderTextColor: "#747f8c"
    background: Rectangle {
        radius: 8
        color: "#11161c"
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#a0e5d5" : "#38414c"
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
    // Templates supply editing behavior; the placeholder is rendered here.
    Text {
        anchors.fill: parent
        anchors.leftMargin: control.leftPadding
        anchors.rightMargin: control.rightPadding
        verticalAlignment: Text.AlignVCenter
        text: control.placeholderText
        color: control.placeholderTextColor
        font: control.font
        visible: !control.length && !control.preeditText
        elide: Text.ElideRight
    }
}

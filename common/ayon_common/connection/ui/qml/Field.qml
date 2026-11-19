import QtQuick 2.15
import QtQuick.Templates 2.15 as T
import "."

// Mirrors the ayon-react-components InputText.
T.TextField {
    id: control
    implicitWidth: 286
    implicitHeight: Theme.inputHeight
    leftPadding: 8
    rightPadding: 8
    topPadding: 0
    bottomPadding: 0
    color: Theme.textColor
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodyMedium
    selectionColor: Theme.primary
    selectedTextColor: Theme.textOnPrimary
    selectByMouse: true
    persistentSelection: false
    verticalAlignment: TextInput.AlignVCenter
    placeholderTextColor: Theme.placeholder
    opacity: enabled ? 1 : 0.5

    background: Rectangle {
        radius: Theme.radiusM
        color: Theme.surfaceContainerLow
        border.width: 1
        border.color: control.activeFocus ? Theme.primary : Theme.outlineVariant
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

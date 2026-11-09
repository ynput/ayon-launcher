import QtQuick 2.15
import QtQuick.Templates 2.15 as T
import "."

// Mirrors the ayon-react-components Button ("surface" default, "text" variant)
// plus "accent" (AYON green) and "danger" variants.
T.Button {
    id: control
    property string variant: "surface"
    property bool compact: false
    // Square top corners, for a button attached to the item above it
    property bool squareTop: false
    // Outline matching the border of panels and inputs
    property bool outlined: false

    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    implicitHeight: compact ? 24 : Theme.buttonHeight
    leftPadding: compact ? 8 : 12
    rightPadding: leftPadding
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : 0.5
    Accessible.name: text
    Keys.onReturnPressed: clicked()
    Keys.onEnterPressed: clicked()

    contentItem: Text {
        text: control.text
        textFormat: Text.PlainText
        font.family: Theme.fontFamily
        font.pixelSize: control.compact ? Theme.bodySmall : Theme.bodyMedium
        font.weight: Font.Medium
        color: control.variant === "accent" ? Theme.textOnAccent
             : control.variant === "danger" ? Theme.errorTextColor : Theme.textColor
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    // The top corners are clipped off for 'squareTop'
    background: Item {
        clip: control.squareTop

        Rectangle {
            anchors.fill: parent
            anchors.topMargin: control.squareTop ? -radius : 0
            radius: Theme.radiusM
            color: {
                if (control.variant === "accent") {
                    if (control.enabled && control.down)
                        return Theme.accentActive
                    if (control.enabled && control.hovered)
                        return Theme.accentHover
                    return Theme.accent
                }
                if (control.variant === "danger") {
                    if (control.enabled && control.down)
                        return Theme.errorContainerActive
                    if (control.enabled && control.hovered)
                        return Theme.errorContainerHover
                    return Theme.errorContainer
                }
                if (control.enabled && control.down)
                    return Theme.surfaceContainerHighestActive
                if (control.enabled && control.hovered)
                    return Theme.surfaceContainerHighestHover
                return control.variant === "text" ? "transparent" : Theme.surfaceContainerHighest
            }
            border.width: control.visualFocus || control.outlined ? 1 : 0
            border.color: !control.visualFocus ? Theme.outlineVariant
                        : control.variant === "accent" ? Theme.textColor : Theme.primary
            Behavior on color { ColorAnimation { duration: 100 } }
        }
    }
}

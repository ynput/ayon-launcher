pragma Singleton
import QtQuick 2.15

// Design tokens mirrored from @ynput/ayon-react-components (dark theme),
// as used by the AYON web frontend login page.
QtObject {
    readonly property string fontFamily: "Nunito Sans"

    // --md-sys-color-*-dark
    readonly property color surface: "#252B32"
    readonly property color surfaceContainerLow: "#1C2026"
    readonly property color surfaceContainerLowHover: "#23282F"
    readonly property color surfaceContainer: "#272D35"
    readonly property color surfaceContainerHighest: "#424A57"
    readonly property color surfaceContainerHighestHover: "#4D5560"
    readonly property color surfaceContainerHighestActive: "#535965"
    readonly property color textColor: "#F4F5F5"
    readonly property color textVariant: "#C1C7CE"
    readonly property color outline: "#8B9198"
    readonly property color outlineVariant: "#41474D"
    readonly property color primary: "#8FCEFF"
    readonly property color textOnPrimary: "#00344F"
    readonly property color error: "#FFB4AB"
    readonly property color errorContainer: "#93000A"
    readonly property color errorContainerHover: "#9C1F11"
    readonly property color errorContainerActive: "#9E271A"
    readonly property color errorTextColor: "#FFDAD6"
    readonly property color placeholder: "#757575"
    readonly property color accent: "#27D6A4"
    readonly property color accentHover: "#3FDCAF"
    readonly property color accentActive: "#23C093"
    readonly property color textOnAccent: "#1C2026"

    // Login card: rgba(28, 32, 38, 0.95) over the surface color
    readonly property color loginCard: "#1D2026"

    // Sizes
    readonly property int radiusM: 4
    readonly property int radiusXxl: 12
    readonly property int inputHeight: 32
    readonly property int buttonHeight: 40
    readonly property int gapLarge: 8

    // Typescale
    readonly property int bodyMedium: 14
    readonly property int bodySmall: 12
}

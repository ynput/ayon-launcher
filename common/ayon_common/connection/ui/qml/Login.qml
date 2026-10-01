import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."

// Styled after the AYON web frontend login page
// (ayon-frontend/src/pages/LoginPage).
Rectangle {
    id: root
    width: 560
    height: 720
    color: Theme.surface
    property int currentPage: login.page
    property bool locked: login.busy || login.waitingForBrowser
    property bool confirmingLogout: false

    function escapeHtml(value) {
        return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                            .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    }

    function reveal(item) {
        var position = item.mapToItem(viewport.contentItem, 0, 0)
        if (position.y < viewport.contentY)
            viewport.contentY = Math.max(0, position.y - 8)
        else if (position.y + item.height > viewport.contentY + viewport.height)
            viewport.contentY = Math.min(viewport.contentHeight - viewport.height,
                                        position.y + item.height - viewport.height + 8)
    }

    onCurrentPageChanged: {
        password.text = ""
        password.revealed = false
        if (currentPage === 0)
            serverUrl.forceActiveFocus()
        else if (!username.text.length)
            username.forceActiveFocus()
        else
            password.forceActiveFocus()
    }
    Component.onCompleted: serverUrl.forceActiveFocus()

    Connections {
        target: login
        function onClear_password() {
            password.text = ""
            password.revealed = false
        }
    }

    component FieldLabel: Text {
        Layout.fillWidth: true
        color: Theme.textColor
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodyMedium
        elide: Text.ElideRight
    }

    component Note: Text {
        Layout.fillWidth: true
        color: Theme.outline
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySmall
        lineHeight: 16
        lineHeightMode: Text.FixedHeight
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }

    // Current session (change user mode); used below the server input
    Component {
        id: sessionPanelComponent

        Rectangle {
            objectName: "sessionPanel"
            implicitHeight: sessionColumn.implicitHeight + 16
            radius: Theme.radiusM
            color: Theme.surfaceContainerLow
            border.width: 1
            border.color: root.confirmingLogout ? Theme.errorContainer : Theme.outlineVariant

            ColumnLayout {
                id: sessionColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 8
                anchors.leftMargin: 10
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Rectangle { width: 6; height: 6; radius: 3; color: Theme.accent }
                    Text {
                        Layout.fillWidth: true
                        text: "Logged in as <b>" + root.escapeHtml(login.sessionUsername) + "</b>"
                        textFormat: Text.StyledText
                        color: Theme.textColor
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySmall
                        elide: Text.ElideRight
                    }
                    ActionButton {
                        objectName: "logoutButton"
                        visible: login.loggedIn && !root.confirmingLogout
                        compact: true
                        text: "Logout"
                        enabled: !root.locked
                        onClicked: root.confirmingLogout = true
                    }
                    ActionButton {
                        objectName: "continueSessionButton"
                        visible: !login.loggedIn
                        compact: true
                        text: "Continue"
                        enabled: !root.locked
                        onClicked: login.continueSession()
                    }
                }

                // Inline logout confirmation
                ColumnLayout {
                    visible: root.confirmingLogout
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        Layout.fillWidth: true
                        text: "Logging out invalidates your login. Applications"
                              + " launched with it won't be able to use it anymore."
                        color: Theme.textVariant
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySmall
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Item { Layout.fillWidth: true }
                        ActionButton {
                            objectName: "cancelLogoutButton"
                            compact: true
                            variant: "text"
                            text: "Cancel"
                            onClicked: root.confirmingLogout = false
                        }
                        ActionButton {
                            objectName: "confirmLogoutButton"
                            compact: true
                            variant: "danger"
                            text: "Logout"
                            onClicked: login.logout()
                        }
                    }
                }
            }
        }
    }
    Flickable {
        id: viewport
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: Math.max(height, card.height + 48)
        boundsBehavior: Flickable.StopAtBounds

        // Login card (LoginForm)
        Rectangle {
            id: card
            width: panel.width + 64
            height: panel.height + 64
            x: Math.max(0, (viewport.width - width) / 2)
            y: Math.max(24, (viewport.height - height) / 2)
            radius: Theme.radiusXxl
            color: Theme.loginCard

            // Soft drop shadow (box-shadow: 0 0 10px rgba(0, 0, 0, 0.25))
            Repeater {
                model: 4
                Rectangle {
                    z: -1
                    anchors.fill: parent
                    anchors.margins: -(index + 1) * 2
                    radius: card.radius + (index + 1) * 2
                    color: "transparent"
                    border.width: 2
                    border.color: Qt.rgba(0, 0, 0, 0.09 - index * 0.02)
                }
            }

            // Login panel
            Rectangle {
                id: panel
                x: 32
                y: 32
                width: 350
                height: content.implicitHeight + 64
                radius: Theme.radiusM
                color: Theme.surfaceContainer

                ColumnLayout {
                    id: content
                    x: 32
                    y: 32
                    width: panel.width - 64
                    spacing: 16

                    Image {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredHeight: 60
                        Layout.preferredWidth: 60 * sourceSize.width / Math.max(1, sourceSize.height)
                        source: "images/ayon_logo.png"
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                        Accessible.role: Accessible.Graphic
                        Accessible.name: "AYON"
                    }

                    Rectangle {
                        objectName: "errorPanel"
                        visible: login.errorMessage.length > 0
                        Layout.fillWidth: true
                        implicitHeight: errorText.implicitHeight + 16
                        radius: Theme.radiusM
                        color: Qt.rgba(0.576, 0, 0.039, 0.35)
                        border.color: Theme.errorContainer
                        Text {
                            id: errorText
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 8
                            text: login.errorMessage
                            textFormat: Text.PlainText
                            color: Theme.errorTextColor
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySmall
                            wrapMode: Text.WordWrap
                            Accessible.role: Accessible.StaticText
                            Accessible.name: text
                        }
                    }

                    // Page 0: server address
                    ColumnLayout {
                        visible: login.page === 0
                        Layout.fillWidth: true
                        spacing: Theme.gapLarge

                        FieldLabel { text: "Server URL" }
                        Field {
                            id: serverUrl
                            objectName: "serverUrl"
                            Layout.fillWidth: true
                            text: login.serverUrl
                            placeholderText: "https://ayon.yourstudio.com"
                            Accessible.name: "AYON server URL"
                            inputMethodHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoAutoUppercase
                            enabled: !root.locked
                            onTextEdited: login.clearError()
                            onAccepted: login.validateServer(text)
                            onActiveFocusChanged: if (activeFocus) root.reveal(serverUrl)
                        }
                        Loader {
                            visible: login.loggedIn
                            active: login.loggedIn
                            Layout.fillWidth: true
                            sourceComponent: sessionPanelComponent
                        }
                        ActionButton {
                            objectName: "connectButton"
                            Layout.fillWidth: true
                            text: login.busy ? "Connecting…"
                                  : login.connectionFailed ? "Try again" : "Connect"
                            enabled: !root.locked && serverUrl.text.trim().length > 0
                            onClicked: login.validateServer(serverUrl.text)
                        }
                        RowLayout {
                            visible: login.busy
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 8
                            Spinner {}
                            Text {
                                text: "Connecting to your AYON server"
                                color: Theme.outline
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.bodySmall
                            }
                        }
                        Note {
                            visible: !login.busy
                            text: "Not sure? Ask your studio administrator."
                        }
                    }

                    // Page 1: sign in
                    ColumnLayout {
                        visible: login.page === 1
                        Layout.fillWidth: true
                        spacing: 16

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapLarge

                            FieldLabel { text: "Server" }
                            // Read-only server field (LockedInput) with the Change button inside
                            Rectangle {
                                id: serverLocked
                                Layout.fillWidth: true
                                implicitHeight: Theme.inputHeight
                                radius: Theme.radiusM
                                // Flat, panel-colored background reads as "not editable"
                                color: Theme.surfaceContainer
                                border.width: 1
                                border.color: Theme.outlineVariant
                                Accessible.role: Accessible.StaticText
                                Accessible.name: "AYON server URL (read-only)"
                                Accessible.description: login.serverUrl

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 4
                                    spacing: 8

                                    // Lock glyph
                                    Item {
                                        implicitWidth: 10
                                        implicitHeight: 13
                                        Rectangle {
                                            x: 1.5
                                            y: 0
                                            width: 7
                                            height: 9
                                            radius: 3.5
                                            color: "transparent"
                                            border.width: 1.5
                                            border.color: Theme.outline
                                        }
                                        Rectangle {
                                            y: 5
                                            width: 10
                                            height: 8
                                            radius: 1.5
                                            color: Theme.outline
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        verticalAlignment: Text.AlignVCenter
                                        text: login.serverUrl
                                        textFormat: Text.PlainText
                                        color: Theme.outline
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.bodyMedium
                                        elide: Text.ElideMiddle
                                        MouseArea {
                                            anchors.fill: parent
                                            acceptedButtons: Qt.NoButton
                                            cursorShape: Qt.ForbiddenCursor
                                        }
                                    }

                                    ActionButton {
                                        objectName: "changeServerButton"
                                        compact: true
                                        text: "Change"
                                        enabled: !root.locked
                                        onClicked: login.back()
                                    }
                                }
                            }

                            Loader {
                                // Only for the current session's server
                                visible: login.isCurrentSession || login.canContinue
                                active: visible
                                Layout.fillWidth: true
                                sourceComponent: sessionPanelComponent
                            }
                        }

                        ColumnLayout {
                            visible: login.browserSupported && !login.isCurrentSession
                            Layout.fillWidth: true
                            spacing: Theme.gapLarge

                            ActionButton {
                                objectName: "browserButton"
                                visible: login.browserSupported && !login.waitingForBrowser
                                Layout.fillWidth: true
                                variant: "accent"
                                text: "Login with AYON server"
                                enabled: !root.locked
                                onClicked: login.openBrowser()
                            }

                            Rectangle {
                                visible: login.waitingForBrowser
                                Layout.fillWidth: true
                                implicitHeight: waitingColumn.implicitHeight + 24
                                radius: Theme.radiusM
                                color: Theme.surfaceContainerLow
                                border.color: Theme.outlineVariant
                                ColumnLayout {
                                    id: waitingColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 12
                                    spacing: 12
                                    RowLayout {
                                        Layout.alignment: Qt.AlignHCenter
                                        spacing: 10
                                        Spinner {}
                                        Text {
                                            text: "Finish signing in in your browser"
                                            color: Theme.textColor
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.bodyMedium
                                        }
                                    }
                                    ActionButton {
                                        objectName: "cancelBrowserButton"
                                        Layout.fillWidth: true
                                        variant: "text"
                                        text: "Cancel"
                                        onClicked: login.cancelBrowser()
                                    }
                                }
                            }
                        }

                        // Separator between browser login and credentials
                        RowLayout {
                            visible: login.browserSupported && !login.isCurrentSession
                            Layout.fillWidth: true
                            spacing: 12
                            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.outlineVariant }
                            Text {
                                text: "or"
                                color: Theme.outline
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.bodySmall
                            }
                            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.outlineVariant }
                        }

                        ColumnLayout {
                            visible: !login.isCurrentSession
                            Layout.fillWidth: true
                            spacing: Theme.gapLarge

                            FieldLabel { text: "Username" }
                            Field {
                                id: username
                                objectName: "username"
                                Layout.fillWidth: true
                                text: login.username
                                placeholderText: "Enter your username"
                                Accessible.name: "Username"
                                readOnly: login.forceUsername
                                enabled: !root.locked
                                inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                                onTextEdited: login.clearError()
                                onAccepted: password.forceActiveFocus()
                                onActiveFocusChanged: if (activeFocus) root.reveal(username)
                            }

                            FieldLabel { text: "Password" }
                            Field {
                                id: password
                                objectName: "password"
                                property bool revealed: false
                                Layout.fillWidth: true
                                placeholderText: "Enter password"
                                Accessible.name: "Password"
                                enabled: !root.locked
                                echoMode: revealed ? TextInput.Normal : TextInput.Password
                                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                                rightPadding: 36
                                onTextEdited: login.clearError()
                                onAccepted: login.signIn(username.text, text)
                                onActiveFocusChanged: if (activeFocus) root.reveal(password)

                                MouseArea {
                                    id: revealButton
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.rightMargin: 4
                                    width: 28
                                    height: 24
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    Accessible.role: Accessible.Button
                                    Accessible.name: password.revealed ? "Hide password" : "Show password"
                                    onClicked: password.revealed = !password.revealed
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: Theme.radiusM
                                        color: revealButton.containsMouse
                                               ? Theme.surfaceContainerLowHover : "transparent"
                                    }
                                    Image {
                                        anchors.centerIn: parent
                                        width: 18
                                        height: 18
                                        source: password.revealed
                                                ? "../../../resources/eye_closed.png"
                                                : "../../../resources/eye.png"
                                        fillMode: Image.PreserveAspectFit
                                        smooth: true
                                        mipmap: true
                                        opacity: revealButton.containsMouse ? 0.95 : 0.65
                                    }
                                }
                            }

                            ActionButton {
                                objectName: "signInButton"
                                Layout.fillWidth: true
                                text: login.busy && !login.waitingForBrowser
                                      ? "Logging in…" : "Login with password"
                                enabled: !root.locked && username.text.trim().length > 0 && password.text.length > 0
                                onClicked: login.signIn(username.text, password.text)
                                onActiveFocusChanged: if (activeFocus) root.reveal(this)
                            }
                        }
                    }

                    // LoginTerms
                    Note {
                        text: 'By logging in you agree to our '
                              + '<a href="https://ynput.io/terms/">Terms of Service</a>'
                              + ' and <a href="https://ynput.io/privacy-policy">Privacy Policy</a>'
                        textFormat: Text.StyledText
                        linkColor: Theme.outline
                        onLinkActivated: function(link) { Qt.openUrlExternally(link) }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.NoButton
                            cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.rightMargin: 4
        y: viewport.contentY / viewport.contentHeight * viewport.height
        width: 4
        height: Math.max(24, viewport.height * viewport.height / viewport.contentHeight)
        radius: 2
        color: Theme.surfaceContainerHighest
        visible: viewport.contentHeight > viewport.height
    }
}

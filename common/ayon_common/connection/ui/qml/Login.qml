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
    // Signed in on the connected server (current or saved session)
    property bool hasSession: login.isCurrentSession || login.canContinue
    // Show login options for the session's server instead of the session
    property bool anotherAccount: false
    property bool showSession: hasSession && !anotherAccount
    readonly property int fadeDuration: 300

    function initials(name) {
        var parts = String(name).split(/[\s._-]+/).filter(function(part) {
            return part.length > 0
        })
        return parts.slice(0, 2).map(function(part) {
            return part.charAt(0).toUpperCase()
        }).join("")
    }

    function focusDefault() {
        if (currentPage === 0)
            serverUrl.forceActiveFocus()
        else if (showSession)
            continueButton.forceActiveFocus()
        else if (!username.text.length)
            username.forceActiveFocus()
        else
            password.forceActiveFocus()
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
        anotherAccount = false
        confirmingLogout = false
        password.text = ""
        password.revealed = false
        focusDefault()
    }
    onShowSessionChanged: {
        confirmingLogout = false
        focusDefault()
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

    // Studio background of the connected server; fades in once loaded
    Image {
        id: studioBackground
        property string latest: login.studioBackground
        property bool shown: login.page === 1 && latest.length > 0
                             && status === Image.Ready
        // Keep the image while it fades out
        onLatestChanged: if (latest.length) source = latest
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        clip: true
        smooth: true
        asynchronous: true
        opacity: shown ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: root.fadeDuration } }
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

                    // AYON logo; cross-fades to the studio logo of the
                    // connected server once that is loaded
                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 60

                        Image {
                            anchors.fill: parent
                            source: "images/ayon_logo.png"
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                            opacity: studioLogo.shown ? 0 : 1
                            Behavior on opacity { NumberAnimation { duration: root.fadeDuration } }
                            Accessible.role: Accessible.Graphic
                            Accessible.name: "AYON"
                        }
                        Image {
                            id: studioLogo
                            objectName: "studioLogo"
                            property string latest: login.studioLogo
                            property bool shown: login.page === 1 && latest.length > 0
                                                 && status === Image.Ready
                            // Keep the image while it fades out
                            onLatestChanged: if (latest.length) source = latest
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                            opacity: shown ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: root.fadeDuration } }
                            Accessible.role: Accessible.Graphic
                            Accessible.name: "Studio logo"
                        }
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

                    // Page 1: signed in (current or saved session)
                    ColumnLayout {
                        visible: login.page === 1 && root.showSession
                        Layout.fillWidth: true
                        spacing: 16

                        Text {
                            Layout.fillWidth: true
                            text: "You are currently signed in as:"
                            color: Theme.textVariant
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodyMedium
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                        }

                        // Account
                        Item {
                            objectName: "sessionPanel"
                            Layout.fillWidth: true
                            implicitHeight: accountRow.implicitHeight + 24
                            clip: true

                            // Bottom corners are clipped off so the card
                            // is square where the button attaches
                            Rectangle {
                                anchors.fill: parent
                                anchors.bottomMargin: -radius
                                radius: Theme.radiusM
                                color: Theme.surfaceContainerLow
                                border.width: 1
                                border.color: Theme.outlineVariant
                            }

                            RowLayout {
                                id: accountRow
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.margins: 12
                                spacing: 12

                                // Avatar; initials until the image is loaded
                                Rectangle {
                                    implicitWidth: 48
                                    implicitHeight: 48
                                    radius: 24
                                    color: Theme.surfaceContainerHighest
                                    Text {
                                        anchors.centerIn: parent
                                        text: root.initials(login.sessionDisplayName)
                                        textFormat: Text.PlainText
                                        color: Theme.textColor
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 18
                                        font.weight: Font.Medium
                                    }
                                    Image {
                                        objectName: "sessionAvatar"
                                        anchors.fill: parent
                                        source: login.sessionAvatar
                                        smooth: true
                                        mipmap: true
                                        opacity: status === Image.Ready ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: root.fadeDuration } }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        Layout.fillWidth: true
                                        text: login.sessionDisplayName
                                        textFormat: Text.PlainText
                                        color: Theme.textColor
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.bodyMedium
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        visible: text.length > 0
                                        Layout.fillWidth: true
                                        text: login.sessionEmail
                                        textFormat: Text.PlainText
                                        color: Theme.textVariant
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.bodySmall
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: login.serverUrl.replace(/^https?:\/\//, "")
                                        textFormat: Text.PlainText
                                        color: Theme.outline
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.bodySmall
                                        elide: Text.ElideMiddle
                                    }
                                }
                            }
                        }

                        ActionButton {
                            id: continueButton
                            objectName: "continueSessionButton"
                            Layout.fillWidth: true
                            // Attached to the account card above
                            Layout.topMargin: -parent.spacing
                            squareTop: true
                            outlined: true
                            variant: "accent"
                            text: "Continue as " + login.sessionShortName
                            enabled: !root.locked
                            onClicked: login.continueSession()
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 1
                            color: Theme.outlineVariant
                        }

                        ColumnLayout {
                            visible: !root.confirmingLogout
                            Layout.fillWidth: true
                            spacing: Theme.gapLarge

                            ActionButton {
                                objectName: "changeUserButton"
                                Layout.fillWidth: true
                                text: "Switch accounts"
                                enabled: !root.locked
                                onClicked: root.anotherAccount = true
                            }
                            ActionButton {
                                objectName: "logoutButton"
                                Layout.fillWidth: true
                                text: "Log out"
                                enabled: !root.locked
                                onClicked: root.confirmingLogout = true
                            }
                        }

                        // Inline logout confirmation
                        ColumnLayout {
                            visible: root.confirmingLogout
                            Layout.fillWidth: true
                            spacing: Theme.gapLarge
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
                                spacing: Theme.gapLarge
                                ActionButton {
                                    objectName: "cancelLogoutButton"
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    text: "Cancel"
                                    enabled: !root.locked
                                    onClicked: root.confirmingLogout = false
                                }
                                ActionButton {
                                    objectName: "confirmLogoutButton"
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    variant: "danger"
                                    text: login.busy ? "Logging out…" : "Log out"
                                    enabled: !root.locked
                                    onClicked: login.logout()
                                }
                            }
                        }
                    }

                    // Page 1: sign in
                    ColumnLayout {
                        visible: login.page === 1 && !root.showSession
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
                        }

                        ColumnLayout {
                            visible: login.browserSupported
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
                            visible: login.browserSupported
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

                            // Back to the session the user is signed in with
                            ActionButton {
                                objectName: "backToSessionButton"
                                visible: root.hasSession
                                Layout.fillWidth: true
                                variant: "text"
                                text: "Back"
                                enabled: !root.locked
                                onClicked: root.anotherAccount = false
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

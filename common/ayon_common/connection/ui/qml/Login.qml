import QtQuick 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    width: 940
    height: 740
    color: "#151a20"
    property bool wide: width >= 820
    property int currentPage: login.page
    property bool locked: login.busy || login.waitingForBrowser

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

    Rectangle {
        id: brandPanel
        visible: root.wide
        width: visible ? 330 : 0
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: "#0e1318"
        clip: true

        Column {
            x: 36
            y: 38
            spacing: 9
            Text {
                text: "AYON"
                font.pixelSize: 32
                font.weight: Font.Bold
                font.letterSpacing: 6
                color: "#f3f6f6"
            }
            Text {
                text: "YOUR PIPELINE STARTS HERE"
                font.pixelSize: 10
                font.letterSpacing: 1.3
                color: "#788994"
            }
        }

        // Code-native orbital artwork scales cleanly on high-DPI displays.
        Item {
            width: 360
            height: 330
            x: -16
            y: 158
            rotation: -26
            Repeater {
                model: 5
                Rectangle {
                    width: 122 + index * 54
                    height: width * 0.64
                    anchors.centerIn: parent
                    radius: width / 2
                    color: "transparent"
                    border.width: 1
                    border.color: index === 2 ? "#689b92" : "#263b3f"
                }
            }
            Rectangle {
                width: 78
                height: 78
                radius: 23
                rotation: 26
                anchors.centerIn: parent
                gradient: Gradient {
                    GradientStop { position: 0; color: "#b2eedf" }
                    GradientStop { position: 1; color: "#65aa9e" }
                }
                Image {
                    anchors.centerIn: parent
                    width: 52
                    height: 52
                    source: "../../../resources/AYON.png"
                    fillMode: Image.PreserveAspectFit
                }
            }
            Rectangle {
                x: 281
                y: 195
                width: 12
                height: 12
                radius: 6
                color: "#a0e5d5"
            }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 36
            spacing: 20
            Text {
                text: "Your studio.\nConnected."
                font.pixelSize: 35
                font.weight: Font.DemiBold
                lineHeight: 1.08
                color: "#f0f4f5"
            }
            Text {
                width: parent.width
                text: "One place to connect to your team,\nyour tools, and your next creation."
                font.pixelSize: 13
                lineHeight: 1.45
                color: "#8f9eaa"
                wrapMode: Text.WordWrap
            }
            Rectangle { width: 32; height: 2; color: "#a0e5d5" }
        }
    }

    Item {
        anchors.left: brandPanel.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom

        RowLayout {
            id: progress
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 32
            spacing: 12
            Repeater {
                model: ["Server", "Sign in"]
                RowLayout {
                    spacing: 8
                    Rectangle {
                        width: 23
                        height: 23
                        radius: 12
                        color: index <= login.page ? "#a0e5d5" : "#29313a"
                        Text {
                            anchors.centerIn: parent
                            text: index + 1
                            font.pixelSize: 11
                            font.bold: true
                            color: index <= login.page ? "#142829" : "#84909c"
                        }
                    }
                    Text {
                        text: modelData
                        color: index <= login.page ? "#dbe6e8" : "#84909c"
                        font.pixelSize: 12
                    }
                    Rectangle {
                        visible: index === 0
                        Layout.preferredWidth: 36
                        Layout.preferredHeight: 1
                        Layout.leftMargin: 8
                        Layout.rightMargin: 8
                        color: "#38434e"
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                visible: !root.wide
                text: "AYON"
                color: "#edf3f4"
                font.bold: true
                font.letterSpacing: 3
            }
        }

        Flickable {
            id: viewport
            anchors.top: progress.bottom
            anchors.bottom: footer.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.topMargin: 18
            anchors.bottomMargin: 12
            clip: true
            contentWidth: width
            contentHeight: Math.max(height, form.implicitHeight + 32)
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: form
                width: Math.min(380, viewport.width - 64)
                x: (viewport.width - width) / 2
                y: Math.max(16, (viewport.height - implicitHeight) / 2)
                spacing: root.height < 740 ? 12 : 22

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Text {
                        text: login.page === 0 ? "LET’S GET STARTED" : "WELCOME BACK"
                        color: "#a0e5d5"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        font.letterSpacing: 1.5
                    }
                    Text {
                        Layout.fillWidth: true
                        text: login.page === 0 ? "Connect to your studio" : "Sign in to AYON"
                        color: "#f0f4f5"
                        font.pixelSize: 28
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: login.page === 0
                            ? "Enter the AYON server address provided by your studio."
                            : "Choose how you’d like to sign in."
                        color: "#98a6b3"
                        font.pixelSize: 13
                        lineHeight: 1.3
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle {
                    objectName: "errorPanel"
                    visible: login.errorMessage.length > 0
                    Layout.fillWidth: true
                    implicitHeight: errorText.implicitHeight + 28
                    radius: 8
                    color: "#312427"
                    border.color: "#634047"
                    Text {
                        id: errorText
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        text: login.errorMessage
                        textFormat: Text.PlainText
                        color: "#f1b9bc"
                        font.pixelSize: 12
                        lineHeight: 1.2
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                    }
                }

                ColumnLayout {
                    visible: login.page === 0
                    Layout.fillWidth: true
                    spacing: 10
                    Text { text: "AYON server URL"; color: "#dae1e7"; font.pixelSize: 12 }
                    Field {
                        id: serverUrl
                        objectName: "serverUrl"
                        Layout.fillWidth: true
                        text: login.serverUrl
                        placeholderText: "https://ayon.yourstudio.com"
                        Accessible.name: "AYON server URL"
                        inputMethodHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoAutoUppercase
                        enabled: !root.locked
                        readOnly: login.forceUsername
                        onTextEdited: login.clearError()
                        onAccepted: login.validateServer(text)
                        onActiveFocusChanged: if (activeFocus) root.reveal(serverUrl)
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Not sure? Ask your studio administrator."
                        color: "#85939f"
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                    ActionButton {
                        objectName: "connectButton"
                        Layout.fillWidth: true
                        Layout.topMargin: 14
                        primary: true
                        text: login.busy ? "Checking connection…" : "Continue  →"
                        enabled: !root.locked && serverUrl.text.trim().length > 0
                        onClicked: login.validateServer(serverUrl.text)
                    }
                    RowLayout {
                        visible: login.busy
                        Layout.topMargin: 6
                        spacing: 10
                        Spinner { Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                        Text { text: "Connecting to your AYON server"; color: "#98a6b3"; font.pixelSize: 12 }
                    }
                }

                ColumnLayout {
                    visible: login.page === 1
                    Layout.fillWidth: true
                    spacing: root.height < 740 ? 10 : 18

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 60
                        radius: 8
                        color: "#19282a"
                        border.color: "#2c4544"
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10
                            Rectangle { width: 6; height: 6; radius: 3; color: "#a0e5d5" }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { text: "CONNECTED TO"; color: "#8ea7a5"; font.pixelSize: 9; font.letterSpacing: 1 }
                                Text {
                                    Layout.fillWidth: true
                                    text: login.serverUrl
                                    textFormat: Text.PlainText
                                    color: "#daeae6"
                                    font.pixelSize: 12
                                    elide: Text.ElideMiddle
                                }
                            }
                            ActionButton {
                                objectName: "changeServerButton"
                                text: "Change"
                                implicitWidth: 72
                                implicitHeight: 32
                                enabled: !root.locked
                                onClicked: login.back()
                            }
                        }
                    }

                    ColumnLayout {
                        visible: !login.waitingForBrowser
                        Layout.fillWidth: true
                        spacing: 9
                        ActionButton {
                            objectName: "browserButton"
                            Layout.fillWidth: true
                            text: "Continue in browser  ↗"
                            enabled: login.browserSupported && !root.locked
                            onClicked: login.openBrowser()
                        }
                        Text {
                            Layout.fillWidth: true
                            text: login.browserSupported
                                ? "Use the AYON web frontend, including your studio’s SSO."
                                : "Browser login requires AYON server 1.3.2 or newer."
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            color: "#85939f"
                            font.pixelSize: 11
                        }
                    }

                    Rectangle {
                        visible: login.waitingForBrowser
                        Layout.fillWidth: true
                        implicitHeight: waitingColumn.implicitHeight + 28
                        radius: 8
                        color: "#1b242c"
                        border.color: "#34444c"
                        ColumnLayout {
                            id: waitingColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 14
                            spacing: 12
                            RowLayout {
                                spacing: 12
                                Spinner { Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
                                Text { text: "Finish signing in in your browser"; color: "#e5edf0"; font.pixelSize: 12 }
                            }
                            ActionButton {
                                objectName: "cancelBrowserButton"
                                Layout.fillWidth: true
                                implicitHeight: 34
                                text: "Cancel browser login"
                                onClicked: login.cancelBrowser()
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Rectangle { Layout.fillWidth: true; height: 1; color: "#303943" }
                        Text { text: "or use your credentials"; color: "#85939f"; font.pixelSize: 11 }
                        Rectangle { Layout.fillWidth: true; height: 1; color: "#303943" }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "Username"; color: "#dae1e7"; font.pixelSize: 12 }
                        Field {
                            id: username
                            objectName: "username"
                            Layout.fillWidth: true
                            text: login.username
                            placeholderText: "Your username"
                            Accessible.name: "Username"
                            readOnly: login.forceUsername
                            enabled: !root.locked
                            inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                            onTextEdited: login.clearError()
                            onAccepted: password.forceActiveFocus()
                            onActiveFocusChanged: if (activeFocus) root.reveal(username)
                        }
                        Text { Layout.topMargin: 6; text: "Password"; color: "#dae1e7"; font.pixelSize: 12 }
                        Field {
                            id: password
                            objectName: "password"
                            property bool revealed: false
                            Layout.fillWidth: true
                            placeholderText: "Your password"
                            Accessible.name: "Password"
                            enabled: !root.locked
                            echoMode: revealed ? TextInput.Normal : TextInput.Password
                            inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                            rightPadding: 68
                            onTextEdited: login.clearError()
                            onAccepted: login.signIn(username.text, text)
                            onActiveFocusChanged: if (activeFocus) root.reveal(password)
                            ActionButton {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.rightMargin: 6
                                implicitWidth: 55
                                implicitHeight: 34
                                text: password.revealed ? "Hide" : "Show"
                                Accessible.name: password.revealed ? "Hide password" : "Show password"
                                onClicked: password.revealed = !password.revealed
                            }
                        }
                    }

                    ActionButton {
                        objectName: "signInButton"
                        Layout.fillWidth: true
                        text: login.busy && !login.waitingForBrowser ? "Signing in…" : "Sign in  →"
                        primary: true
                        enabled: !root.locked && username.text.trim().length > 0 && password.text.length > 0
                        onClicked: login.signIn(username.text, password.text)
                        onActiveFocusChanged: if (activeFocus) root.reveal(this)
                    }
                }


            }
        }

        Rectangle {
            anchors.right: viewport.right
            anchors.rightMargin: 8
            y: viewport.y + viewport.contentY / viewport.contentHeight * viewport.height
            width: 3
            height: Math.max(24, viewport.height * viewport.height / viewport.contentHeight)
            radius: 2
            color: "#4c5965"
            visible: viewport.contentHeight > viewport.height
        }

        Text {
            id: footer
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 24
            text: "AYON LAUNCHER  /  MADE FOR YOUR PRODUCTION"
            color: "#74818d"
            font.pixelSize: 9
            font.letterSpacing: 1
        }
    }
}

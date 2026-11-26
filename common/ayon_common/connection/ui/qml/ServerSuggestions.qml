import QtQuick 2.15
import QtQuick.Templates 2.15 as T
import "."

// Known server urls shown below a text field, like a combo box popup.
// The field keeps focus; it forwards navigation keys to this popup.
T.Popup {
    id: control
    property Item field
    property var servers: []
    // Text the servers are filtered by, empty to show all of them
    property string filterText: ""
    readonly property var matches: filterServers(servers, filterText)
    readonly property int count: matches.length
    property int currentIndex: -1
    // Server of the current session, it cannot be removed
    property string protectedServer: ""
    signal serverSelected(string url)
    signal removeRequested(string url)

    readonly property int rowHeight: 28
    readonly property int maxRows: 6

    function normalize(value) {
        return String(value).trim().toLowerCase().replace(/^[a-z]+:\/\//, "")
    }

    function filterServers(urls, text) {
        var needle = normalize(text)
        var result = []
        for (var i = 0; i < urls.length; ++i) {
            if (!needle.length || normalize(urls[i]).indexOf(needle) !== -1)
                result.push(urls[i])
        }
        return result
    }

    // Show the servers matching 'text', all of them when it is empty
    function show(text) {
        filterText = text
        currentIndex = -1
        if (count > 0)
            open()
        else
            close()
    }

    function move(step) {
        if (!count)
            return
        if (currentIndex < 0)
            currentIndex = step > 0 ? 0 : count - 1
        else
            currentIndex = (currentIndex + step + count) % count
        list.positionViewAtIndex(currentIndex, ListView.Contain)
    }

    function canRemove(url) {
        return !protectedServer.length
            || normalize(url).replace(/\/+$/, "")
               !== normalize(protectedServer).replace(/\/+$/, "")
    }

    // Remove the highlighted server, returns false if nothing was removed
    function removeCurrent() {
        if (currentIndex < 0 || currentIndex >= count)
            return false
        var url = matches[currentIndex]
        if (!canRemove(url))
            return false
        removeRequested(url)
        return true
    }

    function selectCurrent() {
        if (currentIndex < 0 || currentIndex >= count)
            return false
        var url = matches[currentIndex]
        close()
        serverSelected(url)
        return true
    }

    onCountChanged: {
        if (currentIndex >= count)
            currentIndex = count - 1
        if (!count)
            close()
    }

    y: field ? field.height + 4 : 0
    width: field ? field.width : 200
    padding: 4
    focus: false
    modal: false
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent
    // At most 'maxRows' rows, the list scrolls if there are more servers
    implicitHeight: list.implicitHeight + topPadding + bottomPadding

    background: Rectangle {
        radius: Theme.radiusM
        color: Theme.surfaceContainer
        border.width: 1
        border.color: Theme.outlineVariant
    }

    contentItem: ListView {
        id: list
        clip: true
        implicitHeight: Math.min(control.count, control.maxRows) * control.rowHeight
        height: implicitHeight
        model: control.matches
        currentIndex: control.currentIndex
        boundsBehavior: Flickable.StopAtBounds
        Accessible.role: Accessible.List
        Accessible.name: "Known servers"

        delegate: Rectangle {
            id: entry
            width: ListView.view.width
            height: control.rowHeight
            radius: Theme.radiusM
            readonly property bool highlighted: index === control.currentIndex
            readonly property bool removable: control.canRemove(modelData)
            color: highlighted || entryMouse.containsMouse
                ? Theme.surfaceContainerHighest : "transparent"
            Accessible.role: Accessible.ListItem
            Accessible.name: modelData

            Text {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: entry.removable ? removeButton.width + 4 : 8
                verticalAlignment: Text.AlignVCenter
                text: modelData
                textFormat: Text.PlainText
                elide: Text.ElideMiddle
                color: Theme.textColor
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodyMedium
            }
            MouseArea {
                id: entryMouse
                anchors.fill: parent
                hoverEnabled: true
                onEntered: control.currentIndex = index
                onClicked: {
                    control.currentIndex = index
                    control.selectCurrent()
                }

                // Child of the row's mouse area so the row stays hovered
                MouseArea {
                    id: removeButton
                    objectName: "removeServerButton"
                    visible: entry.removable
                             && (entry.highlighted || entryMouse.containsMouse)
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.rightMargin: 2
                    width: 24
                    height: 24
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    Accessible.role: Accessible.Button
                    Accessible.name: "Remove " + modelData
                    Accessible.onPressAction: control.removeRequested(modelData)
                    onClicked: control.removeRequested(modelData)

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusM
                        color: removeButton.containsMouse
                            ? Theme.surfaceContainerHighestHover : "transparent"
                    }
                    Canvas {
                        anchors.centerIn: parent
                        width: 8
                        height: 8
                        property color strokeColor: removeButton.containsMouse
                            ? Theme.textColor : Theme.textVariant
                        onStrokeColorChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            ctx.strokeStyle = strokeColor
                            ctx.lineWidth = 1.5
                            ctx.beginPath()
                            ctx.moveTo(0, 0)
                            ctx.lineTo(width, height)
                            ctx.moveTo(width, 0)
                            ctx.lineTo(0, height)
                            ctx.stroke()
                        }
                    }
                }
            }
        }
    }
}

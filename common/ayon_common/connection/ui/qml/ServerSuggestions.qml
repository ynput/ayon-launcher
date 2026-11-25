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
    signal serverSelected(string url)

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
    implicitHeight: list.contentHeight + topPadding + bottomPadding

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
            color: highlighted || entryMouse.containsMouse
                ? Theme.surfaceContainerHighest : "transparent"
            Accessible.role: Accessible.ListItem
            Accessible.name: modelData

            Text {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
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
            }
        }
    }
}

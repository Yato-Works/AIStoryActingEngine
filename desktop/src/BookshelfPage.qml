import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: page
    property var books: null
    property color accent: "#1db954"
    signal openBook(string bookId)

    function hue(id) {
        var s = String(id || ""), h = 0
        for (var i = 0; i < s.length; ++i) h = (h * 31 + s.charCodeAt(i)) % 360
        return h / 360.0
    }

    background: Rectangle { color: "#121212" }

    header: Control {
        padding: 24
        contentItem: RowLayout {
            Text { text: "📚 マイライブラリ"; color: "#eeeeee"; font.pixelSize: 26; font.bold: true }
            Item { Layout.fillWidth: true }
            Text { text: (page.books ? page.books.count : 0) + " 冊"; color: "#a0a0a0"; font.pixelSize: 14 }
        }
    }

    GridView {
        id: grid
        anchors.fill: parent
        anchors.margins: 24
        anchors.topMargin: 0
        clip: true
        cellWidth: 210; cellHeight: 305
        model: page.books

        Text {
            anchors.centerIn: parent
            visible: grid.count === 0
            text: "本棚は空です\n\nWorker が小説を処理すると\nここに本が並びます"
            color: "#666666"; font.pixelSize: 15
            horizontalAlignment: Text.AlignHCenter
        }

        ScrollBar.vertical: ScrollBar { }

        delegate: Item {
            width: grid.cellWidth - 20; height: grid.cellHeight - 20

            Rectangle {
                id: card
                anchors.fill: parent
                radius: 12
                color: cardMa.containsMouse ? "#2c2c2c" : "#1e1e1e"
                Behavior on color { ColorAnimation { duration: 120 } }

                // ---- cover ----
                Rectangle {
                    id: cover
                    width: parent.width - 28; height: width * 1.22
                    x: 14; y: 14
                    radius: 8
                    gradient: Gradient {
                        GradientStop { position: 0; color: Qt.hsla(page.hue(model.id), 0.42, 0.40) }
                        GradientStop { position: 1; color: Qt.hsla(page.hue(model.id), 0.50, 0.16) }
                    }
                    Text {
                        anchors.centerIn: parent
                        text: (model.title || "?").charAt(0)
                        color: "#ffffff"; opacity: 0.8
                        font.pixelSize: 64; font.bold: true
                    }
                    // audio progress
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 5; color: "#99000000"
                        Rectangle {
                            width: parent.width * (model.segments > 0 ? model.audio_done / model.segments : 0)
                            height: parent.height; color: page.accent
                        }
                    }
                    // hover play
                    Rectangle {
                        anchors.centerIn: parent
                        width: 58; height: 58; radius: 29
                        color: page.accent
                        opacity: cardMa.containsMouse ? 0.95 : 0
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                        Text { anchors.centerIn: parent; text: "▶"; color: "#000"; font.pixelSize: 22 }
                    }
                }

                Text {
                    anchors.top: cover.bottom; anchors.topMargin: 10
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.leftMargin: 14; anchors.rightMargin: 14
                    text: model.title || "(無題)"
                    color: "#eeeeee"; font.pixelSize: 14; font.bold: true
                    elide: Text.ElideRight
                }
                Text {
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 10
                    anchors.left: parent.left; anchors.leftMargin: 14
                    text: model.audio_done + " / " + model.segments + " セグメント"
                    color: "#a0a0a0"; font.pixelSize: 11
                }

                MouseArea {
                    id: cardMa
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: page.openBook(model.id)
                }
            }
        }
    }
}

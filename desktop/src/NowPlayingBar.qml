import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtMultimedia 6.0

Control {
    id: bar
    property var player: null
    property var book: null
    property color accent: "#1db954"
    signal openPlayer()
    signal openStudio()

    function hue(id) {
        var s = String(id || ""), h = 0
        for (var i = 0; i < s.length; ++i) h = (h * 31 + s.charCodeAt(i)) % 360
        return h / 360.0
    }
    function fmtTime(ms) {
        var s = Math.max(0, Math.floor((ms || 0) / 1000))
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
        return h > 0 ? h + ":" + ("0" + m).slice(-2) + ":" + ("0" + s % 60).slice(-2)
                     : ("0" + m).slice(-2) + ":" + ("0" + s % 60).slice(-2)
    }

    implicitHeight: 92
    background: Rectangle {
        color: "#181818"
        Rectangle { width: parent.width; height: 1; color: "#2a2a2a" }
    }

    contentItem: RowLayout {
        spacing: 18

        // ---- left: mini cover & title ----
        RowLayout {
            Layout.preferredWidth: 270; spacing: 12
            Rectangle {
                width: 58; height: 58; radius: 8
                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.hsla(bar.hue(bar.book ? bar.book.id : ""), 0.42, 0.40) }
                    GradientStop { position: 1; color: Qt.hsla(bar.hue(bar.book ? bar.book.id : ""), 0.50, 0.16) }
                }
                Text { anchors.centerIn: parent; text: bar.book ? (bar.book.title || "?").charAt(0) : "—"; color: "#fff"; opacity: 0.8; font.pixelSize: 22; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: bar.openPlayer() }
            }
            ColumnLayout {
                spacing: 2; Layout.fillWidth: true
                Text {
                    text: bar.book ? (bar.book.title || "(無題)") : "再生なし"
                    color: "#eeeeee"; font.pixelSize: 14; font.bold: true
                    elide: Text.ElideRight; Layout.fillWidth: true
                }
                Text {
                    text: bar.book ? "AIAE Audiobook" : ""
                    color: "#888888"; font.pixelSize: 11
                    elide: Text.ElideRight; Layout.fillWidth: true
                }
            }
        }

        // ---- center: controls & seek ----
        ColumnLayout {
            Layout.fillWidth: true; spacing: 4
            Row {
                Layout.alignment: Qt.AlignHCenter; spacing: 20
                Button {
                    flat: true
                    text: "↺15"
                    onClicked: if (bar.player) bar.player.setPosition(Math.max(0, bar.player.position - 15000))
                }
                Button {
                    width: 46; height: 46
                    text: bar.player && bar.player.playbackState === MediaPlayer.PlayingState ? "⏸" : "▶"
                    onClicked: {
                        if (!bar.player) return
                        if (bar.player.playbackState === MediaPlayer.PlayingState) bar.player.pause()
                        else bar.player.play()
                    }
                }
                Button {
                    flat: true
                    text: "15↻"
                    onClicked: if (bar.player) bar.player.setPosition(Math.min(bar.player.duration || 0, bar.player.position + 15000))
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: bar.fmtTime(bar.player ? bar.player.position : 0); color: "#a0a0a0"; font.pixelSize: 11 }
                Slider {
                    id: seek
                    Layout.fillWidth: true
                    from: 0; to: Math.max(1, bar.player ? bar.player.duration : 1)
                    value: bar.player ? bar.player.position : 0
                    onMoved: if (bar.player) bar.player.setPosition(value)
                }
                Text { text: bar.fmtTime(bar.player ? bar.player.duration : 0); color: "#a0a0a0"; font.pixelSize: 11 }
            }
        }

        // ---- right: speed / volume / nav ----
        RowLayout {
            Layout.preferredWidth: 240; spacing: 10
            ComboBox {
                id: speedBox
                Layout.preferredWidth: 92
                model: ["0.8x", "1.0x", "1.25x", "1.5x", "2.0x"]
                currentIndex: 1
                onActivated: if (bar.player) bar.player.playbackRate = parseFloat(currentText)
            }
            Text { text: "🔊"; color: "#a0a0a0" }
            Slider {
                id: vol
                Layout.preferredWidth: 70
                from: 0; to: 1; value: 0.8
                onMoved: if (bar.player) bar.player.audioOutput.volume = value
            }
            Button {
                flat: true; text: "🎙"
                ToolTip.visible: pressed; ToolTip.text: "スタジオ"
                onClicked: bar.openStudio()
            }
        }
    }
}

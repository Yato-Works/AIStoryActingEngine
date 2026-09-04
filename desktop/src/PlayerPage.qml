pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtMultimedia 6.0

Page {
    id: page
    property var book: null
    property var player: null
    property var chapters: null
    property color accent: "#1db954"
    signal seekRequested(real seconds)

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

    padding: 32
    background: Rectangle { color: "#121212" }

    RowLayout {
        anchors.fill: parent; spacing: 36

        // ---- left: cover & info ----
        ColumnLayout {
            Layout.preferredWidth: 330; Layout.fillHeight: true; spacing: 14

            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 330; radius: 14
                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.42, 0.40) }
                    GradientStop { position: 1; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.50, 0.16) }
                }
                Text {
                    anchors.centerIn: parent
                    text: page.book ? (page.book.title || "?").charAt(0) : "?"
                    color: "#fff"; opacity: 0.8; font.pixelSize: 110; font.bold: true
                }
            }

            Text {
                text: page.book ? (page.book.title || "(無題)") : "本が選択されていません"
                color: "#eeeeee"; font.pixelSize: 24; font.bold: true
                wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            Text {
                text: page.book
                      ? page.book.audio_done + " / " + page.book.segments + " セグメント  •  総長 " + page.fmtTime((page.book.duration_seconds || 0) * 1000)
                      : ""
                color: "#a0a0a0"; font.pixelSize: 13; Layout.fillWidth: true
            }
            Text {
                text: page.book && page.book.audio
                      ? "音声: " + page.book.audio.kind + " — " + page.book.audio.path
                      : "音声ファイルなし(解析のみ完了)"
                color: "#777777"; font.pixelSize: 11
                elide: Text.ElideMiddle; Layout.fillWidth: true
            }
            Button {
                text: page.player && page.player.playbackState === MediaPlayer.PlayingState ? "⏸ 一時停止" : "▶ 最初から再生"
                onClicked: {
                    if (!page.player) return
                    if (page.player.playbackState === MediaPlayer.PlayingState) page.player.pause()
                    else { page.player.setPosition(0); page.player.play() }
                }
            }
            Item { Layout.fillHeight: true }
        }

        // ---- right: chapters ----
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 10
            Text { text: "章节"; color: "#eeeeee"; font.pixelSize: 18; font.bold: true }
            Text {
                visible: !page.chapters || page.chapters.count === 0
                text: "章情報なし"; color: "#666"; font.pixelSize: 13
            }
            ListView {
                id: chapterList
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; spacing: 4
                model: page.chapters
                ScrollBar.vertical: ScrollBar { }
                delegate: ItemDelegate {
                    id: ch
                    width: chapterList.width
                    height: 52
                    background: Rectangle {
                        radius: 8
                        color: ch.hovered ? "#2c2c2c" : "#1e1e1e"
                    }
                    contentItem: RowLayout {
                        spacing: 12
                        Rectangle {
                            Layout.preferredWidth: 34; Layout.preferredHeight: 34; radius: 17
                            color: "#333333"
                            Text { anchors.centerIn: parent; text: model.chapter; color: "#cccccc"; font.pixelSize: 13 }
                        }
                        Text {
                            text: model.title || ("第" + model.chapter + "章")
                            color: "#eeeeee"; font.pixelSize: 14
                            elide: Text.ElideRight; Layout.fillWidth: true
                        }
                        Text {
                            text: (model.offset_seconds !== null && model.offset_seconds !== undefined)
                                  ? page.fmtTime(model.offset_seconds * 1000) : "—"
                            color: "#a0a0a0"; font.pixelSize: 12
                        }
                    }
                    onClicked: {
                        if (model.offset_seconds !== null && model.offset_seconds !== undefined)
                            page.seekRequested(model.offset_seconds)
                    }
                }
            }
        }
    }
}

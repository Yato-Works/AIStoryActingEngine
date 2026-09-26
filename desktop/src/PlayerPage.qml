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
    background: Rectangle {
        color: "#0f0f13"
        // アンビエントグラデーション
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#181822" }
                GradientStop { position: 0.7; color: "#0f0f13" }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 40

        // ================= 左ペイン: カバーアート & 書籍情報 =================
        ColumnLayout {
            Layout.preferredWidth: 360
            Layout.fillHeight: true
            spacing: 16

            // カバーアート
            Rectangle {
                id: coverBox
                Layout.preferredWidth: 340
                Layout.preferredHeight: 340
                Layout.alignment: Qt.AlignHCenter
                radius: 18
                color: "#1c1c24"
                border.color: "#2e2e3e"
                border.width: 1

                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.45, 0.36) }
                    GradientStop { position: 1; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.52, 0.12) }
                }

                // 微妙なインナーハイライト
                Rectangle {
                    anchors.fill: parent
                    radius: 18
                    color: "transparent"
                    border.color: "#30ffffff"
                    border.width: 1
                }

                Text {
                    anchors.centerIn: parent
                    text: page.book ? (page.book.title || "?").charAt(0) : "📖"
                    color: "#ffffff"
                    opacity: 0.88
                    font.pixelSize: 118
                    font.bold: true
                }

                // 再生中アニメーションバッジ（左下）
                Rectangle {
                    visible: page.player && page.player.playbackState === MediaPlayer.PlayingState
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: 14
                    height: 28; width: rowLive.implicitWidth + 20
                    radius: 14
                    color: "#d9000000"
                    border.color: page.accent
                    border.width: 1

                    RowLayout {
                        id: rowLive
                        anchors.centerIn: parent
                        spacing: 6
                        Rectangle {
                            width: 7; height: 7; radius: 3.5; color: page.accent
                            SequentialAnimation on opacity {
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.3; duration: 500 }
                                NumberAnimation { to: 1.0; duration: 500 }
                            }
                        }
                        Text { text: "PLAYING"; color: "#ffffff"; font.pixelSize: 10; font.bold: true }
                    }
                }
            }

            // タイトル
            Text {
                text: page.book ? (page.book.title || "(無題)") : "本が選択されていません"
                color: "#ffffff"
                font.pixelSize: 24
                font.bold: true
                font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            // メタデータピルバッジ
            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Rectangle {
                    height: 24
                    width: txtSeg.implicitWidth + 16
                    radius: 12
                    color: "#1f2a22"
                    border.color: "#2a5436"
                    border.width: 1
                    Text {
                        id: txtSeg
                        anchors.centerIn: parent
                        text: (page.book ? (page.book.audio_done + "/" + page.book.segments + " セグメント") : "0 セグメント")
                        color: page.accent
                        font.pixelSize: 11
                        font.bold: true
                    }
                }

                Rectangle {
                    height: 24
                    width: txtDur.implicitWidth + 16
                    radius: 12
                    color: "#22222c"
                    border.color: "#353545"
                    border.width: 1
                    Text {
                        id: txtDur
                        anchors.centerIn: parent
                        text: "総長 " + (page.book ? page.fmtTime((page.book.duration_seconds || 0) * 1000) : "00:00")
                        color: "#cccccc"
                        font.pixelSize: 11
                    }
                }
            }

            Text {
                text: page.book && page.book.audio
                      ? "オーディオソース: " + page.book.audio.kind
                      : "音声ファイル未生成（解析のみ完了）"
                color: "#7e7e8c"
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            // メイン再生ボタントリガー
            Rectangle {
                Layout.fillWidth: true
                height: 48
                radius: 24
                color: btnPlayArea.containsMouse ? "#1ed760" : page.accent
                Behavior on color { ColorAnimation { duration: 150 } }

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 10
                    Text {
                        text: page.player && page.player.playbackState === MediaPlayer.PlayingState ? "⏸" : "▶"
                        color: "#000000"
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Text {
                        text: page.player && page.player.playbackState === MediaPlayer.PlayingState ? "オーディオを一時停止" : "オーディオブックを再生"
                        color: "#000000"
                        font.pixelSize: 14
                        font.bold: true
                    }
                }

                MouseArea {
                    id: btnPlayArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (!page.player) return
                        if (page.player.playbackState === MediaPlayer.PlayingState) page.player.pause()
                        else {
                            if (page.player.position === 0 && page.book && page.book.audio && page.book.audio.path) {
                                // play
                            }
                            page.player.play()
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        // ================= 右ペイン: チャプター一覧 =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "📑 チャプター一覧"
                    color: "#ffffff"
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: (page.chapters ? page.chapters.count : 0) + " チャプター"
                    color: "#8a8a9a"
                    font.pixelSize: 13
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 14
                color: "#15151c"
                border.color: "#252532"
                border.width: 1
                clip: true

                Text {
                    anchors.centerIn: parent
                    visible: !page.chapters || page.chapters.count === 0
                    text: "チャプター情報がありません\n本を選択するとここに章一覧が表示されます"
                    color: "#666677"
                    font.pixelSize: 14
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 1.4
                }

                ListView {
                    id: chapterList
                    anchors.fill: parent
                    anchors.margins: 10
                    clip: true
                    spacing: 6
                    model: page.chapters
                    ScrollBar.vertical: ScrollBar { active: true }

                    delegate: Rectangle {
                        id: chItem
                        width: chapterList.width
                        height: 56
                        radius: 10
                        color: chMa.containsMouse ? "#222230" : "#1a1a24"
                        border.color: chMa.containsMouse ? "#3a3a50" : "#242432"
                        border.width: 1

                        Behavior on color { ColorAnimation { duration: 120 } }
                        Behavior on border.color { ColorAnimation { duration: 120 } }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16
                            spacing: 14

                            // チャプター番号ピル
                            Rectangle {
                                Layout.preferredWidth: 32
                                Layout.preferredHeight: 32
                                radius: 8
                                color: "#282838"
                                Text {
                                    anchors.centerIn: parent
                                    text: model.chapter || (index + 1)
                                    color: "#a0a0b8"
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                            }

                            // チャプター名
                            Text {
                                text: model.title || ("第 " + (model.chapter || (index + 1)) + " 章")
                                color: "#eeeeee"
                                font.pixelSize: 14
                                font.bold: true
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            // 再生時間
                            Text {
                                text: (model.offset_seconds !== null && model.offset_seconds !== undefined)
                                      ? page.fmtTime(model.offset_seconds * 1000) : "—"
                                color: "#8a8a9a"
                                font.pixelSize: 12
                            }

                            // ジャンプボタンアイコン
                            Text {
                                text: "▶"
                                color: chMa.containsMouse ? page.accent : "#555566"
                                font.pixelSize: 12
                            }
                        }

                        MouseArea {
                            id: chMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (model.offset_seconds !== null && model.offset_seconds !== undefined)
                                    page.seekRequested(model.offset_seconds)
                            }
                        }
                    }
                }
            }
        }
    }
}

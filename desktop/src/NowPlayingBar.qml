pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtMultimedia 6.0

Control {
    id: bar
    property var player: null
    property var book: null
    property color accent: "#10b981"
    signal openPlayer()
    signal openStudio()
    signal openSettings()

    implicitHeight: 84

    function fmtTime(ms) {
        var s = Math.max(0, Math.floor((ms || 0) / 1000))
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
        return h > 0 ? h + ":" + ("0" + m).slice(-2) + ":" + ("0" + s % 60).slice(-2)
                     : ("0" + m).slice(-2) + ":" + ("0" + s % 60).slice(-2)
    }

    readonly property bool isPlaying: bar.player && bar.player.playbackState === MediaPlayer.PlayingState

    background: Rectangle {
        color: "#10121a"
        border.color: "#1c2130"
        border.width: 1

        // トップアクセントボーダー
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            height: 1
            color: "#1e2436"
        }
    }

    contentItem: RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        spacing: 16

        // ================= 左: ジャケット & タイトル & cava音波インジケーター =================
        RowLayout {
            Layout.preferredWidth: 260
            spacing: 12

            // ミニカバー
            Rectangle {
                Layout.preferredWidth: 48
                Layout.preferredHeight: 48
                radius: 8
                color: "#181c28"
                border.color: "#283044"
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: bar.book ? (bar.book.title || "?").charAt(0) : "📖"
                    color: "#ffffff"
                    font.pixelSize: 18
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bar.openPlayer()
                }
            }

            ColumnLayout {
                spacing: 3
                Layout.fillWidth: true

                RowLayout {
                    spacing: 8
                    Layout.fillWidth: true

                    Text {
                        text: bar.book ? (bar.book.title || "The Last Chronicle") : "作品が選択されていません"
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    // ====== cava風 ライブ音波インジケーター (音が鳴っているときだけ跳ねる) ======
                    Row {
                        spacing: 2
                        anchors.verticalCenter: parent.verticalCenter
                        visible: true

                        Repeater {
                            model: [0.9, 0.4, 1.0, 0.6]
                            delegate: Rectangle {
                                required property var modelData
                                required property int index
                                width: 3
                                radius: 1.5
                                color: bar.isPlaying ? bar.accent : "#3a4155"

                                // 再生中だけ動く cava アニメーション
                                height: bar.isPlaying ? (4 + Math.sin(cavaTimer.phase + index * 1.3) * 6 + 6) : 3

                                Behavior on height { NumberAnimation { duration: 80 } }
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    Timer {
                        id: cavaTimer
                        interval: 70
                        running: bar.isPlaying
                        repeat: true
                        property real phase: 0.0
                        onTriggered: phase = (phase + 0.5) % 6.28
                    }
                }

                Text {
                    text: bar.book ? ("Ch. " + (bar.book.current_chapter || "1") + " • AISAE AI Narration") : "待機中"
                    color: "#6b7288"
                    font.pixelSize: 11
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

        // ================= 中央: Spotify風 再生コントロール & シークバー =================
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            // 上段: ボタン群 (↺15, ⏮, ▶/⏸, ⏭, 15↻)
            Row {
                Layout.alignment: Qt.AlignHCenter
                spacing: 18

                // 15秒戻る
                Rectangle {
                    width: 28; height: 28; radius: 14
                    color: rwMa.containsMouse ? "#202535" : "transparent"
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "↺15"; color: "#9da3ba"; font.pixelSize: 11; font.bold: true }
                    MouseArea {
                        id: rwMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: if (bar.player) bar.player.setPosition(Math.max(0, bar.player.position - 15000))
                    }
                }

                // 前の章 / トラック
                Rectangle {
                    width: 28; height: 28; radius: 14
                    color: prevMa.containsMouse ? "#202535" : "transparent"
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "⏮"; color: "#c0c6dc"; font.pixelSize: 13 }
                    MouseArea {
                        id: prevMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: if (bar.player) bar.player.setPosition(0)
                    }
                }

                // メイン再生/一時停止ボタン (Spotify風の緑丸ボタン)
                Rectangle {
                    width: 36; height: 36; radius: 18
                    color: playMa.containsMouse ? "#1ed760" : bar.accent
                    Behavior on color { ColorAnimation { duration: 120 } }
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                        anchors.centerIn: parent
                        anchors.horizontalCenterOffset: bar.isPlaying ? 0 : 1
                        text: bar.isPlaying ? "⏸" : "▶"
                        color: "#000000"
                        font.pixelSize: 15
                        font.bold: true
                    }

                    MouseArea {
                        id: playMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (!bar.player) return
                            if (bar.isPlaying) bar.player.pause()
                            else bar.player.play()
                        }
                    }
                }

                // 次の章 / トラック
                Rectangle {
                    width: 28; height: 28; radius: 14
                    color: nextMa.containsMouse ? "#202535" : "transparent"
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "⏭"; color: "#c0c6dc"; font.pixelSize: 13 }
                    MouseArea {
                        id: nextMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: if (bar.player) bar.player.setPosition(bar.player.duration || 0)
                    }
                }

                // 15秒進む
                Rectangle {
                    width: 28; height: 28; radius: 14
                    color: ffMa.containsMouse ? "#202535" : "transparent"
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "15↻"; color: "#9da3ba"; font.pixelSize: 11; font.bold: true }
                    MouseArea {
                        id: ffMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: if (bar.player) bar.player.setPosition(Math.min(bar.player.duration || 0, bar.player.position + 15000))
                    }
                }
            }

            // 下段: Spotify スタイル シークバー (どこから流すかを自由にドラッグ・シーク可能)
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                    text: bar.fmtTime(bar.player ? bar.player.position : 0)
                    color: "#747a92"
                    font.pixelSize: 11
                    Layout.preferredWidth: 38
                    horizontalAlignment: Text.AlignRight
                }

                Slider {
                    id: seekSlider
                    Layout.fillWidth: true
                    from: 0
                    to: Math.max(1, bar.player ? bar.player.duration : 1)
                    value: bar.player ? bar.player.position : 0

                    // ユーザーがドラッグまたはクリックした瞬間に正確にシーク！
                    onMoved: {
                        if (bar.player) bar.player.setPosition(value)
                    }

                    background: Rectangle {
                        x: seekSlider.leftPadding
                        y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                        implicitWidth: 200
                        implicitHeight: 4
                        width: seekSlider.availableWidth
                        height: seekHoverArea.containsMouse ? 6 : 4
                        radius: 2
                        color: "#242a3a"
                        Behavior on height { NumberAnimation { duration: 100 } }

                        // 進行トラック (再生済み部分をエメラルドグリーンに)
                        Rectangle {
                            width: seekSlider.visualPosition * parent.width
                            height: parent.height
                            color: seekHoverArea.containsMouse ? "#1ed760" : bar.accent
                            radius: 2
                        }
                    }

                    handle: Rectangle {
                        x: seekSlider.leftPadding + seekSlider.visualPosition * (seekSlider.availableWidth - width)
                        y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                        implicitWidth: seekHoverArea.containsMouse ? 12 : 0
                        implicitHeight: seekHoverArea.containsMouse ? 12 : 0
                        radius: 6
                        color: "#ffffff"
                        Behavior on implicitWidth { NumberAnimation { duration: 100 } }
                        Behavior on implicitHeight { NumberAnimation { duration: 100 } }
                    }

                    MouseArea {
                        id: seekHoverArea
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton // スライダー本来のタッチ・クリックイベントを邪魔しない
                    }
                }

                Text {
                    text: bar.fmtTime(bar.player ? bar.player.duration : 0)
                    color: "#747a92"
                    font.pixelSize: 11
                    Layout.preferredWidth: 38
                }
            }
        }

        // ================= 右: 速度 & 音量 & 設定・スタジオリンク =================
        RowLayout {
            Layout.preferredWidth: 230
            spacing: 12

            // 再生速度
            ComboBox {
                id: speedBox
                Layout.preferredWidth: 74
                height: 28
                model: ["0.8x", "1.0x", "1.25x", "1.5x", "2.0x"]
                currentIndex: 1
                onActivated: if (bar.player) bar.player.playbackRate = parseFloat(currentText)
            }

            // 音量アイコン & スライダー
            Text { text: "🔊"; color: "#747a92"; font.pixelSize: 12 }

            Slider {
                id: volSlider
                Layout.preferredWidth: 70
                from: 0; to: 1; value: bar.player && bar.player.audioOutput ? bar.player.audioOutput.volume : 0.8
                onMoved: if (bar.player && bar.player.audioOutput) bar.player.audioOutput.volume = value
            }

            // 設定ボタン (Settings)
            Rectangle {
                width: 28; height: 28; radius: 14
                color: settingsBtnMa.containsMouse ? "#202535" : "transparent"
                Text { anchors.centerIn: parent; text: "⚙"; font.pixelSize: 13; color: "#a0a6bd" }
                ToolTip.visible: settingsBtnMa.containsMouse
                ToolTip.text: "設定 (TTS / Engine Config)"
                MouseArea {
                    id: settingsBtnMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bar.openSettings()
                }
            }

            // スタジオ・ログボタン
            Rectangle {
                width: 28; height: 28; radius: 14
                color: studioBtnMa.containsMouse ? "#202535" : "transparent"
                Text { anchors.centerIn: parent; text: "📊"; font.pixelSize: 13; color: "#a0a6bd" }
                ToolTip.visible: studioBtnMa.containsMouse
                ToolTip.text: "スタジオ / ログ進捗"
                MouseArea {
                    id: studioBtnMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bar.openStudio()
                }
            }
        }
    }
}

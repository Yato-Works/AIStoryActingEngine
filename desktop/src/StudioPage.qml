pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: page
    property var book: null
    property var events: null   // ListModel {ts,type,payload}

    function hue(id) {
        var s = String(id || ""), h = 0
        for (var i = 0; i < s.length; ++i) h = (h * 31 + s.charCodeAt(i)) % 360
        return h / 360.0
    }
    function evColor(t) {
        if (t === "AUDIO_GENERATED") return "#1db954"
        if (t === "SCENE_EVENT") return "#ffb703"
        if (t === "VOICE_STATE_CHANGED") return "#4cc2e0"
        if (t === "JOB_COMPLETED") return "#1db954"
        if (t === "JOB_FAILED") return "#ff5252"
        return "#8a8a9a"
    }

    padding: 28
    background: Rectangle {
        color: "#0f0f13"
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#161622" }
                GradientStop { position: 0.6; color: "#0f0f13" }
            }
        }
    }

    header: Control {
        padding: 28
        bottomPadding: 16
        background: Rectangle { color: "transparent" }
        contentItem: RowLayout {
            ColumnLayout {
                spacing: 4
                Text {
                    text: "📊 ログ・進捗スタジオ"
                    color: "#ffffff"
                    font.pixelSize: 28
                    font.bold: true
                    font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                }
                Text {
                    text: "音声生成パイプライン・音響イベント・Judge判定のリアルタイム監視"
                    color: "#8a8a9a"
                    font.pixelSize: 13
                }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                height: 36
                width: evRefRow.implicitWidth + 24
                radius: 18
                color: evRefMa.containsMouse ? "#28283a" : "#1a1a26"
                border.color: "#2a2a3e"
                border.width: 1

                RowLayout {
                    id: evRefRow
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "⟳"; color: "#a0a0b8"; font.pixelSize: 14 }
                    Text { text: "イベント最新化"; color: "#ffffff"; font.pixelSize: 12; font.bold: true }
                }

                MouseArea {
                    id: evRefMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bridge.listEvents(80)
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 32

        // ================= 左ペイン: 作品詳細ステータス =================
        ColumnLayout {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            spacing: 16

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 120
                radius: 16
                color: "#15151f"
                border.color: "#252535"
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 16

                    Rectangle {
                        width: 80; height: 80; radius: 12
                        gradient: Gradient {
                            GradientStop { position: 0; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.45, 0.38) }
                            GradientStop { position: 1; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.52, 0.14) }
                        }
                        Text {
                            anchors.centerIn: parent
                            text: page.book ? (page.book.title || "?").charAt(0) : "📖"
                            color: "#ffffff"
                            opacity: 0.9
                            font.pixelSize: 34
                            font.bold: true
                        }
                    }

                    ColumnLayout {
                        spacing: 4
                        Layout.fillWidth: true

                        Text {
                            text: page.book ? (page.book.title || "(無題)") : "作品が未選択です"
                            color: "#ffffff"
                            font.pixelSize: 16
                            font.bold: true
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            text: page.book ? ("ID: " + page.book.id) : "本棚から選択してください"
                            color: "#7e7e8e"
                            font.pixelSize: 11
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        Text {
                            text: page.book ? ("生成完了: " + page.book.audio_done + " / " + page.book.segments + " セグメント") : "—"
                            color: "#1db954"
                            font.pixelSize: 12
                            font.bold: true
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 16
                color: "#15151f"
                border.color: "#252535"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14

                    Text {
                        text: "ℹ️ パイプライン仕様"
                        color: "#ffffff"
                        font.pixelSize: 15
                        font.bold: true
                    }

                    Text {
                        text: "• Single Source of Truth (SSOT)\n  すべての演技パラメーター・音声メトリクス・Judgeレポートは SQLite に記録されます。\n\n• Irodori TTS × 感情絵文字\n  文脈に応じた演技ニュアンスを生成モデルが自動注入。\n\n• キャスティング継承\n  シリーズ・キャラクターごとにロックされた声質が引き継がれます。"
                        color: "#8a8a9e"
                        font.pixelSize: 12
                        lineHeight: 1.5
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    Item { Layout.fillHeight: true }
                }
            }
        }

        // ================= 右ペイン: イベントログ一覧 =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 16
                color: "#15151f"
                border.color: "#252535"
                border.width: 1
                clip: true

                ListView {
                    id: evList
                    anchors.fill: parent
                    anchors.margins: 12
                    clip: true
                    spacing: 6
                    model: page.events
                    ScrollBar.vertical: ScrollBar { active: true }

                    delegate: Rectangle {
                        width: evList.width
                        height: 48
                        radius: 8
                        color: "#1a1a26"
                        border.color: "#222232"
                        border.width: 1

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: page.evColor(model.type)
                                Layout.alignment: Qt.AlignVCenter
                            }

                            Text {
                                text: model.type
                                color: page.evColor(model.type)
                                font.pixelSize: 12
                                font.bold: true
                                Layout.preferredWidth: 160
                                elide: Text.ElideRight
                            }

                            Text {
                                text: model.payload || ""
                                color: "#b0b0c2"
                                font.pixelSize: 11
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }

                            Text {
                                text: String(model.ts || "").replace("T", " ").slice(5, 19)
                                color: "#666677"
                                font.pixelSize: 11
                            }
                        }
                    }
                }
            }
        }
    }
}

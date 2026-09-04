pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: page
    property var book: null
    property var castings: null          // ListModel { character_id, name, gender, age, role, personality, voice_id, voice_internal_id, is_locked, notes }
    property var voiceProfiles: null     // ListModel { voice_id, label, gender, ... }
    property string seriesId: ""
    property color accent: "#1db954"

    signal assignRequested(string bookId, string characterId, string voiceId, string voiceInternalId, bool isLocked)
    signal previewRequested(string text, string voiceId)
    signal refreshRequested(string bookId)

    background: Rectangle { color: "#121212" }

    header: Control {
        padding: 24
        contentItem: RowLayout {
            ColumnLayout {
                spacing: 4
                Text {
                    text: "🎭 キャスティングボード (登場人物の配役設定)"
                    color: "#eeeeee"; font.pixelSize: 24; font.bold: true
                }
                Text {
                    text: page.book ? "対象書籍: " + (page.book.title || page.book.id) : "本が選択されていません"
                    color: "#a0a0a0"; font.pixelSize: 13
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                text: "⟳ 配役を更新"
                flat: true
                onClicked: {
                    if (page.book) page.refreshRequested(page.book.id)
                }
            }
        }
    }

    Item {
        anchors.fill: parent
        anchors.margins: 24
        anchors.topMargin: 0

        Text {
            anchors.centerIn: parent
            visible: !page.book || !page.castings || page.castings.count === 0
            text: !page.book
                  ? "ライブラリから本を選択してください\n解析済みの登場人物がここに表示されます"
                  : "登場人物がまだ解析されていないか、解析中です…"
            color: "#666666"; font.pixelSize: 15
            horizontalAlignment: Text.AlignHCenter
        }

        ListView {
            id: castingList
            anchors.fill: parent
            visible: page.castings && page.castings.count > 0
            clip: true
            spacing: 14
            model: page.castings
            ScrollBar.vertical: ScrollBar { }

            delegate: Rectangle {
                id: charCard
                required property var model   // ListView delegate: 各行のモデルデータが注入される
                property var cast: model   // ComboBox の model プロパティによるスコープ汚染を避ける安定参照
                width: castingList.width
                height: cardCol.implicitHeight + 28
                radius: 12
                color: "#1e1e1e"

                ColumnLayout {
                    id: cardCol
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    // キャラクターヘッダー
                    RowLayout {
                        spacing: 12; Layout.fillWidth: true

                        Rectangle {
                            Layout.preferredWidth: 38; Layout.preferredHeight: 38; radius: 19
                            color: charCard.cast.gender === "female" ? "#e91e63" : "#2196f3"
                            Text {
                                anchors.centerIn: parent
                                text: (charCard.cast.name || "?").charAt(0)
                                color: "#ffffff"; font.pixelSize: 18; font.bold: true
                            }
                        }

                        ColumnLayout {
                            spacing: 2; Layout.fillWidth: true
                            RowLayout {
                                spacing: 8
                                Text {
                                    text: charCard.cast.name || charCard.cast.character_id
                                    color: "#ffffff"; font.pixelSize: 16; font.bold: true
                                }
                                Text {
                                    text: "(" + (charCard.cast.gender || "unknown") + ", " + (charCard.cast.age || "adult") + ")"
                                    color: "#888888"; font.pixelSize: 12
                                }
                                Rectangle {
                                    visible: Boolean(charCard.cast.role)
                                    radius: 4; color: "#333333"
                                    implicitWidth: roleTxt.implicitWidth + 8
                                    implicitHeight: roleTxt.implicitHeight + 4
                                    Text {
                                        id: roleTxt
                                        anchors.centerIn: parent
                                        text: charCard.cast.role || ""
                                        color: "#cccccc"; font.pixelSize: 11
                                    }
                                }
                            }
                            Text {
                                text: (charCard.cast.personality && charCard.cast.personality.length > 0)
                                      ? "性格: " + charCard.cast.personality.join(", ") : ""
                                color: "#a0a0a0"; font.pixelSize: 11
                            }
                        }

                        CheckBox {
                            id: lockCheck
                            text: "🔒 配役を固定"
                            checked: Boolean(charCard.cast.is_locked)
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#2c2c2c" }

                    // ボイス割当選択列
                    RowLayout {
                        spacing: 20; Layout.fillWidth: true

                        // 表の声 (External)
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            Text { text: "🎙 表の声 (台詞・通常発話)"; color: "#a0a0a0"; font.pixelSize: 12 }
                            ComboBox {
                                id: extCombo
                                Layout.fillWidth: true
                                textRole: "label"
                                valueRole: "voice_id"
                                model: page.voiceProfiles

                                Component.onCompleted: {
                                    for (var i = 0; i < count; ++i) {
                                        if (valueAt(i) === charCard.cast.voice_id) {
                                            currentIndex = i; break
                                        }
                                    }
                                }
                            }
                        }

                        // 内面の声 (Internal)
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            Text { text: "🧠 内なる声 (モノローグ・心の声)"; color: "#a0a0a0"; font.pixelSize: 12 }
                            ComboBox {
                                id: intCombo
                                Layout.fillWidth: true
                                textRole: "label"
                                valueRole: "voice_id"
                                model: page.voiceProfiles

                                Component.onCompleted: {
                                    for (var i = 0; i < count; ++i) {
                                        if (valueAt(i) === charCard.cast.voice_internal_id) {
                                            currentIndex = i; break
                                        }
                                    }
                                }
                            }
                        }

                        // アクションボタン
                        ColumnLayout {
                            spacing: 4
                            Item { Layout.fillHeight: true }
                            RowLayout {
                                spacing: 8
                                Button {
                                    text: "▶ 試聴"
                                    flat: true
                                    onClicked: {
                                        var vid = extCombo.currentValue || charCard.cast.voice_id
                                        page.previewRequested("私、" + (charCard.cast.name || "キャラクター") + "の声です。", vid)
                                    }
                                }
                                Button {
                                    text: "適用"
                                    highlighted: true
                                    onClicked: {
                                        var vExt = extCombo.currentValue || charCard.cast.voice_id
                                        var vInt = intCombo.currentValue || charCard.cast.voice_internal_id || (vExt + "i")
                                        page.assignRequested(
                                            page.book.id,
                                            charCard.cast.character_id,
                                            vExt,
                                            vInt,
                                            lockCheck.checked
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

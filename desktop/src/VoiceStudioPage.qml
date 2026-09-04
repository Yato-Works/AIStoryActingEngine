pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: page
    property var voiceProfiles: null  // ListModel { voice_id, label, gender, age, base_pitch, base_pace, base_energy, tags, source }
    property color accent: "#1db954"

    signal previewRequested(string text, string voiceId, string style, real pitch, real pace, string provider)
    signal saveRequested(var profile)
    signal deleteRequested(string voiceId)
    signal refreshRequested()

    background: Rectangle { color: "#121212" }

    header: Control {
        padding: 24
        contentItem: RowLayout {
            Text {
                text: "🎙 ボイススタジオ (簡単キャラ声作成)"
                color: "#eeeeee"; font.pixelSize: 24; font.bold: true
            }
            Item { Layout.fillWidth: true }
            Button {
                text: "⟳ ボイス一覧更新"
                flat: true
                onClicked: page.refreshRequested()
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 24
        anchors.topMargin: 0
        spacing: 28

        // ================= 左ペイン: ボイス作成エディタ =================
        ScrollView {
            Layout.preferredWidth: 460
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: parent.width - 16
                spacing: 16

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: editorCol.implicitHeight + 32
                    radius: 12
                    color: "#1e1e1e"

                    ColumnLayout {
                        id: editorCol
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 14

                        Text {
                            text: "新規ボイス作成"
                            color: "#ffffff"; font.pixelSize: 17; font.bold: true
                        }

                        // ボイス名
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            Text { text: "ボイス名（例: 杉田智和風_渋みモノローグ）"; color: "#a0a0a0"; font.pixelSize: 12 }
                            TextField {
                                id: nameField
                                Layout.fillWidth: true
                                placeholderText: "杉田智和風_前世の男"
                                text: "杉田智和風_前世の男"
                                color: "#eeeeee"
                                background: Rectangle { radius: 6; color: "#2a2a2a" }
                            }
                        }

                        // 性別 & 年齢
                        RowLayout {
                            spacing: 16; Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 4; Layout.fillWidth: true
                                Text { text: "性別"; color: "#a0a0a0"; font.pixelSize: 12 }
                                ComboBox {
                                    id: genderCombo
                                    Layout.fillWidth: true
                                    model: ["male", "female", "unknown"]
                                    currentIndex: 0
                                }
                            }
                            ColumnLayout {
                                spacing: 4; Layout.fillWidth: true
                                Text { text: "年代"; color: "#a0a0a0"; font.pixelSize: 12 }
                                ComboBox {
                                    id: ageCombo
                                    Layout.fillWidth: true
                                    model: ["adult", "young", "child", "elder"]
                                    currentIndex: 0
                                }
                            }
                        }

                        // モデル選択
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            Text { text: "ベースモデル (SBV2)"; color: "#a0a0a0"; font.pixelSize: 12 }
                            ComboBox {
                                id: modelCombo
                                Layout.fillWidth: true
                                model: ["jvnv-M1-jp (男性標準)", "jvnv-F1-jp (女性・少年標準)"]
                                currentIndex: genderCombo.currentIndex === 1 ? 1 : 0
                            }
                        }

                        // ピッチスライダー
                        ColumnLayout {
                            spacing: 2; Layout.fillWidth: true
                            RowLayout {
                                Text { text: "声の高さ (Pitch)"; color: "#a0a0a0"; font.pixelSize: 12 }
                                Item { Layout.fillWidth: true }
                                Text { text: (pitchSlider.value >= 0 ? "+" : "") + pitchSlider.value.toFixed(2); color: page.accent; font.pixelSize: 12 }
                            }
                            Slider {
                                id: pitchSlider
                                Layout.fillWidth: true
                                from: -0.40; to: 0.40; value: -0.15; stepSize: 0.01
                            }
                        }

                        // 速度スライダー
                        ColumnLayout {
                            spacing: 2; Layout.fillWidth: true
                            RowLayout {
                                Text { text: "話す速度 (Pace)"; color: "#a0a0a0"; font.pixelSize: 12 }
                                Item { Layout.fillWidth: true }
                                Text { text: paceSlider.value.toFixed(2) + "x"; color: page.accent; font.pixelSize: 12 }
                            }
                            Slider {
                                id: paceSlider
                                Layout.fillWidth: true
                                from: 0.70; to: 1.30; value: 0.90; stepSize: 0.02
                            }
                        }

                        // エナジースライダー
                        ColumnLayout {
                            spacing: 2; Layout.fillWidth: true
                            RowLayout {
                                Text { text: "太さ / 声の強さ (Energy)"; color: "#a0a0a0"; font.pixelSize: 12 }
                                Item { Layout.fillWidth: true }
                                Text { text: energySlider.value.toFixed(2); color: page.accent; font.pixelSize: 12 }
                            }
                            Slider {
                                id: energySlider
                                Layout.fillWidth: true
                                from: 0.50; to: 1.50; value: 0.95; stepSize: 0.05
                            }
                        }

                        // タグ
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            Text { text: "声質タグ (カンマ区切り: 例 杉田智和風, 低音, 渋い)"; color: "#a0a0a0"; font.pixelSize: 12 }
                            TextField {
                                id: tagsField
                                Layout.fillWidth: true
                                text: "杉田智和風, 低音, 渋い, 前世の男"
                                color: "#eeeeee"
                                background: Rectangle { radius: 6; color: "#2a2a2a" }
                            }
                        }

                        // プレビュー文章
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            Text { text: "試し聞き文章"; color: "#a0a0a0"; font.pixelSize: 12 }
                            TextField {
                                id: previewTextField
                                Layout.fillWidth: true
                                text: "……トラックに撥ねられて死んだはずだが、どうやら異世界に転生したらしい。"
                                color: "#eeeeee"
                                background: Rectangle { radius: 6; color: "#2a2a2a" }
                            }
                        }

                        // アクションボタン群
                        RowLayout {
                            spacing: 12; Layout.fillWidth: true
                            Button {
                                text: "▶ 声を聴いてみる"
                                Layout.fillWidth: true
                                onClicked: {
                                    var voiceId = genderCombo.currentText === "female" ? "voice_02" : "voice_01"
                                    page.previewRequested(
                                        previewTextField.text,
                                        voiceId,
                                        "Neutral",
                                        pitchSlider.value,
                                        paceSlider.value,
                                        "edge"
                                    )
                                }
                            }
                            Button {
                                text: "💾 名前を付けて保存"
                                Layout.fillWidth: true
                                highlighted: true
                                onClicked: {
                                    var vid = "voice_user_" + Date.now().toString(36)
                                    var tags = tagsField.text.split(",").map(function(s) { return s.trim() }).filter(function(s) { return s.length > 0 })
                                    var selectedModel = modelCombo.currentIndex === 1 ? "jvnv-F1-jp" : "jvnv-M1-jp"
                                    var ttsVoice = genderCombo.currentText === "female" ? "ja-JP-NanamiNeural" : "ja-JP-KeitaNeural"
                                    var profile = {
                                        "voice_id": vid,
                                        "label": nameField.text || "マイボイス",
                                        "gender": genderCombo.currentText,
                                        "age": ageCombo.currentText,
                                        "base_pitch": pitchSlider.value,
                                        "base_pace": paceSlider.value,
                                        "base_energy": energySlider.value,
                                        "sbv2_model_name": selectedModel,
                                        "sbv2_style": "Neutral",
                                        "tts_voice": ttsVoice,
                                        "source": "user",
                                        "tags": tags,
                                        "description": nameField.text + " (カスタム作成)"
                                    }
                                    page.saveRequested(profile)
                                }
                            }
                        }
                    }
                }
            }
        }

        // ================= 右ペイン: 登録済みボイスライブラリ =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            Text {
                text: "📚 ボイスライブラリ (" + (page.voiceProfiles ? page.voiceProfiles.count : 0) + " 種)"
                color: "#eeeeee"; font.pixelSize: 18; font.bold: true
            }

            ListView {
                id: voiceList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: page.voiceProfiles
                ScrollBar.vertical: ScrollBar { }

                delegate: Rectangle {
                    id: voiceCard
                    required property var model   // ListView delegate: 各行のモデルデータが注入される
                    property var cast: model   // delegate モデルの安定参照
                    width: voiceList.width
                    height: 84
                    radius: 10
                    color: "#1e1e1e"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 14

                        // アイコンバッジ
                        Rectangle {
                            Layout.preferredWidth: 46; Layout.preferredHeight: 46; radius: 23
                            color: voiceCard.cast.source === "user" ? "#9c27b0" : "#2a5298"
                            Text {
                                anchors.centerIn: parent
                                text: voiceCard.cast.gender === "female" ? "♀" : "♂"
                                color: "#ffffff"; font.pixelSize: 20; font.bold: true
                            }
                        }

                        // ボイス情報
                        ColumnLayout {
                            spacing: 3; Layout.fillWidth: true
                            RowLayout {
                                spacing: 8
                                Text {
                                    text: voiceCard.cast.label || voiceCard.cast.voice_id
                                    color: "#ffffff"; font.pixelSize: 15; font.bold: true
                                }
                                Rectangle {
                                    radius: 4
                                    color: voiceCard.cast.source === "user" ? "#4a148c" : "#1a365d"
                                    implicitWidth: sourceTxt.implicitWidth + 8
                                    implicitHeight: sourceTxt.implicitHeight + 4
                                    Text {
                                        id: sourceTxt
                                        anchors.centerIn: parent
                                        text: voiceCard.cast.source === "user" ? "カスタム" : "公式"
                                        color: "#cccccc"; font.pixelSize: 10
                                    }
                                }
                            }
                            Text {
                                text: "pitch: " + (voiceCard.cast.base_pitch >= 0 ? "+" : "") + (voiceCard.cast.base_pitch || 0).toFixed(2)
                                      + "  |  speed: " + (voiceCard.cast.base_pace || 1.0).toFixed(2) + "x"
                                      + "  |  年代: " + (voiceCard.cast.age || "adult")
                                color: "#888888"; font.pixelSize: 11
                            }
                            Text {
                                text: (voiceCard.cast.tags && voiceCard.cast.tags.length > 0) ? "タグ: " + voiceCard.cast.tags.join(", ") : ""
                                color: page.accent; font.pixelSize: 11; elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }

                        // アクションボタン
                        Button {
                            text: "▶ 試聴"
                            flat: true
                            onClicked: {
                                page.previewRequested(
                                    "私の声はどうですか？",
                                    voiceCard.cast.voice_id,
                                    voiceCard.cast.sbv2_style || "Neutral",
                                    voiceCard.cast.base_pitch || 0.0,
                                    voiceCard.cast.base_pace || 1.0,
                                    "edge"
                                )
                            }
                        }
                        Button {
                            visible: voiceCard.cast.source === "user"
                            text: "🗑"
                            flat: true
                            onClicked: page.deleteRequested(voiceCard.cast.voice_id)
                        }
                    }
                }
            }
        }
    }
}

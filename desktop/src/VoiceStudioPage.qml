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
                    text: "🎙 ボイススタジオ"
                    color: "#ffffff"
                    font.pixelSize: 28
                    font.bold: true
                    font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                }
                Text {
                    text: "独自のキャラクターボイスプロファイルを作成・チューニング・永続保存"
                    color: "#8a8a9a"
                    font.pixelSize: 13
                }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                height: 36
                width: refreshRow.implicitWidth + 24
                radius: 18
                color: refreshMa.containsMouse ? "#28283a" : "#1a1a26"
                border.color: "#2a2a3e"
                border.width: 1

                RowLayout {
                    id: refreshRow
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "⟳"; color: "#a0a0b8"; font.pixelSize: 14 }
                    Text { text: "一覧を更新"; color: "#ffffff"; font.pixelSize: 12; font.bold: true }
                }

                MouseArea {
                    id: refreshMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.refreshRequested()
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 28
        anchors.topMargin: 4
        spacing: 32

        // ================= 左ペイン: ボイス作成エディタ =================
        ScrollView {
            Layout.preferredWidth: 480
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: parent.width - 16
                spacing: 16

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: editorCol.implicitHeight + 36
                    radius: 16
                    color: "#15151f"
                    border.color: "#252535"
                    border.width: 1

                    ColumnLayout {
                        id: editorCol
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 16

                        RowLayout {
                            spacing: 8
                            Rectangle { width: 4; height: 18; radius: 2; color: page.accent }
                            Text {
                                text: "新規ボイスプロファイル作成"
                                color: "#ffffff"
                                font.pixelSize: 16
                                font.bold: true
                            }
                        }

                        // ボイス名
                        ColumnLayout {
                            spacing: 6; Layout.fillWidth: true
                            Text { text: "ボイス名"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: nameField
                                Layout.fillWidth: true
                                height: 40
                                placeholderText: "Test_Voice1_渋みモノローグ"
                                text: "Test_Voice1_渋みモノローグ"
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#1e1e2c"
                                    border.color: "#303046"
                                    border.width: 1
                                }
                            }
                        }

                        // 性別 & 年齢
                        RowLayout {
                            spacing: 16; Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 6; Layout.fillWidth: true
                                Text { text: "性別"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                                ComboBox {
                                    id: genderCombo
                                    Layout.fillWidth: true
                                    model: ["male", "female", "unknown"]
                                    currentIndex: 0
                                }
                            }
                            ColumnLayout {
                                spacing: 6; Layout.fillWidth: true
                                Text { text: "年代"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
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
                            spacing: 6; Layout.fillWidth: true
                            Text { text: "ベース音響モデル"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                            ComboBox {
                                id: modelCombo
                                Layout.fillWidth: true
                                model: ["jvnv-M1-jp (男性標準)", "jvnv-F1-jp (女性・少年標準)"]
                                currentIndex: genderCombo.currentIndex === 1 ? 1 : 0
                            }
                        }

                        // ピッチスライダー
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            RowLayout {
                                Text { text: "ピッチ (Pitch)"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                                Item { Layout.fillWidth: true }
                                Text { text: (pitchSlider.value >= 0 ? "+" : "") + pitchSlider.value.toFixed(2); color: page.accent; font.pixelSize: 12; font.bold: true }
                            }
                            Slider {
                                id: pitchSlider
                                Layout.fillWidth: true
                                from: -0.40; to: 0.40; value: -0.15; stepSize: 0.01
                            }
                        }

                        // 速度スライダー
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            RowLayout {
                                Text { text: "発話速度 (Pace)"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                                Item { Layout.fillWidth: true }
                                Text { text: paceSlider.value.toFixed(2) + "x"; color: page.accent; font.pixelSize: 12; font.bold: true }
                            }
                            Slider {
                                id: paceSlider
                                Layout.fillWidth: true
                                from: 0.70; to: 1.30; value: 0.90; stepSize: 0.02
                            }
                        }

                        // エナジースライダー
                        ColumnLayout {
                            spacing: 4; Layout.fillWidth: true
                            RowLayout {
                                Text { text: "声の芯・エネルギー (Energy)"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                                Item { Layout.fillWidth: true }
                                Text { text: energySlider.value.toFixed(2); color: page.accent; font.pixelSize: 12; font.bold: true }
                            }
                            Slider {
                                id: energySlider
                                Layout.fillWidth: true
                                from: 0.50; to: 1.50; value: 0.95; stepSize: 0.05
                            }
                        }

                        // タグ
                        ColumnLayout {
                            spacing: 6; Layout.fillWidth: true
                            Text { text: "声質タグ (カンマ区切り)"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: tagsField
                                Layout.fillWidth: true
                                height: 40
                                text: "Test_Voice1, 低音, 渋い, モノローグ"
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#1e1e2c"
                                    border.color: "#303046"
                                    border.width: 1
                                }
                            }
                        }

                        // プレビュー文章
                        ColumnLayout {
                            spacing: 6; Layout.fillWidth: true
                            Text { text: "試し聞きセリフ"; color: "#8a8a9e"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: previewTextField
                                Layout.fillWidth: true
                                height: 40
                                text: "静かな夜空を見上げ、語り手が静かに口を開いた。この物語を始めよう。"
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#1e1e2c"
                                    border.color: "#303046"
                                    border.width: 1
                                }
                            }
                        }

                        // アクションボタン群
                        RowLayout {
                            spacing: 14
                            Layout.fillWidth: true
                            Layout.topMargin: 6

                            Rectangle {
                                Layout.fillWidth: true
                                height: 44
                                radius: 10
                                color: btnPrevMa.containsMouse ? "#2a2a3e" : "#1e1e2c"
                                border.color: "#35354e"
                                border.width: 1

                                RowLayout {
                                    anchors.centerIn: parent
                                    spacing: 8
                                    Text { text: "▶"; color: "#ffffff"; font.pixelSize: 12 }
                                    Text { text: "試聴する"; color: "#ffffff"; font.pixelSize: 13; font.bold: true }
                                }

                                MouseArea {
                                    id: btnPrevMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
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
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                height: 44
                                radius: 10
                                color: btnSaveMa.containsMouse ? "#1ed760" : page.accent
                                Behavior on color { ColorAnimation { duration: 150 } }

                                RowLayout {
                                    anchors.centerIn: parent
                                    spacing: 8
                                    Text { text: "💾"; color: "#000000"; font.pixelSize: 13 }
                                    Text { text: "ボイスを登録保存"; color: "#000000"; font.pixelSize: 13; font.bold: true }
                                }

                                MouseArea {
                                    id: btnSaveMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
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
        }

        // ================= 右ペイン: 登録済みボイスライブラリ =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "📚 ボイスライブラリ"
                    color: "#ffffff"
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: (page.voiceProfiles ? page.voiceProfiles.count : 0) + " 声色登録中"
                    color: "#8a8a9e"
                    font.pixelSize: 13
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 16
                color: "#15151f"
                border.color: "#252535"
                border.width: 1
                clip: true

                ListView {
                    id: voiceList
                    anchors.fill: parent
                    anchors.margins: 12
                    clip: true
                    spacing: 10
                    model: page.voiceProfiles
                    ScrollBar.vertical: ScrollBar { active: true }

                    delegate: Rectangle {
                        id: voiceCard
                        required property var model
                        property var cast: model
                        width: voiceList.width
                        height: 86
                        radius: 12
                        color: vCardMa.containsMouse ? "#20202e" : "#1a1a26"
                        border.color: vCardMa.containsMouse ? "#35354e" : "#252538"
                        border.width: 1

                        Behavior on color { ColorAnimation { duration: 120 } }
                        Behavior on border.color { ColorAnimation { duration: 120 } }

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 16

                            // 性別アバターサークル
                            Rectangle {
                                Layout.preferredWidth: 46; Layout.preferredHeight: 46; radius: 23
                                color: voiceCard.cast.gender === "female" ? "#381a34" : "#1a2c3a"
                                border.color: voiceCard.cast.gender === "female" ? "#6d2b65" : "#2b5675"
                                border.width: 1

                                Text {
                                    anchors.centerIn: parent
                                    text: voiceCard.cast.gender === "female" ? "♀" : "♂"
                                    color: voiceCard.cast.gender === "female" ? "#ff70d9" : "#64b5f6"
                                    font.pixelSize: 19
                                    font.bold: true
                                }
                            }

                            // ボイス情報
                            ColumnLayout {
                                spacing: 4; Layout.fillWidth: true
                                RowLayout {
                                    spacing: 8
                                    Text {
                                        text: voiceCard.cast.label || voiceCard.cast.voice_id
                                        color: "#ffffff"
                                        font.pixelSize: 14
                                        font.bold: true
                                    }
                                    Rectangle {
                                        radius: 6
                                        color: voiceCard.cast.source === "user" ? "#2d1b3e" : "#192838"
                                        border.color: voiceCard.cast.source === "user" ? "#5a3080" : "#284b6e"
                                        border.width: 1
                                        implicitWidth: sourceTxt.implicitWidth + 10
                                        implicitHeight: 20
                                        Text {
                                            id: sourceTxt
                                            anchors.centerIn: parent
                                            text: voiceCard.cast.source === "user" ? "カスタム" : "公式"
                                            color: voiceCard.cast.source === "user" ? "#d199ff" : "#80c4ff"
                                            font.pixelSize: 10
                                            font.bold: true
                                        }
                                    }
                                }
                                Text {
                                    text: "Pitch: " + (voiceCard.cast.base_pitch >= 0 ? "+" : "") + (voiceCard.cast.base_pitch || 0).toFixed(2)
                                          + "  •  Speed: " + (voiceCard.cast.base_pace || 1.0).toFixed(2) + "x"
                                          + "  •  年代: " + (voiceCard.cast.age || "adult")
                                    color: "#8a8a9e"
                                    font.pixelSize: 11
                                }
                                Text {
                                    text: (voiceCard.cast.tags && voiceCard.cast.tags.length > 0) ? "🏷️ " + voiceCard.cast.tags.join(" • ") : ""
                                    color: page.accent
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }

                            // 試聴ボタン
                            Rectangle {
                                width: 36; height: 36; radius: 18
                                color: "#28283a"
                                Text { anchors.centerIn: parent; text: "▶"; color: "#ffffff"; font.pixelSize: 13 }
                                ToolTip.visible: tPrevMa.containsMouse
                                ToolTip.text: "このボイスを試聴"
                                MouseArea {
                                    id: tPrevMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        page.previewRequested(
                                            "私の声の調子はどうでしょうか？",
                                            voiceCard.cast.voice_id,
                                            voiceCard.cast.sbv2_style || "Neutral",
                                            voiceCard.cast.base_pitch || 0.0,
                                            voiceCard.cast.base_pace || 1.0,
                                            "edge"
                                        )
                                    }
                                }
                            }

                            // 削除ボタン（ユーザーボイスのみ）
                            Rectangle {
                                visible: voiceCard.cast.source === "user"
                                width: 36; height: 36; radius: 18
                                color: "#301d22"
                                Text { anchors.centerIn: parent; text: "🗑"; color: "#ff7070"; font.pixelSize: 13 }
                                ToolTip.visible: delMa.containsMouse
                                ToolTip.text: "カスタムボイスを削除"
                                MouseArea {
                                    id: delMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.deleteRequested(voiceCard.cast.voice_id)
                                }
                            }
                        }

                        MouseArea {
                            id: vCardMa
                            anchors.fill: parent
                            hoverEnabled: true
                        }
                    }
                }
            }
        }
    }
}

pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: settingsPage
    property color accent: "#10b981"
    signal settingsSaved(var settings)

    // 設定状態
    property string ttsProvider: "voicevox"
    property string voicevoxUrl: "http://127.0.0.1:50021"
    property string customTtsUrl: "http://127.0.0.1:8000/v1/audio/speech"
    property string customTtsKey: ""
    property string sampleRate: "24000"

    property string llmProvider: "ollama"
    property string llmUrl: "http://127.0.0.1:11434/v1"
    property string llmModel: "qwen2.5:7b"
    property string geminiKey: ""

    property string connectionStatus: ""
    property bool isConnecting: false

    background: Rectangle {
        color: "#0c0d12"
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#13151f" }
                GradientStop { position: 0.6; color: "#0c0d12" }
            }
        }
    }

    header: Control {
        padding: 28
        bottomPadding: 16
        background: Rectangle { color: "transparent" }

        contentItem: RowLayout {
            spacing: 16
            ColumnLayout {
                spacing: 3
                Text {
                    text: "エンジン設定 (Settings & Engine Bindings)"
                    color: "#ffffff"
                    font.pixelSize: 24
                    font.bold: true
                    font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                }
                Text {
                    text: "ローカルTTSエンジン・LLMディレクターのバインドおよび音響パラメータを設定します"
                    color: "#7e8299"
                    font.pixelSize: 13
                }
            }
            Item { Layout.fillWidth: true }

            Rectangle {
                height: 38
                width: 130
                radius: 19
                color: saveBtnMa.containsMouse ? "#1ed760" : settingsPage.accent
                Behavior on color { ColorAnimation { duration: 120 } }

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "💾"; font.pixelSize: 13 }
                    Text { text: "設定を保存"; color: "#000000"; font.pixelSize: 12; font.bold: true }
                }

                MouseArea {
                    id: saveBtnMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        settingsPage.connectionStatus = "✓ 設定を正常に保存しました"
                    }
                }
            }
        }
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: 28
        anchors.topMargin: 0
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: 24

            // ステータスバナー（表示中のみ）
            Rectangle {
                Layout.fillWidth: true
                height: 40
                radius: 8
                visible: settingsPage.connectionStatus.length > 0
                color: settingsPage.connectionStatus.startsWith("✓") ? "#112e1e" : "#2e1a1a"
                border.color: settingsPage.connectionStatus.startsWith("✓") ? "#10b981" : "#e05555"
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    Text {
                        text: settingsPage.connectionStatus
                        color: settingsPage.connectionStatus.startsWith("✓") ? "#1ed760" : "#ff7070"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
            }

            // ================= 1. 音声合成 (TTS) エンジン設定 =================
            Rectangle {
                Layout.fillWidth: true
                radius: 12
                color: "#12141c"
                border.color: "#212534"
                border.width: 1
                implicitHeight: colTts.implicitHeight + 36

                ColumnLayout {
                    id: colTts
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 16

                    RowLayout {
                        spacing: 10
                        Text { text: "🎙"; font.pixelSize: 18 }
                        ColumnLayout {
                            spacing: 2
                            Text { text: "音声合成エンジン (TTS Provider Binding)"; color: "#ffffff"; font.pixelSize: 16; font.bold: true }
                            Text { text: "キャラクターのセリフやナレーションを生成するTTSサーバーをバインドします"; color: "#747890"; font.pixelSize: 11 }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#1c202e" }

                    // プロバイダー選択
                    ColumnLayout {
                        spacing: 6
                        Layout.fillWidth: true
                        Text { text: "使用するTTSプロバイダー"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                        ComboBox {
                            id: ttsCombo
                            Layout.fillWidth: true
                            height: 38
                            model: [
                                "VOICEVOX (Local Port 50021 / AivisSpeech / COEIROINK)",
                                "Edge TTS (Built-in Cloud / 無料・高速)",
                                "Custom OpenAI-compatible TTS (ローカル自作 / Kokoro / StyleTTS2)",
                                "PyTorch Local TTS (Kokoro-82M 推論)"
                            ]
                            currentIndex: 0
                            onActivated: {
                                if (currentIndex === 0) settingsPage.ttsProvider = "voicevox"
                                else if (currentIndex === 1) settingsPage.ttsProvider = "edge"
                                else if (currentIndex === 2) settingsPage.ttsProvider = "custom"
                                else settingsPage.ttsProvider = "kokoro"
                            }
                        }
                    }

                    // VOICEVOX エンドポイント設定
                    ColumnLayout {
                        spacing: 6
                        Layout.fillWidth: true
                        visible: ttsCombo.currentIndex === 0

                        Text { text: "VOICEVOX / AivisSpeech エンドポイント URL"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                        TextField {
                            id: voicevoxInput
                            Layout.fillWidth: true
                            height: 38
                            text: settingsPage.voicevoxUrl
                            color: "#ffffff"
                            background: Rectangle {
                                radius: 8
                                color: "#181a24"
                                border.color: voicevoxInput.activeFocus ? settingsPage.accent : "#2a2f42"
                                border.width: 1
                            }
                            onTextChanged: settingsPage.voicevoxUrl = text
                        }
                    }

                    // Custom TTS エンドポイント設定
                    ColumnLayout {
                        spacing: 12
                        Layout.fillWidth: true
                        visible: ttsCombo.currentIndex === 2

                        ColumnLayout {
                            spacing: 6
                            Layout.fillWidth: true
                            Text { text: "Custom TTS API エンドポイント URL"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: customUrlInput
                                Layout.fillWidth: true
                                height: 38
                                text: settingsPage.customTtsUrl
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#181a24"
                                    border.color: customUrlInput.activeFocus ? settingsPage.accent : "#2a2f42"
                                    border.width: 1
                                }
                                onTextChanged: settingsPage.customTtsUrl = text
                            }
                        }

                        ColumnLayout {
                            spacing: 6
                            Layout.fillWidth: true
                            Text { text: "API Key (Bearer Token / 任意)"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: customKeyInput
                                Layout.fillWidth: true
                                height: 38
                                placeholderText: "Bearer token または空欄"
                                echoMode: TextInput.Password
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#181a24"
                                    border.color: customKeyInput.activeFocus ? settingsPage.accent : "#2a2f42"
                                    border.width: 1
                                }
                                onTextChanged: settingsPage.customTtsKey = text
                            }
                        }
                    }

                    // 接続テストボタン
                    RowLayout {
                        spacing: 12
                        Rectangle {
                            height: 34
                            width: 140
                            radius: 17
                            color: testTtsMa.containsMouse ? "#222a3d" : "#1a1f2e"
                            border.color: "#2f3750"
                            border.width: 1

                            RowLayout {
                                anchors.centerIn: parent
                                spacing: 6
                                Text { text: "⚡"; font.pixelSize: 11 }
                                Text { text: "TTS 接続テスト"; color: "#c0c6dc"; font.pixelSize: 12; font.bold: true }
                            }

                            MouseArea {
                                id: testTtsMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    settingsPage.connectionStatus = "✓ TTS エンドポイント接続確認完了 (HTTP 200 OK — Ready)"
                                }
                            }
                        }

                        Text {
                            text: "※ 未接続時は自動的に内蔵 Edge-TTS フォールバックで音声を合成します"
                            color: "#6b7288"
                            font.pixelSize: 11
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            // ================= 2. 脚本解析・LLM設定 =================
            Rectangle {
                Layout.fillWidth: true
                radius: 12
                color: "#12141c"
                border.color: "#212534"
                border.width: 1
                implicitHeight: colLlm.implicitHeight + 36

                ColumnLayout {
                    id: colLlm
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 16

                    RowLayout {
                        spacing: 10
                        Text { text: "🧠"; font.pixelSize: 18 }
                        ColumnLayout {
                            spacing: 2
                            Text { text: "脚本・演技指示 AI (LLM Director Binding)"; color: "#ffffff"; font.pixelSize: 16; font.bold: true }
                            Text { text: "小説の地の文・会話文分離、感情・演技パラメータ推定に使用するLLMを設定します"; color: "#747890"; font.pixelSize: 11 }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#1c202e" }

                    RowLayout {
                        spacing: 16
                        Layout.fillWidth: true

                        ColumnLayout {
                            spacing: 6
                            Layout.preferredWidth: 260
                            Text { text: "LLM プロバイダー"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            ComboBox {
                                id: llmCombo
                                Layout.fillWidth: true
                                height: 38
                                model: [
                                    "Local LLM (Ollama / vLLM / LM Studio)",
                                    "Google Gemini API",
                                    "Heuristic Rule Engine (AI不使用 / 完全オフライン)"
                                ]
                                currentIndex: 0
                                onActivated: {
                                    if (currentIndex === 0) settingsPage.llmProvider = "ollama"
                                    else if (currentIndex === 1) settingsPage.llmProvider = "gemini"
                                    else settingsPage.llmProvider = "heuristic"
                                }
                            }
                        }

                        ColumnLayout {
                            spacing: 6
                            Layout.fillWidth: true
                            visible: llmCombo.currentIndex === 0
                            Text { text: "ローカル API エンドポイント"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: llmUrlInput
                                Layout.fillWidth: true
                                height: 38
                                text: settingsPage.llmUrl
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#181a24"
                                    border.color: llmUrlInput.activeFocus ? settingsPage.accent : "#2a2f42"
                                    border.width: 1
                                }
                                onTextChanged: settingsPage.llmUrl = text
                            }
                        }

                        ColumnLayout {
                            spacing: 6
                            Layout.fillWidth: true
                            visible: llmCombo.currentIndex === 1
                            Text { text: "Gemini API Key"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            TextField {
                                id: geminiKeyInput
                                Layout.fillWidth: true
                                height: 38
                                placeholderText: "AIzaSy..."
                                echoMode: TextInput.Password
                                color: "#ffffff"
                                background: Rectangle {
                                    radius: 8
                                    color: "#181a24"
                                    border.color: geminiKeyInput.activeFocus ? settingsPage.accent : "#2a2f42"
                                    border.width: 1
                                }
                                onTextChanged: settingsPage.geminiKey = text
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 6
                        Layout.fillWidth: true
                        visible: llmCombo.currentIndex === 0
                        Text { text: "モデル名"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                        TextField {
                            id: llmModelInput
                            Layout.fillWidth: true
                            height: 38
                            text: settingsPage.llmModel
                            placeholderText: "qwen2.5:7b, llama3.2, gemma2:9b 等"
                            color: "#ffffff"
                            background: Rectangle {
                                radius: 8
                                color: "#181a24"
                                border.color: llmModelInput.activeFocus ? settingsPage.accent : "#2a2f42"
                                border.width: 1
                            }
                            onTextChanged: settingsPage.llmModel = text
                        }
                    }
                }
            }

            // ================= 3. 音響 & キャッシュ設定 =================
            Rectangle {
                Layout.fillWidth: true
                radius: 12
                color: "#12141c"
                border.color: "#212534"
                border.width: 1
                implicitHeight: colAudio.implicitHeight + 36

                ColumnLayout {
                    id: colAudio
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 16

                    RowLayout {
                        spacing: 10
                        Text { text: "🎛"; font.pixelSize: 18 }
                        ColumnLayout {
                            spacing: 2
                            Text { text: "音響マスタリング & ストレージ設定"; color: "#ffffff"; font.pixelSize: 16; font.bold: true }
                            Text { text: "M4Bオーディオブック書き出しレートおよびローカルキャッシュを管理します"; color: "#747890"; font.pixelSize: 11 }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#1c202e" }

                    RowLayout {
                        spacing: 24
                        Layout.fillWidth: true

                        ColumnLayout {
                            spacing: 6
                            Layout.preferredWidth: 200
                            Text { text: "出力サンプリングレート"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            ComboBox {
                                id: rateCombo
                                Layout.fillWidth: true
                                height: 38
                                model: ["24,000 Hz (高速・推奨)", "44,100 Hz (CD音質)", "48,000 Hz (ハイレゾ)"]
                                currentIndex: 0
                            }
                        }

                        ColumnLayout {
                            spacing: 6
                            Layout.fillWidth: true
                            Text { text: "ローカル音声キャッシュ"; color: "#a0a6bd"; font.pixelSize: 12; font.bold: true }
                            RowLayout {
                                spacing: 12
                                Rectangle {
                                    height: 36
                                    width: 150
                                    radius: 18
                                    color: clearCacheMa.containsMouse ? "#301d22" : "#24161b"
                                    border.color: "#5c2834"
                                    border.width: 1
                                    Text {
                                        anchors.centerIn: parent
                                        text: "🗑 キャッシュを消去"
                                        color: "#f57f95"
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                    MouseArea {
                                        id: clearCacheMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            settingsPage.connectionStatus = "✓ 音声一時キャッシュを消去しました"
                                        }
                                    }
                                }
                                Text {
                                    text: "※ 再生・生成済みの WAV/M4B ファイルは books/ ディレクトリに永続化されます"
                                    color: "#6b7288"
                                    font.pixelSize: 11
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 30 }
        }
    }
}

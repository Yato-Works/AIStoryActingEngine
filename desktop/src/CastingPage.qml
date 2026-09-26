import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: page
    property var book: null
    property var castings: null          // ListModel
    property var voiceProfiles: null     // ListModel
    property string seriesId: ""
    property color accent: "#6366f1"     // Indigo Accent
    property bool atlasConnected: false  // AI Atlas 連携状態（ヘッダーでトグル可能）
    property int selectedIndex: 0        // 選択中キャラクターインデックス
    property bool isPlayingPreview: false

    signal assignRequested(string bookId, string characterId, string voiceId, string voiceInternalId, bool isLocked)
    signal previewRequested(string text, string voiceId, string caption, real pace, bool useGemini, var options)
    signal imagineRequested(string bookId, string characterId)
    signal applyAllRequested(string bookId, string provider)
    signal refreshRequested(string bookId)
    signal toggleAtlasRequested(bool connected)

    background: Rectangle {
        color: "#0b0d13" // Deep Obsidian
    }

    // 現在選択されているキャラクターのデータヘルパー
    function currentCharacter() {
        if (!castings || castings.count === 0 || selectedIndex < 0 || selectedIndex >= castings.count) {
            return null;
        }
        return castings.get(selectedIndex);
    }

    // AI Voice Imagineer からの音声設計結果をUIに反映
    function applyImaginedVoice(voiceDesign) {
        if (!voiceDesign) return;
        if (voiceDesign.gender) {
            tunerCard.selectedGender = voiceDesign.gender;
        }
        if (voiceDesign.caption) {
            captionInput.text = voiceDesign.caption;
        }
        if (voiceDesign.sample_line) {
            sampleInput.text = voiceDesign.sample_line;
        }
        if (voiceDesign.suggested_cfg) {
            cfgSlider.value = voiceDesign.suggested_cfg;
            tunerCard.cfgScaleCaption = voiceDesign.suggested_cfg;
        }
        if (voiceDesign.suggested_sway) {
            swaySlider.value = voiceDesign.suggested_sway;
            tunerCard.swayCoeff = voiceDesign.suggested_sway;
        }
        if (voiceDesign.suggested_pace) {
            paceSlider.value = voiceDesign.suggested_pace;
        }
        if (voiceDesign.actor_homage) {
            tunerCard.selectedVoiceName = voiceDesign.actor_homage;
        } else if (voiceDesign.concept_summary) {
            tunerCard.selectedVoiceName = voiceDesign.concept_summary;
        }
        if (voiceDesign.concept_summary) {
            tunerCard.selectedVoiceDesc = voiceDesign.concept_summary;
        }
        tunerCard.selectedVoiceIcon = (voiceDesign.gender === "female") ? "🌸" : ((voiceDesign.gender === "male") ? "⚡" : "🧒");
    }

    // ------------------------------------------------------------------------
    // Header
    // ------------------------------------------------------------------------
    header: Rectangle {
        height: 72
        color: "#0f121a"
        border.color: "#0fffffff"
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 16

            // タイトル＆書籍情報
            RowLayout {
                spacing: 12
                Rectangle {
                    width: 38; height: 38; radius: 10
                    color: "#266366f1"
                    border.color: "#4c6366f1"
                    Text {
                        anchors.centerIn: parent
                        text: "🎭"
                        font.pixelSize: 18
                    }
                }
                ColumnLayout {
                    spacing: 2
                    Text {
                        text: "キャスティング & ボイススタジオ"
                        color: "#ffffff"
                        font.pixelSize: 17
                        font.bold: true
                    }
                    Text {
                        text: page.book ? "対象書籍: " + (page.book.title || page.book.id) : "本が選択されていません"
                        color: "#8e95a5"
                        font.pixelSize: 12
                    }
                }
            }

            Item { Layout.fillWidth: true }

            // ----------------------------------------------------------------
            // Atlas 連携ステータス切替トグル（Mobbin風ピルスイッチ）
            // ----------------------------------------------------------------
            Rectangle {
                Layout.preferredHeight: 36
                Layout.preferredWidth: atlasRow.implicitWidth + 20
                radius: 18
                color: page.atlasConnected ? "#1f10b981" : "#0dffffff"
                border.color: page.atlasConnected ? "#5910b981" : "#1affffff"
                border.width: 1

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        page.atlasConnected = !page.atlasConnected;
                        page.toggleAtlasRequested(page.atlasConnected);
                    }
                }

                RowLayout {
                    id: atlasRow
                    anchors.centerIn: parent
                    spacing: 8

                    Rectangle {
                        width: 8; height: 8; radius: 4
                        color: page.atlasConnected ? "#10b981" : "#71717a"
                        // 接続時の微細パルス効果
                        SequentialAnimation on opacity {
                            running: page.atlasConnected
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.4; duration: 900 }
                            NumberAnimation { to: 1.0; duration: 900 }
                        }
                    }

                    Text {
                        text: page.atlasConnected ? "StoryAtlas 連携中 (v1.0)" : "StoryAtlas 未接続 (切替可)"
                        color: page.atlasConnected ? "#34d399" : "#a1a1aa"
                        font.pixelSize: 12
                        font.bold: page.atlasConnected
                    }
                }
            }

            // 更新ボタン
            Button {
                text: "⟳ 配役更新"
                flat: true
                contentItem: Text {
                    text: parent.text
                    color: "#a1a1aa"
                    font.pixelSize: 13
                }
                background: Rectangle {
                    color: parent.hovered ? "#0fffffff" : "transparent"
                    radius: 8
                }
                onClicked: {
                    if (page.book) page.refreshRequested(page.book.id)
                }
            }

            // ----------------------------------------------------------------
            // 「✨ 小説全体に配役を適用」ボタン（Mobbin風グラデーション）
            // ----------------------------------------------------------------
            Rectangle {
                Layout.preferredHeight: 38
                Layout.preferredWidth: applyBtnContent.implicitWidth + 28
                radius: 10
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: applyMouseArea.containsPress ? "#4f46e5" : "#6366f1" }
                    GradientStop { position: 1.0; color: applyMouseArea.containsPress ? "#7c3aed" : "#8b5cf6" }
                }

                MouseArea {
                    id: applyMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: applyDialog.open()
                }

                RowLayout {
                    id: applyBtnContent
                    anchors.centerIn: parent
                    spacing: 8
                    Text { text: "✨"; font.pixelSize: 14 }
                    Text {
                        text: "小説全体に配役を適用"
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------------
    // Main Body: 2-Pane Layout
    // ------------------------------------------------------------------------
    RowLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 20

        // ====================================================================
        // 左ペイン: キャラクター一覧（380px）
        // ====================================================================
        Rectangle {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            radius: 14
            color: "#11141e"
            border.color: "#12ffffff"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                // リストヘッダー
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "登場人物一覧"
                        color: "#ffffff"
                        font.pixelSize: 15
                        font.bold: true
                    }
                    Text {
                        text: page.castings ? "(" + page.castings.count + "名)" : "(0名)"
                        color: "#71717a"
                        font.pixelSize: 13
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        visible: page.atlasConnected
                        width: atlasBadgeText.implicitWidth + 12
                        height: 20
                        radius: 10
                        color: "#266366f1"
                        border.color: "#4c6366f1"
                        Text {
                            id: atlasBadgeText
                            anchors.centerIn: parent
                            text: "⚡ Atlas情報表示中"
                            color: "#818cf8"
                            font.pixelSize: 10
                            font.bold: true
                        }
                    }
                }

                // キャラクターカード一覧 ListView
                ListView {
                    id: charListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 10
                    model: page.castings
                    currentIndex: page.selectedIndex

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    delegate: Rectangle {
                        id: charCard
                        width: charListView.width - 6
                        // Atlas連携時はリッチな情報を表示するため高さを拡張、非連携時はスリム
                        height: page.atlasConnected ? 116 : 74
                        radius: 12

                        property bool isSelected: index === page.selectedIndex
                        color: isSelected
                               ? (page.atlasConnected ? "#191d2c" : "#171a24")
                               : (cardArea.containsMouse ? "#151822" : "#131620")
                        border.color: isSelected ? "#6366f1" : "#0fffffff"
                        border.width: isSelected ? 1.5 : 1

                        Behavior on color { ColorAnimation { duration: 150 } }
                        Behavior on height { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

                        MouseArea {
                            id: cardArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                page.selectedIndex = index;
                                charListView.currentIndex = index;
                                // チューナーにセリフや演出を自動プリセット
                                sampleInput.text = model.sample_line || (model.name + "のセリフです。");
                                if (page.atlasConnected && model.personality) {
                                    // 演出プロンプト未入力なら性格から自動推薦
                                    if (captionInput.text === "") {
                                        var pList = Array.isArray(model.personality) ? model.personality.join("、") : model.personality;
                                        captionInput.text = (model.gender === "female" ? "女性、" : "男性、") + pList + "な口調";
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8

                            // 上段: アバター + 名前 + 配役ボイス
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                // アバター（イニシャル または 性別アイコン）
                                Rectangle {
                                    width: 42; height: 42; radius: 21
                                    color: model.gender === "female" ? "#db2777" : (model.gender === "male" ? "#2563eb" : "#475569")

                                    Text {
                                        anchors.centerIn: parent
                                        text: (model.name || "?").charAt(0)
                                        color: "#ffffff"
                                        font.pixelSize: 18
                                        font.bold: true
                                    }

                                    // Atlas連携時: ロールバッジの小インジケータ
                                    Rectangle {
                                        visible: page.atlasConnected && model.role
                                        width: 14; height: 14; radius: 7
                                        color: model.role === "protagonist" ? "#f59e0b" : "#6366f1"
                                        border.color: "#11141e"
                                        border.width: 2
                                        anchors.bottom: parent.bottom
                                        anchors.right: parent.right
                                    }
                                }

                                // 名前 & ボイス情報
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    RowLayout {
                                        spacing: 8
                                        Text {
                                            text: model.name || "名称未定"
                                            color: charCard.isSelected ? "#ffffff" : "#e4e4e7"
                                            font.pixelSize: 15
                                            font.bold: true
                                        }

                                        // Atlas連携時のみ: ロールタグ表示
                                        Rectangle {
                                            visible: page.atlasConnected && model.role
                                            height: 18
                                            width: roleText.implicitWidth + 10
                                            radius: 9
                                            color: model.role === "protagonist" ? "#26f59e0b" : "#266366f1"
                                            Text {
                                                id: roleText
                                                anchors.centerIn: parent
                                                text: model.role === "protagonist" ? "主人公" : (model.role === "antagonist" ? "敵役" : (model.role === "narrator" ? "語り手" : "主要人物"))
                                                color: model.role === "protagonist" ? "#fbbf24" : "#a5b4fc"
                                                font.pixelSize: 10
                                            }
                                        }
                                    }

                                    // 配役ステータス（非連携時でも表示される必要最小限の情報）
                                    RowLayout {
                                        spacing: 6
                                        Text {
                                            text: "🎙"
                                            font.pixelSize: 11
                                        }
                                        Text {
                                            text: model.voice_id ? model.voice_id : "ボイス未設定 (Anime推奨)"
                                            color: model.voice_id ? "#a1a1aa" : "#eab308"
                                            font.pixelSize: 12
                                        }
                                    }
                                }

                                // ロックアイコン
                                Text {
                                    visible: model.is_locked
                                    text: "🔒"
                                    font.pixelSize: 12
                                }
                            }

                            // ------------------------------------------------
                            // 下段: Atlas 連携時のみ展開されるリッチ詳細
                            // ------------------------------------------------
                            ColumnLayout {
                                visible: page.atlasConnected
                                Layout.fillWidth: true
                                spacing: 4

                                // 種族・所属
                                Text {
                                    visible: page.atlasConnected && (model.species || model.affiliation)
                                    text: (model.species ? model.species : "") + (model.affiliation ? " • " + model.affiliation : "")
                                    color: "#94a3b8"
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }

                                // 性格タグチップ（横並び）
                                Row {
                                    spacing: 6
                                    visible: page.atlasConnected && model.personality && model.personality.length > 0
                                    Repeater {
                                        model: model.personality ? (Array.isArray(model.personality) ? model.personality.slice(0, 3) : [model.personality]) : []
                                        delegate: Rectangle {
                                            height: 18
                                            width: persText.implicitWidth + 10
                                            radius: 9
                                            color: "#0dffffff"
                                            border.color: "#14ffffff"
                                            Text {
                                                id: persText
                                                anchors.centerIn: parent
                                                text: modelData
                                                color: "#cbd5e1"
                                                font.pixelSize: 10
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

        // ====================================================================
        // 右ペイン: ボイスチューナー＆インサイト（メイン領域）
        // ====================================================================
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: parent.width - 12
                spacing: 16

                // ------------------------------------------------------------
                // 1. キャラクターインサイトカード（Atlas連携状態によって激変）
                // ------------------------------------------------------------
                Rectangle {
                    Layout.fillWidth: true
                    radius: 14
                    color: "#11141e"
                    border.color: "#12ffffff"
                    border.width: 1
                    Layout.preferredHeight: page.atlasConnected ? atlasInsightCol.implicitHeight + 36 : noAtlasInsightCol.implicitHeight + 32

                    Behavior on Layout.preferredHeight { NumberAnimation { duration: 220; easing.type: Easing.OutQuad } }

                    // A. Atlas 非連携時（シンプル・ミニマル表示）
                    ColumnLayout {
                        id: noAtlasInsightCol
                        visible: !page.atlasConnected
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 12

                        RowLayout {
                            spacing: 14
                            Rectangle {
                                width: 48; height: 48; radius: 24
                                color: (page.currentCharacter() && page.currentCharacter().gender === "female") ? "#db2777" : "#2563eb"
                                Text {
                                    anchors.centerIn: parent
                                    text: page.currentCharacter() ? (page.currentCharacter().name || "?").charAt(0) : "?"
                                    color: "#ffffff"
                                    font.pixelSize: 22
                                    font.bold: true
                                }
                            }
                            ColumnLayout {
                                spacing: 3
                                Text {
                                    text: page.currentCharacter() ? page.currentCharacter().name : "キャラクターを選択してください"
                                    color: "#ffffff"
                                    font.pixelSize: 18
                                    font.bold: true
                                }
                                Text {
                                    text: "基本キャスティングモード (Atlas未接続)"
                                    color: "#71717a"
                                    font.pixelSize: 12
                                }
                            }
                            Item { Layout.fillWidth: true }
                            // ✨ このキャラから声を想像するボタン（非連携時）
                            Rectangle {
                                visible: page.currentCharacter() !== null
                                height: 36
                                width: imagineBtnRow1.implicitWidth + 24
                                radius: 18
                                color: imagineBtnArea1.containsPress ? "#4338ca" : (imagineBtnArea1.containsMouse ? "#4f46e5" : "#6366f1")
                                MouseArea {
                                    id: imagineBtnArea1
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        var ch = page.currentCharacter();
                                        if (ch && page.book) {
                                            page.imagineRequested(page.book.id, ch.character_id);
                                        }
                                    }
                                }
                                RowLayout {
                                    id: imagineBtnRow1
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Text { text: "✨"; font.pixelSize: 13 }
                                    Text { text: "このキャラから声を想像する"; color: "#ffffff"; font.pixelSize: 12; font.bold: true }
                                }
                            }
                        }

                        // Atlas 未接続プロンプトバナー（控えめで洗練されたデザイン）
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 52
                            radius: 10
                            color: "#08ffffff"
                            border.color: "#0fffffff"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 12
                                Text { text: "💡"; font.pixelSize: 16 }
                                Text {
                                    text: "StoryAtlas と連携すると、立ち絵・性格・所属・相関図などの詳細情報がここに自動展開されます。"
                                    color: "#94a3b8"
                                    font.pixelSize: 12
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                }
                                Button {
                                    text: "連携を試す"
                                    flat: true
                                    contentItem: Text { text: parent.text; color: "#818cf8"; font.pixelSize: 12; font.bold: true }
                                    onClicked: {
                                        page.atlasConnected = true;
                                        page.toggleAtlasRequested(true);
                                    }
                                }
                            }
                        }
                    }

                    // B. Atlas 連携時（Mobbin スタイルの最高峰リッチインサイト）
                    ColumnLayout {
                        id: atlasInsightCol
                        visible: page.atlasConnected
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 16

                        // 上段: ヘッダープロファイル
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16

                            // アバター画像枠（将来の立ち絵・イラスト用）
                            Rectangle {
                                width: 68; height: 68; radius: 14
                                color: (page.currentCharacter() && page.currentCharacter().gender === "female") ? "#be185d" : "#1d4ed8"
                                border.color: "#26ffffff"
                                border.width: 1.5

                                Text {
                                    anchors.centerIn: parent
                                    text: page.currentCharacter() ? (page.currentCharacter().name || "?").charAt(0) : "?"
                                    color: "#ffffff"
                                    font.pixelSize: 32
                                    font.bold: true
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                RowLayout {
                                    spacing: 10
                                    Text {
                                        text: page.currentCharacter() ? page.currentCharacter().name : ""
                                        color: "#ffffff"
                                        font.pixelSize: 20
                                        font.bold: true
                                    }
                                    // ロールバッジ
                                    Rectangle {
                                        height: 22
                                        width: detailRoleText.implicitWidth + 14
                                        radius: 11
                                        color: "#336366f1"
                                        border.color: "#666366f1"
                                        Text {
                                            id: detailRoleText
                                            anchors.centerIn: parent
                                            text: page.currentCharacter() ? (page.currentCharacter().role || "主要人物") : ""
                                            color: "#a5b4fc"
                                            font.pixelSize: 11
                                            font.bold: true
                                        }
                                    }
                                    // Atlas 認証マーク
                                    Rectangle {
                                        height: 22
                                        width: verifiedText.implicitWidth + 12
                                        radius: 11
                                        color: "#2610b981"
                                        Text {
                                            id: verifiedText
                                            anchors.centerIn: parent
                                            text: "✓ Atlas Synced"
                                            color: "#34d399"
                                            font.pixelSize: 11
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                    // ✨ このキャラから声を想像するボタン（連携時）
                                    Rectangle {
                                        visible: page.currentCharacter() !== null
                                        height: 36
                                        width: imagineBtnRow2.implicitWidth + 24
                                        radius: 18
                                        color: imagineBtnArea2.containsPress ? "#4338ca" : (imagineBtnArea2.containsMouse ? "#4f46e5" : "#6366f1")
                                        MouseArea {
                                            id: imagineBtnArea2
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                var ch = page.currentCharacter();
                                                if (ch && page.book) {
                                                    page.imagineRequested(page.book.id, ch.character_id);
                                                }
                                            }
                                        }
                                        RowLayout {
                                            id: imagineBtnRow2
                                            anchors.centerIn: parent
                                            spacing: 6
                                            Text { text: "✨"; font.pixelSize: 13 }
                                            Text { text: "性格から声を想像する"; color: "#ffffff"; font.pixelSize: 12; font.bold: true }
                                        }
                                    }
                                }

                                // 詳細説明
                                Text {
                                    text: page.currentCharacter() && page.currentCharacter().description
                                          ? page.currentCharacter().description
                                          : "物語の登場人物。Atlasから抽出されたプロファイル設定を保持しています。"
                                    color: "#cbd5e1"
                                    font.pixelSize: 13
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        // 中段: メタデータグリッド（種族・所属・相関関係・感情レンジ）
                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: "#0fffffff"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 20

                            // 種族 & 所属
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text { text: "種族 / 所属"; color: "#64748b"; font.pixelSize: 11; font.bold: true }
                                Text {
                                    text: (page.currentCharacter() && page.currentCharacter().species ? page.currentCharacter().species : "人間")
                                          + " / " + (page.currentCharacter() && page.currentCharacter().affiliation ? page.currentCharacter().affiliation : "所属なし")
                                    color: "#e2e8f0"; font.pixelSize: 13
                                }
                            }

                            // 特殊能力
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text { text: "特殊能力 / 特技"; color: "#64748b"; font.pixelSize: 11; font.bold: true }
                                Text {
                                    text: page.currentCharacter() && page.currentCharacter().abilities && page.currentCharacter().abilities.length > 0
                                          ? page.currentCharacter().abilities.join(", ")
                                          : "特記事項なし"
                                    color: "#e2e8f0"; font.pixelSize: 13
                                }
                            }

                            // 相関関係
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text { text: "相関関係 (Relationships)"; color: "#64748b"; font.pixelSize: 11; font.bold: true }
                                Text {
                                    text: page.currentCharacter() && page.currentCharacter().relationships && page.currentCharacter().relationships.length > 0
                                          ? page.currentCharacter().relationships[0].label || page.currentCharacter().relationships[0].type
                                          : "単独行動 / 独立"
                                    color: "#e2e8f0"; font.pixelSize: 13
                                }
                            }
                        }

                        // 性格タグ（クリックでプロンプトに注入できるワンタップアシスト！）
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            RowLayout {
                                Text { text: "性格タグ (クリックで下の演出プロンプトにワンタップ注入):"; color: "#94a3b8"; font.pixelSize: 11 }
                            }
                            Row {
                                spacing: 8
                                Repeater {
                                    model: page.currentCharacter() && page.currentCharacter().personality
                                           ? (Array.isArray(page.currentCharacter().personality) ? page.currentCharacter().personality : [page.currentCharacter().personality])
                                           : ["落ち着いた", "知的"]
                                    delegate: Rectangle {
                                        height: 24
                                        width: chipText.implicitWidth + 16
                                        radius: 12
                                        color: chipArea.containsMouse ? "#4c6366f1" : "#266366f1"
                                        border.color: "#596366f1"

                                        MouseArea {
                                            id: chipArea
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                if (captionInput.text === "") {
                                                    captionInput.text = modelData;
                                                } else {
                                                    captionInput.text = captionInput.text + "、" + modelData;
                                                }
                                            }
                                        }

                                        RowLayout {
                                            anchors.centerIn: parent
                                            spacing: 4
                                            Text { text: "+"; color: "#818cf8"; font.pixelSize: 11; font.bold: true }
                                            Text {
                                                id: chipText
                                                text: modelData
                                                color: "#c7d2fe"
                                                font.pixelSize: 11
                                                font.bold: true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ------------------------------------------------------------
                // 2. Spotify Style: Irodori Anime ボイススタジオ ＆ 詳細チューナー
                // ------------------------------------------------------------
                Rectangle {
                    id: tunerCard
                    Layout.fillWidth: true
                    radius: 16
                    color: "#181818" // Spotify Card Dark
                    border.color: "#282828"
                    border.width: 1
                    Layout.preferredHeight: tunerCol.implicitHeight + 44

                    // 詳細チューナーの開閉状態
                    property bool showAdvanced: false
                    // 性別コントロール ("male" | "female" | "neutral")
                    property string selectedGender: "male"
                    // 詳細パラメータ群
                    property real cfgScaleCaption: 3.2
                    property real swayCoeff: -1.0
                    property int numSteps: 28
                    property int currentSeed: 42
                    property bool seedLocked: true

                    // 現在選択中の声質・スタイル情報（選択している感を最大化！）
                    property string selectedVoiceName: "Test_Voice4 (皮肉・渋み主人公)"
                    property string selectedVoiceIcon: "🕶"
                    property string selectedVoiceDesc: "低音・気だるげツッコミ"

                    ColumnLayout {
                        id: tunerCol
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 20

                        // 最上部: Spotify グリーンアクセントバー
                        Rectangle {
                            Layout.fillWidth: true
                            height: 2
                            radius: 1
                            color: "#1db954" // Spotify Green Accent
                        }

                        // チューナーヘッダー
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            Rectangle {
                                width: 34; height: 34; radius: 17
                                color: "#1db954"
                                Text { anchors.centerIn: parent; text: "🎛"; font.pixelSize: 16 }
                            }
                            ColumnLayout {
                                spacing: 1
                                Text {
                                    text: "IRODORI VOICE STUDIO"
                                    color: "#ffffff"
                                    font.pixelSize: 17
                                    font.bold: true
                                    font.letterSpacing: 0.5
                                }
                                Text {
                                    text: "声優オマージュ演出 & 直感スタジオチューナー"
                                    color: "#b3b3b3"
                                    font.pixelSize: 12
                                }
                            }
                            Item { Layout.fillWidth: true }
                            // 稼働ステータスバッジ
                            Rectangle {
                                height: 26
                                width: statusBadgeRow.implicitWidth + 18
                                radius: 13
                                color: "#1a1db954"
                                border.color: "#401db954"
                                RowLayout {
                                    id: statusBadgeRow
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Rectangle {
                                        width: 8; height: 8; radius: 4
                                        color: "#1db954"
                                        SequentialAnimation on opacity {
                                            loops: Animation.Infinite
                                            NumberAnimation { to: 0.3; duration: 800 }
                                            NumberAnimation { to: 1.0; duration: 800 }
                                        }
                                    }
                                    Text {
                                        text: "Anime v4.1 Active"
                                        color: "#1db954"
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                }
                            }
                        }

                        // ====================================================
                        // セクション 0: 確実な性別コントロール (Gender Switch & Lock)
                        // ====================================================
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            RowLayout {
                                Text { text: "⚧ 声の性別・基底コントロール (Gender Lock)"; color: "#ffffff"; font.pixelSize: 13; font.bold: true }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: tunerCard.selectedGender === "male" ? "♂ 男性声（太い低音・胸鳴り地声を強制拘束）" : (tunerCard.selectedGender === "female" ? "♀ 女性声（澄んだ高音・透明感を拘束）" : "🧒 少年・中性（ハスキーな少年声を拘束）")
                                    color: tunerCard.selectedGender === "male" ? "#60a5fa" : (tunerCard.selectedGender === "female" ? "#f472b6" : "#a78bfa")
                                    font.pixelSize: 11
                                    font.bold: true
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                Repeater {
                                    model: [
                                        { id: "male", label: "♂ 男性声 (野太い低音)", sub: "低音ボイス・男声地声", color: "#3b82f6" },
                                        { id: "female", label: "♀ 女性声 (澄んだ高音)", sub: "透明感・アニメヒロイン", color: "#ec4899" },
                                        { id: "neutral", label: "🧒 少年 / 中性声", sub: "少しハスキー・中性的", color: "#8b5cf6" }
                                    ]
                                    delegate: Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 48
                                        radius: 10
                                        property bool isCur: tunerCard.selectedGender === modelData.id
                                        color: isCur ? "#262938" : "#1f1f1f"
                                        border.color: isCur ? modelData.color : "#333333"
                                        border.width: isCur ? 2 : 1

                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                tunerCard.selectedGender = modelData.id;
                                                var cur = captionInput.text;
                                                cur = cur.replace(/【明確な男性声】[^\s、,]*[、,]?\s*/g, "");
                                                cur = cur.replace(/【澄んだ女性声】[^\s、,]*[、,]?\s*/g, "");
                                                cur = cur.replace(/【少年・中性声】[^\s、,]*[、,]?\s*/g, "");
                                                if (modelData.id === "male") {
                                                    captionInput.text = "【明確な男性声】太く低い男声、喉を鳴らすような野太い地声、" + cur;
                                                    if (tunerCard.cfgScaleCaption < 3.2) tunerCard.cfgScaleCaption = 3.2;
                                                } else if (modelData.id === "female") {
                                                    captionInput.text = "【澄んだ女性声】透明感のある女性声、自然な中高音、" + cur;
                                                } else {
                                                    captionInput.text = "【少年・中性声】少しハスキーな少年の声、中性的な声質、" + cur;
                                                }
                                            }
                                        }

                                        RowLayout {
                                            anchors.centerIn: parent
                                            spacing: 10
                                            ColumnLayout {
                                                spacing: 2
                                                RowLayout {
                                                    spacing: 6
                                                    Text {
                                                        text: modelData.label
                                                        color: parent.parent.parent.isCur ? "#ffffff" : "#b3b3b3"
                                                        font.pixelSize: 12
                                                        font.bold: parent.parent.parent.isCur
                                                    }
                                                    Rectangle {
                                                        visible: parent.parent.parent.isCur
                                                        width: 14; height: 14; radius: 7
                                                        color: modelData.color
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: "✓"
                                                            color: "#ffffff"
                                                            font.pixelSize: 9
                                                            font.bold: true
                                                        }
                                                    }
                                                }
                                                Text {
                                                    text: modelData.sub
                                                    color: parent.parent.parent.isCur ? modelData.color : "#666666"
                                                    font.pixelSize: 10
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // ====================================================
                        // セクション 1: 声優オマージュ & 感覚的プリセットパレット
                        // ====================================================
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            RowLayout {
                                Text { text: "🎯 声優オマージュ & 直感スタイル (ワンタップ適用)"; color: "#ffffff"; font.pixelSize: 13; font.bold: true }
                                Item { Layout.fillWidth: true }
                                Text { text: "※タップで演出文・話速・詳細パラメータを即時セット"; color: "#888888"; font.pixelSize: 11 }
                            }

                            // プリセットタイル（Spotify Playlist 風チップ）
                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: [
                                        {
                                            name: "Test_Voice1 (無頼・ハスキー青年)",
                                            icon: "🎙️",
                                            desc: "ハスキー・自嘲切ない若者",
                                            prompt: "少しハスキーで若々しい青年の声、飾り気のないぶっきらぼうな話し方、少し擦れた少年声、自嘲気味で切ないトーン",
                                            sample: "俺のこぶしは軽いってわけだ。勝てっこないや。",
                                            pace: 1.00, cfg: 3.2, sway: -1.0, steps: 28, seed: 777
                                        },
                                        {
                                            name: "Test_Voice2 (冷静・知的参謀)",
                                            icon: "♟️",
                                            desc: "キレのある知的冷徹クール",
                                            prompt: "キレのある知的で冷徹な声、落ち着いた低音、命令口調、冷静沈着なトーン",
                                            sample: "おい、何をもたもたしている。さっさと片付けるぞ。",
                                            pace: 0.98, cfg: 3.3, sway: -1.0, steps: 24, seed: 999
                                        },
                                        {
                                            name: "Test_Voice3 (重厚・歴戦の男)",
                                            icon: "🛡️",
                                            desc: "重厚な超低音・威厳",
                                            prompt: "歴戦の重厚な超低音、渋く深みのある男声、威厳ある語り口",
                                            sample: "待たせたな。戦場に迷いなど無用だ。",
                                            pace: 0.90, cfg: 3.5, sway: -0.8, steps: 24, seed: 404
                                        },
                                        {
                                            name: "Test_Voice4 (皮肉・渋み主人公)",
                                            icon: "🕶️",
                                            desc: "低音・気だるげツッコミ",
                                            prompt: "落ち着いた低めの男声、少し気だるげで皮肉っぽい、低音の魅力、ツッコミ口調",
                                            sample: "まったく……俺の声の調子はどうだ？悪くない響きだろ。",
                                            pace: 0.95, cfg: 3.2, sway: -1.0, steps: 24, seed: 42
                                        },
                                        {
                                            name: "Test_Voice5 (正統派・熱血青年)",
                                            icon: "⚔️",
                                            desc: "熱血ツッコミ・少年主人公",
                                            prompt: "熱血で芯の通った少年・青年声、ハキハキとしたツッコミ口調、勇敢な響き",
                                            sample: "行くぞ！ここからが本当の勝負だ！",
                                            pace: 1.02, cfg: 3.0, sway: -1.0, steps: 24, seed: 123
                                        },
                                        {
                                            name: "Test_Voice6 (余裕・兄貴肌)",
                                            icon: "✨",
                                            desc: "余裕ある兄貴肌・色気低音",
                                            prompt: "色気のある落ち着いた青年声、飄々として余裕のある話し方、甘い低音",
                                            sample: "大丈夫、僕に任せておきなよ。",
                                            pace: 1.00, cfg: 3.0, sway: -0.9, steps: 24, seed: 101
                                        },
                                        {
                                            name: "Test_Voice7 (癒やし・清楚ヒロイン)",
                                            icon: "🌸",
                                            desc: "癒やし透明感・甘い少女",
                                            prompt: "透明感のある甘い少女声、柔らかく癒やされる高音、愛らしい話し方",
                                            sample: "私、ずっとあなたの力になりたかったんです。",
                                            pace: 1.05, cfg: 2.8, sway: -1.0, steps: 24, seed: 202
                                        },
                                        {
                                            name: "Test_Voice8 (凛冽・高貴令嬢)",
                                            icon: "❄️",
                                            desc: "知的で凛とした令嬢",
                                            prompt: "知的で凛とした令嬢声、澄み渡るシルキーなトーン、丁寧で落ち着いた話し方",
                                            sample: "お言葉ですが、私は私の信念を曲げるつもりはありません。",
                                            pace: 0.95, cfg: 3.0, sway: -1.1, steps: 24, seed: 303
                                        },
                                        {
                                            name: "Test_Voice9 (元気・マスコット妖精)",
                                            icon: "🧚",
                                            desc: "元気マスコット高音",
                                            prompt: "透明感のある甘い高音少女声、愛らしいマスコット口調、元気で表情豊かな話し方",
                                            sample: "おいおい、オイラはお前の一番の相棒だぞ！",
                                            pace: 1.05, cfg: 2.8, sway: -1.0, steps: 24, seed: 888
                                        },
                                        {
                                            name: "Test_Voice10 (強がり・ツンデレ少女)",
                                            icon: "🎀",
                                            desc: "強がり・照れ屋高音",
                                            prompt: "少女、ツンデレ、高めの声、照れ屋、感情豊か、強がり",
                                            sample: "べ、別にアンタのためにやったんじゃないんだからね！",
                                            pace: 1.08, cfg: 2.8, sway: -1.2, steps: 24, seed: 606
                                        },
                                        {
                                            name: "Test_Voice11 (爽やか青年)",
                                            icon: "☀️",
                                            desc: "好青年・丁寧な口調",
                                            prompt: "爽やかな男性の声、丁寧に話す、親しみやすい、明るい好青年",
                                            sample: "こんにちは！今日も一日、よろしくお願いします。",
                                            pace: 1.00, cfg: 2.5, sway: -1.0, steps: 24, seed: 505
                                        }
                                    ]

                                    delegate: Rectangle {
                                        id: pCard
                                        property bool isSelected: tunerCard.selectedVoiceName === modelData.name

                                        width: pCardCol.implicitWidth + (isSelected ? 36 : 24)
                                        height: 54
                                        radius: 12
                                        color: isSelected ? "#143820" : (pCardArea.containsMouse ? "#2a2a2a" : "#202020")
                                        border.color: isSelected ? "#1db954" : (pCardArea.containsMouse ? "#1ed760" : "#333333")
                                        border.width: isSelected ? 2 : 1

                                        Behavior on color { ColorAnimation { duration: 150 } }
                                        Behavior on border.color { ColorAnimation { duration: 150 } }

                                        MouseArea {
                                            id: pCardArea
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                tunerCard.selectedVoiceName = modelData.name;
                                                tunerCard.selectedVoiceIcon = modelData.icon;
                                                tunerCard.selectedVoiceDesc = modelData.desc;
                                                captionInput.text = modelData.prompt;
                                                if (modelData.sample) {
                                                    sampleInput.text = modelData.sample;
                                                }
                                                paceSlider.value = modelData.pace;
                                                tunerCard.cfgScaleCaption = modelData.cfg;
                                                tunerCard.swayCoeff = modelData.sway;
                                                tunerCard.numSteps = modelData.steps;
                                                tunerCard.currentSeed = modelData.seed;
                                            }
                                        }

                                        RowLayout {
                                            id: pCardCol
                                            anchors.centerIn: parent
                                            spacing: 10
                                            Text {
                                                text: modelData.icon
                                                font.pixelSize: 18
                                            }
                                            ColumnLayout {
                                                spacing: 2
                                                RowLayout {
                                                    spacing: 6
                                                    Text {
                                                        text: modelData.name
                                                        color: pCard.isSelected ? "#1db954" : (pCardArea.containsMouse ? "#ffffff" : "#e0e0e0")
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                    }
                                                    // 選択中バッジ
                                                    Rectangle {
                                                        visible: pCard.isSelected
                                                        width: 14; height: 14; radius: 7
                                                        color: "#1db954"
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: "✓"
                                                            color: "#000000"
                                                            font.pixelSize: 9
                                                            font.bold: true
                                                        }
                                                    }
                                                }
                                                Text {
                                                    text: modelData.desc
                                                    color: pCard.isSelected ? "#a7f3d0" : "#888888"
                                                    font.pixelSize: 10
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // ------------------------------------------------
                            // 🌟 Now Playing 風: 現在選択中のアクティブ声優バナー
                            // ------------------------------------------------
                            Rectangle {
                                Layout.fillWidth: true
                                height: 42
                                radius: 8
                                color: "#16281c"
                                border.color: "#2a5436"
                                border.width: 1

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    spacing: 10

                                    Text {
                                        text: tunerCard.selectedVoiceIcon
                                        font.pixelSize: 16
                                    }
                                    Text {
                                        text: "選択中の声質:"
                                        color: "#888888"
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        text: tunerCard.selectedVoiceName
                                        color: "#1db954"
                                        font.pixelSize: 13
                                        font.bold: true
                                    }
                                    Text {
                                        text: "• " + tunerCard.selectedVoiceDesc
                                        color: "#b3b3b3"
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    // パルスインジケーター
                                    RowLayout {
                                        spacing: 6
                                        Rectangle {
                                            width: 8; height: 8; radius: 4; color: "#1db954"
                                            SequentialAnimation on opacity {
                                                loops: Animation.Infinite
                                                NumberAnimation { to: 0.3; duration: 600 }
                                                NumberAnimation { to: 1.0; duration: 600 }
                                            }
                                        }
                                        Text { text: "Active"; color: "#1db954"; font.pixelSize: 10; font.bold: true }
                                    }
                                }
                            }
                        }

                        // ====================================================
                        // セクション 2: 🎨 Voice Architect (声の想像＆精密設計スタジオ)
                        // ====================================================
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            RowLayout {
                                Text { text: "💬 声の想像＆演出プロンプト (Voice Architect)"; color: "#ffffff"; font.pixelSize: 13; font.bold: true }
                                Item { Layout.fillWidth: true }
                                Text { text: "頭の中で想像した声を、自由な言葉や以下のチップで自在に具現化"; color: "#1db954"; font.pixelSize: 11 }
                                Text {
                                    text: "↺ クリア"
                                    color: "#a1a1aa"
                                    font.pixelSize: 11
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            captionInput.text = "";
                                            tunerCard.selectedVoiceName = "カスタム演出";
                                            tunerCard.selectedVoiceIcon = "🎨";
                                            tunerCard.selectedVoiceDesc = "自由調整プロンプト";
                                        }
                                    }
                                }
                            }

                            TextField {
                                id: captionInput
                                Layout.fillWidth: true
                                placeholderText: "例: 爽やかな男性の声、丁寧に話す / 落ち着いた低めの男声、少し気だるげで皮肉っぽい"
                                text: "【明確な男性声】太く低い男声、喉を鳴らすような野太い地声、少し気だるげで皮肉っぽい、低音の魅力、ツッコミ口調"
                                color: "#ffffff"
                                font.pixelSize: 13
                                padding: 14
                                background: Rectangle {
                                    radius: 10
                                    color: "#222222"
                                    border.color: parent.activeFocus ? "#1db954" : "#333333"
                                    border.width: parent.activeFocus ? 2 : 1
                                }
                                onTextEdited: {
                                    if (tunerCard.selectedVoiceName.indexOf("カスタム") === -1) {
                                        tunerCard.selectedVoiceName = "カスタム演出";
                                        tunerCard.selectedVoiceIcon = "🎨";
                                        tunerCard.selectedVoiceDesc = "自由調整プロンプト";
                                    }
                                }
                            }

                            // ------------------------------------------------
                            // 想像を具現化する 4大要素パレット (Voice Architect Palette)
                            // ------------------------------------------------
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                // A. 音域・太さ (Pitch / Depth)
                                RowLayout {
                                    spacing: 8
                                    Rectangle {
                                        width: 80; height: 24; radius: 6
                                        color: "#263b82f6"
                                        Text { anchors.centerIn: parent; text: "音域・太さ"; color: "#60a5fa"; font.pixelSize: 10; font.bold: true }
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        Repeater {
                                            model: ["野太い超低音", "落ち着いた低音", "自然な中音", "澄んだ中高音", "ハリのある高音", "ハイトーン"]
                                            delegate: Rectangle {
                                                height: 24
                                                width: chipT1.implicitWidth + 16
                                                radius: 12
                                                color: chipArea1.containsMouse ? "#333333" : "#242424"
                                                border.color: "#3a3a3a"
                                                MouseArea {
                                                    id: chipArea1
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: {
                                                        if (captionInput.text.trim() === "") captionInput.text = modelData;
                                                        else captionInput.text = captionInput.text + "、" + modelData;
                                                    }
                                                }
                                                Text {
                                                    id: chipT1
                                                    anchors.centerIn: parent
                                                    text: "+ " + modelData
                                                    color: chipArea1.containsMouse ? "#60a5fa" : "#b3b3b3"
                                                    font.pixelSize: 11
                                                }
                                            }
                                        }
                                    }
                                }

                                // B. 声質・質感 (Timbre / Texture)
                                RowLayout {
                                    spacing: 8
                                    Rectangle {
                                        width: 80; height: 24; radius: 6
                                        color: "#2610b981"
                                        Text { anchors.centerIn: parent; text: "声質・質感"; color: "#34d399"; font.pixelSize: 10; font.bold: true }
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        Repeater {
                                            model: ["ハスキー・擦れ声", "息混じり色気", "澄んだ透明感", "乾いた素朴さ", "芯のある通る声", "掠れた渋み"]
                                            delegate: Rectangle {
                                                height: 24
                                                width: chipT2.implicitWidth + 16
                                                radius: 12
                                                color: chipArea2.containsMouse ? "#333333" : "#242424"
                                                border.color: "#3a3a3a"
                                                MouseArea {
                                                    id: chipArea2
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: {
                                                        if (captionInput.text.trim() === "") captionInput.text = modelData;
                                                        else captionInput.text = captionInput.text + "、" + modelData;
                                                    }
                                                }
                                                Text {
                                                    id: chipT2
                                                    anchors.centerIn: parent
                                                    text: "+ " + modelData
                                                    color: chipArea2.containsMouse ? "#34d399" : "#b3b3b3"
                                                    font.pixelSize: 11
                                                }
                                            }
                                        }
                                    }
                                }

                                // C. 口調・演技 (Style / Tone)
                                RowLayout {
                                    spacing: 8
                                    Rectangle {
                                        width: 80; height: 24; radius: 6
                                        color: "#26f59e0b"
                                        Text { anchors.centerIn: parent; text: "口調・演技"; color: "#fbbf24"; font.pixelSize: 10; font.bold: true }
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        Repeater {
                                            model: ["ぶっきらぼう・自嘲", "丁寧・敬語", "威厳・重厚", "気だるげ", "ツンデレ", "熱血・荒々しい", "淡々と話す"]
                                            delegate: Rectangle {
                                                height: 24
                                                width: chipT3.implicitWidth + 16
                                                radius: 12
                                                color: chipArea3.containsMouse ? "#333333" : "#242424"
                                                border.color: "#3a3a3a"
                                                MouseArea {
                                                    id: chipArea3
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: {
                                                        if (captionInput.text.trim() === "") captionInput.text = modelData;
                                                        else captionInput.text = captionInput.text + "、" + modelData;
                                                    }
                                                }
                                                Text {
                                                    id: chipT3
                                                    anchors.centerIn: parent
                                                    text: "+ " + modelData
                                                    color: chipArea3.containsMouse ? "#fbbf24" : "#b3b3b3"
                                                    font.pixelSize: 11
                                                }
                                            }
                                        }
                                    }
                                }

                                // D. 年代・キャラクター像 (Age / Persona)
                                RowLayout {
                                    spacing: 8
                                    Rectangle {
                                        width: 80; height: 24; radius: 6
                                        color: "#268b5cf6"
                                        Text { anchors.centerIn: parent; text: "年代・像"; color: "#a78bfa"; font.pixelSize: 10; font.bold: true }
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        Repeater {
                                            model: ["青年 (20代)", "壮年 (40代)", "老年 (渋みベテラン)", "少年少女", "お姉さん", "知的な参謀"]
                                            delegate: Rectangle {
                                                height: 24
                                                width: chipT4.implicitWidth + 16
                                                radius: 12
                                                color: chipArea4.containsMouse ? "#333333" : "#242424"
                                                border.color: "#3a3a3a"
                                                MouseArea {
                                                    id: chipArea4
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: {
                                                        if (captionInput.text.trim() === "") captionInput.text = modelData;
                                                        else captionInput.text = captionInput.text + "、" + modelData;
                                                    }
                                                }
                                                Text {
                                                    id: chipT4
                                                    anchors.centerIn: parent
                                                    text: "+ " + modelData
                                                    color: chipArea4.containsMouse ? "#a78bfa" : "#b3b3b3"
                                                    font.pixelSize: 11
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // ====================================================
                        // セクション 3: 🎛 詳細スタジオチューナー (アコーディオン展開)
                        // ====================================================
                        Rectangle {
                            Layout.fillWidth: true
                            radius: 12
                            color: "#202020"
                            border.color: tunerCard.showAdvanced ? "#1db954" : "#2c2c2c"
                            border.width: 1
                            Layout.preferredHeight: tunerCard.showAdvanced ? advInnerCol.implicitHeight + 28 : 46
                            clip: true

                            Behavior on Layout.preferredHeight {
                                NumberAnimation { duration: 240; easing.type: Easing.OutQuad }
                            }

                            ColumnLayout {
                                id: advInnerCol
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 16

                                // 開閉トグルバー
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 10
                                    MouseArea {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 24
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: tunerCard.showAdvanced = !tunerCard.showAdvanced

                                        RowLayout {
                                            anchors.fill: parent
                                            spacing: 8
                                            Text { text: "🎛"; font.pixelSize: 14 }
                                            Text {
                                                text: "詳細スタジオチューナー (プロ向け拘束力・抑揚・シード調整)"
                                                color: "#ffffff"
                                                font.pixelSize: 13
                                                font.bold: true
                                            }
                                            Item { Layout.fillWidth: true }
                                            Text {
                                                text: tunerCard.showAdvanced ? "▲ 折りたたむ" : "▼ 詳細設定を展開"
                                                color: "#1db954"
                                                font.pixelSize: 12
                                                font.bold: true
                                            }
                                        }
                                    }
                                }

                                // 展開される詳細パラメータ群
                                ColumnLayout {
                                    visible: tunerCard.showAdvanced
                                    Layout.fillWidth: true
                                    spacing: 16

                                    // A. 演出プロンプト反映度 (CFG Scale Caption)
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        RowLayout {
                                            Text { text: "演出プロンプト反映度 (CFG Scale Caption)"; color: "#e0e0e0"; font.pixelSize: 12; font.bold: true }
                                            Item { Layout.fillWidth: true }
                                            Text {
                                                text: cfgSlider.value.toFixed(1) + " (推奨: 2.5〜3.5)"
                                                color: "#1db954"; font.pixelSize: 12; font.bold: true
                                            }
                                        }
                                        Text {
                                            text: "数値を高くすると、声優オマージュや指定した演技プロンプトへの拘束力が強くなります。"
                                            color: "#888888"; font.pixelSize: 11
                                        }
                                        Slider {
                                            id: cfgSlider
                                            Layout.fillWidth: true
                                            from: 1.0; to: 5.0; value: tunerCard.cfgScaleCaption; stepSize: 0.1
                                            onValueChanged: tunerCard.cfgScaleCaption = value
                                        }
                                    }

                                    // B. 声の抑揚・自然さ (Sway Coefficient)
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        RowLayout {
                                            Text { text: "声の抑揚・感情の波 (Sway Coeff)"; color: "#e0e0e0"; font.pixelSize: 12; font.bold: true }
                                            Item { Layout.fillWidth: true }
                                            Text {
                                                text: swaySlider.value.toFixed(2) + " (推奨: -1.0)"
                                                color: "#1db954"; font.pixelSize: 12; font.bold: true
                                            }
                                        }
                                        Text {
                                            text: "サンプリングの揺らぎ。声優らしい感情のダイナミクスや自然な抑揚をコントロールします。"
                                            color: "#888888"; font.pixelSize: 11
                                        }
                                        Slider {
                                            id: swaySlider
                                            Layout.fillWidth: true
                                            from: -2.0; to: 0.0; value: tunerCard.swayCoeff; stepSize: 0.05
                                            onValueChanged: tunerCard.swayCoeff = value
                                        }
                                    }

                                    // C. 生成品質 / サンプリングステップ数
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        RowLayout {
                                            Text { text: "サンプリングステップ数 (生成品質)"; color: "#e0e0e0"; font.pixelSize: 12; font.bold: true }
                                            Item { Layout.fillWidth: true }
                                            Text {
                                                text: tunerCard.numSteps + " steps"
                                                color: "#1db954"; font.pixelSize: 12; font.bold: true
                                            }
                                        }
                                        Row {
                                            spacing: 8
                                            Repeater {
                                                model: [
                                                    { label: "Fast (16)", steps: 16 },
                                                    { label: "Balanced (24)", steps: 24 },
                                                    { label: "Studio HQ (32)", steps: 32 },
                                                    { label: "Master (40)", steps: 40 }
                                                ]
                                                delegate: Rectangle {
                                                    height: 28
                                                    width: stepBtnText.implicitWidth + 20
                                                    radius: 14
                                                    color: tunerCard.numSteps === modelData.steps ? "#1db954" : "#2c2c2c"
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        cursorShape: Qt.PointingHandCursor
                                                        onClicked: tunerCard.numSteps = modelData.steps
                                                    }
                                                    Text {
                                                        id: stepBtnText
                                                        anchors.centerIn: parent
                                                        text: modelData.label
                                                        color: tunerCard.numSteps === modelData.steps ? "#000000" : "#b3b3b3"
                                                        font.pixelSize: 11
                                                        font.bold: true
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    // D. 話者シード固定 & ランダムダイス
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 14
                                        ColumnLayout {
                                            spacing: 2
                                            Text { text: "話者シード固定 (Seed Lock)"; color: "#e0e0e0"; font.pixelSize: 12; font.bold: true }
                                            Text {
                                                text: "シードを固定すると、小説全編で同一の声質・トーンを完全維持します。"
                                                color: "#888888"; font.pixelSize: 11
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                        // ランダムダイスボタン
                                        Rectangle {
                                            height: 32
                                            width: diceRow.implicitWidth + 18
                                            radius: 16
                                            color: "#2c2c2c"
                                            border.color: "#3d3d3d"
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    tunerCard.currentSeed = Math.floor(Math.random() * 999999) + 1;
                                                }
                                            }
                                            RowLayout {
                                                id: diceRow
                                                anchors.centerIn: parent
                                                spacing: 6
                                                Text { text: "🎲"; font.pixelSize: 13 }
                                                Text {
                                                    text: "Seed: " + tunerCard.currentSeed
                                                    color: "#ffffff"
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                }
                                            }
                                        }
                                        Switch {
                                            checked: tunerCard.seedLocked
                                            onCheckedChanged: tunerCard.seedLocked = checked
                                        }
                                    }
                                }
                            }
                        }

                        // ====================================================
                        // セクション 4: Gemini 感情台本 & 話速スライダー
                        // ====================================================
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16

                            // Gemini 感情絵文字スイッチ
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 52
                                radius: 10
                                color: geminiSwitch.checked ? "#1a1db954" : "#222222"
                                border.color: geminiSwitch.checked ? "#401db954" : "#333333"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 10
                                    Text { text: "🎭"; font.pixelSize: 18 }
                                    ColumnLayout {
                                        spacing: 1
                                        Text { text: "Gemini 感情絵文字演出 (生きた演技)"; color: "#ffffff"; font.pixelSize: 12; font.bold: true }
                                        Text { text: "Geminiが笑い(🤭)やため息(😮‍💨)を注入した台本を自動生成"; color: "#888888"; font.pixelSize: 10 }
                                    }
                                    Item { Layout.fillWidth: true }
                                    Switch {
                                        id: geminiSwitch
                                        checked: true
                                    }
                                }
                            }

                            // 話速スライダー
                            Rectangle {
                                Layout.preferredWidth: 260
                                Layout.preferredHeight: 52
                                radius: 10
                                color: "#222222"
                                border.color: "#333333"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 10
                                    ColumnLayout {
                                        spacing: 1
                                        Text { text: "話速 (Pace)"; color: "#b3b3b3"; font.pixelSize: 11 }
                                        Text {
                                            text: paceSlider.value.toFixed(2) + "x"
                                            color: "#1db954"; font.pixelSize: 12; font.bold: true
                                        }
                                    }
                                    Slider {
                                        id: paceSlider
                                        Layout.fillWidth: true
                                        from: 0.7; to: 1.4; value: 1.0; stepSize: 0.05
                                    }
                                }
                            }
                        }

                        // ====================================================
                        // セクション 5: 試し聞きセリフ & Spotify 風再生・確定バー
                        // ====================================================
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: "🎧 試し聞きセリフ (小説内の代表セリフ)"; color: "#b3b3b3"; font.pixelSize: 12 }
                            TextField {
                                id: sampleInput
                                Layout.fillWidth: true
                                placeholderText: "喋らせたいセリフを入力してください"
                                text: page.currentCharacter() ? page.currentCharacter().sample_line : "まったく……俺の声の調子はどうだ？悪くない響きだろ。"
                                color: "#ffffff"
                                font.pixelSize: 13
                                padding: 12
                                background: Rectangle {
                                    radius: 8
                                    color: "#222222"
                                    border.color: parent.activeFocus ? "#1db954" : "#333333"
                                }
                            }
                        }

                        // ----------------------------------------------------
                        // 🌟 Voice Blueprint（音声設計図）適用テレメトリー
                        // ----------------------------------------------------
                        Rectangle {
                            Layout.fillWidth: true
                            height: 44
                            radius: 10
                            color: "#16201a"
                            border.color: "#284a33"
                            border.width: 1

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 12

                                RowLayout {
                                    spacing: 6
                                    Text { text: "📐"; font.pixelSize: 13 }
                                    Text { text: "音声設計図:"; color: "#888888"; font.pixelSize: 11; font.bold: true }
                                }

                                // 性別タグ
                                Rectangle {
                                    height: 22
                                    width: bpGenderText.implicitWidth + 12
                                    radius: 11
                                    color: tunerCard.selectedGender === "male" ? "#263b82f6" : (tunerCard.selectedGender === "female" ? "#26ec4899" : "#268b5cf6")
                                    Text {
                                        id: bpGenderText
                                        anchors.centerIn: parent
                                        text: tunerCard.selectedGender === "male" ? "♂ 男性低音拘束" : (tunerCard.selectedGender === "female" ? "♀ 女性高音拘束" : "🧒 少年・中性")
                                        color: tunerCard.selectedGender === "male" ? "#60a5fa" : (tunerCard.selectedGender === "female" ? "#f472b6" : "#a78bfa")
                                        font.pixelSize: 10
                                        font.bold: true
                                    }
                                }

                                // 拘束力 (CFG)
                                Text {
                                    text: "CFG: " + tunerCard.cfgScaleCaption.toFixed(1) + (tunerCard.cfgScaleCaption >= 3.2 ? " (強拘束)" : "")
                                    color: "#1db954"
                                    font.pixelSize: 11
                                    font.bold: true
                                }

                                // 抑揚
                                Text {
                                    text: "Sway: " + tunerCard.swayCoeff.toFixed(2)
                                    color: "#b3b3b3"
                                    font.pixelSize: 11
                                }

                                // ステップ数 & シード
                                Text {
                                    text: tunerCard.numSteps + " steps • " + (tunerCard.seedLocked ? ("Seed #" + tunerCard.currentSeed) : "Random Seed")
                                    color: "#b3b3b3"
                                    font.pixelSize: 11
                                }

                                Item { Layout.fillWidth: true }

                                // 反映保証バッジ
                                RowLayout {
                                    spacing: 4
                                    Text { text: "⚡"; font.pixelSize: 11 }
                                    Text { text: "100% 適用中"; color: "#1db954"; font.pixelSize: 10; font.bold: true }
                                }
                            }
                        }

                        // 試聴アクション ＆ 配役保存バー
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14

                            // Spotify 特大再生ボタン
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 48
                                radius: 24 // Spotify Pill
                                color: previewMouseArea.containsPress ? "#169c46" : (previewMouseArea.containsMouse ? "#1ed760" : "#1db954")

                                MouseArea {
                                    id: previewMouseArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        var ch = page.currentCharacter();
                                        var vid = "none";
                                        var opts = {
                                            "gender": tunerCard.selectedGender,
                                            "cfg_scale_caption": tunerCard.cfgScaleCaption,
                                            "sway_coeff": tunerCard.swayCoeff,
                                            "num_steps": tunerCard.numSteps,
                                            "seed": tunerCard.seedLocked ? tunerCard.currentSeed : null
                                        };
                                        page.previewRequested(
                                            sampleInput.text,
                                            vid,
                                            captionInput.text,
                                            paceSlider.value,
                                            geminiSwitch.checked,
                                            opts
                                        );
                                    }
                                }

                                RowLayout {
                                    anchors.centerIn: parent
                                    spacing: 10
                                    Text {
                                        text: page.isPlayingPreview ? "🔊" : "▶"
                                        color: "#000000"
                                        font.pixelSize: 16
                                        font.bold: true
                                    }
                                    Text {
                                        text: page.isPlayingPreview
                                              ? ("🔊 " + (tunerCard.selectedGender === "male" ? "♂ " : (tunerCard.selectedGender === "female" ? "♀ " : "🧒 ")) + tunerCard.selectedVoiceName + " を再生中…")
                                              : ("▶ " + (tunerCard.selectedGender === "male" ? "【♂ 男性声】" : (tunerCard.selectedGender === "female" ? "【♀ 女性声】" : "【🧒 少年声】")) + tunerCard.selectedVoiceName + " で声を聴いてみる")
                                        color: "#000000"
                                        font.pixelSize: 13
                                        font.bold: true
                                    }
                                }
                            }

                            // 「この配役で決定」ボタン
                            Button {
                                Layout.preferredHeight: 48
                                Layout.preferredWidth: 190
                                text: "この配役で決定"
                                contentItem: Text {
                                    text: parent.text
                                    color: "#ffffff"
                                    font.pixelSize: 13
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    radius: 24
                                    color: parent.hovered ? "#333333" : "#242424"
                                    border.color: "#3d3d3d"
                                    border.width: 1
                                }
                                onClicked: {
                                    var ch = page.currentCharacter();
                                    if (ch && page.book) {
                                        var vid = "irodori_custom";
                                        page.assignRequested(page.book.id, ch.character_id, vid, vid + "i", true);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------------
    // 小説全体への適用 確認モーダルダイアログ
    // ------------------------------------------------------------------------
    Dialog {
        id: applyDialog
        anchors.centerIn: parent
        width: 440
        modal: true
        padding: 24

        background: Rectangle {
            color: "#151824"
            radius: 16
            border.color: "#1affffff"
            border.width: 1
        }

        contentItem: ColumnLayout {
            spacing: 16

            RowLayout {
                spacing: 12
                Rectangle {
                    width: 40; height: 40; radius: 12
                    color: "#336366f1"
                    Text { anchors.centerIn: parent; text: "✨"; font.pixelSize: 20 }
                }
                ColumnLayout {
                    spacing: 2
                    Text {
                        text: "小説全体に配役を適用しますか？"
                        color: "#ffffff"
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Text {
                        text: page.book ? (page.book.title || page.book.id) : ""
                        color: "#818cf8"
                        font.pixelSize: 12
                    }
                }
            }

            Text {
                text: "現在のキャスティング設定とIrodori Anime声優モデルを小説全体に反映し、全編の音声を再生成します。\n\nGeminiによる感情絵文字演出が適用され、キャラクターが生き生きと演技します。"
                color: "#cbd5e1"
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Item { Layout.fillWidth: true }

                Button {
                    text: "キャンセル"
                    flat: true
                    contentItem: Text { text: parent.text; color: "#a1a1aa"; font.pixelSize: 13 }
                    onClicked: applyDialog.close()
                }

                Rectangle {
                    Layout.preferredHeight: 38
                    Layout.preferredWidth: 140
                    radius: 8
                    color: "#6366f1"
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            applyDialog.close();
                            if (page.book) {
                                page.applyAllRequested(page.book.id, "irodori");
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        text: "適用して再生成"
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
            }
        }
    }
}


pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtMultimedia 6.0

ApplicationWindow {
    id: root
    width: 1280; height: 830; visible: true
    title: "AIStoryActingEngine"
    color: "#121212"
    minimumWidth: 1000; minimumHeight: 680

    readonly property color cAccent: "#1db954"

    // ---- state ----
    property string currentPage: "library"
    property var currentBook: null
    property string statusText: "Worker 起動中…"
    property bool workerRunning: false
    property string currentSeriesId: ""  // 選択中書籍のシリーズ（キャスティング参照用）

    ListModel { id: booksModel }
    ListModel { id: chaptersModel }
    ListModel { id: eventsModel }
    ListModel { id: voiceProfilesModel }
    ListModel { id: castingsModel }

    MediaPlayer { id: player; audioOutput: audioOut }
    AudioOutput { id: audioOut; volume: 0.8 }

    MediaPlayer { id: previewPlayer; audioOutput: previewAudioOut }
    AudioOutput { id: previewAudioOut; volume: 0.9 }

    // ---- helpers ----
    function fmtTime(ms) {
        var s = Math.max(0, Math.floor((ms || 0) / 1000))
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
        return h > 0 ? h + ":" + ("0" + m).slice(-2) + ":" + ("0" + s % 60).slice(-2)
                     : ("0" + m).slice(-2) + ":" + ("0" + s % 60).slice(-2)
    }
    function toFileUrl(p) {
        if (!p) return ""
        var n = String(p).replace(/\\/g, "/")
        return n.indexOf("://") >= 0 ? n : encodeURI("file:///" + n)
    }
    function openBook(bookId) { statusText = "読み込み中…"; bridge.getBook(bookId); bridge.getCastings(bookId) }
    function playBook(book) {
        currentBook = book
        chaptersModel.clear()
        var chs = book.chapters || []
        for (var i = 0; i < chs.length; ++i) chaptersModel.append(chs[i])
        var url = toFileUrl((book.audio || {}).path || "")
        if (url) { player.source = url; player.play() }
        currentPage = "player"
        statusText = "再生中: " + book.title
    }
    function seekTo(sec) { player.setPosition(Math.round(sec * 1000)) }

    // ---- bridge wiring ----
    Connections {
        target: bridge
        function onRunningChanged(r) {
            root.workerRunning = r
            if (r) {
                root.statusText = "接続完了 — 書籍一覧を取得中…"
                bridge.listBooks()
                bridge.listVoiceProfiles()
            }
        }
        function onBooksLoaded(books) {
            booksModel.clear()
            for (var i = 0; i < books.length; ++i) booksModel.append(books[i])
            root.statusText = books.length + " 冊の本"
            if (books.length > 0 && !root.currentBook) {
                root.currentBook = books[0]
            }
        }
        function onBookLoaded(book) {
            if (book && book.ok !== false) root.playBook(book)
        }
        function onEventsLoaded(ev) {
            eventsModel.clear()
            for (var i = 0; i < ev.length; ++i) eventsModel.append(ev[i])
        }
        function onVoiceProfilesLoaded(profiles) {
            voiceProfilesModel.clear()
            for (var i = 0; i < profiles.length; ++i) voiceProfilesModel.append(profiles[i])
        }
        function onCastingsLoaded(castings, seriesId) {
            castingsModel.clear()
            for (var i = 0; i < castings.length; ++i) castingsModel.append(castings[i])
            root.currentSeriesId = seriesId || ""
        }
        function onVoiceProfileSaved(voiceId) {
            root.statusText = "✓ ボイス保存完了: " + voiceId
            bridge.listVoiceProfiles()
        }
        function onVoiceProfileDeleted(voiceId) {
            root.statusText = "✓ ボイス削除完了: " + voiceId
            bridge.listVoiceProfiles()
        }
        function onCastingAssigned(characterId, voiceId) {
            root.statusText = "✓ 配役完了: " + characterId + " → " + voiceId
            if (root.currentBook) bridge.getCastings(root.currentBook.id)
        }
        function onVoicePreviewReady(path) {
            console.log("[preview] voicePreviewReady received:", path)
            root.statusText = "▶ プレビュー音声を再生中…"
            var url = root.toFileUrl(path)
            console.log("[preview] loading url:", url)
            previewPlayer.source = url
            previewPlayer.play()
        }
        function onCharacterVoiceImagined(voiceDesign) {
            root.statusText = "✨ キャラクターから声を想像しました: " + (voiceDesign.concept_summary || "")
            if (castingPage && castingPage.applyImaginedVoice) {
                castingPage.applyImaginedVoice(voiceDesign)
            }
        }
        function onDocumentImported(novelPath, title) {
            root.statusText = "✓ ドキュメント取り込み完了: " + title + " — 解析ジョブを開始します"
            bridge.startJob(novelPath, "edge", false, false)
            root.currentPage = "studio"
            bridge.listEvents(80)
        }
        function onErrorOccurred(code, message) { root.statusText = "⚠ " + message }
        function onLogMessage(line) { console.log("[worker]", line) }
    }

    // ---- layout ----
    Row {
        anchors.fill: parent

        // ===== sidebar =====
        Rectangle {
            width: 240; height: parent.height
            color: "#111117"
            border.color: "#1c1c28"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent; anchors.margins: 16; spacing: 6

                // ブランドヘッダー
                ColumnLayout {
                    spacing: 2
                    Layout.leftMargin: 6; Layout.bottomMargin: 18; Layout.topMargin: 8
                    RowLayout {
                        spacing: 8
                        Rectangle {
                            width: 32; height: 32; radius: 8
                            color: "#192d20"
                            border.color: "#2a5436"
                            border.width: 1
                            Text { anchors.centerIn: parent; text: "🎧"; font.pixelSize: 18 }
                        }
                        Text {
                            text: "AISAE"
                            color: "#ffffff"
                            font.pixelSize: 20
                            font.bold: true
                            font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                        }
                    }
                    Text {
                        text: "AI Story Acting Engine"
                        color: "#8a8a9e"
                        font.pixelSize: 10
                        font.bold: true
                        Layout.leftMargin: 2
                    }
                }

                // ナビゲーション一覧
                Repeater {
                    model: [
                        { key: "library", label: "My Bookshelf", icon: "📗" },
                        { key: "player", label: "Player", icon: "▷" },
                        { key: "casting", label: "Casting Studio", icon: "📹" },
                        { key: "voiceStudio", label: "Voice Lab", icon: "🎙" },
                        { key: "settings", label: "Settings", icon: "⚙" }
                    ]
                    delegate: Rectangle {
                        id: navItem
                        required property var modelData
                        Layout.fillWidth: true
                        height: 44
                        radius: 12
                        color: navMa.containsMouse ? "#1c1f2e" : "transparent"

                        // アクティブ時はエメラルドグリーンの発光グラデーション
                        Rectangle {
                            anchors.fill: parent
                            radius: 12
                            visible: root.currentPage === modelData.key
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "#10b981" }
                                GradientStop { position: 1.0; color: "#059669" }
                            }
                        }

                        Behavior on color { ColorAnimation { duration: 120 } }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 12

                            Text {
                                text: modelData.icon
                                font.pixelSize: 14
                                opacity: root.currentPage === modelData.key ? 1.0 : 0.7
                            }
                            Text {
                                text: modelData.label
                                color: root.currentPage === modelData.key ? "#ffffff" : "#9499b0"
                                font.pixelSize: 13
                                font.bold: true
                                Layout.fillWidth: true
                            }
                        }

                        MouseArea {
                            id: navMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                root.currentPage = modelData.key
                                if (modelData.key === "casting" && root.currentBook) bridge.getCastings(root.currentBook.id)
                                if (modelData.key === "voiceStudio") bridge.listVoiceProfiles()
                            }
                        }
                    }
                }

                Item { Layout.preferredHeight: 14 }

                // セカンダリナビゲーション (Projects, Community, Library)
                Repeater {
                    model: [
                        { label: "Projects", icon: "📁" },
                        { label: "Community", icon: "👥" },
                        { label: "Studio Logs", icon: "📊" }
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        height: 38
                        radius: 8
                        color: subNavMa.containsMouse ? "#181a24" : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 12
                            Text { text: modelData.icon; font.pixelSize: 13; opacity: 0.6 }
                            Text { text: modelData.label; color: "#747890"; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true }
                        }
                        MouseArea {
                            id: subNavMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (modelData.label === "Studio Logs") {
                                    root.currentPage = "studio"
                                    bridge.listEvents(80)
                                }
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // ステータスバナー（下部）
                Rectangle {
                    Layout.fillWidth: true
                    height: colStatus.implicitHeight + 20
                    radius: 10
                    color: "#161622"
                    border.color: "#222232"
                    border.width: 1

                    ColumnLayout {
                        id: colStatus
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6

                        RowLayout {
                            spacing: 8
                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: root.workerRunning ? root.cAccent : "#e05555"
                                SequentialAnimation on opacity {
                                    loops: Animation.Infinite
                                    running: root.workerRunning
                                    NumberAnimation { to: 0.3; duration: 800 }
                                    NumberAnimation { to: 1.0; duration: 800 }
                                }
                            }
                            Text {
                                text: root.workerRunning ? "Engine Online" : "Engine Offline"
                                color: root.workerRunning ? root.cAccent : "#e05555"
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }

                        Text {
                            text: root.statusText
                            color: "#808092"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        // ===== main area =====
        Item {
            width: parent.width - 240; height: parent.height

            StackLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: nowPlayingBar.top
                currentIndex: root.currentPage === "library" ? 0
                            : root.currentPage === "player" ? 1
                            : root.currentPage === "casting" ? 2
                            : root.currentPage === "voiceStudio" ? 3
                            : root.currentPage === "settings" ? 4 : 5
                BookshelfPage {
                    books: booksModel
                    accent: root.cAccent
                    activeBookId: root.currentBook ? root.currentBook.id : ""
                    onOpenBook: (bid) => root.openBook(bid)
                    onImportRequested: importDialog.open()
                }
                PlayerPage {
                    book: root.currentBook
                    player: player
                    chapters: chaptersModel
                    accent: root.cAccent
                    onSeekRequested: (sec) => root.seekTo(sec)
                }
                CastingPage {
                    id: castingPage
                    book: root.currentBook
                    seriesId: root.currentSeriesId
                    castings: castingsModel
                    voiceProfiles: voiceProfilesModel
                    accent: root.cAccent
                    atlasConnected: bridge.atlasConnected
                    isPlayingPreview: previewPlayer.playbackState === MediaPlayer.PlayingState
                    onAssignRequested: (bid, cid, vext, vint, locked) => {
                        bridge.assignCasting(bid, cid, vext, vint, locked, "")
                    }
                    onPreviewRequested: (txt, vid, cap, pac, gemini, options) => {
                        bridge.previewVoiceIrodori(txt, vid, cap, pac, gemini, options || {})
                    }
                    onImagineRequested: (bid, cid) => {
                        root.statusText = "🧠 キャラクターから声を想像中…"
                        bridge.imagineCharacterVoice(bid, cid)
                    }
                    onApplyAllRequested: (bid, prov) => {
                        bridge.applyCastingsAndRegen(bid, prov)
                        root.statusText = "✨ 小説全体への配役適用ジョブを開始しました"
                        root.currentPage = "studio"
                        bridge.listEvents(80)
                    }
                    onToggleAtlasRequested: (conn) => {
                        bridge.atlasConnected = conn
                    }
                    onRefreshRequested: (bid) => bridge.getCastings(bid)
                }
                VoiceStudioPage {
                    voiceProfiles: voiceProfilesModel
                    accent: root.cAccent
                    onRefreshRequested: () => bridge.listVoiceProfiles()
                    onSaveRequested: (prof) => bridge.saveVoiceProfile(prof)
                    onDeleteRequested: (vid) => bridge.deleteVoiceProfile(vid)
                    onPreviewRequested: (txt, vid, sty, pit, pac, prov) => {
                        bridge.previewVoice(txt, vid, sty, pit, pac, prov)
                    }
                }
                SettingsPage {
                    accent: root.cAccent
                }
                StudioPage {
                    book: root.currentBook
                    events: eventsModel
                }
            }

            // ドッキングされた NowPlayingBar (下部に固定されコンテンツと絶対に被らない)
            NowPlayingBar {
                id: nowPlayingBar
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                player: player
                book: root.currentBook
                accent: root.cAccent
                onOpenPlayer: root.currentPage = "player"
                onOpenStudio: { root.currentPage = "studio"; bridge.listEvents(80) }
                onOpenSettings: root.currentPage = "settings"
            }
        }
    }

    // ---- 書籍インポートダイアログ ----
    Dialog {
        id: importDialog
        title: "📥 書籍の取り込み (PDF / 画像 / テキスト)"
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: parent
        width: 500
        background: Rectangle {
            radius: 16
            color: "#161622"
            border.color: "#28283a"
            border.width: 1
        }

        contentItem: ColumnLayout {
            spacing: 16
            Text {
                text: "小説ファイル（PDF、テキストファイル、または画像）を指定してください:"
                color: "#b0b0c2"; font.pixelSize: 13
                wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            ColumnLayout {
                spacing: 6; Layout.fillWidth: true
                Text { text: "本のタイトル"; color: "#8a8a9e"; font.pixelSize: 11; font.bold: true }
                TextField {
                    id: importTitleInput
                    Layout.fillWidth: true
                    height: 38
                    placeholderText: "星詠みのアルカディア 第1巻"
                    color: "#ffffff"
                    background: Rectangle {
                        radius: 8
                        color: "#20202e"
                        border.color: "#303045"
                        border.width: 1
                    }
                }
            }
            ColumnLayout {
                spacing: 6; Layout.fillWidth: true
                Text { text: "ファイルパス (またはカンマ区切りの画像パス)"; color: "#8a8a9e"; font.pixelSize: 11; font.bold: true }
                TextField {
                    id: importPathInput
                    Layout.fillWidth: true
                    height: 38
                    placeholderText: "C:/path/to/novel.txt または .pdf"
                    color: "#ffffff"
                    background: Rectangle {
                        radius: 8
                        color: "#20202e"
                        border.color: "#303045"
                        border.width: 1
                    }
                }
            }
        }

        onAccepted: {
            var paths = importPathInput.text.split(",").map(function(p) { return p.trim() }).filter(function(p) { return p.length > 0 })
            if (paths.length > 0) {
                root.statusText = "ドキュメントを取り込み中…"
                bridge.importDocument(paths, importTitleInput.text)
            }
        }
    }

    Component.onCompleted: {
        bridge.listBooks()
        bridge.listVoiceProfiles()
    }
}

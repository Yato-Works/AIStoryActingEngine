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
        function onRunningChanged(r) { root.workerRunning = r }
        function onBooksLoaded(books) {
            booksModel.clear()
            for (var i = 0; i < books.length; ++i) booksModel.append(books[i])
            root.statusText = books.length + " 冊の本"
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
            root.statusText = "▶ プレビュー再生中…"
            previewPlayer.source = root.toFileUrl(path)
            previewPlayer.play()
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
            width: 230; height: parent.height; color: "#181818"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 14; spacing: 4
                Text {
                    text: "🎧 AIAE"; color: "#eeeeee"
                    font.pixelSize: 22; font.bold: true
                    Layout.leftMargin: 8; Layout.bottomMargin: 14
                }
                Repeater {
                    model: [
                        { key: "library", label: "📚 本棚" },
                        { key: "player", label: "▶ プレイヤー" },
                        { key: "casting", label: "🎭 キャスティング" },
                        { key: "voiceStudio", label: "🎙 ボイス作成" },
                        { key: "studio", label: "📊 ログ・進捗" }
                    ]
                    delegate: Button {
                        required property var modelData
                        text: modelData.label
                        Layout.fillWidth: true
                        flat: true
                        highlighted: root.currentPage === modelData.key
                        onClicked: {
                            root.currentPage = modelData.key
                            if (modelData.key === "studio") bridge.listEvents(80)
                            if (modelData.key === "casting" && root.currentBook) bridge.getCastings(root.currentBook.id)
                            if (modelData.key === "voiceStudio") bridge.listVoiceProfiles()
                        }
                    }
                }
                Item { Layout.fillHeight: true }
                RowLayout {
                    spacing: 6; Layout.leftMargin: 8
                    Rectangle {
                        width: 9; height: 9; radius: 4
                        color: root.workerRunning ? root.cAccent : "#e05555"
                    }
                    Text {
                        text: root.workerRunning ? "Worker 接続中" : "Worker 停止中"
                        color: "#a0a0a0"; font.pixelSize: 12
                    }
                }
                Text {
                    text: root.statusText; color: "#777777"; font.pixelSize: 11
                    wrapMode: Text.WordWrap; Layout.fillWidth: true; Layout.leftMargin: 8
                }
            }
        }

        // ===== main column =====
        ColumnLayout {
            width: parent.width - 230; height: parent.height; spacing: 0
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                currentIndex: root.currentPage === "library" ? 0
                            : root.currentPage === "player" ? 1
                            : root.currentPage === "casting" ? 2
                            : root.currentPage === "voiceStudio" ? 3 : 4
                BookshelfPage {
                    books: booksModel
                    accent: root.cAccent
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
                    book: root.currentBook
                    castings: castingsModel
                    voiceProfiles: voiceProfilesModel
                    accent: root.cAccent
                    onAssignRequested: (bid, cid, vext, vint, locked) => {
                        bridge.assignCasting(bid, cid, vext, vint, locked, "")
                    }
                    onPreviewRequested: (txt, vid) => {
                        bridge.previewVoice(txt, vid, "Neutral", 0.0, 1.0, "edge")
                    }
                    onRefreshRequested: (bid) => bridge.getCastings(bid)
                }
                VoiceStudioPage {
                    voiceProfiles: voiceProfilesModel
                    accent: root.cAccent
                    onSaveRequested: (prof) => bridge.saveVoiceProfile(prof)
                    onDeleteRequested: (vid) => bridge.deleteVoiceProfile(vid)
                    onPreviewRequested: (txt, vid, sty, pit, pac, prov) => {
                        bridge.previewVoice(txt, vid, sty, pit, pac, prov)
                    }
                }
                StudioPage {
                    book: root.currentBook
                    events: eventsModel
                }
            }
            NowPlayingBar {
                Layout.fillWidth: true
                player: player
                book: root.currentBook
                accent: root.cAccent
                onOpenPlayer: root.currentPage = "player"
                onOpenStudio: { root.currentPage = "studio"; bridge.listEvents(80) }
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
        width: 480
        background: Rectangle { radius: 12; color: "#222222"; border.color: "#333333" }

        contentItem: ColumnLayout {
            spacing: 14
            Text {
                text: "持っている本のファイルパス（PDF / 画像 / TXT）を指定してください:"
                color: "#cccccc"; font.pixelSize: 13
            }
            ColumnLayout {
                spacing: 4; Layout.fillWidth: true
                Text { text: "本のタイトル"; color: "#888888"; font.pixelSize: 11 }
                TextField {
                    id: importTitleInput
                    Layout.fillWidth: true
                    placeholderText: "無職転生 第1巻"
                    color: "#eeeeee"
                    background: Rectangle { radius: 6; color: "#2d2d2d" }
                }
            }
            ColumnLayout {
                spacing: 4; Layout.fillWidth: true
                Text { text: "ファイルパス (またはカンマ区切りの画像パス)"; color: "#888888"; font.pixelSize: 11 }
                TextField {
                    id: importPathInput
                    Layout.fillWidth: true
                    placeholderText: "C:/path/to/novel.txt または .pdf"
                    color: "#eeeeee"
                    background: Rectangle { radius: 6; color: "#2d2d2d" }
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

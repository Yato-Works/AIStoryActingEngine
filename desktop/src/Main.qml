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

    MediaPlayer { id: player; audioOutput: audioOut }
    AudioOutput { id: audioOut; volume: 0.8 }

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
    function openBook(bookId) { statusText = "読み込み中…"; bridge.getBook(bookId) }
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
                        { key: "library", label: "📚 ライブラリ" },
                        { key: "player", label: "▶ プレイヤー" },
                        { key: "studio", label: "🎙 スタジオ" }
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
                            : root.currentPage === "player" ? 1 : 2
                BookshelfPage {
                    books: booksModel
                    accent: root.cAccent
                    onOpenBook: (bid) => root.openBook(bid)
                }
                PlayerPage {
                    book: root.currentBook
                    player: player
                    chapters: chaptersModel
                    accent: root.cAccent
                    onSeekRequested: (sec) => root.seekTo(sec)
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

    Component.onCompleted: bridge.listBooks()
}

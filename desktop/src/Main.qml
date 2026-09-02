import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtMultimedia 6.0

ApplicationWindow {
    id: root
    width: 1100; height: 780; visible: true
    title: "AIStoryActingEngine Studio"
    color: "#faf7f2"

    property string currentPage: "bookshelf"
    property string statusText: "Worker 起動中…"
    property bool workerRunning: false
    property var currentBook: null
    property int currentChapter: -1

    ListModel { id: booksModel }
    ListModel { id: logModel }
    ListModel { id: chaptersModel }

    MediaPlayer { id: audioPlayer; playbackRate: 1.0; audioOutput: audioOut }
    AudioOutput { id: audioOut; volume: 0.8 }

    function jobMark(status) {
        if (status === "completed") return "✓"
        if (status === "failed") return "✗"
        if (status === "cancelled") return "⏸"
        if (status === "running") return "▶"
        if (status === "paused") return "⏸"
        return "○"
    }
    function bookHue(id) {
        var s = String(id || ""); var h = 0
        for (var i = 0; i < s.length; ++i) h = (h * 31 + s.charCodeAt(i)) % 360
        return h / 360.0
    }
    function fmtTime(ms) {
        var sec = Math.max(0, Math.floor((ms || 0) / 1000))
        var h = Math.floor(sec / 3600); var m = Math.floor((sec % 3600) / 60); var s = sec % 60
        var mm = ("0" + m).slice(-2); var ss = ("0" + s).slice(-2)
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss
    }
    function toFileUrl(p) {
        if (!p) return ""
        var norm = String(p).replace(/\\/g, "/")
        if (norm.indexOf("://") >= 0) return norm
        return encodeURI("file:///" + norm)
    }
    function openBook(bookId) { statusText = "読み込み中…"; bridge.getBook(bookId) }
    function loadChapters(book) {
        chaptersModel.clear()
        var chs = book.chapters || []
        for (var i = 0; i < chs.length; ++i) {
            var chap = book.chapters[i]
            var off = chap.offset_seconds
            chaptersModel.append({ title: chap.title || ("Chapter " + chap.chapter), offset: (off === null || off === undefined) ? -1 : Number(off) })
        }
    }
    function updateCurrentChapter() {
        if (chaptersModel.count === 0) { currentChapter = -1; return }
        var pos = audioPlayer.position; var idx = -1
        for (var i = 0; i < chaptersModel.count; ++i) {
            var o = chaptersModel.get(i).offset
            if (o >= 0 && o <= pos) idx = i
        }
        currentChapter = idx
    }


    // ---- connections ----
    Connections {
        target: bridge
        function onRunningChanged(running) { workerRunning = running }
        function onBooksLoaded(books) {
            booksModel.clear()
            for (var i = 0; i < books.length; ++i) booksModel.append(books[i])
        }
        function onBookLoaded(book) {
            currentBook = book
            if (book && book.ok !== false) {
                loadChapters(book)
                var url = toFileUrl(book.audio_path || "")
                if (url) { audioPlayer.source = url; audioPlayer.play() }
                currentPage = "player"
                statusText = "再生中: " + book.title
            }
        }
        function onErrorOccurred(code, message) {
            logModel.append({t: fmtTime(0), msg: "Error " + code + ": " + message})
            statusText = "エラー: " + message
        }
        function onLogMessage(line) { logModel.append({t: new Date().toLocaleTimeString(), msg: line}) }
    }

    // ---- pages ----
    StackLayout {
        anchors.fill: parent; anchors.margins: 8
        currentIndex: currentPage === "bookshelf" ? 0 : (currentPage === "player" ? 1 : 2)

        // BOOKSHELF
        Page {
            GridView {
                anchors.fill: parent; clip: true; model: booksModel
                cellWidth: 180; cellHeight: 270
                delegate: Rectangle {
                    width: 180; height: 270; radius: 10
                    color: Qt.hsla(bookHue(model.book_id), 0.55, 0.92, 1)
                    border.color: "#ddd"
                    Column {
                        anchors.centerIn: parent; width: 160; spacing: 6
                        Image { source: toFileUrl(model.cover_url) || ""; width: 120; height: 160; anchors.horizontalCenter: parent.horizontalCenter; fillMode: Image.PreserveAspectFit }
                        Text { text: model.title || "(untitled)"; font.pixelSize: 14; width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter }
                        Text { text: model.author || ""; color: "#666"; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; width: parent.width }
                        Text { text: model.voice_profile || ""; color: "#888"; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; width: parent.width }
                    }
                    MouseArea { anchors.fill: parent; onClicked: openBook(model.book_id) }
                }
            }
        }

        // PLAYER
        Page {
            ColumnLayout {
                anchors.centerIn: parent; spacing: 16
                Text { text: currentBook ? currentBook.title : "No book"; font.pixelSize: 22; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                Text { text: currentBook ? "by " + currentBook.author : ""; color: "#777"; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
                Slider { id: seek; Layout.fillWidth: true; from: 0; to: Math.max(1, audioPlayer.duration); value: audioPlayer.position || 0; onMoved: audioPlayer.setPosition(value) }
                Row {
                    spacing: 10; anchors.horizontalCenter: parent.horizontalCenter
                    Button { text: audioPlayer.playbackState === MediaPlayer.PlayingState ? "⏸" : "▶"; onClicked: { if (audioPlayer.playbackState === MediaPlayer.PlayingState) audioPlayer.pause(); else audioPlayer.play() } }
                    Button { text: "⏮"; onClicked: audioPlayer.setPosition(0) }
                    Text { text: fmtTime(audioPlayer.position) + " / " + fmtTime(audioPlayer.duration); color: "#555"; font.pixelSize: 13 }
                }
                Button { text: "⇱ Bookshelf"; Layout.fillWidth: true; onClicked: currentPage = "bookshelf" }
                Button { text: "🎙 Studio"; Layout.fillWidth: true; onClicked: currentPage = "studio" }
            }
        }

        // STUDIO
        Page {
            id: studioPage
            readonly property var bk: currentBook || {}
            readonly property var jd: bk.judge || {}
            Column {
                anchors.fill: parent; anchors.margins: 24; spacing: 12
                Text { text: "🎙 Studio"; font.pixelSize: 22 }
                Rectangle {
                    width: parent.width; height: 200; radius: 8; color: "#fff"; border.color: "#ddd"
                    Column {
                        anchors.fill: parent; anchors.margins: 12; spacing: 6
                        Text { text: "Title: " + (studioPage.bk.title || "(none)") }
                        Text { text: "State Delta: " + JSON.stringify(studioPage.bk.state_delta || {}) }
                        Text { text: "Voice Profile: " + JSON.stringify(studioPage.bk.voice_profile || {}) }
                        Text { text: "Performance Plan: " + JSON.stringify(studioPage.bk.performance_plan || {}) }
                        Text { text: "Judge: " + (studioPage.jd.score !== undefined ? studioPage.jd.score : "n/a") + " / " + JSON.stringify(studioPage.jd.feedback || {}) }
                        Text { text: "Audio Metrics: " + JSON.stringify(studioPage.bk.audio_metrics || {}) }
                    }
                }
                Button { text: "⇱ Player"; onClicked: currentPage = "player" }
            }
        }
    }

    Text { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.margins: 8; text: statusText; color: "#666"; font.pixelSize: 12 }

    Component.onCompleted: { bridge.listBooks(); statusText = "Ready" }
}
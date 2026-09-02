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
        if (t === "SCENE_EVENT") return "#e8a13c"
        if (t === "VOICE_STATE_CHANGED") return "#4cc2e0"
        if (t === "JOB_COMPLETED") return "#1db954"
        if (t === "JOB_FAILED") return "#e05555"
        return "#8a8a8a"
    }

    padding: 32
    background: Rectangle { color: "#121212" }

    RowLayout {
        anchors.fill: parent; spacing: 32

        // ---- book detail ----
        ColumnLayout {
            Layout.preferredWidth: 380; Layout.fillHeight: true; spacing: 12
            Text { text: "🎙 スタジオ"; color: "#eeeeee"; font.pixelSize: 26; font.bold: true }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 110; radius: 12
                color: "#1e1e1e"
                RowLayout {
                    anchors.fill: parent; anchors.margins: 14; spacing: 14
                    Rectangle {
                        width: 78; height: 78; radius: 8
                        gradient: Gradient {
                            GradientStop { position: 0; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.42, 0.40) }
                            GradientStop { position: 1; color: Qt.hsla(page.hue(page.book ? page.book.id : ""), 0.50, 0.16) }
                        }
                        Text { anchors.centerIn: parent; text: page.book ? (page.book.title || "?").charAt(0) : "?"; color: "#fff"; opacity: 0.8; font.pixelSize: 34; font.bold: true }
                    }
                    ColumnLayout {
                        spacing: 2; Layout.fillWidth: true
                        Text { text: page.book ? (page.book.title || "(無題)") : "本を選択してください"; color: "#eeeeee"; font.pixelSize: 16; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text { text: page.book ? "id: " + page.book.id : "—"; color: "#777"; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                        Text { text: page.book ? "音声 " + page.book.audio_done + " / " + page.book.segments : ""; color: "#a0a0a0"; font.pixelSize: 12 }
                    }
                }
            }
            Text { text: "工程の進捗・音声メトリクス・Judge レポートは\nEvent Log に流れます (SSOT)"; color: "#666"; font.pixelSize: 12; wrapMode: Text.WordWrap }
            Item { Layout.fillHeight: true }
        }

        // ---- event log ----
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Text { text: "Event Log"; color: "#eeeeee"; font.pixelSize: 18; font.bold: true }
                Item { Layout.fillWidth: true }
                Button {
                    flat: true; text: "⟳ 更新"
                    onClicked: bridge.listEvents(80)
                }
            }
            ListView {
                id: evList
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; spacing: 4
                model: page.events
                ScrollBar.vertical: ScrollBar { }
                delegate: Rectangle {
                    width: evList.width; height: 46; radius: 8
                    color: "#1e1e1e"
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 10; spacing: 10
                        Rectangle {
                            width: 8; height: 8; radius: 4
                            color: page.evColor(model.type)
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Text { text: model.type; color: page.evColor(model.type); font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 170; elide: Text.ElideRight }
                        Text { text: model.payload || ""; color: "#bbbbbb"; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                        Text { text: String(model.ts).replace("T", " ").slice(5, 19); color: "#666"; font.pixelSize: 11 }
                    }
                }
            }
        }
    }
}

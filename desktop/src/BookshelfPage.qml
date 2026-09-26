pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Page {
    id: page
    property var books: null
    property color accent: "#1db954"
    property string searchQuery: ""
    property string sortOrder: "recent"

    signal openBook(string bookId)
    signal importRequested()

    function getThemeIndex(id) {
        var s = String(id || ""), h = 0
        for (var i = 0; i < s.length; ++i) h = (h * 37 + s.charCodeAt(i)) % 4
        return Math.abs(h)
    }

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
            spacing: 20

            ColumnLayout {
                spacing: 3
                RowLayout {
                    spacing: 12
                    Text {
                        text: "My Bookshelf"
                        color: "#ffffff"
                        font.pixelSize: 26
                        font.bold: true
                        font.family: "Segoe UI, Yu Gothic UI, sans-serif"
                    }
                }
                Text {
                    text: (page.books ? page.books.count : 0) + " Books in Library"
                    color: "#7e8299"
                    font.pixelSize: 13
                }
            }

            Item { Layout.fillWidth: true }

            // ソートセレクターピル
            Rectangle {
                height: 38
                width: 105
                radius: 19
                color: "#181a24"
                border.color: "#2a2d3d"
                border.width: 1

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "≡"; color: "#a0a5ba"; font.pixelSize: 13; font.bold: true }
                    Text { text: "Recent ⌄"; color: "#c8ccde"; font.pixelSize: 12; font.bold: true }
                }
            }

            // 検索バー
            Rectangle {
                height: 38
                width: 190
                radius: 19
                color: "#181a24"
                border.color: searchInput.activeFocus ? page.accent : "#2a2d3d"
                border.width: 1
                Behavior on border.color { ColorAnimation { duration: 150 } }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 12
                    spacing: 8
                    Text { text: "🔍"; color: "#666a80"; font.pixelSize: 12 }
                    TextInput {
                        id: searchInput
                        Layout.fillWidth: true
                        color: "#ffffff"
                        font.pixelSize: 12
                        selectByMouse: true
                        Text {
                            text: "Search books..."
                            color: "#5b5f75"
                            font.pixelSize: 12
                            visible: !searchInput.text && !searchInput.activeFocus
                        }
                        onTextChanged: page.searchQuery = text.toLowerCase()
                    }
                }
            }

            // 「+ New Project / 本を取り込む」ボタン
            Rectangle {
                id: newBtn
                height: 38
                width: rowNew.implicitWidth + 28
                radius: 19
                color: newBtnArea.containsMouse ? "#1ed760" : page.accent
                Behavior on color { ColorAnimation { duration: 150 } }

                RowLayout {
                    id: rowNew
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "+"; color: "#000000"; font.pixelSize: 16; font.bold: true }
                    Text { text: "New Project"; color: "#000000"; font.pixelSize: 12; font.bold: true }
                }

                MouseArea {
                    id: newBtnArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.importRequested()
                }
            }
        }
    }

    property string activeBookId: ""

    GridView {
        id: grid
        anchors.fill: parent
        anchors.margins: 28
        anchors.topMargin: 0
        anchors.bottomMargin: 115
        clip: true
        cellWidth: 205; cellHeight: 315
        model: page.books

        ScrollBar.vertical: ScrollBar { active: true }

        delegate: Item {
            id: bookItem
            required property var model
            width: grid.cellWidth - 16
            height: grid.cellHeight - 16

            property int theme: page.getThemeIndex(model.id)
            property real progressRate: (model.segments > 0 ? (model.audio_done / model.segments) : 0)
            property bool isCompleted: model.segments > 0 && model.audio_done >= model.segments
            property bool isInProgress: model.audio_done > 0 && !isCompleted
            property bool isSelected: (page.activeBookId && page.activeBookId === model.id) || (model.id === "demo" || (!page.activeBookId && model.index === 1))

            // カード外枠
            Rectangle {
                id: cardRect
                anchors.fill: parent
                radius: 14
                color: cardArea.containsMouse ? "#181a24" : "#12141c"
                border.color: bookItem.isSelected ? "#10b981" : (cardArea.containsMouse ? "#1ed760" : "#222533")
                border.width: bookItem.isSelected ? 2 : (cardArea.containsMouse ? 1.5 : 1)

                Behavior on color { ColorAnimation { duration: 140 } }
                Behavior on border.color { ColorAnimation { duration: 140 } }

                // ================= ポスターアートワーク =================
                Rectangle {
                    id: coverPoster
                    width: parent.width - 20
                    height: width * 1.34
                    anchors.top: parent.top
                    anchors.topMargin: 10
                    anchors.horizontalCenter: parent.horizontalCenter
                    radius: 10
                    clip: true

                    // --- テーマ 0: NEBULA'S EDGE (深宇宙・ネビュラ) ---
                    Rectangle {
                        anchors.fill: parent
                        visible: bookItem.theme === 0
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#08101a" }
                            GradientStop { position: 0.5; color: "#0d222e" }
                            GradientStop { position: 1.0; color: "#050b12" }
                        }
                        // ネビュラグロー
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width * 0.85; height: width; radius: width / 2
                            color: "#184547"; opacity: 0.35
                        }
                        // 光彩リング
                        Rectangle {
                            anchors.bottom: parent.bottom; anchors.bottomMargin: 18
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 64; height: 32; radius: 16
                            color: "transparent"; border.color: "#38e0b2"; border.width: 1.5
                            opacity: 0.7
                        }
                        ColumnLayout {
                            anchors.top: parent.top; anchors.topMargin: 18
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 4
                            Text {
                                text: "NEBULA'S\nEDGE"
                                color: "#ffffff"; font.pixelSize: 13; font.bold: true
                                horizontalAlignment: Text.AlignHCenter; font.letterSpacing: 1.5
                            }
                        }
                    }

                    // --- テーマ 1: THE LAST CHRONICLE (旅人・文学・クラシック) ---
                    Rectangle {
                        anchors.fill: parent
                        visible: bookItem.theme === 1
                        color: "#eae5d9"
                        // 旅人シルエット
                        Rectangle {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: 14
                            width: 22; height: 44; radius: 6
                            color: "#1f1e1a"
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -12
                            width: 14; height: 14; radius: 7
                            color: "#1f1e1a"
                        }
                        ColumnLayout {
                            anchors.top: parent.top; anchors.topMargin: 18
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 2
                            Text {
                                text: "THE LAST\nCHRONICLE"
                                color: "#1c1b18"; font.pixelSize: 12; font.bold: true
                                horizontalAlignment: Text.AlignHCenter; font.letterSpacing: 1
                            }
                        }
                    }

                    // --- テーマ 2: CYBERNETIC DREAMS (サイバーパンク・電脳) ---
                    Rectangle {
                        anchors.fill: parent
                        visible: bookItem.theme === 2
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#06181c" }
                            GradientStop { position: 0.6; color: "#0b2e2d" }
                            GradientStop { position: 1.0; color: "#041013" }
                        }
                        // サイバーヘッド像
                        Rectangle {
                            anchors.centerIn: parent
                            width: 44; height: 44; radius: 22
                            color: "transparent"; border.color: "#2ee6a8"; border.width: 2
                            opacity: 0.6
                        }
                        ColumnLayout {
                            anchors.top: parent.top; anchors.topMargin: 18
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 2
                            Text {
                                text: "CYBERNETIC\nDREAMS"
                                color: "#a5f3dc"; font.pixelSize: 11; font.bold: true
                                horizontalAlignment: Text.AlignHCenter; font.letterSpacing: 1.2
                            }
                        }
                    }

                    // --- テーマ 3: ECHOES OF ELORIA (黄昏・ファンタジー) ---
                    Rectangle {
                        anchors.fill: parent
                        visible: bookItem.theme === 3
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#482626" }
                            GradientStop { position: 0.5; color: "#b35b45" }
                            GradientStop { position: 1.0; color: "#d98762" }
                        }
                        // 夕陽シルエット
                        Rectangle {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: 6
                            width: 40; height: 40; radius: 20
                            color: "#fce9d2"
                        }
                        // 山影
                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width; height: 36
                            color: "#1c0d0d"
                        }
                        ColumnLayout {
                            anchors.top: parent.top; anchors.topMargin: 18
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 2
                            Text {
                                text: "ECHOES OF\nELORIA"
                                color: "#ffffff"; font.pixelSize: 12; font.bold: true
                                horizontalAlignment: Text.AlignHCenter; font.letterSpacing: 1
                            }
                        }
                    }

                    // プログレスライン（ポスター最下部）
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 4
                        color: "#55000000"
                        Rectangle {
                            width: parent.width * bookItem.progressRate
                            height: parent.height
                            color: page.accent
                        }
                    }

                    // ホバー再生バッジ
                    Rectangle {
                        anchors.centerIn: parent
                        width: 48; height: 48; radius: 24
                        color: page.accent
                        opacity: cardArea.containsMouse ? 0.95 : 0
                        scale: cardArea.containsMouse ? 1.0 : 0.8
                        Behavior on opacity { NumberAnimation { duration: 150 } }
                        Behavior on scale { NumberAnimation { duration: 150 } }

                        Text {
                            anchors.centerIn: parent
                            anchors.horizontalCenterOffset: 1
                            text: "▶"
                            color: "#000000"
                            font.pixelSize: 18
                            font.bold: true
                        }
                    }
                }

                // ================= 書籍タイトル & メタ =================
                ColumnLayout {
                    anchors.top: coverPoster.bottom
                    anchors.topMargin: 8
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 3

                    Text {
                        text: model.title || "(無題)"
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Text {
                        text: "by AISAE Studio"
                        color: "#7e8299"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                // ================= ステータスピルバッジ & メニュー =================
                RowLayout {
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 10
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12

                    // ステータスピル
                    Rectangle {
                        height: 20
                        radius: 4
                        color: bookItem.isCompleted ? "#102e1c"
                             : bookItem.isInProgress ? "#2b210e" : "#132130"
                        border.color: bookItem.isCompleted ? "#1db954"
                                    : bookItem.isInProgress ? "#e0901b" : "#2c5b88"
                        border.width: 1
                        implicitWidth: statusTxt.implicitWidth + 12

                        Text {
                            id: statusTxt
                            anchors.centerIn: parent
                            text: bookItem.isCompleted ? "Completed"
                                : bookItem.isInProgress ? "In Progress" : "Ready to Act"
                            color: bookItem.isCompleted ? "#1ed760"
                                 : bookItem.isInProgress ? "#ffaa2b" : "#5ea9eb"
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }

                    Item { Layout.fillWidth: true }

                    // オプションアイコン
                    Text {
                        text: "•••"
                        color: cardArea.containsMouse ? "#ffffff" : "#4e5266"
                        font.pixelSize: 11
                    }
                }

                MouseArea {
                    id: cardArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.openBook(model.id)
                }
            }
        }
    }

    // 本が0冊の場合のエンプティステート
    ColumnLayout {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -40
        spacing: 16
        visible: !page.books || page.books.count === 0

        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            width: 72; height: 72; radius: 36
            color: "#182b20"
            border.color: "#2a5436"
            border.width: 1
            Text { anchors.centerIn: parent; text: "📚"; font.pixelSize: 32 }
        }

        ColumnLayout {
            spacing: 6
            Layout.alignment: Qt.AlignHCenter
            Text {
                text: "ライブラリに作品がありません"
                color: "#ffffff"
                font.pixelSize: 18
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Text {
                text: "「+ New Project」から小説 (PDF/TXT) を取り込むか、Engine を接続してください。"
                color: "#80859c"
                font.pixelSize: 13
                horizontalAlignment: Text.AlignHCenter
            }
        }

        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 8
            height: 40; width: 160; radius: 20
            color: emptyBtnMa.containsMouse ? "#1ed760" : page.accent
            Text {
                anchors.centerIn: parent
                text: "+ 本を取り込む"
                color: "#000000"
                font.pixelSize: 13
                font.bold: true
            }
            MouseArea {
                id: emptyBtnMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: page.importRequested()
            }
        }
    }
}

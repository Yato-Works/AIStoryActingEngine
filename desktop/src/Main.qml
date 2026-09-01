import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 980
    height: 720
    visible: true
    title: "AIStoryActingEngine Desktop (Phase 3B)"

    ListModel { id: booksModel }
    ListModel { id: stepsModel }
    ListModel { id: historyModel }
    ListModel { id: logModel }

    property string currentJobId: ""
    property string statusText: "Worker 起動中…"
    property bool workerRunning: false
    property bool crashed: false

    function jobMark(status) {
        if (status === "completed") return "✓"
        if (status === "failed") return "✗"
        if (status === "cancelled") return "⏸"
        if (status === "running") return "▶"
        if (status === "paused") return "⏸"
        return "○"
    }

    Connections {
        target: bridge
        function onRunningChanged(running) {
            workerRunning = running
            statusText = running ? "Worker 接続済み" : "Worker 停止"
            if (running) {
                crashed = false
                bridge.ping()
                bridge.listJobs(20)
            }
        }
        function onPingResult(ok) {
            statusText = ok ? "Worker 応答 OK" : "Worker 応答なし"
        }
        function onBooksLoaded(books) {
            booksModel.clear()
            for (var i = 0; i < books.length; ++i)
                booksModel.append(books[i])
        }
        function onJobStarted(jobId, bookId) {
            currentJobId = jobId
            statusText = "ジョブ開始: " + bookId
            stepsModel.clear()
            bridge.listJobs(20)
        }
        function onJobLoaded(job, polled) {
            if (job.id !== currentJobId)
                return
            stepsModel.clear()
            var steps = job.steps || []
            for (var s = 0; s < steps.length; ++s) {
                var st = steps[s]
                stepsModel.append({
                    name: st.name,
                    status: st.status,
                    progress: st.progress,
                    total: st.progress_total,
                    checkpoint: st.checkpoint ? JSON.stringify(st.checkpoint) : ""
                })
            }
            if (job.status === "completed")
                statusText = "✅ Job 完了: " + (job.book_id || "")
            else if (job.status === "failed")
                statusText = "❌ Job 失敗: " + (job.error || "")
            else if (job.status === "cancelled")
                statusText = "🛑 キャンセル済み（Resume で続きから）"
            else if (job.status === "paused")
                statusText = "⏸ 一時停止中"
            else
                statusText = "実行中…"
        }
        function onJobCancelRequested(jobId) {
            statusText = "キャンセル要求送信…"
        }
        function onJobPauseRequested(jobId) {
            statusText = "一時停止要求送信…"
        }
        function onJobResumed(jobId) {
            currentJobId = jobId
            statusText = "再開: " + jobId
        }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // ---- ヘッダ ----
        RowLayout {
            Layout.fillWidth: true
            Label { text: "AIStoryActingEngine"; font.bold: true; font.pixelSize: 18 }
            Item { Layout.fillWidth: true }
            Rectangle {
                width: 10; height: 10; radius: 5
                color: workerRunning ? "#3ddc84" : "#e53935"
            }
            Label { text: statusText; color: "#555" }
        }

        // ---- クラッシュ復旧バナー ----
        Rectangle {
            visible: crashed
            Layout.fillWidth: true
            color: "#fff3e0"
            radius: 6
            height: 44
            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 10
                Label {
                    Layout.fillWidth: true
                    text: "Worker が異常終了しました。未完了の Job は DB に記録されています。"
                    color: "#bf360c"
                    wrapMode: Text.WrapAnywhere
                }
                Button {
                    text: "⟳ 再起動"
                    onClicked: bridge.restart()
                }
            }
        }

        // ---- Job 実行パネル ----
        GroupBox {
            title: "実行"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "小説パス" }
                    TextField {
                        id: novelField
                        Layout.fillWidth: true
                        text: "../../../samples/sample_novel_long.txt"
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "TTS" }
                    ComboBox { id: providerBox; model: ["edge", "sbv2", "aivis"] }
                    CheckBox { id: resumeBox; text: "resume"; checked: true }
                    CheckBox { id: noTtsBox; text: "no-tts" }
                    Item { Layout.fillWidth: true }
                    Button {
                        text: "▶ 開始"
                        enabled: workerRunning
                        onClicked: {
                            stepsModel.clear()
                            bridge.startJob(novelField.text, providerBox.currentText,
                                            resumeBox.checked, noTtsBox.checked)
                        }
                    }
                    Button {
                        text: "⏸ 一時停止"
                        enabled: currentJobId !== "" && workerRunning
                        onClicked: bridge.pauseJob(currentJobId)
                    }
                    Button {
                        text: "⏵ 再開"
                        enabled: currentJobId !== "" && workerRunning
                        onClicked: bridge.resumeJob(currentJobId)
                    }
                    Button {
                        text: "⏹ キャンセル"
                        enabled: currentJobId !== "" && workerRunning
                        onClicked: bridge.cancelJob(currentJobId)
                    }
                }
            }
        }

        function onJobsLoaded(jobs) {
            historyModel.clear()
            for (var i = 0; i < jobs.length; ++i) {
                var j = jobs[i]
                historyModel.append({
                    jid: j.id,
                    bookId: j.book_id || "?",
                    status: j.status,
                    mark: jobMark(j.status),
                    updated: (j.updated_at || "").replace("T", " ")
                })
            }
        }
        function onWorkerCrashed() {
            crashed = true
            statusText = "💀 Worker が落ちました — 再起動ボタンで復旧できます"
            bridge.listJobs(20)
        }
        function onErrorOccurred(code, message) {
            statusText = "⚠ RPC エラー(" + code + "): " + message
        }
        function onLogMessage(line) {
            logModel.insert(0, { text: line })
            if (logModel.count > 200)
                logModel.remove(200, logModel.count - 200)
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            // ---- 進行（Step ごとのプログレス） ----
            GroupBox {
                title: "進行"
                Layout.fillWidth: true
                Layout.fillHeight: true
                ListView {
                    anchors.fill: parent
                    model: stepsModel
                    clip: true
                    delegate: RowLayout {
                        width: parent.width
                        spacing: 8
                        Text { text: model.name; font.bold: true; Layout.preferredWidth: 80 }
                        Text {
                            text: model.status === "completed" ? "✓" :
                                  model.status === "failed" ? "✗" :
                                  model.status === "running" ? "▶" : "○"
                            color: model.status === "completed" ? "#2e7d32" :
                                   model.status === "failed" ? "#c62828" :
                                   model.status === "running" ? "#1565c0" : "#888"
                            Layout.preferredWidth: 20
                        }
                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0; to: Math.max(1, model.total)
                            value: model.progress
                        }
                        Text {
                            text: model.total > 0 ? (model.progress + "/" + model.total) : ""
                            color: "#666"
                            Layout.preferredWidth: 56
                        }
                        Text {
                            text: model.checkpoint
                            color: "#999"; elide: Text.ElideRight
                            Layout.preferredWidth: 140
                        }
                    }
                }
            }

    }


            // ---- Job History ----
            GroupBox {
                title: "Job History"
                Layout.fillWidth: true
                Layout.fillHeight: true
                ListView {
                    anchors.fill: parent
                    model: historyModel
                    clip: true
                    delegate: RowLayout {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: model.mark
                            color: model.status === "completed" ? "#2e7d32" :
                                   model.status === "failed" ? "#c62828" :
                                   model.status === "running" ? "#1565c0" : "#888"
                            Layout.preferredWidth: 18
                        }
                        Text {
                            text: model.bookId
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            text: model.status
                            color: "#666"
                            Layout.preferredWidth: 80
                        }
                        Button {
                            text: "↺"
                            visible: model.status === "failed" ||
                                     model.status === "cancelled" ||
                                     model.status === "paused"
                            enabled: workerRunning
                            onClicked: {
                                currentJobId = model.jid
                                bridge.resumeJob(model.jid)
                            }
                        }
                    }
                }
            }
        }


        // ---- ログ ----
        GroupBox {
            title: "ログ"
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            ListView {
                anchors.fill: parent
                model: logModel
                clip: true
                delegate: Text {
                    text: model.text
                    font.family: "Consolas"
                    font.pixelSize: 11
                    color: "#333"
                    wrapMode: Text.WrapAnywhere
                }
            }
        }
    }

    onClosing: bridge.shutdown()
}

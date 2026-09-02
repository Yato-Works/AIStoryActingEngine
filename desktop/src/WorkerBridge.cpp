#include "WorkerBridge.h"

#if defined(Q_OS_WIN)
#include <windows.h>
#endif

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QStandardPaths>
#include <utility>

namespace {

QJsonObject makeRequest(int id, const QString &method, const QJsonObject &params)
{
    return {
        {"jsonrpc", "2.0"},
        {"id", id},
        {"method", method},
        {"params", params},
    };
}

QVariantList toVariantList(const QJsonValue &value)
{
    return value.toArray().toVariantList();
}

} // namespace

WorkerBridge::WorkerBridge(const QString &pythonExe,
                           const QString &workerScript,
                           const QDir &repoRoot,
                           QObject *parent)
    : QObject(parent)
    , m_pythonExe(pythonExe)
    , m_workerScript(workerScript)
    , m_repoRoot(repoRoot)
{
    connect(&m_proc, &QProcess::readyReadStandardOutput,
            this, &WorkerBridge::onReadyRead);
    connect(&m_proc, &QProcess::readyReadStandardError,
            this, &WorkerBridge::onReadyReadError);
    connect(&m_proc, &QProcess::finished,
            this, &WorkerBridge::onProcessFinished);
    connect(&m_proc, &QProcess::stateChanged, this, [this](QProcess::ProcessState st) {
        emit runningChanged(st != QProcess::NotRunning);
    });
    connect(&m_proc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError err) {
        emit logMessage(QStringLiteral("[bridge] QProcess error %1: %2")
                            .arg(int(err))
                            .arg(m_proc.errorString()));
    });
}

int WorkerBridge::nextId()
{
    return m_nextId++;
}

void WorkerBridge::start()
{
    if (m_proc.state() != QProcess::NotRunning)
        return;
#if defined(Q_OS_WIN)
    // python.exe をコンソール窓なしで起動する（stdio パイプは維持される）
    m_proc.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *args) {
        args->flags |= CREATE_NO_WINDOW;
    });
#endif
    m_proc.setProgram(m_pythonExe);
    m_proc.setArguments({m_workerScript});
    // worker.py が engine 内のモジュール (main.py 等) を import できるよう、
    // 起動 cwd を engine ディレクトリに合わせる。
    m_proc.setWorkingDirectory(QFileInfo(m_workerScript).absolutePath());
    m_proc.start();
}

void WorkerBridge::send(const QJsonObject &req)
{
    if (m_proc.state() != QProcess::Running) {
        emit errorOccurred(-32000, QStringLiteral("Worker が起動していません"));
        return;
    }
    const int id = req.value(QStringLiteral("id")).toInt();
    const QString method = req.value(QStringLiteral("method")).toString();
    m_pending.insert(id, method);
    m_proc.write(QJsonDocument(req).toJson(QJsonDocument::Compact) + "\n");
}
void WorkerBridge::onReadyRead()
{
    m_inBuffer += m_proc.readAllStandardOutput();
    int nl = -1;
    while ((nl = m_inBuffer.indexOf('\n')) >= 0) {
        const QByteArray line = m_inBuffer.left(nl).trimmed();
        m_inBuffer.remove(0, nl + 1);
        if (line.isEmpty())
            continue;
        const QJsonDocument doc = QJsonDocument::fromJson(line);
        if (!doc.isObject())
            continue;
        handleResponse(doc.object());
    }
}

void WorkerBridge::onReadyReadError()
{
    const QByteArray chunk = m_proc.readAllStandardError();
    for (const QByteArray &line : chunk.split('\n')) {
        const QString s = QString::fromUtf8(line).trimmed();
        if (!s.isEmpty())
            emit logMessage(s);
    }
}

void WorkerBridge::onProcessFinished(int exitCode, QProcess::ExitStatus status)
{
    emit logMessage(QStringLiteral("[worker] 終了 code=%1 status=%2")
                        .arg(exitCode).arg(status == QProcess::NormalExit ? "normal" : "crash"));
    for (auto *timer : std::as_const(m_polls)) {
        timer->stop();
        timer->deleteLater();
    }
    m_polls.clear();
    m_pending.clear();
    // ユーザー主導の shutdown 以外の終了はクラッシュ扱い（Resume UI を出す）
    if (!m_shuttingDown)
        emit workerCrashed();
}

// ---------------------------------------------------------------- リクエスト

void WorkerBridge::ping()
{
    send(makeRequest(nextId(), QStringLiteral("ping"), {}));
}

void WorkerBridge::listBooks()
{
    send(makeRequest(nextId(), QStringLiteral("list_books"), {}));
}

void WorkerBridge::getBook(const QString &bookId)
{
    send(makeRequest(nextId(), QStringLiteral("get_book"),
                     {{QStringLiteral("book_id"), bookId}}));
}

void WorkerBridge::listEvents(int limit, const QString &type)
{
    QJsonObject params{{"limit", limit}};
    if (!type.isEmpty())
        params.insert("type", type);
    send(makeRequest(nextId(), QStringLiteral("get_events"), params));
}

void WorkerBridge::search(const QString &query, int limit)
{
    send(makeRequest(nextId(), QStringLiteral("search"),
                     {{"query", query}, {"limit", limit}}));
}

void WorkerBridge::startJob(const QString &novel, const QString &provider,
                            bool resume, bool noTts)
{
    send(makeRequest(nextId(), QStringLiteral("start_job"),
                     {{"novel", novel}, {"provider", provider},
                      {"resume", resume}, {"no_tts", noTts}}));
}

void WorkerBridge::getJob(const QString &jobId)
{
    send(makeRequest(nextId(), QStringLiteral("get_job"), {{"job_id", jobId}}));
}

void WorkerBridge::cancelJob(const QString &jobId)
{
    send(makeRequest(nextId(), QStringLiteral("cancel_job"), {{"job_id", jobId}}));
}

void WorkerBridge::pauseJob(const QString &jobId)
{
    send(makeRequest(nextId(), QStringLiteral("pause_job"), {{"job_id", jobId}}));
}

void WorkerBridge::resumeJob(const QString &jobId)
{
    send(makeRequest(nextId(), QStringLiteral("resume_job"), {{"job_id", jobId}}));
}

void WorkerBridge::listJobs(int limit)
{
    send(makeRequest(nextId(), QStringLiteral("list_jobs"), {{"limit", limit}}));
}

void WorkerBridge::restart()
{
    if (m_proc.state() != QProcess::NotRunning)
        return;
    emit logMessage(QStringLiteral("[worker] 再起動..."));
    start();  // worker.py は serve() 冒頭で stale Job を復旧する
}

void WorkerBridge::shutdown()
{
    if (m_proc.state() == QProcess::NotRunning)
        return;
    m_shuttingDown = true;
    for (auto *timer : std::as_const(m_polls))
        timer->stop();
    // stdin を閉じると worker.py の serve() が EOF で正常終了する。
    // 強制 terminate/kill はパイプ IO の teardown で問題を起こすことがある。
    m_proc.closeWriteChannel();
    if (!m_proc.waitForFinished(5000))
        m_proc.kill();
    m_proc.waitForFinished(1000);
    m_shuttingDown = false;
}
// ---------------------------------------------------------------- 応答処理

void WorkerBridge::handleResponse(const QJsonObject &resp)
{
    const int id = resp.value(QStringLiteral("id")).toInt(-1);
    const QString method = m_pending.take(id);
    if (resp.contains("error")) {
        const QJsonObject err = resp.value("error").toObject();
        emit errorOccurred(err.value("code").toInt(-32000),
                           err.value("message").toString());
        return;
    }
    const QJsonValue result = resp.value("result");

    if (method == QStringLiteral("ping")) {
        emit pingResult(result.toObject().value("pong").toBool());
    } else if (method == QStringLiteral("list_books")) {
        emit booksLoaded(toVariantList(result.toObject().value("books")));
    } else if (method == QStringLiteral("get_book")) {
        emit bookLoaded(result.toVariant());
    } else if (method == QStringLiteral("get_events")) {
        emit eventsLoaded(toVariantList(result.toObject().value("events")));
    } else if (method == QStringLiteral("search")) {
        emit searchResults(toVariantList(result.toObject().value("results")));
    } else if (method == QStringLiteral("start_job")) {
        const QJsonObject o = result.toObject();
        const QString jobId = o.value("job_id").toString();
        emit jobStarted(jobId, o.value("book_id").toString());
        startPolling(jobId);
    } else if (method == QStringLiteral("get_job")) {
        const QJsonObject o = result.toObject();
        const QString status = o.value("status").toString();
        emit jobLoaded(result.toVariant(), true);
        if (isTerminalStatus(status))
            stopPolling(o.value("id").toString());
    } else if (method == QStringLiteral("cancel_job")) {
        emit jobCancelRequested(result.toObject().value("job_id").toString());
    } else if (method == QStringLiteral("pause_job")) {
        emit jobPauseRequested(result.toObject().value("job_id").toString());
    } else if (method == QStringLiteral("resume_job")) {
        const QJsonObject o = result.toObject();
        const QString jobId = o.value("job_id").toString();
        emit jobResumed(jobId);
        // 再開後は進捗ポーリングを再開（新規 Job ID の場合もここで追跡）
        startPolling(jobId);
    } else if (method == QStringLiteral("list_jobs")) {
        emit jobsLoaded(toVariantList(result.toObject().value("jobs")));
    }
}

bool WorkerBridge::isTerminalStatus(const QString &status) const
{
    return status == QStringLiteral("completed")
        || status == QStringLiteral("failed")
        || status == QStringLiteral("cancelled")
        || status == QStringLiteral("skipped");
}

void WorkerBridge::startPolling(const QString &jobId)
{
    if (m_polls.contains(jobId))
        return;
    auto *timer = new QTimer(this);
    timer->setInterval(1000);
    connect(timer, &QTimer::timeout, this, [this, jobId]() {
        getJob(jobId);
    });
    m_polls.insert(jobId, timer);
    timer->start();
}

void WorkerBridge::stopPolling(const QString &jobId)
{
    QTimer *timer = m_polls.take(jobId);
    if (timer) {
        timer->stop();
        timer->deleteLater();
    }
}
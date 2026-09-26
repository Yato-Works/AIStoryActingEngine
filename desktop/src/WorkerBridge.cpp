#include "WorkerBridge.h"
#include "LocalApiServer.h"

#if defined(Q_OS_WIN)
#include <windows.h>
#endif

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QStandardPaths>
#include <QTcpSocket>
#include <QDesktopServices>
#include <QUrl>
#include <QSettings>
#include <QCoreApplication>
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

    // Atlas Integration: Setup local API server
    setupLocalApiServer();
    
    // Atlas Integration: Start periodic discovery
    m_atlasDiscoveryTimer = new QTimer(this);
    m_atlasDiscoveryTimer->setInterval(30000); // 30秒ごと
    connect(m_atlasDiscoveryTimer, &QTimer::timeout, this, &WorkerBridge::discoverAtlas);
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

void WorkerBridge::listVoiceProfiles(const QString &gender, const QString &source)
{
    QJsonObject params;
    if (!gender.isEmpty()) params.insert("gender", gender);
    if (!source.isEmpty()) params.insert("source", source);
    send(makeRequest(nextId(), QStringLiteral("list_voice_profiles"), params));
}

void WorkerBridge::saveVoiceProfile(const QVariantMap &profile)
{
    QJsonObject p = QJsonObject::fromVariantMap(profile);
    send(makeRequest(nextId(), QStringLiteral("save_voice_profile"), {{"profile", p}}));
}

void WorkerBridge::deleteVoiceProfile(const QString &voiceId)
{
    send(makeRequest(nextId(), QStringLiteral("delete_voice_profile"), {{"voice_id", voiceId}}));
}

void WorkerBridge::getCastings(const QString &bookId)
{
    send(makeRequest(nextId(), QStringLiteral("get_castings"), {{"book_id", bookId}}));
}

void WorkerBridge::assignCasting(const QString &bookId, const QString &characterId,
                                 const QString &voiceId, const QString &voiceInternalId,
                                 bool isLocked, const QString &notes)
{
    QJsonObject params{
        {"book_id", bookId},
        {"character_id", characterId},
        {"voice_id", voiceId},
        {"is_locked", isLocked},
        {"notes", notes}
    };
    if (!voiceInternalId.isEmpty())
        params.insert("voice_internal_id", voiceInternalId);
    send(makeRequest(nextId(), QStringLiteral("assign_casting"), params));
}

void WorkerBridge::applyCastingsAndRegen(const QString &bookId, const QString &provider)
{
    QJsonObject params{
        {"book_id", bookId},
        {"provider", provider}
    };
    send(makeRequest(nextId(), QStringLiteral("apply_castings_and_regen"), params));
}

void WorkerBridge::previewVoice(const QString &text, const QString &voiceId,
                                const QString &style, double pitch, double pace,
                                const QString &provider)
{
    QJsonObject params{
        {"text", text},
        {"voice_id", voiceId},
        {"style", style},
        {"pitch", pitch},
        {"pace", pace},
        {"provider", provider}
    };
    send(makeRequest(nextId(), QStringLiteral("preview_voice"), params));
}

void WorkerBridge::previewVoiceIrodori(const QString &text, const QString &voiceId,
                                      const QString &caption, double pace,
                                      bool useGemini,
                                      const QVariantMap &options)
{
    QJsonObject params{
        {"text", text},
        {"voice_id", voiceId},
        {"caption", caption},
        {"pace", pace},
        {"provider", QStringLiteral("irodori")},
        {"use_gemini_script", useGemini}
    };
    if (!options.isEmpty()) {
        QJsonObject optsObj = QJsonObject::fromVariantMap(options);
        for (auto it = optsObj.begin(); it != optsObj.end(); ++it) {
            params.insert(it.key(), it.value());
        }
    }
    send(makeRequest(nextId(), QStringLiteral("preview_voice"), params));
}

void WorkerBridge::imagineCharacterVoice(const QString &bookId, const QString &characterId)
{
    QJsonObject params{
        {"book_id", bookId},
        {"character_id", characterId}
    };
    send(makeRequest(nextId(), QStringLiteral("imagine_character_voice"), params));
}

void WorkerBridge::listSeries()
{
    send(makeRequest(nextId(), QStringLiteral("list_series"), {}));
}

void WorkerBridge::upsertSeries(const QVariantMap &series)
{
    send(makeRequest(nextId(), QStringLiteral("upsert_series"), {{"series", QJsonObject::fromVariantMap(series)}}));
}

void WorkerBridge::assignBookToSeries(const QString &bookId, const QString &seriesId)
{
    send(makeRequest(nextId(), QStringLiteral("assign_book_to_series"), {
        {"book_id", bookId},
        {"series_id", seriesId.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(seriesId)}
    }));
}

void WorkerBridge::importDocument(const QStringList &sources, const QString &title)
{
    QJsonArray arr;
    for (const auto &s : sources) arr.append(s);
    QJsonObject params{{"sources", arr}};
    if (!title.isEmpty()) params.insert("title", title);
    send(makeRequest(nextId(), QStringLiteral("import_document"), params));
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
        QVariant bookData = result.toVariant();
        emit bookLoaded(bookData);
        
        // Atlas接続中ならWork Matchingを試みる
        if (m_atlasConnected && !m_atlasApiUrl.isEmpty()) {
            QJsonObject book = result.toObject();
            QString bookId = book.value("id").toString();
            matchWorkWithAtlas(bookId);
        }
    } else if (method == QStringLiteral("get_events")) {
        emit eventsLoaded(toVariantList(result.toObject().value("events")));
    } else if (method == QStringLiteral("search")) {
        emit searchResults(toVariantList(result.toObject().value("results")));
    } else if (method == QStringLiteral("start_job") || method == QStringLiteral("apply_castings_and_regen")) {
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
    } else if (method == QStringLiteral("list_voice_profiles")) {
        emit voiceProfilesLoaded(toVariantList(result.toObject().value("profiles")));
    } else if (method == QStringLiteral("save_voice_profile")) {
        emit voiceProfileSaved(result.toObject().value("voice_id").toString());
    } else if (method == QStringLiteral("delete_voice_profile")) {
        emit voiceProfileDeleted(result.toObject().value("deleted").toString());
    } else if (method == QStringLiteral("get_castings")) {
        emit castingsLoaded(toVariantList(result.toObject().value("castings")),
                            result.toObject().value("series_id").toString());
    } else if (method == QStringLiteral("assign_casting")) {
        const QJsonObject o = result.toObject();
        emit castingAssigned(o.value("character_id").toString(), o.value("voice_id").toString());
    } else if (method == QStringLiteral("preview_voice")) {
        emit voicePreviewReady(result.toObject().value("path").toString());
    } else if (method == QStringLiteral("imagine_character_voice")) {
        const QJsonObject o = result.toObject();
        emit characterVoiceImagined(o.value("voice_design").toObject().toVariantMap());
    } else if (method == QStringLiteral("list_series")) {
        emit seriesLoaded(toVariantList(result.toObject().value("series")));
    } else if (method == QStringLiteral("upsert_series")) {
        emit seriesSaved(result.toObject().value("series_id").toString());
    } else if (method == QStringLiteral("import_document")) {
        const QJsonObject o = result.toObject();
        emit documentImported(o.value("novel_path").toString(), o.value("title").toString());
    } else if (method == QStringLiteral("navigate_to_passage")) {
        const QJsonObject o = result.toObject();
        QString deepLink = o.value("deepLink").toString();
        if (!deepLink.isEmpty()) {
            QDesktopServices::openUrl(QUrl(deepLink));
        }
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

// ============================================================================
// Atlas Integration Methods
// ============================================================================

void WorkerBridge::setupLocalApiServer()
{
    m_localApiServer = new LocalApiServer(this);
    
    // Atlasからのリクエストハンドラを登録
    connect(m_localApiServer, &LocalApiServer::engineDiscovered, this, [this](const QString& apiUrl) {
        onAtlasDiscovered(apiUrl, "StoryAtlas", "0.1.0");
    });
    
    connect(m_localApiServer, &LocalApiServer::workMatchRequested, this, [this](const QJsonObject& req) {
        handleAtlasWorkMatch(req);
    });
    
    connect(m_localApiServer, &LocalApiServer::contextQueryRequested, this, [this](const QJsonObject& req) {
        handleAtlasContextQuery(req);
    });
    
    connect(m_localApiServer, &LocalApiServer::navigationRequested, this, [this](const QJsonObject& req) {
        handleAtlasNavigate(req);
    });
    
    if (m_localApiServer->start(18421)) {
        emit logMessage("[atlas] Local API server started on port 18421");
    } else {
        emit logMessage("[atlas] Failed to start local API server");
    }
}

void WorkerBridge::discoverAtlas()
{
    if (!m_localApiServer) return;
    
    // Atlasの一般的なポートをスキャン
    const QList<quint16> atlasPorts = {18422, 18423, 18424, 18425};
    
    for (quint16 port : atlasPorts) {
        QTcpSocket* socket = new QTcpSocket(this);
        connect(socket, &QTcpSocket::connected, this, [this, socket, port]() {
            // Discovery リクエスト送信
            QJsonObject request;
            request["protocolVersion"] = "story/1";
            QJsonArray caps;
            caps << "library" << "reader" << "audio" << "tts" << "capture" << "ocr" << "playback";
            request["capabilities"] = caps;
            
            QByteArray json = QJsonDocument(request).toJson(QJsonDocument::Compact);
            QString httpRequest = QString(
                "POST /api/v1/discover HTTP/1.1\r\n"
                "Host: localhost:%1\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: %2\r\n"
                "\r\n"
                "%3"
            ).arg(port).arg(json.size()).arg(QString::fromUtf8(json));
            
            socket->write(httpRequest.toUtf8());
        });
        
        connect(socket, &QTcpSocket::readyRead, this, [this, socket, port]() {
            QByteArray response = socket->readAll();
            int bodyStart = response.indexOf("\r\n\r\n");
            if (bodyStart != -1) {
                QByteArray body = response.mid(bodyStart + 4);
                QJsonDocument doc = QJsonDocument::fromJson(body);
                if (doc.isObject()) {
                    handleAtlasDiscover(doc.object());
                }
            }
            socket->deleteLater();
        });
        
        connect(socket, QOverload<QAbstractSocket::SocketError>::of(&QTcpSocket::errorOccurred),
                this, [socket, port](QAbstractSocket::SocketError) {
            socket->deleteLater();
        });
        
        socket->connectToHost(QHostAddress::LocalHost, port);
        if (!socket->waitForConnected(1000)) {
            socket->deleteLater();
        }
    }
}

void WorkerBridge::handleAtlasDiscover(const QJsonObject& response)
{
    QString apiUrl = response.value("apiBaseUrl").toString();
    QString appName = response.value("appName").toString();
    QString appVersion = response.value("appVersion").toString();
    
    if (!apiUrl.isEmpty() && apiUrl != m_atlasApiUrl) {
        m_atlasApiUrl = apiUrl;
        m_atlasConnected = true;
        emit atlasDiscovered(apiUrl, appName, appVersion);
        emit atlasConnectionStatusChanged(true);
        emit logMessage(QString("[atlas] Discovered %1 v%2 at %3").arg(appName, appVersion, apiUrl));
        
        // 既存の本をAtlasとマッチング
        listBooks(); // この後 booksLoaded でマッチングを試みる
    }
}

void WorkerBridge::matchWorkWithAtlas(const QString& bookId)
{
    if (m_atlasApiUrl.isEmpty()) {
        emit logMessage("[atlas] No Atlas connection for work matching");
        return;
    }
    
    // Book details を取得してからマッチングリクエスト送信
    // getBook は非同期なので、ここではまず book 情報を構築して直接送信
    // 簡易実装: 既知の book 情報からリクエスト構築
    QJsonObject engineWork;
    engineWork["id"] = bookId;
    engineWork["metadata"] = QJsonObject{
        {"title", ""}, // TODO: 実際のタイトルを取得
        {"author", ""},
        {"isbn", ""},
        {"series", ""},
        {"volume", QJsonValue::Null}
    };
    engineWork["documents"] = QJsonArray(); // TODO: 実際のドキュメント情報
    
    QJsonObject request;
    request["engineWork"] = engineWork;
    
    // Atlas API に POST
    QTcpSocket* socket = new QTcpSocket(this);
    QUrl url(m_atlasApiUrl);
    QString host = url.host();
    quint16 port = url.port(18422);
    
    connect(socket, &QTcpSocket::connected, this, [this, socket, request, host]() {
        QByteArray json = QJsonDocument(request).toJson(QJsonDocument::Compact);
        QString httpRequest = QString(
            "POST /api/v1/work/match HTTP/1.1\r\n"
            "Host: %1\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: %2\r\n"
            "\r\n"
            "%3"
        ).arg(host).arg(json.size()).arg(QString::fromUtf8(json));
        socket->write(httpRequest.toUtf8());
    });
    
    connect(socket, &QTcpSocket::readyRead, this, [this, socket]() {
        QByteArray response = socket->readAll();
        int bodyStart = response.indexOf("\r\n\r\n");
        if (bodyStart != -1) {
            QByteArray body = response.mid(bodyStart + 4);
            QJsonDocument doc = QJsonDocument::fromJson(body);
            if (doc.isObject()) {
                onAtlasWorkMatchResponse(doc.object());
            }
        }
        socket->deleteLater();
    });
    
    connect(socket, QOverload<QAbstractSocket::SocketError>::of(&QTcpSocket::errorOccurred),
            this, [socket](QAbstractSocket::SocketError) {
        socket->deleteLater();
    });
    
    socket->connectToHost(url.host(), url.port(18422));
}

void WorkerBridge::sendContextToAtlas(const QString& workId, const QString& chapterId, const QString& sentenceId)
{
    if (m_atlasApiUrl.isEmpty()) return;
    
    QJsonObject context = getCurrentContext(workId, chapterId, sentenceId);
    if (context.isEmpty()) return;
    
    QTcpSocket* socket = new QTcpSocket(this);
    connect(socket, &QTcpSocket::connected, this, [this, socket, context]() {
        QByteArray json = QJsonDocument(context).toJson(QJsonDocument::Compact);
        QString httpRequest = QString(
            "POST /api/v1/context/query HTTP/1.1\r\n"
            "Host: %1\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: %2\r\n"
            "\r\n"
            "%3"
        ).arg(m_atlasApiUrl).arg(json.size()).arg(QString::fromUtf8(json));
        socket->write(httpRequest.toUtf8());
    });
    
    connect(socket, &QTcpSocket::readyRead, this, [this, socket]() {
        QByteArray response = socket->readAll();
        int bodyStart = response.indexOf("\r\n\r\n");
        if (bodyStart != -1) {
            QByteArray body = response.mid(bodyStart + 4);
            QJsonDocument doc = QJsonDocument::fromJson(body);
            if (doc.isObject()) {
                onAtlasContextResponse(doc.object());
            }
        }
        socket->deleteLater();
    });
    
    // URLからホストを抽出
    QUrl url(m_atlasApiUrl);
    socket->connectToHost(url.host(), url.port(18422));
}

void WorkerBridge::navigateToPassage(const QString& workId, const QString& chapterId, const QString& sentenceId, const QString& mode)
{
    // aiae:// Deep Link を生成して処理
    QString passageRef = buildPassageRef(workId, chapterId, sentenceId);
    QString deepLink = QString("aiae://open?workId=%1&chapterId=%2&sentenceId=%3&mode=%4")
        .arg(workId, chapterId, sentenceId, mode);
    
    // OSで開く
    QDesktopServices::openUrl(QUrl(deepLink));
}

QString WorkerBridge::buildPassageRef(const QString& workId, const QString& chapterId, const QString& sentenceId)
{
    QString ref = QString("work:%1").arg(workId);
    if (!chapterId.isEmpty()) ref += QString("/ch:%1").arg(chapterId);
    if (!sentenceId.isEmpty()) ref += QString("/sen:%1").arg(sentenceId);
    return ref;
}

QJsonObject WorkerBridge::getCurrentContext(const QString& workId, const QString& chapterId, const QString& sentenceId)
{
    QJsonObject context;
    context["workId"] = workId;
    
    QJsonObject passageRef;
    passageRef["workId"] = workId;
    if (!chapterId.isEmpty()) passageRef["chapterId"] = chapterId;
    if (!sentenceId.isEmpty()) passageRef["sentenceId"] = sentenceId;
    context["passageRef"] = passageRef;
    
    QJsonArray requestTypes;
    requestTypes << "characters" << "foreshadowing" << "plot" << "timeline" << "world";
    context["requestTypes"] = requestTypes;
    
    QJsonObject options;
    options["characterLimit"] = 10;
    options["foreshadowingLimit"] = 10;
    options["plotLimit"] = 10;
    options["timelineLimit"] = 10;
    options["includeResolvedForeshadowing"] = false;
    context["options"] = options;
    
    return context;
}

void WorkerBridge::onAtlasDiscovered(const QString& apiUrl, const QString& appName, const QString& appVersion)
{
    m_atlasApiUrl = apiUrl;
    m_atlasConnected = true;
    emit atlasConnectionStatusChanged(true);
    m_atlasDiscoveryTimer->stop(); // 見つかったら定期検索停止
}

void WorkerBridge::handleAtlasWorkMatch(const QJsonObject& req)
{
    // AtlasからのWork Matchingリクエストを処理
    // Engine側の本情報を返す
    QJsonObject engineWork = req.value("engineWork").toObject();
    QString bookId = engineWork.value("id").toString();
    
    // Book details を取得してレスポンス送信
    QJsonObject bookData = getBookForWorkMatch(bookId);
    if (!bookData.isEmpty()) {
        sendAtlasResponse("/api/v1/work/match", bookData);
    }
}

QJsonObject WorkerBridge::getBookForWorkMatch(const QString& bookId)
{
    // 同期的に本情報を取得（Python Worker経由）
    // 簡易実装: 同期呼び出しで book データ取得
    QJsonObject request;
    request["jsonrpc"] = "2.0";
    request["id"] = nextId();
    request["method"] = "get_book";
    
    QJsonObject params;
    params["book_id"] = bookId;
    request["params"] = params;
    
    // 同期呼び出し用の一時的な処理
    // 実際には非同期でやるべきだが、ここでは同期的に待つ
    m_pendingSyncRequest = request.value("id").toInt();
    m_syncResponse = QJsonObject();
    
    send(request);
    
    // 最大5秒待機
    QEventLoop loop;
    QTimer::singleShot(5000, &loop, &QEventLoop::quit);
    connect(this, &WorkerBridge::bookLoaded, &loop, [this, &loop](const QVariant& book) {
        m_syncResponse = book.toJsonObject();
        loop.quit();
    });
    loop.exec();
    
    return m_syncResponse;
}

void WorkerBridge::handleAtlasContextQuery(const QJsonObject& req)
{
    // AtlasからのContext Queryを処理
    // 現在の読書位置のコンテキストを返す
    QString workId = req.value("workId").toString();
    QJsonObject passageRef = req.value("passageRef").toObject();
    QString chapterId = passageRef.value("chapterId").toString();
    QString sentenceId = passageRef.value("sentenceId").toString();
    
    QJsonObject context = getCurrentContext(workId, chapterId, sentenceId);
    
    // Python Workerにキャラクター情報等を問い合わせてからレスポンス送信
    // ここでは同期的にPython Workerに問い合わせ
    QJsonObject fullContext = getFullContextFromWorker(workId, chapterId, sentenceId);
    sendAtlasResponse("/api/v1/context/query", fullContext);
}

QJsonObject WorkerBridge::getFullContextFromWorker(const QString& workId, const QString& chapterId, const QString& sentenceId)
{
    m_pendingSyncRequest = nextId();
    m_syncResponse = QJsonObject();
    
    QJsonObject request;
    request["jsonrpc"] = "2.0";
    request["id"] = m_pendingSyncRequest;
    request["method"] = "get_current_context";
    
    QJsonObject params;
    params["book_id"] = workId;
    params["chapter_id"] = chapterId;
    params["sentence_id"] = sentenceId;
    request["params"] = params;
    
    send(request);
    
    // 最大5秒待機
    QEventLoop loop;
    QTimer::singleShot(5000, &loop, &QEventLoop::quit);
    connect(this, &WorkerBridge::bookLoaded, &loop, [this, &loop](const QVariant& book) {
        m_syncResponse = book.toJsonObject();
        loop.quit();
    });
    loop.exec();
    
    return m_syncResponse;
}

void WorkerBridge::handleAtlasNavigate(const QJsonObject& req)
{
    // Atlasからのナビゲーションリクエスト
    QJsonObject passageRef = req.value("passageRef").toObject();
    QString mode = req.value("mode").toString();
    
    QString workId = passageRef.value("workId").toString();
    QString chapterId = passageRef.value("chapterId").toString();
    QString sentenceId = passageRef.value("sentenceId").toString();
    
    navigateToPassage(workId, chapterId, sentenceId, mode);
}

void WorkerBridge::onAtlasWorkMatchResponse(const QJsonObject& response)
{
    bool matched = response.value("matched").toBool();
    QString workId = response.value("workId").toString();
    double confidence = response.value("confidence").toDouble();
    QString bookId = response.value("bookId").toString(); // 別途管理が必要
    
    if (matched && !workId.isEmpty()) {
        emit atlasWorkMatched(bookId, workId, confidence);
    }
}

void WorkerBridge::onAtlasContextResponse(const QJsonObject& response)
{
    QString workId = response.value("workId").toString();
    emit atlasContextReceived(workId, response);
}

// Atlas同期レスポンス送信
void WorkerBridge::sendAtlasResponse(const QString& endpoint, const QJsonObject& data)
{
    if (m_atlasApiUrl.isEmpty()) return;
    
    QTcpSocket* socket = new QTcpSocket(this);
    QUrl url(m_atlasApiUrl);
    QString host = url.host();
    quint16 port = url.port(18422);
    
    connect(socket, &QTcpSocket::connected, this, [this, socket, endpoint, data, host]() {
        QJsonObject request;
        request["jsonrpc"] = "2.0";
        request["method"] = endpoint;
        request["params"] = data;
        
        QByteArray json = QJsonDocument(request).toJson(QJsonDocument::Compact);
        QString httpRequest = QString(
            "POST %1 HTTP/1.1\r\n"
            "Host: %2\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: %3\r\n"
            "\r\n"
            "%4"
        ).arg(endpoint).arg(host).arg(json.size()).arg(QString::fromUtf8(json));
        
        socket->write(httpRequest.toUtf8());
    });
    
    socket->connectToHost(QHostAddress::LocalHost, 18422);
}
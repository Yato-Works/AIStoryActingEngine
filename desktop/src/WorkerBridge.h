#pragma once

#include <QDir>
#include <QHash>
#include <QObject>
#include <QProcess>
#include <QString>
#include <QUrl>
#include <QVariantList>
#include <QTimer>
#include <QHostAddress>
#include <QJsonObject>
#include <QEventLoop>

class LocalApiServer;

/// WorkerBridge — Python Worker (worker.py) を QProcess で spawn し、
/// stdio 上の改行区切り JSON-RPC 2.0（ADR-0004）で通信する C++ ブリッジ。
///
/// プロトコル専用 stdout を読み、行ごとに QJsonDocument で応答をハンドリングする。
/// startJob() 後は QTimer で getJob をポーリングし、進捗を jobLoaded シグナルで
/// QML に流す。これが Phase 3 Desktop と Python Engine の境界になる。
class WorkerBridge : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool running READ isRunning NOTIFY runningChanged)
    Q_PROPERTY(bool atlasConnected READ isAtlasConnected WRITE setAtlasConnected NOTIFY atlasConnectionStatusChanged)

public:
    explicit WorkerBridge(const QString &pythonExe,
                          const QString &workerScript,
                          const QDir &repoRoot,
                          QObject *parent = nullptr);

    bool isRunning() const { return m_proc.state() != QProcess::NotRunning; }
    bool isAtlasConnected() const { return m_atlasConnected; }
    void setAtlasConnected(bool connected) {
        if (m_atlasConnected != connected) {
            m_atlasConnected = connected;
            emit atlasConnectionStatusChanged(connected);
        }
    }

    /// worker.py を子プロセスで起動する（起動成功で runningChanged が発火）
    Q_INVOKABLE void start();

    // ---- リクエスト（QML から Q_INVOKABLE で呼ぶ） ----
    Q_INVOKABLE void ping();
    Q_INVOKABLE void listBooks();
    Q_INVOKABLE void getBook(const QString &bookId);   // 本棚 → プレイヤー（Phase 3C）
    Q_INVOKABLE void listEvents(int limit = 20, const QString &type = QString());
    Q_INVOKABLE void search(const QString &query, int limit = 10);
    Q_INVOKABLE void startJob(const QString &novel, const QString &provider,
                              bool resume, bool noTts);
    Q_INVOKABLE void getJob(const QString &jobId);
    Q_INVOKABLE void cancelJob(const QString &jobId);
    Q_INVOKABLE void pauseJob(const QString &jobId);
    Q_INVOKABLE void resumeJob(const QString &jobId);
    Q_INVOKABLE void listJobs(int limit = 20);
    // ---- ボイス & キャスティング & シリーズ ----
    Q_INVOKABLE void listVoiceProfiles(const QString &gender = QString(), const QString &source = QString());
    Q_INVOKABLE void saveVoiceProfile(const QVariantMap &profile);
    Q_INVOKABLE void deleteVoiceProfile(const QString &voiceId);
    Q_INVOKABLE void getCastings(const QString &bookId);
    Q_INVOKABLE void assignCasting(const QString &bookId, const QString &characterId,
                                   const QString &voiceId, const QString &voiceInternalId = QString(),
                                   bool isLocked = true, const QString &notes = QString());
    Q_INVOKABLE void applyCastingsAndRegen(const QString &bookId, const QString &provider = QStringLiteral("irodori"));
    Q_INVOKABLE void previewVoice(const QString &text, const QString &voiceId,
                                  const QString &style = QStringLiteral("Neutral"),
                                  double pitch = 0.0, double pace = 1.0,
                                  const QString &provider = QStringLiteral("edge"));
    Q_INVOKABLE void previewVoiceIrodori(const QString &text, const QString &voiceId,
                                         const QString &caption, double pace = 1.0,
                                         bool useGemini = true,
                                         const QVariantMap &options = QVariantMap());
    Q_INVOKABLE void imagineCharacterVoice(const QString &bookId, const QString &characterId);
    Q_INVOKABLE void listSeries();
    Q_INVOKABLE void upsertSeries(const QVariantMap &series);
    Q_INVOKABLE void assignBookToSeries(const QString &bookId, const QString &seriesId);
    Q_INVOKABLE void importDocument(const QStringList &sources, const QString &title = QString());

    // ---- Atlas Integration ----
    Q_INVOKABLE void discoverAtlas();
    Q_INVOKABLE void matchWorkWithAtlas(const QString& bookId);
    Q_INVOKABLE void sendContextToAtlas(const QString& workId, const QString& chapterId, const QString& sentenceId);
    Q_INVOKABLE void navigateToPassage(const QString& workId, const QString& chapterId, const QString& sentenceId, const QString& mode);

    Q_INVOKABLE void restart();            // クラッシュ後の worker 再起動
    Q_INVOKABLE void shutdown();

signals:
    void runningChanged(bool running);
    void pingResult(bool ok);
    void booksLoaded(QVariantList books);
    void bookLoaded(QVariant book);         // get_book の応答（プレイヤー用）
    void eventsLoaded(QVariantList events);
    void searchResults(QVariantList results);
    void jobStarted(QString jobId, QString bookId);
    void jobLoaded(QVariant job, bool polled);
    void jobCancelRequested(QString jobId);
    void jobPauseRequested(QString jobId);
    void jobResumed(QString jobId);
    void jobsLoaded(QVariantList jobs);     // Job History
    void voiceProfilesLoaded(QVariantList profiles);
    void voiceProfileSaved(QString voiceId);
    void voiceProfileDeleted(QString voiceId);
    void castingsLoaded(QVariantList castings, QString seriesId);
    void castingAssigned(QString characterId, QString voiceId);
    void characterVoiceImagined(QVariantMap voiceDesign);
    void voicePreviewReady(QString path);
    void seriesLoaded(QVariantList series);
    void seriesSaved(QString seriesId);
    void documentImported(QString novelPath, QString title);
    void workerCrashed();                   // Worker の異常終了（Resume UI 用）
    void errorOccurred(int code, QString message);
    void logMessage(QString line);          // worker の stderr を QML ログへ

    // Atlas Integration Signals
    void atlasDiscovered(QString apiUrl, QString appName, QString appVersion);
    void atlasWorkMatched(QString bookId, QString workId, double confidence);
    void atlasContextReceived(QString workId, QVariant context);
    void atlasConnectionStatusChanged(bool connected);

private slots:
    void onReadyRead();
    void onReadyReadError();
    void onProcessFinished(int exitCode, QProcess::ExitStatus status);

private:
    int nextId();
    void send(const QJsonObject &req);
    void handleResponse(const QJsonObject &resp);
    void startPolling(const QString &jobId);
    void stopPolling(const QString &jobId);
    bool isTerminalStatus(const QString &status) const;

    // Atlas Integration
    void setupLocalApiServer();
    void handleAtlasDiscover(const QJsonObject& req);
    void handleAtlasWorkMatch(const QJsonObject& req);
    void handleAtlasContextQuery(const QJsonObject& req);
    void handleAtlasNavigate(const QJsonObject& req);
    void onAtlasDiscovered(const QString& apiUrl, const QString& appName, const QString& appVersion);
    void onAtlasWorkMatchResponse(const QJsonObject& response);
    void onAtlasContextResponse(const QJsonObject& response);
    QString buildPassageRef(const QString& workId, const QString& chapterId, const QString& sentenceId);
    QJsonObject getCurrentContext(const QString& workId, const QString& chapterId, const QString& sentenceId);

    // Atlas同期リクエスト用
    QJsonObject getBookForWorkMatch(const QString& bookId);
    QJsonObject getFullContextFromWorker(const QString& workId, const QString& chapterId, const QString& sentenceId);
    void sendAtlasResponse(const QString& endpoint, const QJsonObject& data);

    int m_pendingSyncRequest = -1;
    QJsonObject m_syncResponse;

    QProcess m_proc;
    QByteArray m_inBuffer;
    int m_nextId = 1;
    bool m_shuttingDown = false;
    QHash<int, QString> m_pending;
    QHash<QString, QTimer *> m_polls;
    QString m_pythonExe;
    QString m_workerScript;
    QDir m_repoRoot;

    // Atlas Integration
    LocalApiServer* m_localApiServer = nullptr;
    QString m_atlasApiUrl;
    bool m_atlasConnected = false;
    QTimer* m_atlasDiscoveryTimer = nullptr;
};
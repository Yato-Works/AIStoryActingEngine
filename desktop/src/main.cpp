#include <QCommandLineParser>
#include <QDebug>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QTimer>
#include <QUrl>

#include "WorkerBridge.h"

namespace {

/// 実行ファイルの所在からリポジトリルートを逆算する。
/// 親を辿って pytest.ini（repo ルートのマーカー）が見つかる場所を採用する。
QDir findRepoRoot(const QString &appDir)
{
    QDir d(appDir);
    for (int i = 0; i < 8; ++i) {
        d.cdUp();
        if (QFileInfo::exists(d.absoluteFilePath(QStringLiteral("pytest.ini"))))
            return d;
    }
    // フォールバック: 現在のワーキングディレクトリ周辺
    QDir wd(QDir::current());
    for (int i = 0; i < 4; ++i) {
        if (QFileInfo::exists(wd.absoluteFilePath(QStringLiteral("pytest.ini"))))
            return wd;
        wd.cdUp();
    }
    return QDir::current();
}

QString defaultPythonExe(const QDir &repo)
{
    // 開発時は venv の python.exe を使う。worker が stdio で応答するため
    // pythonw（stdout が None）は使わない。コンソール窓はブリッジ側で隠す。
    const QString p = repo.absoluteFilePath(
        QStringLiteral("workers/python/.venv/Scripts/python.exe"));
    return QFileInfo::exists(p) ? p
                                : repo.absoluteFilePath(
                                      QStringLiteral("workers/python/.venv/Scripts/python.exe"));
}

} // namespace

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("AIStoryActingEngine Desktop"));
    QCoreApplication::setOrganizationName(QStringLiteral("aiae"));
    QCoreApplication::setApplicationVersion(QStringLiteral("0.1.0"));

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("AIStoryActingEngine Desktop — Python Worker を stdio JSON-RPC で操作する Phase 3 スケルトン"));
    parser.addHelpOption();
    parser.addVersionOption();
    QCommandLineOption pythonOpt(QStringLiteral("python"),
                                 QStringLiteral("Python 実行ファイル（既定: venv の pythonw）"),
                                 QStringLiteral("path"));
    QCommandLineOption workerOpt(QStringLiteral("worker"),
                                 QStringLiteral("worker.py へのパス"),
                                 QStringLiteral("path"));
    QCommandLineOption selfTestOpt(QStringLiteral("self-test"),
                                   QStringLiteral("GUI を表示せず worker 接続を確認して終了する"));
    parser.addOption(pythonOpt);
    parser.addOption(workerOpt);
    parser.addOption(selfTestOpt);
    parser.process(app);

    const QDir repoRoot = findRepoRoot(QCoreApplication::applicationDirPath());
    const QString pythonExe = parser.value(pythonOpt).isEmpty()
        ? defaultPythonExe(repoRoot)
        : parser.value(pythonOpt);
    const QString workerScript = parser.value(workerOpt).isEmpty()
        ? repoRoot.absoluteFilePath(
              QStringLiteral("workers/python/engine/worker.py"))
        : parser.value(workerOpt);

    WorkerBridge bridge(pythonExe, workerScript, repoRoot);

    // ---- self-test モード: GUI なしで worker 接続 (ping) を確認して終了 ----
    if (parser.isSet(selfTestOpt)) {
        const QString resultPath = QDir::current().absoluteFilePath("aiae_selftest.txt");
        QString diag;
        auto writeResult = [&](const QString &text) {
            QFile f(resultPath);
            if (f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
                f.write(text.toUtf8());
                f.write("\n---- diag ----\n");
                f.write(diag.toUtf8());
                f.close();
            }
        };
        QObject::connect(&bridge, &WorkerBridge::logMessage, &app, [&](const QString &line) {
            diag += line + QLatin1Char('\n');
        });
        diag += QStringLiteral("python=%1 exists=%2\nworker=%3 exists=%4\n")
                    .arg(pythonExe, QFileInfo(pythonExe).exists() ? "yes" : "NO",
                         workerScript, QFileInfo(workerScript).exists() ? "yes" : "NO");
        QObject::connect(&bridge, &WorkerBridge::runningChanged, &app, [&](bool running) {
            diag += QStringLiteral("state: %1\n").arg(running ? "running" : "not-running");
        });
        QObject::connect(&bridge, &WorkerBridge::pingResult, &app, [&](bool ok) {
            writeResult(ok ? "ping OK\n" : "ping FAIL\n");
            bridge.shutdown();
            app.exit(ok ? 0 : 1);
        });
        QObject::connect(&bridge, &WorkerBridge::errorOccurred, &app, [&](int code, const QString &msg) {
            writeResult(QStringLiteral("rpc error %1: %2\n").arg(code).arg(msg));
            bridge.shutdown();
            app.exit(2);
        });
        QTimer::singleShot(15000, &app, [&] {
            writeResult(QStringLiteral("timeout\n"));
            app.exit(3);
        });
        bridge.start();
        // 起動直後に ping を送る（イベントループ開始後に発火）
        QTimer::singleShot(0, &app, [&bridge] { bridge.ping(); });
        return app.exec();
    }

    // 通常モード: ワーカー子プロセスを起動して接続を確立
    bridge.start();

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("bridge"), &bridge);
    engine.loadFromModule(QStringLiteral("AIAE"), QStringLiteral("Main"));

    return app.exec();
}
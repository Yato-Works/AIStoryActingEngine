#include "LocalApiServer.h"
#include <QRegularExpression>
#include <QDateTime>
#include <QDebug>
#include <QJsonArray>
#include <QHostAddress>

LocalApiServer::LocalApiServer(QObject *parent) : QObject(parent)
{
    connect(&m_server, &QTcpServer::newConnection, this, &LocalApiServer::onNewConnection);
}

LocalApiServer::~LocalApiServer()
{
    stop();
}

bool LocalApiServer::start(quint16 port)
{
    if (m_server.isListening()) {
        return true;
    }

    if (!m_server.listen(QHostAddress::LocalHost, port)) {
        qWarning() << "LocalApiServer: Failed to start on port" << port << "-" << m_server.errorString();
        return false;
    }

    qInfo() << "LocalApiServer: Listening on localhost:" << port;

    // デフォルトハンドラ登録
    registerHandler("/api/v1/discover", [this](const QJsonObject& req) {
        return handleDiscover(req);
    });

    registerHandler("/api/v1/work/match", [this](const QJsonObject& req) {
        emit workMatchRequested(req);
        return QJsonObject{{"status", "accepted"}};
    });

    registerHandler("/api/v1/context/query", [this](const QJsonObject& req) {
        emit contextQueryRequested(req);
        return QJsonObject{{"status", "accepted"}};
    });

    registerHandler("/api/v1/navigate", [this](const QJsonObject& req) {
        emit navigationRequested(req);
        return QJsonObject{{"success", true}};
    });

    return true;
}

void LocalApiServer::stop()
{
    if (m_server.isListening()) {
        m_server.close();
        qInfo() << "LocalApiServer: Stopped";
    }
}

void LocalApiServer::registerHandler(const QString& path, RequestHandler handler)
{
    m_handlers[path] = handler;
}

void LocalApiServer::onNewConnection()
{
    while (m_server.hasPendingConnections()) {
        QTcpSocket* socket = m_server.nextPendingConnection();
        connect(socket, &QTcpSocket::readyRead, this, &LocalApiServer::onReadyRead);
        connect(socket, &QTcpSocket::disconnected, this, &LocalApiServer::onDisconnected);
        m_buffers[socket] = QByteArray();
    }
}

void LocalApiServer::onReadyRead()
{
    QTcpSocket* socket = qobject_cast<QTcpSocket*>(sender());
    if (!socket) return;

    m_buffers[socket] += socket->readAll();
    QByteArray& buffer = m_buffers[socket];

    // HTTPリクエストの終わりを検出 (\r\n\r\n)
    int headerEnd = buffer.indexOf("\r\n\r\n");
    if (headerEnd == -1) return;

    QByteArray headerPart = buffer.left(headerEnd);
    int contentLength = 0;

    // Content-Length ヘッダーを解析
    QRegularExpression clRegex("Content-Length:\\s*(\\d+)", QRegularExpression::CaseInsensitiveOption);
    auto match = clRegex.match(QString::fromUtf8(headerPart));
    if (match.hasMatch()) {
        contentLength = match.captured(1).toInt();
    }

    int totalSize = headerEnd + 4 + contentLength;
    if (buffer.size() < totalSize) return; // まだ全部来てない

    QByteArray requestData = buffer.left(totalSize);
    buffer.remove(0, totalSize);

    handleRequest(socket, requestData);
}

void LocalApiServer::onDisconnected()
{
    QTcpSocket* socket = qobject_cast<QTcpSocket*>(sender());
    if (socket) {
        m_buffers.remove(socket);
        socket->deleteLater();
    }
}

void LocalApiServer::handleRequest(QTcpSocket* socket, const QByteArray& requestData)
{
    QString path = extractPath(requestData);
    QJsonObject body = parseJsonBody(requestData);

    QJsonObject responseBody;
    int statusCode = 404;

    auto it = m_handlers.find(path);
    if (it != m_handlers.end()) {
        try {
            responseBody = it.value()(body);
            statusCode = 200;
        } catch (const std::exception& e) {
            responseBody = {{"error", QString("Internal error: %1").arg(e.what())}};
            statusCode = 500;
        }
    } else {
        responseBody = {{"error", "Not found"}};
    }

    socket->write(buildResponse(statusCode, responseBody));
    socket->disconnectFromHost();
}

QByteArray LocalApiServer::buildResponse(int statusCode, const QJsonObject& body)
{
    QByteArray json = QJsonDocument(body).toJson(QJsonDocument::Compact);
    QString statusText;
    switch (statusCode) {
        case 200: statusText = "OK"; break;
        case 404: statusText = "Not Found"; break;
        case 500: statusText = "Internal Server Error"; break;
        default: statusText = "Unknown";
    }

    QString response = QString(
        "HTTP/1.1 %1 %2\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %3\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n"
        "Access-Control-Allow-Headers: Content-Type\r\n"
        "\r\n"
        "%4"
    ).arg(statusCode).arg(statusText).arg(json.size()).arg(QString::fromUtf8(json));

    return response.toUtf8();
}

QString LocalApiServer::extractPath(const QByteArray& request)
{
    // "POST /api/v1/discover HTTP/1.1" からパスを抽出
    QRegularExpression regex("^(?:GET|POST|PUT|DELETE|OPTIONS)\\s+(/\\S+)");
    auto match = regex.match(QString::fromUtf8(request));
    if (match.hasMatch()) {
        QString fullPath = match.captured(1);
        // クエリパラメータを除去
        int qPos = fullPath.indexOf('?');
        if (qPos != -1) fullPath = fullPath.left(qPos);
        return fullPath;
    }
    return "/";
}

QJsonObject LocalApiServer::parseJsonBody(const QByteArray& request)
{
    int bodyStart = request.indexOf("\r\n\r\n");
    if (bodyStart == -1) return {};

    QByteArray body = request.mid(bodyStart + 4);
    QJsonParseError error;
    QJsonDocument doc = QJsonDocument::fromJson(body, &error);
    if (error.error != QJsonParseError::NoError) return {};
    return doc.object();
}

QJsonObject LocalApiServer::handleDiscover(const QJsonObject& req)
{
    QJsonObject response;
    response["protocolVersion"] = "story/1";
    response["appName"] = "AIStoryActingEngine";
    response["appVersion"] = "0.1.0";
    response["apiBaseUrl"] = "http://localhost:18421";
    response["deepLinkScheme"] = "aiae://";

    QJsonArray caps;
    caps.append("library");
    caps.append("reader");
    caps.append("audio");
    caps.append("tts");
    caps.append("capture");
    caps.append("ocr");
    caps.append("playback");
    response["capabilities"] = caps;

    return response;
}
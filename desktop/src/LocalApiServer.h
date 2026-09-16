#pragma once

#include <QObject>
#include <QTcpServer>
#include <QTcpSocket>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QString>
#include <functional>

/// LocalApiServer — Atlas連携用のローカルHTTP APIサーバー
/// 設計書 §25-31 に基づく Engine ↔ Atlas 通信
class LocalApiServer : public QObject
{
    Q_OBJECT

public:
    explicit LocalApiServer(QObject *parent = nullptr);
    ~LocalApiServer();

    bool start(quint16 port = 18421);
    void stop();

    // Atlasが呼び出すエンドポイント
    using RequestHandler = std::function<QJsonObject(const QJsonObject&)>;
    void registerHandler(const QString& path, RequestHandler handler);

    // Engine側からAtlasへ通知するシグナル
    Q_SIGNAL void engineDiscovered(const QString& apiUrl);
    Q_SIGNAL void workMatchRequested(const QJsonObject& request);
    Q_SIGNAL void contextQueryRequested(const QJsonObject& request);
    Q_SIGNAL void navigationRequested(const QJsonObject& request);

private slots:
    void onNewConnection();
    void onReadyRead();
    void onDisconnected();

private:
    QTcpServer m_server;
    QMap<QTcpSocket*, QByteArray> m_buffers;
    QMap<QString, RequestHandler> m_handlers;

    void handleRequest(QTcpSocket* socket, const QByteArray& requestData);
    QByteArray buildResponse(int statusCode, const QJsonObject& body);
    QString extractPath(const QByteArray& request);
    QJsonObject parseJsonBody(const QByteArray& request);
    QJsonObject handleDiscover(const QJsonObject& req);
};
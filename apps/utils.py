from email.mime.text import MIMEText
from datetime import datetime
from datetime import date
import os
import logging
from logging.handlers import RotatingFileHandler
import smtplib
import tempfile
import time

from app_config import load_app_config


# ログ出力先ディレクトリ。本番 (Docker コンテナ) では `/insta360-auto-converter-data/logs` を使うが、
# テスト環境などでは `INSTA360_LOGS_DIR` で差し替え可能。
# どちらも書けない (RO FS / 権限なし) 場合は OS 一時ディレクトリにフォールバックして
# import 自体は失敗させない。
log_dir = os.environ.get('INSTA360_LOGS_DIR', '/insta360-auto-converter-data/logs')
try:
    os.makedirs(log_dir, exist_ok=True)
except OSError:
    log_dir = tempfile.mkdtemp(prefix='insta360-auto-converter-logs-')

logger = logging.getLogger('insta360-auto-converter-logger')
logFile = '{}/insta360-auto-converter-logger-'.format(log_dir) + time.strftime("%Y%m%d") + '.log'
handler = RotatingFileHandler(logFile, mode='a', maxBytes=50 * 1024 * 1024,
                              backupCount=5, encoding=None, delay=False)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# YAML 設定を起動時 (モジュールロード時) に 1 度だけロードする。
# 不在 / パース失敗 / 必須キー欠落の場合は AppConfigError で即座に落ちる (フェイルファスト)。
# テスト時は conftest.py が `INSTA360_CONFIGS_PATH` を tmp YAML に向ける。
_app_config = load_app_config()


def log(content, mail_out=False):
    log_content = '[{}] {}'.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), content)
    if mail_out:
        logger.error(log_content)
    else:
        logger.info(log_content)
    print(log_content)
    if mail_out:
        send_mail(_app_config.gmail.error_mail_to, 'insta360-auto-converter Job Failed', content)


def silentremove(filename):
    try:
        os.remove(filename)
        os.rmdir(filename)
    except:
        pass


def send_mail(to, subject, body):
    s = _app_config.gmail.password
    gmail_user = _app_config.gmail.address
    sent_from = gmail_user

    mime = MIMEText(body, "plain", "utf-8")
    mime["Subject"] = subject
    mime["From"] = gmail_user
    mime["To"] = to

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.ehlo()
        server.login(gmail_user, s)
        server.sendmail(sent_from, to, mime.as_string())
        server.close()
        log('Email sent!')
    except Exception as e:
        log('Send mail error: {}'.format(e))
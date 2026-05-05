# syntax=docker/dockerfile:1.7

# uv 公式イメージから uv バイナリだけ取得
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:latest AS uv

# MediaSDK 3.1.1 は amd64 専用配布のため、Apple Silicon ホストでも
# linux/amd64 を強制ビルド (Rosetta / qemu でエミュレートされる)
FROM --platform=linux/amd64 ubuntu:focal

ENV DEBIAN_FRONTEND=noninteractive

# システム依存をまとめてインストール
# 旧 MediaSDK が要求した libssl1.0-dev は MediaSDK 3.1.1 では不要
# (新 SDK が libssl.so.1.1 / libcrypto.so.1.1 を MediaSDK/lib/ にバンドル)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        libimage-exiftool-perl \
        vim \
    && rm -rf /var/lib/apt/lists/*

# uv バイナリを公式イメージから配置
COPY --from=uv /uv /usr/local/bin/uv

# uv 設定: バイトコンパイル / リンク方式 / venv 配置先 / Python 自動ダウンロード
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=automatic \
    PATH=/opt/venv/bin:/usr/local/bin:$PATH

WORKDIR /insta360-auto-converter

# 依存だけ先にインストール（レイヤキャッシュ最適化）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Google API クライアントのタイムアウトを延長（>2GB resumable upload 対応）
RUN python -c "from pathlib import Path; \
import google.auth.transport.requests as m; \
p = Path(m.__file__); \
p.write_text(p.read_text().replace('_DEFAULT_TIMEOUT = 120', '_DEFAULT_TIMEOUT = 86400'))"

# プロジェクト本体をコピー
COPY . .

# Insta360 MediaSDK のビルド
ENV LD_LIBRARY_PATH=/insta360-auto-converter/MediaSDK/lib/:${LD_LIBRARY_PATH}
WORKDIR /insta360-auto-converter/MediaSDK
RUN g++ -Wno-error -std=c++11 example/main.cc \
        -o stitcherSDKDemo \
        -I/insta360-auto-converter/MediaSDK/include/ \
        -L/insta360-auto-converter/MediaSDK/lib/ \
        -lMediaSDK \
        -lpthread

WORKDIR /insta360-auto-converter/apps
CMD ["python", "insta360_auto_converter.py"]

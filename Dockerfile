# syntax=docker/dockerfile:1.7

# uv 公式イメージから uv バイナリだけ取得
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:latest AS uv

# MediaSDK 3.1.1 は amd64 専用配布のため、Apple Silicon ホストでも
# linux/amd64 を強制ビルド (Rosetta / qemu でエミュレートされる)
# Ubuntu 22.04 (jammy) を選ぶ理由: 新 SDK は GLIBC 2.34/2.35 と
# GLIBCXX_3.4.29 (gcc 11+) のシンボルを参照しており、focal (glibc 2.31 / gcc 9)
# では link 段階で undefined reference が大量発生する。
FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# システム依存をまとめてインストール
# - libdc1394-dev / libegl-dev: libMediaSDK.so が DT_NEEDED で参照
# - 旧 MediaSDK が要求した libssl1.0-dev は MediaSDK 3.1.1 では不要
#   (新 SDK が libssl.so.1.1 / libcrypto.so.1.1 を MediaSDK/lib/ にバンドル)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        libdc1394-dev \
        libegl-dev \
        libimage-exiftool-perl \
        libvulkan1 \
        mesa-vulkan-drivers \
        vim \
    && rm -rf /var/lib/apt/lists/*

# WSL2 + NVIDIA ドライバーは Linux 用 Vulkan ICD を提供しないため、Microsoft の
# d3d12 backend (Windows host driver 経由) は WSL 専用の bind-mount が必要で
# Docker Desktop 4.x では未提供。代替として **lavapipe (Mesa の CPU Vulkan ICD)**
# を `mesa-vulkan-drivers` から拾い、SDK の `VulkanDevice::DefaultDevice()` 初期化を
# 通す。CUDA decode / stitching の本流は GPU で走るので、Vulkan 経路が CPU でも
# ボトルネックにならない (PR #12 / WSL2 + RTX 3070 で実機確認)。
ENV VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json

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

# SDK 同梱の `libcuda.so.1` (29MB native Linux 版) を削除する。
# WSL2 + `--gpus all` 環境では NVIDIA Container Toolkit が host から `/usr/lib/x86_64-linux-gnu/libcuda.so.1`
# (175KB 程度の WSL2 stub、`/dev/dxg` 経由で host driver と通信) を inject するが、
# `LD_LIBRARY_PATH` 先頭が SDK の lib なので bundled native libcuda が優先されてしまい、
# 結果 `cuInit` が `no CUDA-capable device is detected` で失敗 → SDK が CPU フォールバック →
# 出力 mp4 が dual-fisheye SBS のままになる (PR #12 / Issue #9 で実機確認)。
# bundled libcuda は build に不要 (`-lcuda` を渡していない) ので物理削除して system stub に
# 切替える。SDK 内部で `dlopen("libcuda.so.1", ...)` するパスは ldconfig 経由で system 側を拾う。
RUN rm -f /insta360-auto-converter/MediaSDK/lib/libcuda.so.1

RUN g++ -Wno-error -std=c++11 example/main.cc \
        -o stitcherSDKDemo \
        -I/insta360-auto-converter/MediaSDK/include/ \
        -L/insta360-auto-converter/MediaSDK/lib/ \
        -lMediaSDK \
        -lpthread

WORKDIR /insta360-auto-converter/apps
CMD ["python", "insta360_auto_converter.py"]

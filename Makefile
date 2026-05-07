# 再帰的な Make メッセージを非表示にする
MAKEFLAGS += --no-print-directory

# Docker（v2 を期待）
DOCKER := docker

# Docker イメージ・コンテナ名（.envrc で上書き可能）
DOCKER_IMAGE_NAME ?= insta360-auto-converter
DOCKER_CONTAINER_NAME ?= insta360-auto-converter

# データディレクトリのデフォルト（.envrc で上書き推奨）
INSTA360_DATA_DIR ?= $(CURDIR)/insta360-auto-converter-data

# NVIDIA GPU 経由で SDK を動かすかのトグル。
# `INSTA360_GPU=1 make docker/run/local` のように指定すると `--gpus all` が付く。
# Insta360 MediaSDK は CUDA 11.7 + libnvcuvid を要求するため、GPU 非搭載環境
# (Mac / linux/amd64 emulation) では SDK の dual-lens stitching が動かず出力が
# dual-fisheye SBS のままになる (Issue #9 動作確認で判明)。
# 本番想定: Linux + NVIDIA GPU (例: WSL2 + RTX 30/40 系) で `INSTA360_GPU=1` を有効化。
#
# capabilities に `video` を含める理由:
#   `--gpus all` (デフォルト = compute,utility) では `libnvcuvid.so.1` (HEVC NVDEC) が
#   container に注入されず、SDK 内部の hevc_cuvid 経由 raw decode が失敗 → stitcher が
#   flow estimator まで到達できず dual-fisheye SBS のまま出力される (PR #12 / WSL2 で確認)。
#   capabilities に `video` を加えると Docker Desktop の NVIDIA Container Toolkit が
#   `libnvcuvid` / `libnvidia-encode` を host (`/usr/lib/wsl/lib/`) から container に
#   投入する。詳細: https://github.com/NVIDIA/nvidia-container-toolkit
# `,` は make 関数引数の区切り扱いになるため変数経由でリテラルを差し込む
comma := ,
INSTA360_GPU ?=
DOCKER_GPU_FLAGS := $(if $(INSTA360_GPU),--gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute$(comma)video$(comma)utility,)

# ================================================
# 初期設定（おそらく、一度しか実行しないもの）
# ================================================
.PHONY: cp
cp:
	cp .envrc.sample .envrc
	${MAKE} env/allow

.PHONY: init
init:
	${MAKE} install
	${MAKE} sync
	@echo "初期セットアップが完了しました！"

# ================================================
# よく使うコマンド
# ================================================
.PHONY: install
install:
	mise install

.PHONY: sync
sync:
	@echo "uv で Python 依存をインストール中..."
	uv sync

.PHONY: lock
lock:
	@echo "uv.lock を更新中..."
	uv lock

.PHONY: env/check
env/check:
	@./scripts/check-env-diff.sh

.PHONY: env/allow
env/allow:
	direnv allow .

# ================================================
# Lint / 構文チェック (CI と同じコマンド)
# ================================================
.PHONY: lint
lint:
	uv run ruff check apps scripts tests

.PHONY: lint/fix
lint/fix:
	uv run ruff check --fix apps scripts tests

.PHONY: syntax
syntax:
	uv run python -m compileall -q apps

.PHONY: test
test:
	uv run pytest

# ================================================
# アプリ実行（ローカル）
# ================================================
# 注意: 本来 Insta360 Media SDK のネイティブバイナリ実行や
# /insta360-auto-converter-data へのマウントが必要なため、
# 通常は docker/run でコンテナ内実行する。
# ローカル実行は Python スクリプト単体の動作確認用。
.PHONY: run
run:
	uv run python apps/insta360_auto_converter.py

.PHONY: refresh-gphotos
refresh-gphotos:
	uv run python apps/refersh_gphotos_cred.py $(INSTA360_DATA_DIR)/gphotos_auth.json

# ================================================
# Docker 操作
# ================================================
.PHONY: docker/build
docker/build:
	@echo "Docker イメージをビルド中: $(DOCKER_IMAGE_NAME)"
	$(DOCKER) build -t $(DOCKER_IMAGE_NAME) .
	@echo "Docker イメージのビルドが完了しました！"

.PHONY: docker/run
docker/run:
	@echo "Docker コンテナを起動中 (Drive モード): $(DOCKER_CONTAINER_NAME)"
	@echo "  データディレクトリ: $(INSTA360_DATA_DIR)"
	@echo "  GPU: $(if $(INSTA360_GPU),enabled (--gpus all),disabled)"
	$(DOCKER) run -d \
		--name $(DOCKER_CONTAINER_NAME) \
		$(DOCKER_GPU_FLAGS) \
		-v $(INSTA360_DATA_DIR):/insta360-auto-converter-data \
		$(DOCKER_IMAGE_NAME)
	@echo "Docker コンテナが起動しました！"

# ローカル入力モード: $(INSTA360_DATA_DIR)/local-input/<アルバム名>/ に置いた raw を
# 監視して Drive と Photos の両方にアップロードする。
.PHONY: docker/run/local
docker/run/local:
	@echo "Docker コンテナを起動中 (ローカル入力モード): $(DOCKER_CONTAINER_NAME)"
	@echo "  データディレクトリ: $(INSTA360_DATA_DIR)"
	@echo "  ローカル入力ディレクトリ: $(INSTA360_DATA_DIR)/local-input"
	@echo "  GPU: $(if $(INSTA360_GPU),enabled (--gpus all),disabled)"
	$(DOCKER) run -d \
		--name $(DOCKER_CONTAINER_NAME) \
		$(DOCKER_GPU_FLAGS) \
		-v $(INSTA360_DATA_DIR):/insta360-auto-converter-data \
		$(DOCKER_IMAGE_NAME) \
		python local_auto_converter.py
	@echo "Docker コンテナが起動しました！"

.PHONY: docker/logs
docker/logs:
	$(DOCKER) logs -f $(DOCKER_CONTAINER_NAME)

.PHONY: docker/stop/d
docker/stop/d:
	@echo "Docker コンテナを停止・削除中..."
	$(DOCKER) stop $(DOCKER_CONTAINER_NAME) || true
	$(DOCKER) rm $(DOCKER_CONTAINER_NAME) || true
	@echo "Docker コンテナを停止しました！"

.PHONY: docker/exec
docker/exec:
	$(DOCKER) exec -it $(DOCKER_CONTAINER_NAME) bash

.PHONY: docker/rebuild/d
docker/rebuild/d:
	${MAKE} docker/stop/d
	${MAKE} docker/build
	${MAKE} docker/run

# ================================================
# /d を付けるのを促すコマンド
# ================================================
.PHONY: docker/stop
docker/stop:
	@echo "あなたが実行したいコマンドは docker/stop/d ですか？"
	@echo "安全性の観点から /d をつけて実行してください"
	@echo "make docker/stop/d"

.PHONY: docker/rebuild
docker/rebuild:
	@echo "あなたが実行したいコマンドは docker/rebuild/d ですか？"
	@echo "安全性の観点から /d をつけて実行してください"
	@echo "make docker/rebuild/d"

# ================================================
# ヘルプ
# ================================================
.PHONY: help
help:
	@echo "insta360-auto-converter - Insta360 .insv/.insp を Google Drive / Photos に自動変換・アップロード"
	@echo ""
	@echo "Usage: make [COMMAND]"
	@echo ""
	@echo "Commands:"
	@echo "  初期設定:"
	@echo "    cp                   .envrc.sample をコピーして direnv allow"
	@echo "    init                 mise install + uv sync を一括実行"
	@echo ""
	@echo "  よく使うコマンド:"
	@echo "    install              mise install で Python / uv をインストール"
	@echo "    sync                 uv sync で Python 依存をインストール"
	@echo "    lock                 uv lock で uv.lock を更新"
	@echo "    env/check            .envrc と .envrc.sample のキー差分をチェック"
	@echo "    env/allow            direnv allow を実行"
	@echo "    lint                 ruff check で apps/scripts/tests を lint (CI と同じ)"
	@echo "    lint/fix             ruff check --fix で自動修正"
	@echo "    syntax               python -m compileall で apps/ の構文チェック"
	@echo "    test                 pytest でユニットテストを実行 (CI と同じ)"
	@echo ""
	@echo "  ローカル実行（参考: 通常は Docker 内で動作させる）:"
	@echo "    run                  apps/insta360_auto_converter.py を直接実行 (Drive モード)"
	@echo "    refresh-gphotos      Google Photos の OAuth 認証を更新"
	@echo ""
	@echo "  Docker:"
	@echo "    docker/build         Docker イメージをビルド"
	@echo "    docker/run           Docker コンテナを起動 (Drive モード, INSTA360_DATA_DIR をマウント)"
	@echo "    docker/run/local     Docker コンテナを起動 (ローカル入力モード)"
	@echo "    docker/logs          Docker コンテナのログを追従"
	@echo "    docker/exec          Docker コンテナに bash で入る"
	@echo "    docker/stop/d        Docker コンテナを停止・削除"
	@echo "    docker/rebuild/d     停止 → ビルド → 起動 を一括実行"
	@echo ""
	@echo "  Docker GPU (Linux + NVIDIA GPU 環境のみ、例: WSL2 + RTX 系):"
	@echo "    INSTA360_GPU=1 make docker/run/local   # --gpus all 付きで起動"
	@echo "    詳細は README の \"NVIDIA GPU で動かす (WSL2 / Linux)\" を参照"
	@echo ""
	@echo "Examples:"
	@echo ""
	@echo "  $$ make cp                プロジェクトを初期化（.envrc 作成）"
	@echo "  $$ make init              mise install + uv sync"
	@echo "  $$ make docker/build      Docker イメージをビルド"
	@echo "  $$ make docker/run        コンテナを起動"
	@echo "  $$ make docker/logs       ログを追従"
	@echo ""
	@echo "注意: Docker コンテナの停止・再ビルドは安全性のため /d を付けたコマンドを使用してください"
	@echo "      例: make docker/stop/d"

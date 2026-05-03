# 再帰的な Make メッセージを非表示にする
MAKEFLAGS += --no-print-directory

# Docker（v2 を期待）
DOCKER := docker

# Docker イメージ・コンテナ名（.envrc で上書き可能）
DOCKER_IMAGE_NAME ?= insta360-auto-converter
DOCKER_CONTAINER_NAME ?= insta360-auto-converter

# データディレクトリのデフォルト（.envrc で上書き推奨）
INSTA360_DATA_DIR ?= $(CURDIR)/insta360-auto-converter-data

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
	uv run ruff check apps scripts

.PHONY: lint/fix
lint/fix:
	uv run ruff check --fix apps scripts

.PHONY: syntax
syntax:
	uv run python -m compileall -q apps

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
	@echo "Docker コンテナを起動中: $(DOCKER_CONTAINER_NAME)"
	@echo "  データディレクトリ: $(INSTA360_DATA_DIR)"
	$(DOCKER) run -d \
		--name $(DOCKER_CONTAINER_NAME) \
		-v $(INSTA360_DATA_DIR):/insta360-auto-converter-data \
		$(DOCKER_IMAGE_NAME)
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
	@echo "insta360-auto-converter - Insta360 .insv/.insp を Google Photos / YouTube に自動変換・アップロード"
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
	@echo "    lint                 ruff check で apps/scripts を lint (CI と同じ)"
	@echo "    lint/fix             ruff check --fix で自動修正"
	@echo "    syntax               python -m compileall で apps/ の構文チェック"
	@echo ""
	@echo "  ローカル実行（参考: 通常は Docker 内で動作させる）:"
	@echo "    run                  apps/insta360_auto_converter.py を直接実行"
	@echo "    refresh-gphotos      Google Photos の OAuth 認証を更新"
	@echo ""
	@echo "  Docker:"
	@echo "    docker/build         Docker イメージをビルド"
	@echo "    docker/run           Docker コンテナを起動（INSTA360_DATA_DIR をマウント）"
	@echo "    docker/logs          Docker コンテナのログを追従"
	@echo "    docker/exec          Docker コンテナに bash で入る"
	@echo "    docker/stop/d        Docker コンテナを停止・削除"
	@echo "    docker/rebuild/d     停止 → ビルド → 起動 を一括実行"
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

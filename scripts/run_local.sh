#!/usr/bin/env bash
# ローカル起動用のスクリプト（macOS / Linux）。
#
#   ./scripts/run_local.sh --example     付属の合成データで起動する
#   ./scripts/run_local.sh               data/ の自分のデータで起動する
#   ./scripts/run_local.sh --port 9000   ポートを変える
#   ./scripts/run_local.sh --rebuild     フロントエンドを作り直す
#   ./scripts/run_local.sh --api-only    フロントを使わず API のみ起動する
#
# 初回は仮想環境の作成・依存関係の導入・フロントエンドのビルドを行うため
# 数分かかる。2 回目以降は既にあるものを再利用する。

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

USE_EXAMPLE=0
REBUILD=0
API_ONLY=0
PORT=8000

while [[ $# -gt 0 ]]; do
  case "$1" in
    --example) USE_EXAMPLE=1; shift ;;
    --rebuild) REBUILD=1; shift ;;
    --api-only) API_ONLY=1; shift ;;
    --port) PORT="${2:?--port にはポート番号が必要です}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1（--help を参照）" >&2; exit 1 ;;
  esac
done

# ---- Python の確認 ----
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.11 以上が見つかりません。https://www.python.org/downloads/ から導入してください。" >&2
  exit 1
fi
echo "Python: $("$PYTHON" --version)"

# ---- 仮想環境と依存関係 ----
if [[ ! -d .venv ]]; then
  echo "仮想環境を作成します (.venv)…"
  "$PYTHON" -m venv .venv
fi
VENV_PY="$ROOT/.venv/bin/python"

# dmdeg が入っていなければ導入する
if ! "$VENV_PY" -c 'import dmdeg' >/dev/null 2>&1; then
  echo "依存関係を導入します（初回のみ・数分かかります）…"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -e ".[dev]"
fi

# ---- データの場所を決める ----
if [[ $USE_EXAMPLE -eq 1 ]]; then
  export DMDEG_DATA_DIR="$ROOT/example_data"
  export DMDEG_BUILD_DIR="$ROOT/build_example"
  if [[ ! -f "$DMDEG_DATA_DIR/datasets.csv" ]]; then
    echo "合成データを生成します…"
    "$VENV_PY" scripts/make_example_data.py --force
  fi
  echo "データ: 付属の合成データ (example_data/)"
else
  export DMDEG_DATA_DIR="$ROOT/data"
  export DMDEG_BUILD_DIR="$ROOT/build"
  echo "データ: data/（自分で登録した CSV）"
fi

# ---- 取り込み ----
echo
echo "CSV を検証して検索用ストアを構築します…"
if ! "$VENV_PY" -m dmdeg.ingest; then
  echo
  echo "取り込みに失敗しました。上のエラーを直してから再実行してください。" >&2
  echo "列の仕様は docs/DATA_FORMAT.md にあります。" >&2
  exit 1
fi

# ---- フロントエンド ----
if [[ $API_ONLY -eq 0 ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo
    echo "npm が見つかりません。Web 画面には Node.js 20 以上が必要です。" >&2
    echo "https://nodejs.org/ から導入するか、--api-only で API だけ起動してください。" >&2
    exit 1
  fi
  if [[ ! -d frontend/node_modules ]]; then
    echo "フロントエンドの依存関係を導入します（初回のみ）…"
    (cd frontend && npm install --no-audit --no-fund)
  fi
  if [[ $REBUILD -eq 1 || ! -f frontend/dist/index.html ]]; then
    echo "フロントエンドをビルドします（1〜2 分かかります）…"
    (cd frontend && npm run build)
  fi
fi

# ---- 起動 ----
echo
echo "------------------------------------------------------------"
if [[ $API_ONLY -eq 1 ]]; then
  echo " API:      http://127.0.0.1:${PORT}/api/docs"
else
  echo " Web 画面: http://127.0.0.1:${PORT}"
  echo " API 仕様: http://127.0.0.1:${PORT}/api/docs"
fi
echo " 終了するには Ctrl+C"
echo "------------------------------------------------------------"
echo

exec "$VENV_PY" -m uvicorn dmdeg.api.main:app --host 127.0.0.1 --port "$PORT"

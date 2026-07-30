#!/usr/bin/env bash
# コンテナ起動時に CSV を取り込んでからサーバを起動する。
#
# 起動のたびに取り込むので、ホスト側で CSV を編集したら
# `docker compose restart` するだけで反映される。
#
# 環境変数:
#   DMDEG_SKIP_INGEST=1   取り込みを飛ばして既存のストアをそのまま使う

set -euo pipefail

if [[ "${DMDEG_SKIP_INGEST:-0}" != "1" ]]; then
  echo "CSV を検証して検索用ストアを構築します (${DMDEG_DATA_DIR})…"
  if ! python -m dmdeg.ingest; then
    echo >&2
    echo "取り込みに失敗しました。上のエラーを直して再起動してください。" >&2
    echo "列の仕様は docs/DATA_FORMAT.md にあります。" >&2
    # 検証に失敗した状態で古いストアを配信すると、登録内容を偽って見せることに
    # なるため、サーバは起動せずに終了する
    exit 1
  fi
  echo
fi

exec "$@"

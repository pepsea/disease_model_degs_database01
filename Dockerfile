# 疾患モデル遺伝子発現データベース
#
# 2 段構成にして、Node.js を画面のビルドだけに使い、最終イメージには残さない。
# 実行に必要なのは Python と生成済みの静的ファイルだけ。

# ---- 1 段目: Web 画面をビルドする ----
FROM node:20-slim AS frontend

WORKDIR /build

# devDependencies の playwright はスモークテスト専用で、画面のビルドには不要。
# 既定ではインストール時に数百 MB のブラウザを取得しにいくため抑止する。
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# 依存関係の導入をソース変更から切り離し、画面のコードだけ直したときに
# npm ci をやり直さずに済むようにする
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/index.html ./
COPY frontend/src ./src
RUN npm run build


# ---- 2 段目: 実行イメージ ----
FROM python:3.12-slim AS runtime

# .pyc を書かず、ログを即座に流す（docker logs で追えるように）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DMDEG_DATA_DIR=/app/data \
    DMDEG_BUILD_DIR=/app/build

WORKDIR /app

# 依存関係を先に解決してレイヤをキャッシュさせる
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-cache-dir -e .

COPY scripts ./scripts
COPY docs ./docs
COPY data ./data
COPY example_data ./example_data
COPY --from=frontend /build/dist ./frontend/dist

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# root で動かさない。ただし取り込み先 (build/) は書き込める必要がある
RUN useradd --create-home --uid 10001 dmdeg \
    && mkdir -p /app/build /app/build_example \
    && chown -R dmdeg:dmdeg /app/build /app/build_example
USER dmdeg

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "dmdeg.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

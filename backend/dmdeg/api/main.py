"""FastAPI アプリ本体。

    uvicorn dmdeg.api.main:app --reload

環境変数:
  DMDEG_BASIC_AUTH  "user:pass" を設定すると全エンドポイントに BASIC 認証をかける
  DMDEG_CORS_ORIGINS  カンマ区切り。既定は Vite 開発サーバのみ許可
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from .. import config
from ..store import get_store
from .routers import analysis, catalog, compare, expression, export

_security = HTTPBasic(auto_error=False)


def _configured_credentials() -> tuple[str, str] | None:
    raw = os.environ.get("DMDEG_BASIC_AUTH", "").strip()
    if not raw or ":" not in raw:
        return None
    user, _, password = raw.partition(":")
    return user, password


def require_auth(credentials: HTTPBasicCredentials | None = Depends(_security)) -> None:
    """DMDEG_BASIC_AUTH が設定されているときのみ認証を要求する。"""
    expected = _configured_credentials()
    if expected is None:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証が必要です。",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(credentials.username, expected[0])
    password_ok = secrets.compare_digest(credentials.password, expected[1])
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザー名またはパスワードが違います。",
            headers={"WWW-Authenticate": "Basic"},
        )


def _mount_frontend(app: FastAPI) -> None:
    """ビルド済みフロントエンドがあれば同じサーバから配信する。

    ローカルでは 1 プロセスで完結させたいため。`npm run build` を実行して
    いない場合は API のみで動く（開発時は Vite の dev サーバを使う）。
    """
    dist = config.ROOT_DIR / "frontend" / "dist"
    index = dist / "index.html"
    if not index.exists():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # SPA なので /compare などのパスもすべて index.html を返し、
        # ルーティングはブラウザ側の react-router に任せる。
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


def create_app() -> FastAPI:
    app = FastAPI(
        title="疾患モデル遺伝子発現データベース",
        description=(
            "疾患モデル動物の遺伝子発現データを閲覧・比較解析する API。"
            "データ登録は data/ 配下の CSV で行う。"
        ),
        version="0.1.0",
        # 既定の /docs はフロントエンドの「データ登録」画面と衝突するため退避する
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    origins = os.environ.get("DMDEG_CORS_ORIGINS")
    allow_origins = (
        [o.strip() for o in origins.split(",") if o.strip()]
        if origins
        else ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (catalog.router, expression.router, compare.router, analysis.router, export.router):
        app.include_router(router, prefix="/api", dependencies=[Depends(require_auth)])

    @app.get("/api/health")
    def health() -> dict:
        """ストアが開けるかまで含めた死活確認。"""
        store = get_store()
        manifest = store.manifest()
        return {
            "status": "ok",
            "data_dir": str(config.data_dir()),
            "build_dir": str(config.build_dir()),
            "ingested_at": manifest.get("generated_at"),
            "counts": manifest.get("counts", {}),
        }

    # SPA のフォールバックは総取りのルートなので、必ず最後に登録する。
    # 先に登録すると /api/* まで index.html を返してしまう。
    _mount_frontend(app)

    return app


app = create_app()

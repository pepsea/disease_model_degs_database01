<#
ローカル起動用のスクリプト（Windows PowerShell）。

  .\scripts\run_local.ps1 -Example      付属の合成データで起動する
  .\scripts\run_local.ps1               data\ の自分のデータで起動する
  .\scripts\run_local.ps1 -Port 9000    ポートを変える
  .\scripts\run_local.ps1 -Rebuild      フロントエンドを作り直す
  .\scripts\run_local.ps1 -ApiOnly      フロントを使わず API のみ起動する

初回は仮想環境の作成・依存関係の導入・フロントエンドのビルドを行うため
数分かかる。2 回目以降は既にあるものを再利用する。

スクリプトの実行が禁止されている場合は、PowerShell で次を一度実行する:
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>

[CmdletBinding()]
param(
  [switch]$Example,
  [switch]$Rebuild,
  [switch]$ApiOnly,
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path

# ---- Python の確認 ----
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
  $command = Get-Command $candidate -ErrorAction SilentlyContinue
  if ($null -eq $command) { continue }
  & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
  if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
}
if (-not $python) {
  Write-Error "Python 3.11 以上が見つかりません。https://www.python.org/downloads/ から導入してください。"
  exit 1
}
Write-Host "Python: $(& $python --version)"

# ---- 仮想環境と依存関係 ----
if (-not (Test-Path ".venv")) {
  Write-Host "仮想環境を作成します (.venv)…"
  & $python -m venv .venv
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

& $venvPy -c "import dmdeg" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "依存関係を導入します（初回のみ・数分かかります）…"
  & $venvPy -m pip install --quiet --upgrade pip
  & $venvPy -m pip install --quiet -e ".[dev]"
}

# ---- データの場所を決める ----
if ($Example) {
  $env:DMDEG_DATA_DIR = Join-Path $root "example_data"
  $env:DMDEG_BUILD_DIR = Join-Path $root "build_example"
  if (-not (Test-Path (Join-Path $env:DMDEG_DATA_DIR "datasets.csv"))) {
    Write-Host "合成データを生成します…"
    & $venvPy scripts\make_example_data.py --force
  }
  Write-Host "データ: 付属の合成データ (example_data\)"
} else {
  $env:DMDEG_DATA_DIR = Join-Path $root "data"
  $env:DMDEG_BUILD_DIR = Join-Path $root "build"
  Write-Host "データ: data\（自分で登録した CSV）"
}

# ---- 取り込み ----
Write-Host ""
Write-Host "CSV を検証して検索用ストアを構築します…"
& $venvPy -m dmdeg.ingest
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Error "取り込みに失敗しました。上のエラーを直してから再実行してください。列の仕様は docs\DATA_FORMAT.md にあります。"
  exit 1
}

# ---- フロントエンド ----
if (-not $ApiOnly) {
  if ($null -eq (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Error "npm が見つかりません。Web 画面には Node.js 20 以上が必要です。https://nodejs.org/ から導入するか、-ApiOnly で API だけ起動してください。"
    exit 1
  }
  if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "フロントエンドの依存関係を導入します（初回のみ）…"
    Push-Location frontend; npm install --no-audit --no-fund; Pop-Location
  }
  if ($Rebuild -or -not (Test-Path "frontend\dist\index.html")) {
    Write-Host "フロントエンドをビルドします（1〜2 分かかります）…"
    Push-Location frontend; npm run build; Pop-Location
  }
}

# ---- 起動 ----
Write-Host ""
Write-Host "------------------------------------------------------------"
if ($ApiOnly) {
  Write-Host " API:      http://127.0.0.1:$Port/api/docs"
} else {
  Write-Host " Web 画面: http://127.0.0.1:$Port"
  Write-Host " API 仕様: http://127.0.0.1:$Port/api/docs"
}
Write-Host " 終了するには Ctrl+C"
Write-Host "------------------------------------------------------------"
Write-Host ""

& $venvPy -m uvicorn dmdeg.api.main:app --host 127.0.0.1 --port $Port

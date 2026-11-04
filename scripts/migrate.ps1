# Apply database migrations (Alembic). Safe & idempotent.
# Usage:  .\scripts\migrate.ps1            (upgrade to latest)
#         .\scripts\migrate.ps1 current    (show current revision)
#         .\scripts\migrate.ps1 history    (list revisions)
param(
    [string]$Action = "upgrade"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

switch ($Action) {
    "upgrade" { & $python -m alembic upgrade head }
    "current" { & $python -m alembic current }
    "history" { & $python -m alembic history --verbose }
    "downgrade" { Write-Error "Downgrade dinonaktifkan (non-destruktif). Lihat alembic/versions." }
    default { Write-Error "Aksi tidak dikenal: $Action" }
}

param(
    [string]$Database = "absensi",
    [string]$User = "root",
    [string]$Password = "",
    [string]$DbHost = "localhost",
    [int]$Port = 3306,
    [string]$OutputDir = "backups"
)

$ErrorActionPreference = "Stop"

$mysqlBin = "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin"
$mysqldump = Join-Path $mysqlBin "mysqldump.exe"

if (-not (Test-Path $mysqldump)) {
    throw "mysqldump.exe tidak ditemukan di $mysqldump"
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $OutputDir ("{0}-{1}.sql" -f $Database, $timestamp)

$args = @("-h", $DbHost, "-P", "$Port", "-u", $User)
if ($Password -ne "") {
    $args += "-p$Password"
}
$args += @("--databases", $Database, "--single-transaction", "--routines", "--triggers")

$dumpOutput = & $mysqldump @args 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Backup gagal: $dumpOutput"
}

$dumpOutput | Set-Content -Path $backupFile -Encoding UTF8
Write-Host "Backup berhasil: $backupFile"

param(
    [Parameter(Mandatory = $true)]
    [string]$File,
    [string]$User = "root",
    [string]$Password = "",
    [string]$DbHost = "localhost",
    [int]$Port = 3306
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $File)) {
    throw "File backup tidak ditemukan: $File"
}

$mysqlBin = "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin"
$mysql = Join-Path $mysqlBin "mysql.exe"

if (-not (Test-Path $mysql)) {
    throw "mysql.exe tidak ditemukan di $mysql"
}

$args = @("-h", $DbHost, "-P", "$Port", "-u", $User)
if ($Password -ne "") {
    $args += "-p$Password"
}

Get-Content -Path $File -Raw | & $mysql @args
if ($LASTEXITCODE -ne 0) {
    throw "Restore gagal"
}

Write-Host "Restore berhasil dari: $File"

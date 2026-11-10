param(
    [ValidateSet('api', 'worker', 'migrate', 'stop-db')]
    [string]$Mode = 'api',
    [string]$PostgresBin = 'D:\Program Files\PostgreSQL\17\bin'
)

$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.local'
$data = Join-Path $runtime 'postgres'
$log = Join-Path $runtime 'postgres.log'
$pgCtl = Join-Path $PostgresBin 'pg_ctl.exe'
$pgPort = 55432
$apiHost = '127.0.0.1'
$apiPort = 8000

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments, [string]$Stage = $Command)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Stage failed (exit code $LASTEXITCODE). See the output above for the original error." }
}

function Assert-ApiPortAvailable {
    $connection = [Net.Sockets.TcpClient]::new()
    try {
        $connection.Connect($apiHost, $apiPort)
    } catch [Net.Sockets.SocketException] {
        if ($_.Exception.SocketErrorCode -eq [Net.Sockets.SocketError]::ConnectionRefused) { return }
        throw
    } finally {
        $connection.Dispose()
    }
    throw "API port ${apiHost}:$apiPort is already in use. To load the current code, stop the previous API (Ctrl+C in its window), then rerun this command. For the training worker, use -Mode worker."
}

if ($Mode -eq 'stop-db') {
    if (Test-Path -LiteralPath (Join-Path $data 'PG_VERSION')) {
        & $pgCtl status -D $data | Out-Null
        if ($LASTEXITCODE -eq 0) { Invoke-Checked $pgCtl @('stop', '-D', $data, '-m', 'fast', '-w') }
    }
    exit
}

if ($Mode -eq 'api') { Assert-ApiPortAvailable }

if (-not $env:WORKBENCH_DATABASE_URL) {
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $passwordPath = Join-Path $runtime 'postgres-password'
    if (-not (Test-Path -LiteralPath $passwordPath)) {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [IO.File]::WriteAllText($passwordPath, [Convert]::ToBase64String($bytes))
    }
    if (-not (Test-Path -LiteralPath (Join-Path $data 'PG_VERSION'))) {
        Invoke-Checked (Join-Path $PostgresBin 'initdb.exe') @(
            '-D', $data, '-U', 'workbench', '-A', 'scram-sha-256',
            '--pwfile', $passwordPath, '--encoding=UTF8', '--no-locale'
        )
        Add-Content -LiteralPath (Join-Path $data 'postgresql.conf') -Encoding ascii -Value @(
            "listen_addresses = '127.0.0.1'", "port = $pgPort"
        )
    }
    & $pgCtl status -D $data | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked $pgCtl @('start', '-D', $data, '-l', $log, '-w')
    }
    $password = [IO.File]::ReadAllText($passwordPath).Trim()
    $encoded = [uri]::EscapeDataString($password)
    $previousPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $password
        $connection = @('-w', '-h', '127.0.0.1', '-p', "$pgPort", '-U', 'workbench')
        $existing = Invoke-Checked (Join-Path $PostgresBin 'psql.exe') (
            $connection + @('-d', 'postgres', '-Atc', "SELECT 1 FROM pg_database WHERE datname = 'inspection_workbench'")
        )
        if ($existing -ne '1') {
            Invoke-Checked (Join-Path $PostgresBin 'createdb.exe') ($connection + 'inspection_workbench')
        }
    } finally { $env:PGPASSWORD = $previousPassword }
    $env:WORKBENCH_DATABASE_URL = "postgresql+psycopg://workbench:${encoded}@127.0.0.1:${pgPort}/inspection_workbench"
}
if (-not $env:WORKBENCH_DATA_DIR) { $env:WORKBENCH_DATA_DIR = Join-Path $runtime 'media' }

Push-Location (Join-Path $PSScriptRoot 'backend')
try {
    Invoke-Checked 'conda' @('run', '--no-capture-output', '-n', 'YoloWebAgentStarter', 'python', '-m', 'alembic', 'upgrade', 'head') 'Database migration (Alembic)'
    if ($Mode -eq 'api') {
        Invoke-Checked 'conda' @('run', '--no-capture-output', '-n', 'YoloWebAgentStarter', 'python', '-m', 'uvicorn',
            'app.main:app', '--host', $apiHost, '--port', "$apiPort") 'API startup (Uvicorn)'
    }
    if ($Mode -eq 'worker') {
        Invoke-Checked 'conda' @('run', '--no-capture-output', '-n', 'YoloWebAgentStarter', 'python', '-B', '-m', 'app.training.worker') 'CPU training worker'
    }
} finally { Pop-Location }

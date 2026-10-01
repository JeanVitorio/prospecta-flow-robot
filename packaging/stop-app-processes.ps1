param(
    [Parameter(Mandatory = $true)]
    [string]$InstallPath
)

$ErrorActionPreference = "SilentlyContinue"
$root = [System.IO.Path]::GetFullPath($InstallPath).TrimEnd("\") + "\"
$currentProcessId = $PID

# Encerra somente executáveis distribuídos dentro da pasta do Prospecta Flow.
# O /T também finaliza Chrome, ChromeDriver e Node iniciados por cada worker.
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $currentProcessId -and
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith(
        $root,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    $_.Name -notlike "unins*.exe"
}

foreach ($process in $processes) {
    & taskkill.exe /PID $process.ProcessId /T /F 2>$null | Out-Null
}

# Aguarda a liberação dos arquivos antes de o desinstalador continuar.
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $remaining = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $currentProcessId -and
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith(
            $root,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        $_.Name -notlike "unins*.exe"
    }
    if (-not $remaining) {
        break
    }
    Start-Sleep -Milliseconds 250
}

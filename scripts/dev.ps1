# hg-dl 一键起前后端：先清 8000/5173，再开两个窗口
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "backend"))) {
  $Root = $PSScriptRoot
}

function Stop-PortListeners([int[]]$Ports) {
  foreach ($port in $Ports) {
    try {
      $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
      foreach ($c in $conns) {
        $procId = $c.OwningProcess
        if ($procId -and $procId -ne 0) {
          Write-Host "kill pid $procId on port $port"
          Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
      }
    } catch {
      # fallback: netstat
      $lines = netstat -ano | Select-String ":$port\s+.*LISTENING"
      foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
        $procId = $parts[-1]
        if ($procId -match "^\d+$") {
          Write-Host "kill pid $procId on port $port"
          Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
      }
    }
  }
}

Write-Host "Stopping listeners on 8000 / 5173 ..."
Stop-PortListeners @(8000, 5173)
Start-Sleep -Seconds 1

$be = Join-Path $Root "backend"
$fe = Join-Path $Root "frontend"

Write-Host "Starting backend (8000) ..."
Start-Process powershell -WorkingDirectory $be -ArgumentList @(
  "-NoExit", "-Command",
  "uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --reload-dir . --reload-dir ..\packages\core"
)

Write-Host "Starting frontend (5173) ..."
Start-Process powershell -WorkingDirectory $fe -ArgumentList @(
  "-NoExit", "-Command",
  "npm run dev -- --host 0.0.0.0 --port 5173"
)

Write-Host "Done. Backend http://127.0.0.1:8000  Frontend http://127.0.0.1:5173"

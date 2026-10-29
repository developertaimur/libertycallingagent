# Hot-reload Jessica agent on Windows (requires SWML_BASIC_AUTH_* in .env)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path .env) {
  Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $name, $value = $_ -split '=', 2
    if ($name -and $value -ne $null) {
      [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
  }
}
$port = if ($env:AGENT_PORT) { $env:AGENT_PORT } else { "3000" }
uvicorn agent.jessica_agent:app --reload --host 0.0.0.0 --port $port

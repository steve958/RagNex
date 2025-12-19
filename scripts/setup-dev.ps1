param(
  [switch]$NoUp
)

$ErrorActionPreference = 'Stop'

$envFile = Join-Path $PSScriptRoot '..\.env'
$envExample = Join-Path $PSScriptRoot '..\.env.example'

if (-not (Test-Path $envFile)) {
  if (Test-Path $envExample) {
    Copy-Item $envExample $envFile -Force
    Write-Host "Created .env from .env.example"
  } else {
    Write-Warning "No .env.example found; create .env manually."
  }
}

if (-not $NoUp) {
  docker compose -f (Join-Path $PSScriptRoot '..\docker-compose.dev.yml') up -d
}

Write-Host "Dev services are starting."
Write-Host "- Postgres: localhost:5432"
Write-Host "- Redis: localhost:6379"
Write-Host "- OpenSearch: http://localhost:9200"
Write-Host "- OpenSearch Dashboards: http://localhost:5601"
Write-Host "- MinIO: http://localhost:9000 (console: http://localhost:9001)"

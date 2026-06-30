# Fix PostgreSQL Password Issue
# This script recreates the PostgreSQL container with the correct password

Write-Host "Stopping and removing old PostgreSQL container..." -ForegroundColor Yellow
docker stop aic_postgres 2>$null
docker rm aic_postgres 2>$null

Write-Host "Removing old PostgreSQL data volume..." -ForegroundColor Yellow
docker volume rm backend_postgres_data 2>$null

Write-Host "Recreating PostgreSQL container with correct password..." -ForegroundColor Green
docker run -d `
  --name aic_postgres `
  --network backend_aic_net `
  -e POSTGRES_DB=ai_coding_assistant `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -p 5432:5432 `
  postgres:16-alpine

Write-Host ""
Write-Host "Waiting for PostgreSQL to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

Write-Host "PostgreSQL is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "Now run: alembic upgrade head" -ForegroundColor Cyan

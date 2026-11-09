# ==============================================================================
# Neutron Search Engine: Automated Hugging Face Spaces Deployment Script
# Usage: .\scripts\deploy_spaces.ps1 -Username "your-hf-username"
# ==============================================================================

param (
    [Parameter(Mandatory=$false)]
    [string]$Username = ""
)

if (-not $Username) {
    $Username = Read-Host "Enter your Hugging Face username"
}

if (-not $Username) {
    Write-Host "Error: Hugging Face username is required." -ForegroundColor Red
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Deploying Neutron Microservices to Hugging Face Spaces" -ForegroundColor Cyan
Write-Host "  Target Username: $Username" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$root = Get-Location

# 1. Deploy Renderer
Write-Host "`n[1/3] Deploying 'neutron-renderer' Space..." -ForegroundColor Yellow
$rendererPath = Join-Path $root "spaces\renderer"
Set-Location $rendererPath
if (-not (Test-Path ".git")) { git init }
git remote remove origin -ErrorAction SilentlyContinue
git remote add origin "https://huggingface.co/spaces/$Username/neutron-renderer"
git add .
git commit -m "Deploy stealth renderer service" -ErrorAction SilentlyContinue
git branch -M main
git push -u origin main --force

# 2. Deploy Crawler
Write-Host "`n[2/3] Deploying 'neutron-crawler' Space..." -ForegroundColor Yellow
$crawlerPath = Join-Path $root "spaces\crawler"
Set-Location $crawlerPath
if (-not (Test-Path ".git")) { git init }
git remote remove origin -ErrorAction SilentlyContinue
git remote add origin "https://huggingface.co/spaces/$Username/neutron-crawler"
git add .
git commit -m "Deploy crawler worker service" -ErrorAction SilentlyContinue
git branch -M main
git push -u origin main --force

# 3. Deploy Gateway
Write-Host "`n[3/3] Deploying 'neutron-gateway' Space..." -ForegroundColor Yellow
$gatewayPath = Join-Path $root "spaces\gateway"
Set-Location $gatewayPath
if (-not (Test-Path ".git")) { git init }
git remote remove origin -ErrorAction SilentlyContinue
git remote add origin "https://huggingface.co/spaces/$Username/neutron-gateway"
git add .
git commit -m "Deploy search gateway service" -ErrorAction SilentlyContinue
git branch -M main
git push -u origin main --force

Set-Location $root

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  🎉 All 3 Spaces Pushed Successfully!" -ForegroundColor Green
Write-Host "  Remember to configure Secrets in Space Settings:" -ForegroundColor Cyan
Write-Host "  - INTERNAL_API_KEY" -ForegroundColor White
Write-Host "  - TURSO_DATABASE_URL and TURSO_AUTH_TOKEN" -ForegroundColor White
Write-Host "  - R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green


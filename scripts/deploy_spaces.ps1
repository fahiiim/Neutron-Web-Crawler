# ==============================================================================
# Neutron Search Engine: Automated Hugging Face Spaces Deployment Script
# Usage: .\scripts\deploy_spaces.ps1 -Username "fahiiim"
# ==============================================================================

param (
    [Parameter(Mandatory=$false)]
    [string]$Username = ""
)

if (-not $Username) {
    $Username = Read-Host "Enter your Hugging Face username (e.g. fahiiim)"
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
Write-Host "`n[1/2] Deploying 'Neutron_Renderer' Space..." -ForegroundColor Yellow
$rendererPath = Join-Path $root "spaces\renderer"
Set-Location $rendererPath
if (-not (Test-Path ".git")) { git init }
git remote remove origin -ErrorAction SilentlyContinue
git remote add origin "https://huggingface.co/spaces/$Username/Neutron_Renderer"
git add .
git commit -m "Deploy stealth renderer service" -ErrorAction SilentlyContinue
git branch -M main
git push -u origin main --force

# 2. Deploy Crawler (Unified Gateway + Search UI + Crawler Worker)
Write-Host "`n[2/2] Deploying 'Neutron_Crawler' Space (UI + Crawler)..." -ForegroundColor Yellow
$crawlerPath = Join-Path $root "spaces\crawler"
Set-Location $crawlerPath
if (-not (Test-Path ".git")) { git init }
git remote remove origin -ErrorAction SilentlyContinue
git remote add origin "https://huggingface.co/spaces/$Username/Neutron_Crawler"
git add .
git commit -m "Deploy unified search engine and crawler" -ErrorAction SilentlyContinue
git branch -M main
git push -u origin main --force

Set-Location $root

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  🎉 Both Spaces Pushed Successfully!" -ForegroundColor Green
Write-Host "  Search UI will be live at: https://$Username-neutron-crawler.hf.space" -ForegroundColor Cyan
Write-Host "  Remember to configure Secrets under Space Settings -> Variables and secrets:" -ForegroundColor Cyan
Write-Host "  - INTERNAL_API_KEY" -ForegroundColor White
Write-Host "  - TURSO_DATABASE_URL and TURSO_AUTH_TOKEN" -ForegroundColor White
Write-Host "  - RENDERER_SERVICE_URL = https://$Username-neutron-renderer.hf.space" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green

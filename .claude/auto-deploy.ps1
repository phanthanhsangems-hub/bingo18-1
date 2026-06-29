param()
$ErrorActionPreference = 'Continue'
$ProjectDir = 'C:\Users\ACER\bingo18'
$LogFile = "$ProjectDir\.claude\deploy.log"
$Ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Log($msg) {
    $line = "[$Ts] $msg"
    Add-Content $LogFile $line
    Write-Host $line
}

Set-Location $ProjectDir
$Hash = git rev-parse --short HEAD 2>&1
if ($LASTEXITCODE -ne 0) { Log "ERROR: git rev-parse failed — $Hash"; exit 1 }

$TAG = "auto-$Hash"
Log "=== Auto-deploy start: $TAG ==="

# Step 1: Build
Log "Building image..."
$buildOut = gcloud builds submit --tag "asia-southeast1-docker.pkg.dev/bingo18-predictor/bingo18-images/bingo18:$TAG" --project bingo18-predictor 2>&1
$buildOut | ForEach-Object { Log $_ }

if ($LASTEXITCODE -ne 0) {
    Log "ERROR: Build failed (exit $LASTEXITCODE)"
    exit 1
}
Log "Build OK"

# Step 2: Deploy
Log "Deploying to Cloud Run..."
$deployOut = gcloud run deploy bingo18 --image "asia-southeast1-docker.pkg.dev/bingo18-predictor/bingo18-images/bingo18:$TAG" --region asia-southeast1 --project bingo18-predictor 2>&1
$deployOut | ForEach-Object { Log $_ }

if ($LASTEXITCODE -ne 0) {
    Log "ERROR: Deploy failed (exit $LASTEXITCODE)"
    exit 1
}
Log "=== Deploy complete ==="

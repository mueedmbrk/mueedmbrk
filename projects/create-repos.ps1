<#
.SYNOPSIS
    Creates one public GitHub repo per project and pushes the code. (Windows / PowerShell)

.DESCRIPTION
    The PowerShell equivalent of create-repos.sh, for Windows users who do not
    have Git Bash or the GitHub CLI.

    Requires: Git for Windows, and a GitHub personal access token with `repo` scope
    (create one at https://github.com/settings/tokens).

    Safe to re-run: repos that already exist are skipped, not overwritten.

.EXAMPLE
    $env:GITHUB_TOKEN = "ghp_your_token_here"
    .\create-repos.ps1

.EXAMPLE
    .\create-repos.ps1 -Token "ghp_your_token_here" -Owner "mueedmbrk"
#>

[CmdletBinding()]
param(
    [string]$Token = $env:GITHUB_TOKEN,
    [string]$Owner = "mueedmbrk"
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 defaults to TLS 1.0, which GitHub rejects.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $Token) {
    Write-Host ""
    Write-Host "No GitHub token supplied." -ForegroundColor Red
    Write-Host ""
    Write-Host "  1. Create one at https://github.com/settings/tokens (scope: repo)"
    Write-Host "  2. Then run:"
    Write-Host ""
    Write-Host '     $env:GITHUB_TOKEN = "ghp_your_token_here"' -ForegroundColor Cyan
    Write-Host "     .\create-repos.ps1" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed. Get it from https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

$headers = @{
    Authorization          = "Bearer $Token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$projects = [ordered]@{
    "elder-care-monitoring-system" = @{
        Description = "Real-time computer vision fall detection for elderly care - OpenCV posture tracking with instant carer alerts"
        Topics      = @("python","ai","machine-learning","computer-vision","opencv","healthcare","fall-detection")
    }
    "disease-prediction-engine" = @{
        Description = "ML engine that ranks probable diseases from symptoms, with independent red-flag escalation for urgent cases"
        Topics      = @("python","ai","machine-learning","scikit-learn","healthcare","classification","fastapi")
    }
    "business-automation-chatbot" = @{
        Description = "FAQ-grounded conversational agent that qualifies leads, answers from your facts, and hands off to a human"
        Topics      = @("python","ai","chatbot","claude","llm","conversational-ai","fastapi")
    }
    "automated-data-pipeline" = @{
        Description = "Scheduled ETL with real quality gates - reports that arrive without anyone touching a spreadsheet"
        Topics      = @("python","etl","data-engineering","pandas","automation")
    }
    "document-intelligence-system" = @{
        Description = "OCR and NLP pipeline turning scans and PDFs into structured records that check their own arithmetic"
        Topics      = @("python","ai","ocr","nlp","document-processing","tesseract")
    }
    "voice-appointment-agent" = @{
        Description = "Voice AI phone agent - Whisper transcription, Claude reasoning, calendar booking and SMS confirmation via n8n"
        Topics      = @("python","ai","voice-ai","whisper","n8n","twilio","automation")
    }
    "rag-knowledge-assistant" = @{
        Description = "RAG assistant answering staff questions from company documents with citations, or an honest I-do-not-know"
        Topics      = @("python","ai","rag","claude","embeddings","supabase","vector-search")
    }
}

# Verify the token before doing anything destructive.
try {
    $me = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -Method Get
    Write-Host "Authenticated as $($me.login)" -ForegroundColor Green
}
catch {
    Write-Host "Token rejected by GitHub. Check it has the 'repo' scope and has not expired." -ForegroundColor Red
    exit 1
}

Write-Host "Publishing $($projects.Count) projects to github.com/$Owner"
Write-Host ""

$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

foreach ($name in $projects.Keys) {
    $info = $projects[$name]
    Write-Host "--- $name ---" -ForegroundColor Cyan

    $path = Join-Path $root $name
    if (-not (Test-Path $path)) {
        Write-Host "    directory missing, skipping" -ForegroundColor Yellow
        continue
    }

    # -- create the repo (or skip if it already exists) ------------------
    $exists = $true
    try {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$name" -Headers $headers -Method Get | Out-Null
    }
    catch {
        $exists = $false
    }

    if ($exists) {
        Write-Host "    repo already exists, skipping creation"
    }
    else {
        $body = @{
            name        = $name
            description = $info.Description
            private     = $false
        } | ConvertTo-Json

        try {
            Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Headers $headers `
                -Method Post -Body $body -ContentType "application/json" | Out-Null
            Write-Host "    repo created" -ForegroundColor Green
        }
        catch {
            Write-Host "    create failed: $($_.Exception.Message)" -ForegroundColor Red
            continue
        }
    }

    # -- topics ----------------------------------------------------------
    try {
        $topicBody = @{ names = $info.Topics } | ConvertTo-Json
        Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$name/topics" -Headers $headers `
            -Method Put -Body $topicBody -ContentType "application/json" | Out-Null
    }
    catch {
        Write-Host "    could not set topics" -ForegroundColor Yellow
    }

    # -- commit and push -------------------------------------------------
    Push-Location $path
    try {
        if (-not (Test-Path ".git")) {
            git init -q -b main
            git add -A
            git commit -q -m "feat: initial implementation`n`nWorking reference implementation with tests, configuration and documentation."
        }

        git remote remove origin 2>$null | Out-Null
        git remote add origin "https://x-access-token:$Token@github.com/$Owner/$name.git"

        $pushed = $false
        foreach ($attempt in 1..4) {
            git push -u origin main 2>$null
            if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
            $delay = [Math]::Pow(2, $attempt)
            Write-Host "    push failed, retrying in $delay s..." -ForegroundColor Yellow
            Start-Sleep -Seconds $delay
        }

        if ($pushed) {
            Write-Host "    pushed to main" -ForegroundColor Green
        }
        else {
            Write-Host "    push failed after 4 attempts" -ForegroundColor Red
        }

        # Never leave the token sitting in the remote URL.
        git remote set-url origin "https://github.com/$Owner/$name.git"
    }
    finally {
        Pop-Location
    }

    Write-Host ""
}

Write-Host "Done. Your repos: https://github.com/$Owner?tab=repositories" -ForegroundColor Green

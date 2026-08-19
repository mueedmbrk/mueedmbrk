<#
    One-paste publisher (Windows PowerShell).

    Clones the project branch to a temp folder and creates all seven repos.
    Nothing needs to exist locally first.

    Usage:
        $env:GITHUB_TOKEN = "ghp_your_token"
        irm https://raw.githubusercontent.com/mueedmbrk/mueedmbrk/claude/github-projects-setup-vxelek/projects/publish.ps1 | iex
#>

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $env:GITHUB_TOKEN) {
    Write-Host ""
    Write-Host "Set your token first:" -ForegroundColor Red
    Write-Host '    $env:GITHUB_TOKEN = "ghp_your_token_here"' -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Create one at https://github.com/settings/tokens (scope: repo)"
    return
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed: https://git-scm.com/download/win" -ForegroundColor Red
    return
}

$branch = "claude/github-projects-setup-vxelek"
$work   = Join-Path $env:TEMP ("mueed-projects-" + [Guid]::NewGuid().ToString("N").Substring(0,8))

Write-Host "Cloning project branch..." -ForegroundColor Cyan
git clone -q --depth 1 --branch $branch https://github.com/mueedmbrk/mueedmbrk.git $work
if ($LASTEXITCODE -ne 0) {
    Write-Host "Clone failed." -ForegroundColor Red
    return
}

$projects = Join-Path $work "projects"
Set-Location $projects
Write-Host "Working in $projects" -ForegroundColor DarkGray
Write-Host ""

& (Join-Path $projects "create-repos.ps1")

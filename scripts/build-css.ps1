# Builds static/css/tailwind.css on Windows. Run from the project folder:
#   .\scripts\build-css.ps1            build once
#   .\scripts\build-css.ps1 -Watch     rebuild automatically while you edit templates
param([switch]$Watch)

$ErrorActionPreference = 'Stop'
$version = '3.4.17'
Set-Location (Join-Path $PSScriptRoot '..')

$tool = "tools/tailwindcss-$version.exe"
if (-not (Test-Path $tool)) {
    Write-Host "Downloading Tailwind CLI $version..."
    New-Item -ItemType Directory -Force tools | Out-Null
    Invoke-WebRequest "https://github.com/tailwindlabs/tailwindcss/releases/download/v$version/tailwindcss-windows-x64.exe" -OutFile $tool
}

New-Item -ItemType Directory -Force static/css | Out-Null
$arguments = @('-c', 'tailwind.config.js', '-i', 'static/src/tailwind.input.css', '-o', 'static/css/tailwind.css')
if ($Watch) { $arguments += '--watch' } else { $arguments += '--minify' }
& $tool @arguments
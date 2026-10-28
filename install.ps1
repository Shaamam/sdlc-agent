<#
.SYNOPSIS
  Install sdlc-agent (/ship) globally for Claude Code on Windows.

.DESCRIPTION
  Copies the skill, subagent and guardrail hook into your Claude config folder
  and registers the hook in settings.json. Re-run after `git pull` to update.
  Honors CLAUDE_CONFIG_DIR and SDLC_AGENT_HOME. Works in Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
.EXAMPLE
  .\install.ps1 -Uninstall -Purge
#>
[CmdletBinding()]
param(
  [switch]$Uninstall,
  [switch]$Force,
  [switch]$Purge
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$RepoDir   = $PSScriptRoot
$HomeDir   = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$ClaudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HomeDir '.claude' }
$AgentHome = if ($env:SDLC_AGENT_HOME) { $env:SDLC_AGENT_HOME } else { Join-Path (Join-Path $HomeDir '.config') 'sdlc-agent' }
$Manifest  = Join-Path $AgentHome 'installed.txt'
$Settings  = Join-Path $ClaudeDir 'settings.json'
$script:NewManifest = @()

function Write-Info([string]$msg) { Write-Host "  $msg" }

function Find-Python {
  foreach ($candidate in @('py -3', 'python', 'python3')) {
    $parts = $candidate -split ' '
    $exe = $parts[0]
    $extra = @()
    if ($parts.Count -gt 1) { $extra = $parts[1..($parts.Count - 1)] }
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try {
      $out = & $exe @extra -c 'import sys; print(sys.executable) if sys.version_info >= (3, 9) else sys.exit(1)' 2>$null
      if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -First 1)).Trim() }
    } catch { }
  }
  return $null
}

function Test-InClaudeDir([string]$path) {
  $root = [System.IO.Path]::GetFullPath($ClaudeDir).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
  return [System.IO.Path]::GetFullPath($path).StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-Ours([string]$target) {
  if (-not (Test-Path -LiteralPath $Manifest)) { return $false }
  return @(Get-Content -LiteralPath $Manifest) -contains $target
}

function Get-Targets {
  $list = @((Join-Path (Join-Path $ClaudeDir 'skills') 'ship'), (Join-Path (Join-Path $ClaudeDir 'hooks') 'sdlc-agent'))
  foreach ($f in Get-ChildItem -LiteralPath (Join-Path $RepoDir 'agents') -Filter '*.md' -File) {
    $list += (Join-Path (Join-Path $ClaudeDir 'agents') $f.Name)
  }
  return $list
}

function Install-Item([string]$src, [string]$target) {
  if (Test-Path -LiteralPath $target) {
    if (-not (Test-Ours $target) -and -not $Force) {
      throw "$target already exists and wasn't installed by sdlc-agent. Re-run with -Force to replace it."
    }
    Remove-Item -LiteralPath $target -Recurse -Force
  }
  $parent = Split-Path -Parent $target
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  Copy-Item -LiteralPath $src -Destination $target -Recurse -Force
  if (Test-Path -LiteralPath $target -PathType Container) {
    Get-ChildItem -LiteralPath $target -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
      Remove-Item -Recurse -Force
  }
  $script:NewManifest += $target
  Write-Info "copy  $target"
}

function Invoke-Python([string]$py, [string[]]$arguments) {
  & $py @arguments | Out-Host
  return $LASTEXITCODE
}

function Install-Agent {
  $py = Find-Python
  if (-not $py) { throw 'Python 3.9+ is required (install from python.org, then re-run).' }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git is required (https://git-scm.com/downloads).' }

  Write-Host "Installing sdlc-agent from $RepoDir"
  New-Item -ItemType Directory -Force -Path $ClaudeDir, $AgentHome | Out-Null

  Install-Item (Join-Path (Join-Path $RepoDir 'skills') 'ship') (Join-Path (Join-Path $ClaudeDir 'skills') 'ship')
  foreach ($f in Get-ChildItem -LiteralPath (Join-Path $RepoDir 'agents') -Filter '*.md' -File) {
    Install-Item $f.FullName (Join-Path (Join-Path $ClaudeDir 'agents') $f.Name)
  }
  Install-Item (Join-Path $RepoDir 'hooks') (Join-Path (Join-Path $ClaudeDir 'hooks') 'sdlc-agent')

  if (Test-Path -LiteralPath $Manifest) {
    foreach ($old in @(Get-Content -LiteralPath $Manifest)) {
      if ($old -and ($script:NewManifest -notcontains $old) -and (Test-InClaudeDir $old) -and (Test-Path -LiteralPath $old)) {
        Remove-Item -LiteralPath $old -Recurse -Force
        Write-Info "removed stale $old"
      }
    }
  }
  Set-Content -LiteralPath $Manifest -Value $script:NewManifest

  $guard = Join-Path (Join-Path (Join-Path $ClaudeDir 'hooks') 'sdlc-agent') 'guard.py'
  $code = Invoke-Python $py @((Join-Path (Join-Path $RepoDir 'installer') 'settings_merge.py'), 'install',
    '--settings', $Settings, '--python', $py, '--hook', $guard)
  if ($code -ne 0) { throw "Could not update $Settings (see message above)." }

  Write-Host 'Checking tools'
  $envCheck = Join-Path (Join-Path (Join-Path (Join-Path $RepoDir 'skills') 'ship') 'scripts') 'env_check.py'
  [void](Invoke-Python $py @($envCheck, '--no-auth', '--text', '--write-userconfig',
    '--python-bin', $py, '--repo-dir', $RepoDir, '--mode', 'copy'))

  Write-Host ''
  Write-Host 'Done. In any repo, start Claude Code and run:  /ship PROJ-123'
  Write-Host 'First time on this machine? Log in once:  gh auth login   and   acli jira auth login'
  Write-Host 'After `git pull` in this repo, run install.ps1 again to update (Windows installs copy files).'
}

function Uninstall-Agent {
  Write-Host 'Uninstalling sdlc-agent'
  $all = @()
  if (Test-Path -LiteralPath $Manifest) { $all += @(Get-Content -LiteralPath $Manifest) }
  $all += Get-Targets
  foreach ($t in ($all | Where-Object { $_ } | Sort-Object -Unique)) {
    if ((Test-Path -LiteralPath $t) -and (Test-InClaudeDir $t) -and (Test-Ours $t)) {
      Remove-Item -LiteralPath $t -Recurse -Force
      Write-Info "removed $t"
    }
  }
  if (Test-Path -LiteralPath $Manifest) { Remove-Item -LiteralPath $Manifest -Force }

  $py = Find-Python
  if ($py) {
    $code = Invoke-Python $py @((Join-Path (Join-Path $RepoDir 'installer') 'settings_merge.py'), 'uninstall', '--settings', $Settings)
    if ($code -ne 0) { Write-Info "Could not update $Settings; remove the hook containing 'hooks/sdlc-agent/guard.py' by hand." }
  } else {
    Write-Info "Python not found: remove the hook containing 'hooks/sdlc-agent/guard.py' from $Settings by hand."
  }

  if ($Purge) {
    if (Test-Path -LiteralPath $AgentHome) { Remove-Item -LiteralPath $AgentHome -Recurse -Force }
    Write-Info "purged $AgentHome"
  } else {
    Write-Info "kept run state in $AgentHome (use -Purge to delete it)"
  }
  Write-Host 'Done.'
}

if ($Uninstall) { Uninstall-Agent } else { Install-Agent }

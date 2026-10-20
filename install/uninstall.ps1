# Personal Jarvis - Windows uninstaller
#
# Usage (from PowerShell), on a machine where Jarvis is installed:
#   & "$env:USERPROFILE\.dodaios\install\uninstall.ps1"
#   & "$env:USERPROFILE\.dodaios\install\uninstall.ps1" --dry-run   # preview
#   & "$env:USERPROFILE\.dodaios\install\uninstall.ps1" --yes       # no prompt
# (an install never moved from its earlier name lives in ~\.personal-jarvis)
#
# It removes four things a plain folder-delete would miss:
#   1. the install folder (~\.dodaios, or ~\.personal-jarvis before the rename;
#      a junction left at the earlier name is removed as a link, never followed)
#   2. the Start-menu launcher and Installed Apps registration
#   3. the login-autostart entry (a logon scheduled task / Startup shortcut)
#   4. the API keys saved in the OS keychain (Windows Credential Manager, service
#      "dodaios", and "personal-jarvis" from before the rename)
#
# Heavy logic lives in `python -m dodaios --uninstall` (cross-platform, tested).
# This bootstrap runs that for the autostart + keys (it asks for confirmation),
# then removes the folder itself from OUTSIDE the venv so the running python.exe
# never locks its own tree.
#
# SOURCE-ENCODING RULE: served BOM-less, read as cp1252 by Windows PowerShell, so
# the source outside here-strings stays ASCII; glyphs are built from code points.

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$e     = [char]27
$Gold  = "${e}[38;2;255;214;10m"; $Green = "${e}[38;2;122;200;140m"
$Dim   = "${e}[38;2;143;143;143m"; $Red   = "${e}[38;2;224;122;110m"
$Bold  = "${e}[1m"; $Rst = "${e}[0m"
$Dot = [char]0x25CF; $Chk = [char]0x2713; $Crs = [char]0x2717

function Write-Step([string]$Text) { Write-Host ""; Write-Host "$Gold  $Dot$Rst $Bold$Text$Rst" }
function Write-Ok([string]$Text)    { Write-Host "$Green    $Chk$Rst $Dim$Text$Rst" }
function Write-Note([string]$Text)  { Write-Host "$Dim      $Text$Rst" }
function Write-Err([string]$Text)   { Write-Host "$Red    $Crs $Text$Rst" }

function Stop-JarvisProcesses([string]$Root) {
    # Any process whose executable lives inside the install dir is the app
    # itself (tray, server, worker). Windows keeps a running .exe and every
    # loaded .dll/.pyd locked, so the folder delete fails with "access denied"
    # while one is alive. Best effort: never this PowerShell, never elevated
    # processes we cannot see.
    $Prefix = $Root.TrimEnd('\') + '\'
    $Procs = @()
    foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
        if ($p.Id -eq $PID) { continue }
        $ProcPath = $null
        try { $ProcPath = $p.Path } catch {}
        if ($ProcPath -and $ProcPath.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $Procs += $p
        }
    }
    if ($Procs.Count -eq 0) { return }
    foreach ($p in $Procs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    foreach ($p in $Procs) {
        try { Wait-Process -Id $p.Id -Timeout 10 -ErrorAction SilentlyContinue } catch {}
    }
    Write-Ok "Stopped the running Dodaios app ($($Procs.Count) process(es))."
}

# Standalone fallback projections of dodaios/core/branding.py. These remain
# available even when a broken venv prevents importing the installed package.
$DefaultInstallDirName = '.dodaios'
$LegacyInstallDirName = '.personal-jarvis'
$WindowsShortcutFileName = 'Dodaios.lnk'
# Earlier names of the shortcut. Removed only where they start this install.
$LegacyWindowsShortcutFileNames = @('Personal Jarvis.lnk')
$WindowsUninstallRegistrySubkey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\PersonalJarvis'
$WindowsAppUserModelId = 'PersonalJarvis.PersonalJarvis'

# --- uninstall-dir begin (extracted by tests/unit/install/test_install_dir_move.py)
# The folder a junction or directory symlink at $Path leads to, or $null when
# $Path is no such link.
function Get-DirectoryLinkTarget([string]$Path) {
    try {
        $Item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    } catch {
        return $null
    }
    if (-not $Item.PSIsContainer -or -not $Item.LinkType) { return $null }
    $Target = [string](@($Item.Target)[0])
    if (-not $Target) { return $null }
    foreach ($Prefix in @('\\?\', '\??\')) {
        if ($Target.StartsWith($Prefix)) { $Target = $Target.Substring($Prefix.Length) }
    }
    if (-not [IO.Path]::IsPathRooted($Target)) {
        $Target = Join-Path (Split-Path -Parent $Path) $Target
    }
    return [IO.Path]::GetFullPath($Target).TrimEnd('\')
}

# DODAIOS_INSTALL_DIR and JARVIS_INSTALL_DIR are one option; the new name wins.
# Without either: the folder under its earlier name while that is a real
# directory (an install that was never moved), else the current one.
$LegacyInstallDir = Join-Path $env:USERPROFILE $LegacyInstallDirName
$CurrentInstallDir = Join-Path $env:USERPROFILE $DefaultInstallDirName
$InstallDir = if ($env:DODAIOS_INSTALL_DIR) { $env:DODAIOS_INSTALL_DIR } elseif ($env:JARVIS_INSTALL_DIR) { $env:JARVIS_INSTALL_DIR } elseif ((Test-Path -LiteralPath $LegacyInstallDir -PathType Container) -and -not (Get-DirectoryLinkTarget $LegacyInstallDir)) { $LegacyInstallDir } else { $CurrentInstallDir }
# What is deleted is the folder itself, never a link to it.
$RealInstallDir = Get-DirectoryLinkTarget $InstallDir
if (-not $RealInstallDir) { $RealInstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\') }
# --- uninstall-dir end
$VenvPython = Join-Path $InstallDir '.venv\Scripts\python.exe'

Write-Step 'Uninstall Dodaios'
Write-Note $InstallDir

$DryRun    = $args -contains '--dry-run'
$AssumeYes = ($args -contains '--yes') -or ($args -contains '-y')

if (-not (Test-Path -LiteralPath $InstallDir)) {
    Write-Err "No install found at $InstallDir - nothing to do."
    exit 0
}

# 2 + 3 + 4: run the tested cleanup (app registration, autostart, and keys),
#            keeping the folder so we can delete it below.
$Rc = 0
if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython -m dodaios --uninstall --keep-folder @args
    $Rc = $LASTEXITCODE
} else {
    Write-Err 'Python environment missing - skipping autostart/key cleanup.'
    Write-Note 'The app registration and folder can still be removed; saved API keys may remain.'
    if ($DryRun) { exit 0 }
    if (-not $AssumeYes) {
        $ans = Read-Host "Type 'yes' to delete $InstallDir"
        if ($ans -ne 'yes') { Write-Note 'Cancelled.'; exit 1 }
    }
    if ($env:APPDATA) {
        $Programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
        $Shortcut = Join-Path $Programs $WindowsShortcutFileName
        Remove-Item -LiteralPath $Shortcut -Force -ErrorAction SilentlyContinue
        # A shortcut written before the install folder moved names it by the
        # earlier path, which the link left there leads through: every path
        # that reaches this install counts.
        $Prefixes = @($InstallDir, $RealInstallDir)
        foreach ($Candidate in @($LegacyInstallDir, $CurrentInstallDir)) {
            if ((Get-DirectoryLinkTarget $Candidate) -eq $RealInstallDir) { $Prefixes += $Candidate }
        }
        $Prefixes = @($Prefixes | ForEach-Object { $_.TrimEnd('\') + '\' })
        foreach ($Legacy in $LegacyWindowsShortcutFileNames) {
            $LegacyShortcut = Join-Path $Programs $Legacy
            if (-not (Test-Path -LiteralPath $LegacyShortcut)) { continue }
            $Target = $null
            try { $Target = (New-Object -ComObject WScript.Shell).CreateShortcut($LegacyShortcut).TargetPath } catch {}
            if (-not $Target) { continue }
            foreach ($Prefix in $Prefixes) {
                if ($Target.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                    Remove-Item -LiteralPath $LegacyShortcut -Force -ErrorAction SilentlyContinue
                    break
                }
            }
        }
    }
    Remove-Item -LiteralPath "Registry::HKEY_CURRENT_USER\$WindowsUninstallRegistrySubkey" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "Registry::HKEY_CURRENT_USER\Software\Classes\AppUserModelId\$WindowsAppUserModelId" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok 'Removed the desktop app registration.'
    $Rc = 0
}

# The Python step returns 1 when the user cancels at its prompt. Respect that.
if ($Rc -ne 0) {
    Write-Note 'Cancelled - nothing was changed.'
    exit $Rc
}

# 1: delete the folder from OUTSIDE the venv. Leave the install dir first so it
#    is not the current location during removal. The Python step above already
#    stops the running app, but anything (re)started since - and the no-venv
#    fallback path - is caught here again. Windows can also hold file locks for
#    a moment after a process dies, so the delete retries before giving up, and
#    a final failure says plainly WHY instead of a red stacktrace.
if (-not $DryRun) {
    Set-Location -LiteralPath $env:USERPROFILE
    # --- uninstall-remove begin (extracted by tests/unit/install/test_install_dir_move.py)
    # Links that lead to this install from another path: the one given, and
    # the junction a move to the current folder name left at the earlier name.
    # Each goes as a link; only the folder they lead to is deleted as a folder.
    if (Get-DirectoryLinkTarget $RealInstallDir) {
        Write-Err "$RealInstallDir is itself a link - refusing to delete through it."
        exit 3
    }
    $Links = @()
    foreach ($Candidate in @($InstallDir, $LegacyInstallDir, $CurrentInstallDir)) {
        $Target = Get-DirectoryLinkTarget $Candidate
        if ($Target -and $Target -eq $RealInstallDir -and $Links -notcontains $Candidate) {
            $Links += $Candidate
        }
    }
    Stop-JarvisProcesses $RealInstallDir
    foreach ($Link in $Links) {
        # A process started through the link reports its path through it.
        Stop-JarvisProcesses $Link
        try {
            # Not recursive: this deletes the junction itself, never a file it leads to.
            [IO.Directory]::Delete($Link, $false)
            Write-Ok "Removed the link $Link"
        } catch {
            Write-Err "Could not remove the link $Link - it holds no files of its own; delete it yourself."
        }
    }
    $Deleted = $false
    for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
        try {
            Remove-Item -LiteralPath $RealInstallDir -Recurse -Force -ErrorAction Stop
            $Deleted = $true
            break
        } catch {
            if (-not (Test-Path -LiteralPath $RealInstallDir)) { $Deleted = $true; break }
            Stop-JarvisProcesses $RealInstallDir
            Start-Sleep -Seconds 2
        }
    }
    if (-not $Deleted -and (Test-Path -LiteralPath $RealInstallDir)) {
        Write-Err "Could not fully remove $RealInstallDir - a program is still using files inside it."
        Write-Note 'Close every Dodaios window (including the tray icon near the clock) and any terminal opened inside that folder, then run this uninstaller again.'
        Write-Note 'Signing out of Windows and back in also releases leftover file locks.'
        exit 3
    }
    # A link at either folder name that now leads to the deleted folder under
    # another spelling of its path (a short 8.3 name) leads nowhere: debris.
    $RealLeaf = Split-Path -Leaf $RealInstallDir
    foreach ($Candidate in @($LegacyInstallDir, $CurrentInstallDir)) {
        $Target = Get-DirectoryLinkTarget $Candidate
        if (-not $Target -or (Test-Path -LiteralPath $Target)) { continue }
        if ((Split-Path -Leaf $Target) -ne $RealLeaf) { continue }
        try { [IO.Directory]::Delete($Candidate, $false) } catch {}
    }
    # --- uninstall-remove end
    Write-Ok "Removed $RealInstallDir"
    # The private Python and Git copies install.ps1 fetched on a machine that
    # had neither. Only the venv just deleted used them.
    if ($env:LOCALAPPDATA) {
        $BundledTools = Join-Path $env:LOCALAPPDATA 'Dodaios\tools'
        if (Test-Path -LiteralPath $BundledTools) {
            try {
                Remove-Item -LiteralPath $BundledTools -Recurse -Force -ErrorAction Stop
                Write-Ok "Removed $BundledTools"
            } catch {
                Write-Note "Could not remove $BundledTools - delete it yourself."
            }
        }
    }
    Write-Step 'Done. Dodaios has been uninstalled.'
}

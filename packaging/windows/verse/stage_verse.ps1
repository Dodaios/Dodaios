#Requires -Version 5.1
<#
.SYNOPSIS
    Put the packaged Unreal Verse into the Windows installer.

.DESCRIPTION
    docs/verse/unreal/work-packages.md WP22.6. Copies a full Verse payload
    (Verse-Win64-<version>.tar from `scripts/unreal/package.py full`) into the
    PyInstaller output the installer wraps, as <FreezeDir>\verse\<name>.
    Dodaios.iss already packs every file below its SourceDir, so the payload
    rides in the normal installer without an extra wizard page.

    On first start the app installs the seed into the per-user Verse folder
    (%LOCALAPPDATA%\Dodaios\verse, `seed_verse_from_bundle` in
    dodaios/core/installer_update.py), verifies every file, and removes the
    seed. Machines without a GPU keep the seed unused: the Verse reports
    "unsupported" and the rest of the app is unaffected.

    Run it after the freeze and before Inno Setup:

        powershell -File packaging\windows\verse\stage_verse.ps1 -Payload dist\verse\Verse-Win64-4.2.0.tar

.PARAMETER Payload
    The full payload tar of the Win64 Shipping build.

.PARAMETER FreezeDir
    The PyInstaller onedir output Dodaios.iss packs (default dist\Jarvis).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Payload,
    [string]$FreezeDir = (Join-Path $PSScriptRoot '..\..\..\dist\Jarvis')
)

$ErrorActionPreference = 'Stop'
$Name = Split-Path -Leaf $Payload
if ($Name -notmatch '^Verse-Win64-\d+\.\d+\.\d+\.tar$') {
    throw "$Name is not a Win64 Verse payload (want Verse-Win64-<version>.tar)"
}
if (-not (Test-Path -LiteralPath $FreezeDir -PathType Container)) {
    throw "no frozen app at $FreezeDir; freeze first (packaging\windows\build.ps1)"
}
$Listing = & tar.exe -tf $Payload
if ($LASTEXITCODE -ne 0 -or -not ($Listing -contains 'verse-tree.json')) {
    throw "$Name has no verse-tree.json; build it with scripts/unreal/package.py full"
}
$Target = Join-Path $FreezeDir 'verse'
if (Test-Path -LiteralPath $Target) {
    Get-ChildItem -LiteralPath $Target -Filter 'Verse-*.tar' | Remove-Item -Force
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -LiteralPath $Payload -Destination (Join-Path $Target $Name) -Force
$Size = (Get-Item -LiteralPath (Join-Path $Target $Name)).Length
Write-Host ("[verse] staged {0} ({1:N0} MB) into {2}" -f $Name, ($Size / 1MB), $Target)

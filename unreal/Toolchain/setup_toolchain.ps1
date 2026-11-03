<#
.SYNOPSIS
  Install the toolchain the Unreal Verse builds with, from the pins in toolchains.json.

.DESCRIPTION
  docs/verse/unreal/work-packages.md WP22.1. Reads unreal/Toolchain/toolchains.json
  and brings this box to it:

    1. Visual Studio 2022 Build Tools with the pinned MSVC, Windows SDK and .NET
       targeting packs (the Visual Studio installer asks for elevation once).
    2. The engine's Linux cross toolchain: the vendor installer is downloaded,
       checked against the pinned size and SHA-256, and unpacked with 7-Zip into
       install_root, so no elevation is needed for it.
    3. The user variable LINUX_MULTIARCH_ROOT pointing at it.

  Without -Apply it only prints what it would do. The Linux target platform of
  the engine install itself is added once through the launcher (UE 5.7, Options,
  Target Platforms, Linux); the script says when it is missing. Afterwards run:

    python scripts/unreal/package.py verify

.PARAMETER Apply
  Install for real. Without it the script changes nothing.
#>
[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$Pins = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'toolchains.json') | ConvertFrom-Json

function Write-Step([string]$Text) { Write-Host "[toolchain] $Text" }

# ---------------------------------------------------------------- Visual Studio
$Vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$Components = @($Pins.visual_studio.components)
$Installed = $null
if (Test-Path -LiteralPath $Vswhere) {
    $Installed = & $Vswhere -products '*' -version "[$($Pins.visual_studio.min_version),18.0)" `
        -requires $Components -property installationPath | Select-Object -First 1
}
if ($Installed) {
    Write-Step "Build Tools with every pinned component: $Installed"
} else {
    $InstallArgs = @('--quiet', '--wait', '--norestart', '--nocache') + ($Components | ForEach-Object { @('--add', $_) })
    Write-Step "Build Tools missing components: vs_buildtools.exe $($InstallArgs -join ' ')"
    if ($Apply) {
        $Boot = Join-Path $env:TEMP 'vs_buildtools.exe'
        Invoke-WebRequest -Uri $Pins.visual_studio.bootstrapper -OutFile $Boot -UseBasicParsing
        $Signature = Get-AuthenticodeSignature -LiteralPath $Boot
        if ($Signature.Status -ne 'Valid') { throw "vs_buildtools.exe signature is $($Signature.Status)" }
        $Process = Start-Process -FilePath $Boot -ArgumentList $InstallArgs -Verb RunAs -Wait -PassThru
        if ($Process.ExitCode -notin 0, 3010) { throw "vs_buildtools.exe exited with $($Process.ExitCode)" }
    }
}

# ------------------------------------------------------- Linux cross toolchain
$Linux = $Pins.linux
$Root = Join-Path $Linux.install_root $Linux.sdk
$Clang = Join-Path $Root 'x86_64-unknown-linux-gnu\bin\clang++.exe'
if (Test-Path -LiteralPath $Clang) {
    Write-Step "Linux toolchain $($Linux.sdk) at $Root"
} else {
    Write-Step "Linux toolchain missing: download $($Linux.installer_url), unpack to $Root"
    if ($Apply) {
        $SevenZip = @('C:\Program Files\7-Zip\7z.exe', (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source) |
            Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if (-not $SevenZip) { throw '7-Zip is needed to unpack the toolchain without elevation' }
        $Download = Join-Path $env:TEMP "$($Linux.sdk).exe"
        & curl.exe -fL -C - -o $Download $Linux.installer_url
        if ($LASTEXITCODE -ne 0) { throw "download failed (curl exit $LASTEXITCODE)" }
        $Size = (Get-Item -LiteralPath $Download).Length
        $Hash = (Get-FileHash -LiteralPath $Download -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Size -ne [int64]$Linux.installer_bytes -or $Hash -ne $Linux.installer_sha256) {
            throw "toolchain installer does not match its pin ($Size bytes, sha256 $Hash)"
        }
        New-Item -ItemType Directory -Force -Path $Root | Out-Null
        & $SevenZip x -tNsis -y "-o$Root" $Download | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "7-Zip exited with $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $Clang)) { throw "no $Clang after unpacking" }
    }
}
$Current = [Environment]::GetEnvironmentVariable($Linux.env, 'User')
if ($Current -ne "$Root\") {
    Write-Step "set user variable $($Linux.env)=$Root\"
    if ($Apply) { [Environment]::SetEnvironmentVariable($Linux.env, "$Root\", 'User') }
}

# ------------------------------------------------- engine Linux target platform
$EngineMarker = Join-Path $Pins.engine.windows_root $Linux.engine_component
if (-not (Test-Path -LiteralPath $EngineMarker)) {
    Write-Step "the engine has no Linux target platform ($EngineMarker): add it once in the launcher (UE 5.7, Options, Target Platforms, Linux)"
}

if (-not $Apply) { Write-Step 'dry run: nothing changed (pass -Apply to install)' }
Write-Step 'next: python scripts/unreal/package.py verify'

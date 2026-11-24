# Dodaios - Windows quick-install bootstrap (Stage 1)
#
# Usage (from PowerShell):
#   irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
#
# This bootstrap is intentionally small. It:
#   1. Uses Python 3.11+ and git when they are installed.
#   2. Otherwise fetches private, checksum-pinned copies (uv-managed Python,
#      MinGit) into %LOCALAPPDATA%\Dodaios\tools - no admin rights, no
#      prompt - and offers WinGet only when that download fails.
#   3. Checks for Node.js 18+ (optional - a missing Node never blocks the install).
#   4. Clones (or updates) Dodaios into ~\.dodaios (an update moves an install
#      made under the earlier name ~\.personal-jarvis there).
#   5. Creates a Python venv with an up-to-date pip and `packaging`.
#   6. Hands control to install/installer.py (the Stage 2 orchestrator).
#
# All heavy logic lives in installer.py so it can be unit-tested and
# kept cross-platform. The shell-native prerequisite block is delimited so it
# can be tested directly even on machines where Python is not installed yet.
#
# SOURCE-ENCODING RULE: this file is served BOM-less (a BOM breaks
# `irm | iex`), and Windows PowerShell then reads it as cp1252. So the
# source stays pure ASCII: the glyphs (check, cross, half blocks, Braille)
# are built from code points at runtime, never pasted as literals -- a
# literal check/dash would cp1252-decode into a smart quote and break
# tokenizing. Console output is forced to UTF-8 so they still render.

$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# `irm | iex` runs this script inside the person's own PowerShell session,
# where `exit` would close that session - and with it the finale card or the
# error they need to read (a classic console window closes outright). A file
# run (the verifying installer starts it that way) keeps its exit code as the
# contract. So every stop goes through Exit-Install, never a bare `exit`.
$InstallRunFromFile = ($MyInvocation.MyCommand.CommandType -eq 'ExternalScript')
function Exit-Install([int]$Code) {
    if ($Code -ne 0) {
        Write-Stopped 'The install stopped here. Nothing was launched; run the same command again once fixed.'
    }
    if ($InstallRunFromFile) { exit $Code }
    $global:LASTEXITCODE = $Code
    # Ends this script the way Ctrl+C would: the session and its output stay.
    if ($Code -ne 0) { throw [System.Management.Automation.PipelineStoppedException]::new() }
}

# --- installer-ui begin (extracted by tests/unit/install/test_install_ui_shell.py)
# How the installer looks: one design across both stages and every platform.
# installer.py continues it (dodaios/setup/install_ui.py) and install.sh is
# the POSIX twin; all three decide what the terminal can show by the same
# rules, written out in that Python module:
#   colour  off with NO_COLOR, TERM=dumb, a host without virtual-terminal
#           output (the ISE) or when output is redirected (FORCE_COLOR turns
#           it back on); 24-bit in a Windows 10+ console and Windows Terminal.
#   glyphs  ASCII with JARVIS_INSTALL_ASCII or a console that is not UTF-8;
#           Windows Terminal and other modern hosts get the full set, a
#           classic console the set its default font (Consolas) can draw.
#   motion  spinners only on an interactive console, never in CI.
#   width   COLUMNS, else the console's, else 80.
# Nothing here waits for effect: a spinner redraws only while real work runs.
# Every glyph is built from its code point: the source stays ASCII.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Test-UiTruthy([string]$Value) {
    if (-not $Value) { return $false }
    return ($Value.Trim().ToLowerInvariant() -notin @('0', 'false', 'no', 'off'))
}

$UiTty = $false
try { $UiTty = -not [Console]::IsOutputRedirected } catch { $UiTty = $false }
$UiVt = $false
try { $UiVt = [bool]$Host.UI.SupportsVirtualTerminal } catch { $UiVt = $false }
if ($Host.Name -eq 'Windows PowerShell ISE Host') { $UiVt = $false }
$UiTerm = "$env:TERM"
$UiWindows = ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)
if ($env:NO_COLOR -or $UiTerm -eq 'dumb') {
    $UiColor = 'none'
} elseif (($UiTty -and $UiVt) -or (-not $UiTty -and (Test-UiTruthy $env:FORCE_COLOR))) {
    if ($UiWindows -or $env:WT_SESSION -or @('truecolor', '24bit') -contains "$env:COLORTERM") {
        $UiColor = 'truecolor'
    } elseif ($UiTerm -like '*256*') {
        $UiColor = '256'
    } else {
        $UiColor = '16'
    }
} else {
    $UiColor = 'none'
}
$UiUtf8 = $true
try { $UiUtf8 = ([Console]::OutputEncoding.CodePage -eq 65001) } catch { $UiUtf8 = $true }
if ((Test-UiTruthy $env:JARVIS_INSTALL_ASCII) -or (Test-UiTruthy $env:DODAIOS_INSTALL_ASCII) -or -not $UiUtf8 -or
    @('linux', 'dumb', 'ansi') -contains $UiTerm -or $UiTerm -like 'vt*') {
    $UiGlyphs = 'ascii'
} elseif ($env:WT_SESSION -or @('vscode', 'WezTerm', 'ghostty', 'iTerm.app') -contains "$env:TERM_PROGRAM" -or
          "$env:ConEmuANSI" -eq 'ON' -or -not $UiWindows) {
    $UiGlyphs = 'full'
} else {
    $UiGlyphs = 'basic'
}
$UiMotion = ($UiTty -and $UiVt -and $UiTerm -ne 'dumb' -and -not (Test-UiTruthy $env:CI))
$UiCols = 0
if ("$env:COLUMNS" -match '^\d+$') { $UiCols = [int]$env:COLUMNS }
if ($UiCols -le 0) {
    try { $UiCols = [int]$Host.UI.RawUI.WindowSize.Width } catch { $UiCols = 0 }
}
if ($UiCols -le 0) { $UiCols = 80 }
if ($UiCols -lt 20) { $UiCols = 20 }
$UiLayout = [Math]::Min($UiCols, 88)

$Esc = [char]27
if ($UiGlyphs -eq 'ascii') {
    $GOk = '+'; $GFail = 'x'; $GSkip = '-'; $GRail = '|'; $GPoint = '>'; $GEll = '...'; $GBar = '#'; $GTrack = '-'
    $GDot = '-'
    $UiSpinFrames = @('|', '/', '-', '\')
} else {
    $GOk = if ($UiGlyphs -eq 'full') { [string][char]0x2713 } else { [string][char]0x221A }
    $GFail = [string][char]0x00D7; $GSkip = [string][char]0x00B7; $GRail = [string][char]0x2503
    $GPoint = [string][char]0x25B8; $GEll = [string][char]0x2026; $GBar = [string][char]0x2501
    $GTrack = if ($UiColor -eq 'none') { [string][char]0x2500 } else { $GBar }
    $GDot = $GSkip
    if ($UiGlyphs -eq 'full') {
        $UiSpinFrames = @(0x280B, 0x2819, 0x2839, 0x2838, 0x283C, 0x2834, 0x2826, 0x2827, 0x2807, 0x280F) |
            ForEach-Object { [string][char]$_ }
    } else {
        $UiSpinFrames = @('|', '/', '-', '\')
    }
}
$GWarn = '!'

# Brand palette (docs/BRAND.md): signal gold, deep gold, the status colours.
# Plain text keeps the console's own foreground, so light themes read it too.
function Get-UiSgr([string]$True24, [string]$Xterm256, [string]$Basic16) {
    switch ($UiColor) {
        'truecolor' { return "$Esc[$($True24)m" }
        '256' { return "$Esc[$($Xterm256)m" }
        '16' { return "$Esc[$($Basic16)m" }
        default { return '' }
    }
}
$CGold = Get-UiSgr '38;2;255;214;10' '38;5;220' '33'
$COk = Get-UiSgr '38;2;34;195;94' '38;5;35' '32'
$CWarn = Get-UiSgr '38;2;245;158;11' '38;5;214' '33'
$CBad = Get-UiSgr '38;2;223;58;58' '38;5;167' '31'
$CMuted = Get-UiSgr '38;2;138;138;138' '38;5;245' '90'
$CBold = Get-UiSgr '1' '1' '1'
$CRst = Get-UiSgr '0' '0' '0'
$PGold = Get-UiSgr '1;38;2;10;10;10;48;2;255;214;10' '1;38;5;232;48;5;220' '1;30;43'
$PBad = Get-UiSgr '1;38;2;10;10;10;48;2;223;58;58' '1;38;5;232;48;5;167' '1;30;41'

function Format-UiDuration([double]$Seconds) {
    $total = [int][Math]::Floor($Seconds)
    if ($total -lt 1) { return '' }
    if ($total -lt 60) { return "$($total)s" }
    return ('{0}m {1:00}s' -f [int][Math]::Floor($total / 60), ($total % 60))
}

# A line with $Right on the layout's right edge; $Visible is the width of $Line.
function Write-UiRight([string]$Line, [int]$Visible, [string]$Right) {
    if (-not $Right) { Write-Host $Line; return }
    $gap = [Math]::Max(2, $UiLayout - 2 - $Visible - $Right.Length)
    Write-Host ($Line + (' ' * $gap) + $CMuted + $Right + $CRst)
}

$script:UiInFail = $false
$script:UiLastSeconds = 0

# One six-phase journey spans BOTH installer stages: this shell owns phases
# 1-3, installer.py continues with 4-6 -- keep the numbering in sync there.
function Write-Phase([string]$Num, [string]$Text) {
    $script:UiInFail = $false
    Write-Host ''
    if ($UiColor -eq 'none') {
        Write-Host "  [$Num] $Text"
    } else {
        Write-Host "  $PGold $Num $CRst  $CBold$Text$CRst"
    }
}
function Write-Ok([string]$Text, [double]$Seconds = 0, [string]$Detail = '') {
    $script:UiInFail = $false
    if ($Detail) {
        Write-Host "     $COk$GOk$CRst  $Text  $CMuted$Detail$CRst"
        return
    }
    Write-UiRight "     $COk$GOk$CRst  $Text" (8 + $Text.Length) (Format-UiDuration $Seconds)
}
function Write-Skip([string]$Text) {
    $script:UiInFail = $false
    Write-Host "     $CMuted$GSkip  $Text$CRst"
}
function Write-Warn([string]$Text) {
    $script:UiInFail = $false
    Write-Host "     $CWarn$CBold$GWarn$CRst  $Text"
}
# After Write-Err, the notes that follow hang on its red rail until the next step.
function Write-Note([string]$Text) {
    if ($script:UiInFail) {
        Write-Host "     $CBad$GRail$CRst  $Text"
    } else {
        Write-Host "        $CMuted$Text$CRst"
    }
}
function Write-Err([string]$Text) {
    $script:UiInFail = $true
    Write-Host "     $CBad$CBold$GFail$CRst  $CBold$Text$CRst"
}
function Write-Stopped([string]$Text) {
    Write-Host ''
    if ($UiColor -eq 'none') {
        Write-Host "  [STOPPED] $Text"
    } else {
        Write-Host "  $PBad STOPPED $CRst  $Text"
    }
}

# The live line of a running step, redrawn in place. $Extra (a bar) is
# already coloured; $ExtraWidth is its visible width.
function Write-UiLive([int]$Frame, [string]$Label, [double]$Seconds, [string]$Extra = '', [int]$ExtraWidth = 0) {
    $glyph = $UiSpinFrames[$Frame % $UiSpinFrames.Count]
    $time = Format-UiDuration $Seconds
    if (-not $time) { $time = '0s' }
    $body = $Label
    $visible = 8 + $Label.Length
    if ($Extra) { $body = "$Label $Extra"; $visible += 1 + $ExtraWidth }
    $gap = $UiLayout - 2 - $visible - $time.Length
    if ($gap -lt 2) {
        # Never wrap the live line: a wrapped line cannot be redrawn in place.
        [Console]::Write("`r$Esc[K     $CGold$glyph$CRst  $CMuted$time$CRst")
    } else {
        [Console]::Write("`r$Esc[K     $CGold$glyph$CRst  $body$(' ' * $gap)$CMuted$time$CRst")
    }
}

# One argument for a Windows command line (the MSVCRT quoting rules).
function ConvertTo-UiArgument([string]$Argument) {
    if ($Argument -eq '') { return '""' }
    if ($Argument -notmatch '[\s"]') { return $Argument }
    $quoted = $Argument -replace '(\\*)"', '$1$1\"'
    $quoted = $quoted -replace '(\\+)$', '$1$1'
    return '"' + $quoted + '"'
}

# Run a slow, otherwise-silent command behind a spinner and its elapsed time,
# so a long step never looks hung. Interactive consoles only: elsewhere the
# label is printed once and the command runs in plain view. Output is
# captured to temp files whose tail is shown on failure, so errors are never
# swallowed. Returns the exit code and sets $script:UiLastSeconds. Never wrap
# anything that may prompt: its prompt would land in the capture file.
function Invoke-UiSpin {
    param([string]$Label, [string]$FilePath, [string[]]$Arguments)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    if (-not $UiMotion) {
        Write-Host "     $CMuted$GSkip  $Label$GEll$CRst"
        & $FilePath @Arguments
        $code = $LASTEXITCODE
        $script:UiLastSeconds = $watch.Elapsed.TotalSeconds
        if ($code -ne 0) { Write-Err "$Label failed (exit code $code)" }
        return $code
    }
    $outFile = [IO.Path]::GetTempFileName()
    $errFile = [IO.Path]::GetTempFileName()
    try {
        $line = ($Arguments | ForEach-Object { ConvertTo-UiArgument $_ }) -join ' '
        $proc = Start-Process -FilePath $FilePath -ArgumentList $line -NoNewWindow -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $null = $proc.Handle  # keeps ExitCode readable after the process ends
        $frame = 0
        [Console]::Write("$Esc[?25l")
        while (-not $proc.HasExited) {
            Write-UiLive $frame $Label $watch.Elapsed.TotalSeconds
            $frame++
            Start-Sleep -Milliseconds 120
        }
        $proc.WaitForExit()
        $code = $proc.ExitCode
        [Console]::Write("`r$Esc[K$Esc[?25h")
        $script:UiLastSeconds = $watch.Elapsed.TotalSeconds
        if ($code -ne 0) {
            Write-Err "$Label failed (exit code $code)"
            $tail = @(Get-Content -LiteralPath $outFile, $errFile -ErrorAction SilentlyContinue |
                Where-Object { $_ } | Select-Object -Last 20)
            foreach ($tailLine in $tail) { Write-Note ([string]$tailLine) }
        }
        return $code
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

# Run git with its transfer progress drawn as one live bar (download, unpack,
# write) instead of git's raw chatter; errors come through on the red rail.
# Interactive consoles only: elsewhere git runs quietly in plain view.
function Invoke-UiGit {
    param([string[]]$Arguments)
    if (-not $UiMotion) {
        & git @Arguments --quiet
        return $LASTEXITCODE
    }
    $outFile = [IO.Path]::GetTempFileName()
    $errFile = [IO.Path]::GetTempFileName()
    try {
        $line = (@($Arguments) + '--progress' | ForEach-Object { ConvertTo-UiArgument $_ }) -join ' '
        $git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $proc = Start-Process -FilePath $git -ArgumentList $line -NoNewWindow -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $null = $proc.Handle
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $frame = 0
        $labels = @{ 'Receiving objects' = 'Downloading'; 'Resolving deltas' = 'Unpacking'; 'Updating files' = 'Writing files' }
        [Console]::Write("$Esc[?25l")
        while (-not $proc.HasExited) {
            $label = 'Connecting'
            $extra = ''
            $extraWidth = 0
            try {
                $stream = [IO.File]::Open($errFile, 'Open', 'Read', 'ReadWrite')
                try {
                    $start = [Math]::Max(0, $stream.Length - 4096)
                    $null = $stream.Seek($start, 'Begin')
                    $text = (New-Object IO.StreamReader($stream)).ReadToEnd()
                } finally { $stream.Dispose() }
                $last = @($text -split "[`r`n]" | Where-Object { $_ -match '^(Receiving objects|Resolving deltas|Updating files):' }) |
                    Select-Object -Last 1
                if ($last -and $last -match '^([^:]+):\s+(\d+)%') {
                    $label = $labels[$Matches[1]]
                    $pct = [int]$Matches[2]
                    $done = [int][Math]::Floor($pct * 24 / 100)
                    $bar = "$CGold$($GBar * $done)$CMuted$($GTrack * (24 - $done))$CRst"
                    $speed = ''
                    if ($last -match '(\d[\d.]* [KMGT]?iB) \| (\d[\d.]* [KMGT]?iB/s)') { $speed = "$($Matches[1])  $($Matches[2])" }
                    $extra = "$bar  $('{0,3}' -f $pct)%  $CMuted$speed$CRst"
                    $extraWidth = 24 + 2 + 4 + 2 + $speed.Length
                }
            } catch {
                # The progress file is mid-write; the next frame reads it again.
                $extra = ''
            }
            Write-UiLive $frame ('{0,-13}' -f $label) $watch.Elapsed.TotalSeconds $extra $extraWidth
            $frame++
            Start-Sleep -Milliseconds 150
        }
        $proc.WaitForExit()
        $code = $proc.ExitCode
        [Console]::Write("`r$Esc[K$Esc[?25h")
        if ($code -ne 0) {
            $errors = @(Get-Content -LiteralPath $errFile -ErrorAction SilentlyContinue |
                ForEach-Object { $_ -split "`r" } | Where-Object { $_ -match '^(error|fatal|warning):' })
            foreach ($errorLine in $errors | Select-Object -Last 8) {
                Write-Host "     $CBad$GRail$CRst  $errorLine"
            }
        }
        return $code
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

# The hero: the hooded figure beside the pixel wordmark, the README banner
# drawn with half blocks (two pixels per text cell). '#' is gold on a
# vertical gradient and 's' the wordmark's drop shadow. Drawn with colour,
# Unicode and room for it; otherwise a plain title stands in. The two images
# are the same as install.sh's (tests/unit/install/test_install_ui_shell.py).
$UiMascot = @(
    '..........###.........'
    '........######........'
    '......########.##.....'
    '....##.#######.#####..'
    '...##.....####.####...'
    '..##......#####.##....'
    '.##.####...####.......'
    '.#.#######..####......'
    '..##########.###......'
    '.#.######..##.###.....'
    '#..#..###..##..##.....'
    '#..#..###..###.###....'
    '#..##.########.##.....'
    '.#...#######.##.......'
    '..###...#####.##......'
    '...#####...####.##....'
    '...########...#..####.'
    '...###########..######'
    '...############..#####'
    '...#############..###.'
    '...######.########....'
    '...#####.#########....'
    '...#####.########.....'
    '....###...######......'
)
$UiWordmark = @(
    '#####....####...#####.....##....####...####....#####'
    '######..######..######...####...####..######..######'
    '##ss##..##ss##..##ss##..######..s##s..##ss##..##ssss'
    '##..##..##..##..##..##..##ss##...##...##..##..#####.'
    '##..##..##..##..##..##..######...##...##..##..s#####'
    '##..##..##..##..##..##..######...##...##..##...sss##'
    '######..######..######..##ss##..####..######..######'
    '#####s..s####s..#####s..##..##..####..s####s..#####s'
    'sssss....ssss...sssss...ss..ss..ssss...ssss...sssss.'
    '....................................................'
)
# The gold of pixel row $Row in an image $Rows tall (an SGR colour without its
# 38/48 prefix): #FFF07A at the top, #FFD60A in the middle, #B8860B at the
# bottom, as in the banner.
function Get-UiGold([int]$Row, [int]$Rows) {
    $t = [int][Math]::Floor($Row * 1000 / ($Rows - 1))
    if ($UiColor -eq 'truecolor') {
        if ($t -le 500) {
            return ('2;255;{0};{1}' -f (240 - [int][Math]::Floor(26 * $t / 500)), (122 - [int][Math]::Floor(112 * $t / 500)))
        }
        $t -= 500
        return ('2;{0};{1};{2}' -f (255 - [int][Math]::Floor(71 * $t / 500)), (214 - [int][Math]::Floor(80 * $t / 500)), (10 + [int][Math]::Floor($t / 500)))
    }
    if ($t -lt 200) { return '5;228' }
    if ($t -lt 400) { return '5;227' }
    if ($t -lt 620) { return '5;220' }
    if ($t -lt 820) { return '5;178' }
    return '5;136'
}
# One text row of an image from its upper and lower pixel rows.
function Get-UiArtRow([string]$Upper, [string]$Lower, [int]$Row, [int]$Rows) {
    $shadow = if ($UiColor -eq 'truecolor') { '2;107;78;0' } else { '5;94' }
    $goldA = Get-UiGold $Row $Rows
    $goldB = Get-UiGold ($Row + 1) $Rows
    $top = [string][char]0x2580
    $bottom = [string][char]0x2584
    $out = New-Object System.Text.StringBuilder
    $last = ''
    for ($x = 0; $x -lt $Upper.Length; $x++) {
        $a = switch ($Upper[$x]) { '#' { $goldA } 's' { $shadow } default { '' } }
        $b = switch ($Lower[$x]) { '#' { $goldB } 's' { $shadow } default { '' } }
        if (-not $a -and -not $b) { $sgr = '0'; $glyph = ' ' }
        elseif (-not $b) { $sgr = "0;38;$a"; $glyph = $top }
        elseif (-not $a) { $sgr = "0;38;$b"; $glyph = $bottom }
        else { $sgr = "0;38;$a;48;$b"; $glyph = $top }
        if ($sgr -ne $last) { $null = $out.Append("$Esc[$($sgr)m"); $last = $sgr }
        $null = $out.Append($glyph)
    }
    $null = $out.Append("$Esc[0m")
    return $out.ToString()
}
function Write-Hero([string]$Subtitle, [string]$Meta) {
    Write-Host ''
    if ($UiColor -eq 'none' -or $UiColor -eq '16' -or $UiGlyphs -eq 'ascii' -or $UiCols -lt 58) {
        if ($UiColor -eq 'none') {
            Write-Host "  DODAIOS  $Subtitle"
            Write-Host "  $Meta"
        } else {
            Write-Host "  $PGold DODAIOS $CRst  $CBold$Subtitle$CRst"
            Write-Host "  $CMuted$Meta$CRst"
        }
        return
    }
    if ($UiCols -lt 80) {
        # No room beside the figure: the wordmark alone, the words below it.
        for ($y = 0; $y -lt 10; $y += 2) {
            Write-Host ('  ' + (Get-UiArtRow $UiWordmark[$y] $UiWordmark[$y + 1] $y 8))
        }
        Write-Host "  $CBold$Subtitle$CRst"
        Write-Host "  $CMuted$Meta$CRst"
        return
    }
    for ($y = 0; $y -lt 12; $y++) {
        $left = Get-UiArtRow $UiMascot[$y * 2] $UiMascot[$y * 2 + 1] ($y * 2) 24
        $right = ''
        if ($y -ge 1 -and $y -le 5) {
            $w = ($y - 1) * 2
            $right = Get-UiArtRow $UiWordmark[$w] $UiWordmark[$w + 1] $w 8
        } elseif ($y -eq 7) {
            $right = "$CBold$Subtitle$CRst"
        } elseif ($y -eq 8) {
            $right = "$CMuted$Meta$CRst"
        }
        Write-Host "  $left   $right"
    }
}
# --- installer-ui end

# ----------------------------------------------------------------- config
# Every JARVIS_ option this script reads also answers to its DODAIOS_
# spelling. When both are set to different values the DODAIOS_ one wins, and
# the clash is named, never its values. The rest of this script, and
# installer.py after it, read the JARVIS_ spelling (dodaios/core/env_prefix.py
# does the same for the app). JARVIS_PAYLOAD_COMMIT is not an option: it is
# the signed commit the verifying installer hands over, and no second name
# may override it.
function Use-InstallOptionNames {
    foreach ($Option in 'INSTALL_REPO', 'INSTALL_REF', 'INSTALL_DIR', 'INSTALL_PREREQS', 'OFFICIAL_REPO_SLUG', 'PYTHON', 'INSTALL_ASCII') {
        $NewName = "DODAIOS_$Option"
        $OldName = "JARVIS_$Option"
        $NewValue = [Environment]::GetEnvironmentVariable($NewName)
        if (-not $NewValue) { continue }
        $OldValue = [Environment]::GetEnvironmentVariable($OldName)
        if ($OldValue -and $OldValue -cne $NewValue) {
            Write-Note "$NewName and $OldName differ; using $NewName."
        }
        [Environment]::SetEnvironmentVariable($OldName, $NewValue)
    }
}
Use-InstallOptionNames

# Standalone bootstrap projections of dodaios/core/branding.py. The branding
# contract test rejects drift because this script runs before Python is installed.
$OfficialRepoSlug = "$env:JARVIS_OFFICIAL_REPO_SLUG"
if (-not $OfficialRepoSlug) { $OfficialRepoSlug = 'Dodaios/Dodaios' }
if ($OfficialRepoSlug -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'JARVIS_OFFICIAL_REPO_SLUG must be an exact owner/repository slug'
}
$RepoUrl    = if ($env:JARVIS_INSTALL_REPO) { $env:JARVIS_INSTALL_REPO } else { "https://github.com/$OfficialRepoSlug.git" }
$LegacyOfficialRepoSlug = 'PersonalJarvis/PersonalJarvis'
$ConfigFileName = 'dodaios.toml'
# An install keeps a config file under this earlier name; it is never renamed.
$LegacyConfigFileName = 'jarvis.toml'
# Empty = the newest published release (Resolve-InstallRef below).
$Branch     = if ($env:JARVIS_INSTALL_REF)  { $env:JARVIS_INSTALL_REF }  else { '' }
# --- install-dir-choice begin (extracted by tests/unit/install/test_install_dir_move.py)
# The checkout lives in ~\.dodaios. An install made under the earlier name
# keeps its directory for as long as that is a real directory (not a junction
# or a link), and an update run moves it (Invoke-InstallDirMigration below). A
# directory given in JARVIS_INSTALL_DIR (or DODAIOS_INSTALL_DIR) is used as
# given, never moved.
$DefaultInstallDirName = '.dodaios'
$LegacyInstallDirName = '.personal-jarvis'
$CurrentInstallDir = Join-Path $env:USERPROFILE $DefaultInstallDirName
$LegacyInstallDir = Join-Path $env:USERPROFILE $LegacyInstallDirName
$MigrateLegacyInstallDir = $false
function Test-RealDirectory([string]$Path) {
    try {
        $Item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    } catch {
        return $false
    }
    return ($Item.PSIsContainer -and -not $Item.LinkType)
}
if ($env:JARVIS_INSTALL_DIR) {
    $InstallDir = $env:JARVIS_INSTALL_DIR
} elseif (Test-RealDirectory $LegacyInstallDir) {
    $InstallDir = $LegacyInstallDir
    $MigrateLegacyInstallDir = $true
} else {
    $InstallDir = $CurrentInstallDir
}
# --- install-dir-choice end
# The migration engine inside the release being installed. It is read from
# the fetched commit, never from the checkout that is about to change.
$IdentityEnginePath = 'dodaios/core/identity_migration.py'
$PrerequisiteMode = if ($env:JARVIS_INSTALL_PREREQS) { $env:JARVIS_INSTALL_PREREQS.ToLowerInvariant() } else { 'ask' }
$InitialPath = $env:Path

# Forward any extra args to installer.py (e.g. --no-launch, --dry-run, --with-voice-local)
$ExtraArgs = $args

# The whole run is timed from here (or from the verifying wrapper, when it
# started the clock); installer.py shows the total on its finale card.
if (-not $env:JARVIS_INSTALL_STARTED_AT) {
    $env:JARVIS_INSTALL_STARTED_AT = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}

# The machine this runs on, for the line under the wordmark.
function Get-UiPlatform {
    $build = [Environment]::OSVersion.Version.Build
    $name = if ($build -ge 22000) { 'Windows 11' } elseif ($build -ge 10240) { 'Windows 10' } else { 'Windows' }
    $arch = "$env:PROCESSOR_ARCHITEW6432"
    if (-not $arch) { $arch = "$env:PROCESSOR_ARCHITECTURE" }
    $arch = switch ($arch) { 'AMD64' { 'x64' } 'ARM64' { 'arm64' } default { $arch } }
    return "$name ($arch)"
}
$UiMeta = "Open source $GSkip MIT $GSkip github.com/$OfficialRepoSlug"
$UiVerb = if (Test-Path -LiteralPath (Join-Path $InstallDir '.git')) { 'Updating Dodaios on' } else { 'Installing on' }
Write-Hero "$UiVerb $(Get-UiPlatform)" $UiMeta

# --- prerequisite-bootstrap begin ------------------------------------------
# This block stays shell-native because Python may not exist yet. Tests extract
# it directly and exercise the retry/continuation state machine with fakes.
function Test-Tool {
    param([string]$Name, [string[]]$VersionArgs = @('--version'))
    try {
        $out = & $Name @VersionArgs 2>&1
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        return @{
            Found = ($code -eq 0)
            Version = [string]($out | Select-Object -First 1)
        }
    } catch {
        return @{ Found = $false; Version = $null }
    }
}

function Test-PythonCandidate {
    param([string]$Exe)
    try {
        # Keep the Python snippet quote-free. Windows PowerShell 5's legacy
        # native-argument marshaller can strip nested quote characters even
        # when the PowerShell string itself is correctly quoted.
        $probe = 'import sys; print(sys.version_info.major, sys.version_info.minor,' +
            'sys.version_info.micro, sep=chr(46))'
        $out = & $Exe -c $probe 2>&1
        if ($LASTEXITCODE -ne 0) { return $null }
        $version = [string]($out | Select-Object -First 1)
        if ($version -notmatch '^(\d+)\.(\d+)\.(\d+)$') { return $null }
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        return [pscustomobject]@{
            Exe = $Exe
            Version = $version
            Compatible = (($major -gt 3) -or ($major -eq 3 -and $minor -ge 11))
        }
    } catch {
        return $null
    }
}

# Private copies of Python and Git for a machine that has neither. They land in
# %LOCALAPPDATA%\Dodaios\tools without administrator rights or a prompt, and
# nothing is added to the user's PATH or registry: this installer and the app
# (dodaios/core/path_augment.py) look in that folder themselves. Every download
# is pinned to a version and checked against its SHA-256 before it is used.
$BundledUvVersion = '0.12.23'
$BundledUvSha256 = @{
    'x86_64'  = '75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90'
    'aarch64' = '13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5'
}
$BundledPythonVersion = '3.12'
$BundledGitTag = 'v2.56.0.windows.2'
$BundledGitZip = @{
    'x86_64'  = @{ Name = 'MinGit-2.56.0.2-64-bit.zip'; Sha256 = 'da35e72aa21c005a5a0d298cfbae110bc1609a815730ea0dde84b01a1b3cd3be' }
    'aarch64' = @{ Name = 'MinGit-2.56.0.2-arm64.zip'; Sha256 = '38b33dc6024026e3315cf88ab2cfea65205bbd7bb3a8e824bd21c8ad4fe609a7' }
}

function Get-BundledToolsDir {
    if (-not $env:LOCALAPPDATA) { return $null }
    return (Join-Path $env:LOCALAPPDATA 'Dodaios\tools')
}

function Get-BundledArch {
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    switch ($arch) {
        'AMD64' { return 'x86_64' }
        'ARM64' { return 'aarch64' }
        default { return $null }
    }
}

function Save-VerifiedDownload {
    param([string]$Url, [string]$Sha256, [string]$Path)
    try {
        try {
            [Net.ServicePointManager]::SecurityProtocol = `
                [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        } catch {}
        $previous = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            # A dropped connection on a slow or filtered network is the common
            # failure here; two more tries with a short pause clear most of it.
            for ($Attempt = 1; ; $Attempt++) {
                try {
                    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
                    break
                } catch {
                    if ($Attempt -ge 3) { throw }
                    Write-Note "download interrupted - retrying ($Attempt/3) ..."
                    Start-Sleep -Seconds (2 * $Attempt)
                }
            }
        } finally {
            $ProgressPreference = $previous
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
        if ($actual -ne $Sha256) {
            Write-Err "checksum mismatch for $Url - the download was discarded."
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
            return $false
        }
        return $true
    } catch {
        Write-Err "download failed: $Url ($($_.Exception.Message))"
        return $false
    }
}

function Expand-BundledZip {
    param([string]$Url, [string]$Sha256, [string]$Destination)
    $zip = Join-Path ([IO.Path]::GetTempPath()) ('dodaios-' + [Guid]::NewGuid().ToString('N') + '.zip')
    try {
        if (-not (Save-VerifiedDownload $Url $Sha256 $zip)) { return $false }
        $staging = "$Destination.partial"
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive -LiteralPath $zip -DestinationPath $staging -Force
        Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $staging -Destination $Destination
        return $true
    } catch {
        Write-Err "could not unpack $Url ($($_.Exception.Message))"
        return $false
    } finally {
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
    }
}

function Install-BundledPython {
    $toolsDir = Get-BundledToolsDir
    $arch = Get-BundledArch
    if (-not $toolsDir -or -not $arch) { return $false }
    $uvDir = Join-Path $toolsDir 'uv'
    $uvExe = Join-Path $uvDir 'uv.exe'
    if (-not (Test-Path -LiteralPath $uvExe)) {
        Write-Note "downloading the uv Python manager $BundledUvVersion"
        $url = "https://github.com/astral-sh/uv/releases/download/$BundledUvVersion/uv-$arch-pc-windows-msvc.zip"
        if (-not (Expand-BundledZip $url $BundledUvSha256[$arch] $uvDir)) { return $false }
    }
    Write-Note "downloading Python $BundledPythonVersion (about 30 MB, only for Dodaios)"
    $uvOutput = & $uvExe python install $BundledPythonVersion --install-dir (Join-Path $toolsDir 'python') `
        --no-bin --no-registry --quiet 2>&1
    $uvCode = $LASTEXITCODE
    if ($uvCode -ne 0) {
        Write-Err "Python $BundledPythonVersion could not be downloaded (uv exit $uvCode)."
        @($uvOutput | Select-Object -Last 8) | ForEach-Object { Write-Note ([string]$_) }
        return $false
    }
    Write-Ok "Python $BundledPythonVersion ready (private copy for Dodaios)"
    return $true
}

function Install-BundledGit {
    $toolsDir = Get-BundledToolsDir
    $arch = Get-BundledArch
    if (-not $toolsDir -or -not $arch) { return $false }
    $asset = $BundledGitZip[$arch]
    Write-Note 'downloading Git (about 40 MB, only for Dodaios)'
    $url = "https://github.com/git-for-windows/git/releases/download/$BundledGitTag/$($asset.Name)"
    if (-not (Expand-BundledZip $url $asset.Sha256 (Join-Path $toolsDir 'git'))) { return $false }
    Write-Ok 'Git ready (private copy for Dodaios)'
    return $true
}

function Install-BundledPrerequisites {
    param($State)
    $allOk = $true
    if (-not $State.Python.Found) {
        if (-not (Install-BundledPython)) { $allOk = $false }
    }
    if (-not $State.GitFound) {
        if (-not (Install-BundledGit)) { $allOk = $false }
    }
    return $allOk
}

function Find-CompatiblePython {
    $candidates = @()
    if ($env:JARVIS_PYTHON) {
        # An explicit pin is authoritative: never silently substitute another
        # interpreter for the one the user selected.
        $candidates += $env:JARVIS_PYTHON
    } else {
        $candidates += @('python', 'python3', 'py')
        $patterns = @()
        if ($env:LOCALAPPDATA) {
            $patterns += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe'
        }
        if ($env:ProgramFiles) {
            $patterns += Join-Path $env:ProgramFiles 'Python*\python.exe'
        }
        $toolsDir = Get-BundledToolsDir
        if ($toolsDir) {
            # The private copy Install-BundledPython fetched on an earlier run.
            $patterns += Join-Path $toolsDir 'python\cpython-3.*\python.exe'
        }
        foreach ($pattern in $patterns) {
            $candidates += @(Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
        }
    }

    $closest = $null
    $seen = @{}
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        $key = $candidate.ToLowerInvariant()
        if ($seen[$key]) { continue }
        $seen[$key] = $true
        $probe = Test-PythonCandidate $candidate
        if ($null -eq $probe) { continue }
        if ($probe.Compatible) {
            return [pscustomobject]@{
                Found = $true
                Exe = $probe.Exe
                Version = $probe.Version
                Closest = $closest
            }
        }
        if ($null -eq $closest) { $closest = $probe }
    }
    return [pscustomobject]@{
        Found = $false
        Exe = $null
        Version = $null
        Closest = $closest
    }
}

function Get-PrerequisiteState {
    $python = Find-CompatiblePython
    $gitCheck = Test-Tool 'git'
    return [pscustomobject]@{
        Python = $python
        GitFound = $gitCheck.Found
        GitVersion = $gitCheck.Version
        Ready = ($python.Found -and $gitCheck.Found)
    }
}

function Write-PrerequisiteState {
    param($State, [switch]$ShowMissing)
    if ($State.Python.Found) {
        Write-Ok "Python $($State.Python.Version)" 0 $State.Python.Exe
    } elseif ($ShowMissing) {
        Write-Err 'Python 3.11+ not found.'
        if ($null -ne $State.Python.Closest) {
            Write-Note "Closest match: Python $($State.Python.Closest.Version) via '$($State.Python.Closest.Exe)' - too old."
            Write-Note 'Python versions count 3.8 < 3.9 < 3.10 < 3.11.'
        }
    }
    if ($State.GitFound) {
        Write-Ok ("$($State.GitVersion)" -replace '^git version ', 'Git ')
    } elseif ($ShowMissing) {
        Write-Err 'git not found.'
    }
}

function Get-MissingPrerequisiteLabels {
    param($State)
    $missing = @()
    if (-not $State.Python.Found) { $missing += 'Python 3.12 (satisfies 3.11+)' }
    if (-not $State.GitFound) { $missing += 'Git' }
    return $missing
}

function Test-InstallPromptAvailable {
    if (-not [Environment]::UserInteractive) { return $false }
    try {
        # `irm ... | iex` is a PowerShell object pipeline, not redirected
        # console input, so it remains prompt-capable. CI/stdin pipelines do
        # not, and must opt in explicitly with JARVIS_INSTALL_PREREQS=auto.
        return (-not [Console]::IsInputRedirected)
    } catch {
        # Hosts such as PowerShell ISE have no console but provide Read-Host.
        return $true
    }
}

function Request-PrerequisiteConsent {
    param([string[]]$Missing)
    switch ($PrerequisiteMode) {
        'auto' {
            Write-Note 'Automatic prerequisite installation was enabled by JARVIS_INSTALL_PREREQS=auto.'
            return $true
        }
        'never' { return $false }
        'ask' { }
        default {
            Write-Err "Invalid JARVIS_INSTALL_PREREQS value '$PrerequisiteMode'. Use ask, auto, or never."
            return $false
        }
    }

    if (-not (Test-InstallPromptAvailable)) {
        Write-Note 'This shell cannot ask for consent. Re-run interactively or set JARVIS_INSTALL_PREREQS=auto.'
        return $false
    }
    Write-Note "Missing required software: $($Missing -join ', ')."
    Write-Note 'Dodaios can install it with WinGet, wait for completion, and continue this same run.'
    Write-Note 'Continuing also accepts the package and WinGet source agreements for these packages.'
    try {
        $answer = Read-Host '  Install the missing prerequisites now? [Y/n]'
    } catch {
        return $false
    }
    return ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^(?i:y|yes)$')
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $commonGitPaths = @()
    if ($env:ProgramFiles) {
        $commonGitPaths += Join-Path $env:ProgramFiles 'Git\cmd'
    }
    if ($env:LOCALAPPDATA) {
        $commonGitPaths += Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd'
    }
    $toolsDir = Get-BundledToolsDir
    if ($toolsDir) {
        $commonGitPaths += Join-Path $toolsDir 'git\cmd'
    }
    $commonGitPaths = @($commonGitPaths | Where-Object { Test-Path $_ })
    $env:Path = ((@($InitialPath, $userPath, $machinePath) + $commonGitPaths |
        Where-Object { $_ }) -join ';')
}

function Invoke-PrerequisitePackage {
    param([string]$PackageId, [string]$Label)
    Write-Note "installing $Label (this may open one Windows approval prompt)"
    $output = & winget install --id $PackageId --exact --source winget --silent `
        --disable-interactivity --accept-source-agreements --accept-package-agreements 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Err "$Label installation did not complete (WinGet exit $code)."
        @($output | Select-Object -Last 8) | ForEach-Object { Write-Note ([string]$_) }
        return $false
    }
    Write-Ok "$Label installer completed"
    return $true
}

function Invoke-MissingPrerequisiteInstall {
    param($State)
    $wingetCheck = Test-Tool 'winget'
    if (-not $wingetCheck.Found) {
        Write-Err 'WinGet is not available, so Dodaios cannot install the prerequisites automatically.'
        return $false
    }
    $installOk = $true
    if (-not $State.Python.Found) {
        if (-not (Invoke-PrerequisitePackage 'Python.Python.3.12' 'Python 3.12')) {
            $installOk = $false
        }
    }
    if (-not $State.GitFound) {
        if (-not (Invoke-PrerequisitePackage 'Git.Git' 'Git')) {
            $installOk = $false
        }
    }
    return $installOk
}

function Wait-ForPrerequisites {
    param([int]$Seconds = 10)
    $attempts = [Math]::Max(1, [int][Math]::Ceiling($Seconds / 2.0))
    $state = $null
    for ($i = 0; $i -lt $attempts; $i++) {
        Refresh-ProcessPath
        $state = Get-PrerequisiteState
        if ($state.Ready) { return $state }
        if ($i -lt ($attempts - 1)) { Start-Sleep -Seconds 2 }
    }
    return $state
}

function Write-ManualPrerequisiteHelp {
    param($State)
    if (-not $State.Python.Found) {
        Write-Note 'Python: https://www.python.org/downloads/windows/'
    }
    if (-not $State.GitFound) {
        Write-Note 'Git:    https://git-scm.com/download/win'
    }
}

function Ensure-Prerequisites {
    Refresh-ProcessPath
    $state = Get-PrerequisiteState
    Write-PrerequisiteState $state -ShowMissing
    if ($state.Ready) { return $state }
    if ($env:JARVIS_PYTHON -and -not $state.Python.Found) {
        Write-Note "JARVIS_PYTHON is pinned to '$($env:JARVIS_PYTHON)' and is not a compatible interpreter."
        Write-Note 'Update or unset that pin before prerequisite installation.'
        return $null
    }

    # A private copy needs no administrator rights and changes nothing outside
    # the Dodaios folder, so it is fetched without asking. WinGet and the
    # consent prompt below stay the fallback when that download fails.
    if ($PrerequisiteMode -ne 'never') {
        if (Install-BundledPrerequisites $state) {
            $state = Wait-ForPrerequisites -Seconds 2
            if ($state.Ready) {
                Write-PrerequisiteState $state
                return $state
            }
        }
    }

    $missing = @(Get-MissingPrerequisiteLabels $state)
    if (-not (Request-PrerequisiteConsent $missing)) {
        Write-ManualPrerequisiteHelp $state
        Write-Note 'Nothing was installed. Run this command again after adding the prerequisites.'
        return $null
    }

    [void](Invoke-MissingPrerequisiteInstall $state)
    $state = Wait-ForPrerequisites

    while (-not $state.Ready) {
        Write-Err 'The required commands are still unavailable in this terminal.'
        Write-ManualPrerequisiteHelp $state
        if ($PrerequisiteMode -eq 'auto' -or -not (Test-InstallPromptAvailable)) {
            return $null
        }
        try {
            $answer = Read-Host '  Finish any manual installer, then press Enter to re-check; R retries WinGet, Q stops'
        } catch {
            return $null
        }
        if ($answer -match '^(?i:q|quit)$') { return $null }
        if ($answer -match '^(?i:r|retry)$') {
            [void](Invoke-MissingPrerequisiteInstall $state)
        }
        $state = Wait-ForPrerequisites
    }

    Write-PrerequisiteState $state
    return $state
}
# --- prerequisite-bootstrap end --------------------------------------------

# ----------------------------------------------------------------- preflight
Write-Phase '1/6' 'Prerequisites'

$prerequisites = Ensure-Prerequisites
if ($null -eq $prerequisites) {
    Write-Err 'Prerequisite setup was not completed.'
    Exit-Install 1
}
$pythonExe = $prerequisites.Python.Exe
$pythonVer = "Python $($prerequisites.Python.Version)"

# Node.js 18+ -- powers only the OPTIONAL agent worker CLIs (Claude
# Code / Codex) that heavy missions delegate to, plus the Node-based
# marketplace integrations. Everything else in Dodaios runs without it, so a
# missing Node must NEVER turn a new user away at the door: we note it and
# continue -- the worker CLI can be added later in-app once Node is installed.
# Skipped entirely on the headless / tiny-VPS path (--headless): a cloud-only
# base install that never spawns a local CLI worker.
if ($ExtraArgs -contains '--headless') {
    Write-Skip 'Node.js check skipped (--headless): the cloud-only base install does not use it.'
} else {
    $nodeOk = $false
    $nodeCheck = Test-Tool 'node'
    if ($nodeCheck.Found -and $nodeCheck.Version -match 'v?(\d+)\.\d+\.\d+') {
        $nodeOk = ([int]$Matches[1] -ge 18)
    }
    if ($nodeOk) {
        Write-Ok "Node.js $($nodeCheck.Version)"
    } else {
        Write-Skip 'Node.js 18+ not found: optional, Dodaios runs fine without it.'
        Write-Note 'It only powers the optional coding-agent worker (Claude Code / Codex).'
        Write-Note 'Install the LTS build any time from https://nodejs.org/ and add the'
        Write-Note 'worker later in the app.'
    }
}

# ----------------------------------------------------------------- clone / update
Write-Phase '2/6' 'Download'

# On an interactive console the transfer shows as one live progress bar
# (Invoke-UiGit) so a slow download never looks hung (maintainer report
# 2026-07-15); a redirected/CI run keeps git --quiet for a clean transcript.
# Real errors surface either way.

# The payload is a single ~80 MB stream and git cannot resume a clone, so a
# flaky network kills installs two ways (maintainer's Mac, 2026-07-18:
# "Receiving objects: 45%" frozen for minutes, then "early EOF" /
# "unexpected disconnect while reading sideband packet"):
#   1. a stalled stream hangs silently -> low-speed limits turn that into a
#      fast, visible failure (under 1 KB/s for 30 s = dead connection);
#   2. a mid-transfer disconnect aborts the install -> retry a clean clone
#      up to 3 times before giving up with an honest message.
$GitNetOpts = @('-c', 'http.lowSpeedLimit=1024', '-c', 'http.lowSpeedTime=30')
# An install never downloads Git LFS objects: older releases carry LFS
# pointers for large binaries, and a ref pinned to one must not pull those.
$env:GIT_LFS_SKIP_SMUDGE = '1'

# --- install-ref begin (extracted by tests/unit/install/test_install_ref.py)
# Without JARVIS_INSTALL_REF an install follows the newest published release,
# the same thing the in-app updater moves to. A release tag carries the
# frontend bundle built from its own sources; main does not have to. main is
# the fallback when the release cannot be looked up (offline API, a fork
# without releases). (POSIX twin: resolve_install_ref in install.sh.)
function Resolve-InstallRef {
    if ($Branch) { return $Branch }
    if ($RepoUrl -notmatch 'github\.com/') { return 'main' }
    $Slug = ($RepoUrl -split 'github\.com/', 2)[1] -replace '\.git$', ''
    $Api = if ($env:INSTALLER_TEST_RELEASE_API) { $env:INSTALLER_TEST_RELEASE_API } else { 'https://api.github.com' }
    try {
        $Release = Invoke-RestMethod -Uri "$Api/repos/$Slug/releases/latest" -TimeoutSec 20 `
            -Headers @{ Accept = 'application/vnd.github+json' } -UseBasicParsing -ErrorAction Stop
        $Tag = [string]$Release.tag_name
        if ($Tag -match '^v\d+\.\d+\.\d+$') { return $Tag }
    } catch {}
    return 'main'
}

# codeload path of the ref: a release tag or a branch.
function Get-RefArchivePath {
    if ($Branch -match '^v\d') { return "refs/tags/$Branch" }
    return "refs/heads/$Branch"
}
# --- install-ref end

function Invoke-CloneWithRetry {
    Write-Note 'About 80 MB: a few minutes on a slow connection.'
    $Attempt = 1
    while ($true) {
        # Attempt 1 uses git's default transport; later attempts force
        # HTTP/1.1 - the known cure for a family of "RPC failed; curl 28 /
        # early EOF" aborts that only bite the bulk pack stream while small
        # requests sail through (observed on the test Mac, 2026-07-18).
        $HttpMode = if ($Attempt -gt 1) { @('-c', 'http.version=HTTP/1.1') } else { @() }
        $code = Invoke-UiGit -Arguments (@($GitNetOpts) + @($HttpMode) + @('clone', '--depth', '1', '--branch', $Branch, $RepoUrl, $InstallDir))
        if ($code -eq 0) { return $true }
        try { Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction Stop } catch {}
        if ($Attempt -ge 3) {
            Write-Warn 'git could not finish the download on this network (3 attempts).'
            return $false
        }
        $Attempt++
        Write-Warn "The download did not finish: retrying ($Attempt/3, compatibility transfer mode)."
        Start-Sleep -Seconds 3
    }
}

# Last-resort transport when git cannot get the pack through AT ALL: a plain
# HTTPS archive download. The release asset (uploaded per release) supports
# HTTP ranges, so curl -C - RESUMES after every disconnect - even a crawling
# connection eventually finishes, which a restarted git clone never does.
# Falls back to the branch snapshot (codeload, not resumable) when no release
# asset is reachable. The tree lands WITHOUT .git metadata; the next installer
# run detects that and repairs it in place (salvage path), so updates keep
# working. Windows 10+ ships both curl.exe and tar.exe.
function Invoke-TarballFallback {
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { return $false }
    if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) { return $false }
    if ($RepoUrl -notmatch 'github\.com/') { return $false }
    $RepoPath = ($RepoUrl -split 'github\.com/', 2)[1] -replace '\.git$', ''
    $AssetBase = "https://github.com/$RepoPath/releases/latest/download"
    # The archive's current name first; releases cut before the rename only
    # carry the earlier one.
    $AssetNames = @('dodaios-src.tar.gz', 'personal-jarvis-src.tar.gz')
    $SnapshotUrl = "https://codeload.github.com/$RepoPath/tar.gz/$(Get-RefArchivePath)"
    if ($env:JARVIS_PAYLOAD_COMMIT) {
        # A verified install is pinned to ONE signed commit; the "latest"
        # release asset cannot honor that pin, so go straight to the
        # commit-addressed snapshot - the URL itself names the exact tree.
        $AssetNames = @()
        $SnapshotUrl = "https://codeload.github.com/$RepoPath/tar.gz/$($env:JARVIS_PAYLOAD_COMMIT)"
    }
    $Tmp = "$InstallDir.payload.tar.gz"
    Write-Warn 'The git transfer keeps stalling on this network: switching to a resumable archive download.'
    $Got = $false
    foreach ($AssetName in $AssetNames) {
        # A partial download of one archive must never be resumed as another.
        try { Remove-Item -LiteralPath $Tmp -Force -ErrorAction Stop } catch {}
        $Try = 1
        while ($Try -le 8) {
            & curl.exe -fL --speed-limit 1024 --speed-time 60 -C - -o $Tmp "$AssetBase/$AssetName"
            if ($LASTEXITCODE -eq 0) { $Got = $true; break }
            if ($LASTEXITCODE -eq 22) { break }  # HTTP error (this archive is not on the release): try the next name
            Write-Note "archive download interrupted - resuming where it stopped ($Try/8) ..."
            $Try++
            Start-Sleep -Seconds 3
        }
        if ($Got) { break }
    }
    if (-not $Got) {
        try { Remove-Item -LiteralPath $Tmp -Force -ErrorAction Stop } catch {}
        Write-Note 'no resumable release archive reachable - trying the direct snapshot (single stream)'
        & curl.exe -fL --speed-limit 1024 --speed-time 60 -o $Tmp $SnapshotUrl
        if ($LASTEXITCODE -ne 0) {
            try { Remove-Item -LiteralPath $Tmp -Force -ErrorAction Stop } catch {}
            return $false
        }
    }
    try { Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction Stop } catch {}
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    & tar.exe -xzf $Tmp -C $InstallDir --strip-components=1
    $TarOk = ($LASTEXITCODE -eq 0)
    try { Remove-Item -LiteralPath $Tmp -Force -ErrorAction Stop } catch {}
    if (-not $TarOk) { return $false }
    Write-Note 'installed from the release archive (git metadata is repaired on a future update)'
    return $true
}

function Invoke-FetchPayload {
    if (Invoke-CloneWithRetry) { return $true }
    if (Invoke-TarballFallback) { return $true }
    Write-Err 'The download kept failing (the connection dropped mid-transfer).'
    Write-Note 'Check your internet connection (Wi-Fi, VPN, proxy), then run the installer'
    Write-Note 'again. It is safe to re-run and picks up where it makes sense.'
    return $false
}

# Nothing is stopped or moved until the download server answers. Without a
# connection the fresh copy cannot arrive, and an install that was moved aside
# for nothing is worse than one that simply was not updated.
# git is asked first. A network that lets no git transfer through still reaches
# the archive download the installer falls back to, so a plain HTTPS answer
# from the same host counts as well.
# (POSIX twin: the salvage-guard block in install.sh.)
function Test-RepositoryReachable {
    # git reports an unreachable repository on stderr, which Windows PowerShell
    # turns into a terminating error under 'Stop'. The exit code is the answer.
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & git @GitNetOpts ls-remote --quiet --heads $RepoUrl 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        if ($RepoUrl -notmatch 'github\.com/') { return $false }
        if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { return $false }
        $ProbePath = ($RepoUrl -split 'github\.com/', 2)[1] -replace '\.git$', ''
        & curl.exe -fsIL --max-time 20 "https://github.com/$ProbePath" 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

# Self-heal a broken install dir (leftover non-git folder from an earlier or
# aborted install, or a checkout whose git state no longer updates): keep the
# old tree as a timestamped sibling backup - never delete - clone fresh, then
# carry the user's local state (data/, the config file, .env) into the new
# checkout. A stale folder must never require manual cleanup to install.
function Invoke-SalvageReclone {
    if (-not (Test-RepositoryReachable)) {
        Write-Err 'Cannot reach the download server right now; nothing was changed.'
        Write-Note 'Check your internet connection (Wi-Fi, VPN, proxy), then re-run the installer.'
        Exit-Install 1
    }
    Stop-RunningApp
    $StaleBackup = "$InstallDir.stale-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    try {
        Move-Item -LiteralPath $InstallDir -Destination $StaleBackup -ErrorAction Stop
    } catch {
        Write-Err "Cannot move the broken install folder aside ($InstallDir -> $StaleBackup)."
        Write-Note 'Close any program using that folder (or move it yourself), then re-run.'
        Exit-Install 1
    }
    Write-Note "moved the old directory to $StaleBackup (nothing was deleted)"
    if (-not (Invoke-FetchPayload)) { Exit-Install 1 }
    # Everything a user can lose: config, credentials file-fallback + DBs
    # (inside data/), the dotenv, AND the wiki vault (its absence from this
    # list is what destroyed a user's wiki pages on 2026-07-20). A failed
    # copy is a loud warning pointing at the backup dir - never silent.
    # NOTE: a "skip when the destination exists" guard is WRONG for wiki -
    # the fresh clone ships a tracked seed wiki/ skeleton, so the guard
    # would silently never restore the user's real vault. Directories that
    # exist on both sides are overlay-MERGED (user files win over seed).
    foreach ($Item in @('data', $LegacyConfigFileName, $ConfigFileName, '.env', 'wiki')) {
        $Old = Join-Path $StaleBackup $Item
        $New = Join-Path $InstallDir $Item
        if (-not (Test-Path $Old)) { continue }
        if (-not (Test-Path $New)) {
            try {
                Copy-Item -LiteralPath $Old -Destination $New -Recurse -ErrorAction Stop
                Write-Note "kept your $Item from the previous install"
            } catch {
                Write-Err "could NOT carry over $Item - it is still safe in $Old; copy it back manually."
            }
        } elseif ((Test-Path $Old -PathType Container) -and (Test-Path $New -PathType Container)) {
            try {
                Copy-Item -Path (Join-Path $Old '*') -Destination $New -Recurse -Force -ErrorAction Stop
                Write-Note "merged your $Item from the previous install over the fresh seed"
            } catch {
                Write-Err "could NOT merge $Item - it is still safe in $Old; copy it back manually."
            }
        }
    }
    Write-Ok 'Reinstalled fresh (your previous state is kept in the backup folder)'
}

# A checkout cloned before the GitHub rename still stores the old origin. Git
# fetches through GitHub's redirect, but the in-app updater identifies a managed
# install by this remote, so an untouched one loses its Update button. Only the
# stock repository is retargeted; an explicit repository override is left alone.
# (POSIX twin: retarget_legacy_origin in install.sh.)
function Update-LegacyOrigin {
    if ($env:JARVIS_INSTALL_REPO -or $env:JARVIS_OFFICIAL_REPO_SLUG) { return }
    $Origin = & git -C $InstallDir config --get remote.origin.url
    if ($LASTEXITCODE -ne 0 -or -not $Origin) { return }
    $Tail = "$Origin".Trim().TrimEnd('/') -replace '\.git$', ''
    if ($Tail -notmatch ('github\.com[:/]' + [regex]::Escape($LegacyOfficialRepoSlug) + '$')) { return }
    & git -C $InstallDir remote set-url origin $RepoUrl
    if ($LASTEXITCODE -eq 0) {
        Write-Note 'pointed this install at the renamed repository'
    } else {
        Write-Note 'could not update the stored repository address - continuing'
    }
}

# Stop any Dodaios still running out of THIS install. Called before the
# checkout is replaced and again before its environment is rebuilt: a release
# may move or delete files the live app still loads, and an app left running
# across that keeps serving a half-old, half-new program until it falls over.
# On Windows the running interpreter additionally holds venv DLLs open, which
# can make pip's in-place upgrade fail.
#
# Every process whose image lives in this install's venv is stopped, whatever
# it is called: the desktop app usually runs as the branded launcher copy
# beside python.exe, not as python.exe itself. Best-effort: a lookup or stop
# failure never blocks the install. Safe to call twice - the second call finds
# nothing left to stop. (POSIX twin: stop_running_app in install.sh.)
function Stop-RunningApp {
    $StopVenv = Join-Path $InstallDir '.venv'
    if (-not (Test-Path (Join-Path $StopVenv 'Scripts\python.exe'))) { return }
    $StartedInsideApp = $false
    try {
        $venvPrefix = $StopVenv.TrimEnd('\') + '\'
        $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        $stale = @($all |
            Where-Object {
                $_.ExecutablePath -and
                $_.ExecutablePath.StartsWith($venvPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
                $_.ProcessId -ne $PID
            })
        if ($stale.Count -gt 0) {
            # The installer refuses to do this to itself. Started from a
            # terminal inside the app, its own parents (the pane's console
            # host, the terminal host, the app) run out of this venv; stopping
            # them would end the installer mid-way with the app gone and
            # nothing installed.
            $staleIds = @{}
            foreach ($proc in $stale) { $staleIds[[int]$proc.ProcessId] = $true }
            $byId = @{}
            foreach ($proc in $all) { $byId[[int]$proc.ProcessId] = $proc }
            $seen = @{}
            $cursor = $byId[[int]$PID]
            while ($cursor -and -not $seen.ContainsKey([int]$cursor.ProcessId)) {
                $seen[[int]$cursor.ProcessId] = $true
                $parent = $byId[[int]$cursor.ParentProcessId]
                # Windows reuses process ids: a "parent" that started after its
                # child is an unrelated process that inherited the number.
                if (-not $parent -or $parent.CreationDate -gt $cursor.CreationDate) { break }
                if ($staleIds.ContainsKey([int]$parent.ProcessId)) { $StartedInsideApp = $true; break }
                $cursor = $parent
            }
        }
        # A refusal is reported below, outside this try: its catch would turn
        # it into "could not check" and carry on.
        if (-not $StartedInsideApp -and $stale.Count -gt 0) {
            foreach ($proc in $stale) {
                try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop } catch {}
            }
            # Give the OS a beat to release file handles before files change.
            Start-Sleep -Milliseconds 500
            Write-Note 'stopped the running Dodaios app for the update'
        }
    } catch {
        Write-Note 'could not check for a running Dodaios app - continuing'
    }
    if ($StartedInsideApp) {
        Write-Err 'this installer was started from inside the running app.'
        Write-Note 'Updating stops the app, which would end this installer with it.'
        Write-Note 'Nothing was changed. Run the install command again from a normal'
        Write-Note 'terminal outside the app.'
        Exit-Install 1
    }
}

# Move an install made under the earlier directory name to the current one,
# once the app is stopped and before the checkout changes. The engine is the
# copy inside the fetched release, written to a temporary file outside both
# directories byte for byte: it never passes through a PowerShell pipeline,
# which would re-encode it. It runs isolated (-I), without writing bytecode
# (-B), from the home directory, renames once and leaves a junction at the old
# path, or changes nothing; the directory it reports is where the update goes
# on. Any failure goes on in place: an install under the earlier name is a
# valid state, not a broken one. Returns the directory to go on in; nothing
# else may reach the output. (POSIX twin: migrate_install_dir in install.sh.)
function Invoke-InstallDirMigration {
    if (-not $MigrateLegacyInstallDir) { return $InstallDir }
    # Native stderr must never become a terminating error here.
    $ErrorActionPreference = 'Continue'
    $Engine = Join-Path ([IO.Path]::GetTempPath()) ('dodaios-identity-migration-' + [guid]::NewGuid().ToString('N') + '.py')
    $Report = $null
    try {
        if ($Branch -notmatch '^[A-Za-z0-9._/-]+$') { throw 'unusual branch name' }
        $Git = Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1
        $Start = New-Object System.Diagnostics.ProcessStartInfo
        $Start.FileName = $Git.Source
        $Start.Arguments = 'show "FETCH_HEAD:' + $IdentityEnginePath + '"'
        $Start.WorkingDirectory = $InstallDir
        $Start.UseShellExecute = $false
        $Start.RedirectStandardOutput = $true
        $Start.RedirectStandardError = $true
        $Start.CreateNoWindow = $true
        $Process = [System.Diagnostics.Process]::Start($Start)
        $ErrorText = $Process.StandardError.ReadToEndAsync()
        $Bytes = New-Object System.IO.MemoryStream
        $Process.StandardOutput.BaseStream.CopyTo($Bytes)
        $Process.WaitForExit()
        [void]$ErrorText.Result
        if ($Process.ExitCode -ne 0 -or $Bytes.Length -eq 0) { throw 'the release carries no migration engine' }
        [IO.File]::WriteAllBytes($Engine, $Bytes.ToArray())
        # Windows refuses to rename a folder that is any process's working
        # directory, this one's included.
        [Environment]::CurrentDirectory = $env:USERPROFILE
        Push-Location -LiteralPath $env:USERPROFILE
        try {
            $Output = & $pythonExe -I -B $Engine migrate $LegacyInstallDir $CurrentInstallDir 2>$null
            if ($LASTEXITCODE -eq 0) { $Report = ($Output | Out-String) | ConvertFrom-Json }
        } finally {
            Pop-Location
        }
    } catch {
        $Report = $null
    } finally {
        try { Remove-Item -LiteralPath $Engine -Force -ErrorAction Stop } catch {}
    }
    $Effective = $null
    if ($Report -and $Report.effective) { $Effective = [string]$Report.effective }
    if (-not $Effective -or -not (Test-Path -LiteralPath $Effective -PathType Container)) {
        Write-Note "kept the install in $InstallDir (the move to $CurrentInstallDir did not run)"
        return $InstallDir
    }
    $Outcome = [string]$Report.outcome
    if (@('migrated', 'link_restored', 'already_linked') -contains $Outcome) {
        Write-Note "moved the install to $Effective (the old folder name still leads there)"
    } elseif ($Outcome -eq 'migrated_without_link') {
        Write-Note "moved the install to $Effective"
    } else {
        Write-Note "kept the install in $Effective (it could not be renamed: $Outcome)"
    }
    return $Effective
}

$Branch = Resolve-InstallRef
Write-Note "Release $Branch into $InstallDir"
$FetchWatch = [Diagnostics.Stopwatch]::StartNew()

# The fetch only writes inside .git, so the app keeps running through it: a
# failed download (offline, an outage) then leaves a working app behind. It is
# stopped at the last moment, right before the files it runs from change.
if (Test-Path (Join-Path $InstallDir '.git')) {
    Update-LegacyOrigin
    $UpdateOk = $true
    Push-Location $InstallDir
    try {
        $code = Invoke-UiGit -Arguments (@($GitNetOpts) + @('fetch', '--depth', '1', 'origin', $Branch))
        if ($code -ne 0) { $UpdateOk = $false }
        if ($UpdateOk) {
            Stop-RunningApp
            $InstallDir = [string](Invoke-InstallDirMigration)
            Set-Location -LiteralPath $InstallDir
            # FETCH_HEAD works for a release tag and a branch alike.
            & git checkout --quiet --detach FETCH_HEAD
            if ($LASTEXITCODE -ne 0) { $UpdateOk = $false }
        }
        if ($UpdateOk) {
            & git reset --quiet --hard FETCH_HEAD
            if ($LASTEXITCODE -ne 0) { $UpdateOk = $false }
        }
    } finally {
        Pop-Location
    }
    if ($UpdateOk) {
        Write-Ok "Updated the install to $Branch" $FetchWatch.Elapsed.TotalSeconds
    } else {
        Write-Note 'existing checkout would not update (broken git state) - reinstalling in place.'
        Invoke-SalvageReclone
    }
} else {
    if (Test-Path $InstallDir) {
        Write-Note "$InstallDir exists but is not a git repo (leftover from an earlier install) - reinstalling in place."
        Invoke-SalvageReclone
    } else {
        if (-not (Invoke-FetchPayload)) { Exit-Install 1 }
        Write-Ok "Downloaded Dodaios $Branch" $FetchWatch.Elapsed.TotalSeconds
    }
}

# WAVE 5 - payload-commit pin (axis E, Wave-5 audit Finding 2).
#
# install-verify.ps1 sets $env:JARVIS_PAYLOAD_COMMIT containing the
# signed payload commit SHA (Wave 1+2+4-authenticated). If set, bind the
# cloned tree to that exact commit so an attacker who flips `main` post-
# release cannot influence what we install. The signed SHA may be 40-char
# (git SHA-1) or 64-char (git SHA-256 repos).
if ($env:JARVIS_PAYLOAD_COMMIT) {
    $PayloadCommit = $env:JARVIS_PAYLOAD_COMMIT
    if ($PayloadCommit -notmatch '^[0-9a-f]{40}([0-9a-f]{24})?$') {
        Write-Err "JARVIS_PAYLOAD_COMMIT is not a well-formed git SHA: '$PayloadCommit' - refusing."
        Exit-Install 1
    }
    if (-not (Test-Path (Join-Path $InstallDir '.git'))) {
        # Tarball-fallback install: the tree was fetched from the commit-
        # addressed archive URL, so the pin is embedded in the download
        # itself; there are no git objects to re-verify against.
        Write-Ok "pinned via commit-addressed archive ($($PayloadCommit.Substring(0,12)))"
        $PinnedViaArchive = $true
    } else {
        $PinnedViaArchive = $false
    }
    if (-not $PinnedViaArchive) {
    Push-Location $InstallDir
    try {
        # Shallow clones don't carry full history; deepen to retrieve the
        # target SHA explicitly. github.com defaults allow fetching arbitrary
        # SHAs on most repos; fall back to unshallow if direct-SHA fetch
        # fails (e.g. tag pushed but workflow ref-name was the merge commit).
        & git fetch --quiet --depth 1 origin $PayloadCommit 2>$null
        if ($LASTEXITCODE -ne 0) {
            & git fetch --quiet --unshallow origin
            if ($LASTEXITCODE -ne 0) { & git fetch --quiet origin }
        }
        & git checkout --quiet --detach $PayloadCommit
        if ($LASTEXITCODE -ne 0) {
            Write-Err "failed to checkout payload-commit $PayloadCommit - refusing."
            Write-Note 'the cloned tree does not contain the signed commit; release may be inconsistent.'
            Exit-Install 1
        }
        # Defensive verify: HEAD must be exactly the signed SHA byte-for-byte.
        $ActualHead = (& git rev-parse HEAD).Trim()
        if ($ActualHead -ne $PayloadCommit) {
            Write-Err "HEAD drift detected: pinned=$PayloadCommit, actual=$ActualHead - refusing."
            Exit-Install 1
        }
        Write-Ok "pinned to signed commit $($PayloadCommit.Substring(0,12))"
    } finally {
        Pop-Location
    }
    }
}

# ----------------------------------------------------------------- venv + bootstrap deps
Write-Phase '3/6' 'Python environment'

$VenvPath = Join-Path $InstallDir '.venv'
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'

# Update runs: stop any Dodaios still running out of THIS install before we
# touch its environment. A live app (often revived by the login autostart)
# keeps serving stale, half-updated features while pip rewrites the venv
# under it - the "app is already open but nothing works yet" field report
# (2026-07-14). The installer relaunches a fresh instance as its very last
# step. The app was already stopped once before the checkout was replaced;
# this second call catches one the login autostart revived in between.
Stop-RunningApp

$script:UiLastSeconds = 0
if (-not (Test-Path $VenvPython)) {
    $code = Invoke-UiSpin -Label 'Virtual environment' -FilePath $pythonExe -Arguments @('-m', 'venv', $VenvPath)
    if ($code -ne 0) { Exit-Install 1 }
}
Write-Ok 'Virtual environment ready' $script:UiLastSeconds

# installer.py itself needs only the standard library and this checkout
# until its own phase 4 has run; an up-to-date pip installs that phase.
$BootstrapArgs = @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip', 'packaging')
$code = Invoke-UiSpin -Label 'Installer tools (pip, packaging)' -FilePath $VenvPython -Arguments $BootstrapArgs
if ($code -ne 0) {
    # Once more: a dropped connection or a file an antivirus scanner still
    # holds open usually clears within seconds.
    Write-Note 'A dropped connection or a locked file often clears up, so: retrying once.'
    Start-Sleep -Seconds 4
    $code = Invoke-UiSpin -Label 'Installer tools (pip, packaging), retry' -FilePath $VenvPython -Arguments $BootstrapArgs
}
if ($code -ne 0) {
    Write-Err 'The installer tools could not be installed.'
    Write-Note 'Check your connection, then run the installer again.'
    Write-Note 'If your antivirus quarantined a file, restore it and allow the Dodaios folder first.'
    Write-Note 'Help: https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md#troubleshooting'
    Exit-Install 1
}
Write-Ok 'Installer tools ready (pip, packaging)' $script:UiLastSeconds

# ----------------------------------------------------------------- hand off
$InstallerPy = Join-Path $InstallDir 'install\installer.py'
if (-not (Test-Path $InstallerPy)) {
    Write-Err "$InstallerPy not found in the download."
    Write-Note 'The download seems incomplete. Please file a bug.'
    Exit-Install 1
}

# The LFS skip is for this script's own git calls only. Drop it before the
# hand-off so the app installer.py launches (and every git it runs in the
# user's own repos) never inherits it.
Remove-Item Env:GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue

Push-Location $InstallDir
try {
    & $VenvPython $InstallerPy @ExtraArgs
    Exit-Install $LASTEXITCODE
} finally {
    Pop-Location
}

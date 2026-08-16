# MusicEditing OTA apply helper (runs OUTSIDE the install tree via system PowerShell).
# Args: -PendingPath <pending_ota.json>
# JSON fields: install_root, source_dir, package_zip (optional), relaunch_exe, wait_pid, version

param(
    [Parameter(Mandatory = $true)][string]$PendingPath
)

$ErrorActionPreference = "Stop"
$logDir = Join-Path $env:LOCALAPPDATA "MusicEditing\ota"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "apply_helper.log"

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
}

$bak = $null
$dstFull = $null
$name = $null
$parent = $null
$stagingNew = $null
$renamedToBak = $false

try {
    Write-Log "start pending=$PendingPath"
    if (-not (Test-Path -LiteralPath $PendingPath)) {
        Write-Log "missing pending file"
        exit 2
    }
    $pending = Get-Content -LiteralPath $PendingPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $installRoot = [string]$pending.install_root
    $sourceDir = [string]$pending.source_dir
    $packageZip = [string]$pending.package_zip
    $relaunch = [string]$pending.relaunch_exe
    $waitPid = 0
    if ($pending.wait_pid) { $waitPid = [int]$pending.wait_pid }
    $version = [string]$pending.version

    if (-not $installRoot -or -not (Test-Path -LiteralPath $installRoot)) {
        Write-Log "bad install_root=$installRoot"
        exit 3
    }
    if (-not $relaunch) {
        $relaunch = Join-Path $installRoot "MusicEditing.exe"
    }

    if ($waitPid -gt 0) {
        Write-Log "wait pid=$waitPid"
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            $p = Get-Process -Id $waitPid -ErrorAction SilentlyContinue
            if (-not $p) { break }
            Start-Sleep -Milliseconds 400
        }
        Start-Sleep -Seconds 1
    } else {
        Start-Sleep -Seconds 2
    }

    if ((-not $sourceDir -or -not (Test-Path -LiteralPath $sourceDir)) -and $packageZip -and (Test-Path -LiteralPath $packageZip)) {
        $extractTo = Join-Path (Split-Path -Parent $packageZip) "extracted"
        if (Test-Path -LiteralPath $extractTo) {
            Remove-Item -LiteralPath $extractTo -Recurse -Force -ErrorAction SilentlyContinue
        }
        New-Item -ItemType Directory -Force -Path $extractTo | Out-Null
        Write-Log "expand $packageZip -> $extractTo"
        Expand-Archive -LiteralPath $packageZip -DestinationPath $extractTo -Force
        $exe = Get-ChildItem -LiteralPath $extractTo -Recurse -Filter "MusicEditing.exe" | Select-Object -First 1
        if ($exe) {
            $sourceDir = $exe.Directory.FullName
        } else {
            Write-Log "expanded zip missing MusicEditing.exe"
            exit 4
        }
        Write-Log "sourceDir=$sourceDir"
    }

    if (-not $sourceDir -or -not (Test-Path -LiteralPath $sourceDir)) {
        Write-Log "missing source_dir"
        exit 4
    }

    $srcExe = Join-Path $sourceDir "MusicEditing.exe"
    if (-not (Test-Path -LiteralPath $srcExe)) {
        Write-Log "source missing MusicEditing.exe: $srcExe"
        exit 4
    }

    $srcFull = (Resolve-Path -LiteralPath $sourceDir).Path.TrimEnd('\')
    $dstFull = (Resolve-Path -LiteralPath $installRoot).Path.TrimEnd('\')
    if ($srcFull.Equals($dstFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Log "source==install, abort"
        exit 5
    }

    $parent = Split-Path -Parent $dstFull
    $name = Split-Path -Leaf $dstFull
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $bak = Join-Path $parent ($name + ".ota_bak_" + $stamp)
    $stagingNew = Join-Path $parent ($name + ".ota_new_" + $stamp)

    if (Test-Path -LiteralPath $stagingNew) {
        Remove-Item -LiteralPath $stagingNew -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Log "copy source -> stagingNew=$stagingNew"
    New-Item -ItemType Directory -Force -Path $stagingNew | Out-Null
    & robocopy $srcFull $stagingNew /E /COPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        Write-Log "robocopy failed rc=$rc"
        if (Test-Path -LiteralPath $stagingNew) {
            Remove-Item -LiteralPath $stagingNew -Recurse -Force -ErrorAction SilentlyContinue
        }
        exit 6
    }
    $newExe = Join-Path $stagingNew "MusicEditing.exe"
    if (-not (Test-Path -LiteralPath $newExe)) {
        Write-Log "stagingNew missing MusicEditing.exe"
        Remove-Item -LiteralPath $stagingNew -Recurse -Force -ErrorAction SilentlyContinue
        exit 6
    }

    Write-Log "rename install -> bak=$bak"
    Rename-Item -LiteralPath $dstFull -NewName (Split-Path -Leaf $bak)
    $renamedToBak = $true

    # 回归钩子：强制 bak 回滚路径（生产勿设）
    if ($env:MUSIC_OTA_TEST_FAIL_AFTER_BAK -eq "1") {
        Write-Log "test hook MUSIC_OTA_TEST_FAIL_AFTER_BAK -> rollback"
        throw "MUSIC_OTA_TEST_FAIL_AFTER_BAK"
    }

    try {
        Write-Log "rename stagingNew -> install"
        Rename-Item -LiteralPath $stagingNew -NewName $name
    } catch {
        Write-Log "rename stagingNew failed: $_ ; rollback bak"
        if ($renamedToBak -and (Test-Path -LiteralPath $bak) -and -not (Test-Path -LiteralPath $dstFull)) {
            Rename-Item -LiteralPath $bak -NewName $name
            $renamedToBak = $false
            Write-Log "rollback ok"
        }
        if (Test-Path -LiteralPath $stagingNew) {
            Remove-Item -LiteralPath $stagingNew -Recurse -Force -ErrorAction SilentlyContinue
        }
        exit 8
    }

    try {
        Remove-Item -LiteralPath $bak -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "removed bak"
    } catch {
        Write-Log "keep bak: $_"
    }

    Remove-Item -LiteralPath $PendingPath -Force -ErrorAction SilentlyContinue
    $relaunchFinal = Join-Path $dstFull "MusicEditing.exe"
    if (-not (Test-Path -LiteralPath $relaunchFinal)) {
        $relaunchFinal = $relaunch
    }
    Write-Log "relaunch $relaunchFinal"
    if (Test-Path -LiteralPath $relaunchFinal) {
        Start-Process -FilePath $relaunchFinal -WorkingDirectory (Split-Path -Parent $relaunchFinal)
    } else {
        Write-Log "relaunch missing"
        exit 7
    }
    Write-Log "done version=$version"
    exit 0
}
catch {
    Write-Log "ERROR $_"
    if ($renamedToBak -and $bak -and $name -and (Test-Path -LiteralPath $bak)) {
        $restored = Join-Path $parent $name
        if (-not (Test-Path -LiteralPath $restored)) {
            try {
                Rename-Item -LiteralPath $bak -NewName $name
                Write-Log "emergency rollback ok"
            } catch {
                Write-Log "emergency rollback failed: $_"
            }
        }
    }
    exit 1
}

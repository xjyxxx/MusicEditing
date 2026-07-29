param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$OutDir
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir "_exiftool_win64.zip"
$name = "exiftool-${Version}_64.zip"
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
$urls = @(
    "https://oliverbetz.de/cms/files/Artikel/ExifTool-for-Windows/$name",
    "https://downloads.sourceforge.net/project/exiftool/$name",
    "https://sourceforge.net/projects/exiftool/files/$name/download"
)

function Download-File([string]$Url, [string]$Dest) {
    if (Test-Path $Dest) { Remove-Item -Force $Dest }
    # Prefer IWR: Oliver Betz rejects bare curl without browser UA / may return tiny HTML
    Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing -UserAgent $ua -TimeoutSec 600
}

$ok = $false
foreach ($u in $urls) {
    Write-Host "Downloading: $u"
    try {
        Download-File $u $zip
        if ((Test-Path $zip) -and ((Get-Item $zip).Length -gt 1000000)) {
            $ok = $true
            break
        }
        Write-Host "  incomplete file ($((Get-Item $zip -ErrorAction SilentlyContinue).Length) bytes)"
    } catch {
        Write-Host "  failed: $($_.Exception.Message)"
    }
}
if (-not $ok) {
    throw "download failed for $name"
}

Write-Host ("Downloaded {0:N0} bytes" -f (Get-Item $zip).Length)

$tmp = Join-Path $OutDir "_extract"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Path $tmp | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force

$exe = Get-ChildItem -Path $tmp -Recurse -Filter "exiftool(-k).exe" | Select-Object -First 1
if (-not $exe) {
    $exe = Get-ChildItem -Path $tmp -Recurse -Filter "exiftool.exe" | Select-Object -First 1
}
if (-not $exe) {
    throw "exiftool(-k).exe not found in zip"
}

$files = Join-Path $exe.Directory.FullName "exiftool_files"
if (-not (Test-Path $files)) {
    throw "exiftool_files missing next to exe"
}

Copy-Item -LiteralPath $exe.FullName -Destination (Join-Path $OutDir "exiftool.exe") -Force
$destFiles = Join-Path $OutDir "exiftool_files"
if (Test-Path $destFiles) { Remove-Item -Recurse -Force $destFiles }
Copy-Item -LiteralPath $files -Destination $destFiles -Recurse -Force

Remove-Item -Recurse -Force $tmp
Remove-Item -Force $zip -ErrorAction SilentlyContinue
Write-Host "[done] exiftool.exe + exiftool_files"

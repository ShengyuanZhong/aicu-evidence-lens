param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) { $Python = $venvPython }

Push-Location $PSScriptRoot
try {
    $root = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    $version = (& $Python -c 'from aicu import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') {
        throw '无法读取有效的应用版本号'
    }
    $stage = Join-Path $root ('dist\staging\' + [guid]::NewGuid().ToString('N'))
    $archive = Join-Path $root "dist\AicuEvidenceLens-v$version-windows-x64.zip"
    foreach ($candidate in @((Join-Path $root 'build\AicuEvidenceLens'), (Join-Path $stage 'AicuEvidenceLens'), $archive)) {
        $target = [System.IO.Path]::GetFullPath($candidate)
        if (-not $target.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "构建目录超出项目工作区: $target"
        }
    }
    & $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
        --distpath $stage `
        --name AicuEvidenceLens `
        --add-data "aicu/assets:aicu/assets" `
        --add-data "examples/demo.json:examples" `
        launcher.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（退出码 $LASTEXITCODE）" }
    Compress-Archive -LiteralPath (Join-Path $stage 'AicuEvidenceLens') -DestinationPath $archive -Force
    Write-Host "已生成: $archive"
}
finally {
    Pop-Location
}

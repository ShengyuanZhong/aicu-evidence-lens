param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) { $Python = $venvPython }

Push-Location $PSScriptRoot
try {
    $root = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    foreach ($relative in @('build\AicuEvidenceLens', 'dist\AicuEvidenceLens')) {
        $target = [System.IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not $target.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "构建目录超出项目工作区: $target"
        }
    }
    & $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
        --name AicuEvidenceLens `
        --add-data "aicu/assets:aicu/assets" `
        --add-data "examples/demo.json:examples" `
        launcher.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（退出码 $LASTEXITCODE）" }
    $archive = Join-Path $root 'dist\AicuEvidenceLens-windows-x64.zip'
    Compress-Archive -LiteralPath (Join-Path $root 'dist\AicuEvidenceLens') -DestinationPath $archive -Force
    Write-Host "已生成: $archive"
}
finally {
    Pop-Location
}

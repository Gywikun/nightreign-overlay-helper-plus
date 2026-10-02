$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Create .venv and install requirements-lock.txt before building.'
}
& $taskPython (Join-Path $PSScriptRoot 'build_windows.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed; see .work/build.log.' }

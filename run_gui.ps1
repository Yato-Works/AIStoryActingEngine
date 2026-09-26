$env:PATH = "C:\msys64\mingw64\bin;$env:PATH"
$repoRoot = $PSScriptRoot
$exe = Join-Path $repoRoot "desktop\build\aiae_desktop.exe"
$python = Join-Path $repoRoot "workers\python\.venv\Scripts\python.exe"
$worker = Join-Path $repoRoot "workers\python\engine\worker.py"

Start-Process $exe -ArgumentList @("--python", "`"$python`"", "--worker", "`"$worker`"") -WorkingDirectory $repoRoot

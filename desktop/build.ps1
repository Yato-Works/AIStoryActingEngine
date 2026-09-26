param(
    [string]$QtDir = "C:\msys64\mingw64",
    [string]$BuildDir = "build",
    [string]$Compiler = "C:\msys64\mingw64\bin\g++.exe"
)
# AIStoryActingEngine Desktop ビルドスクリプト
# 前提: msys2 pacman で Qt6 base/declarative/quickcontrols2 を導入済み
#   pacman -S --needed mingw-w64-x86_64-qt6-base mingw-w64-x86_64-qt6-declarative mingw-w64-x86_64-qt6-quickcontrols2
# または aqt で Qt 6.x mingw_64 を導入した場合は -QtDir で指定。
# msys2 mingw64 g++ / CMake / Ninja が必要。

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Test-Path (Join-Path $QtDir "lib\cmake\Qt6\Qt6Config.cmake"))) {
    Write-Error "Qt が見つかりません: $QtDir (lib\cmake\Qt6\Qt6Config.cmake がありません)"
}

$mingwBin = Split-Path -Parent $Compiler
$env:PATH = "$mingwBin;$(Join-Path $QtDir 'bin');" + $env:PATH

$build = Join-Path $root $BuildDir
$cc  = Join-Path $mingwBin "gcc.exe"
& cmake -S $root -B $build -G Ninja `
    "-DCMAKE_PREFIX_PATH=$QtDir" `
    "-DCMAKE_BUILD_TYPE=Release" `
    "-DCMAKE_C_COMPILER=$cc" `
    "-DCMAKE_CXX_COMPILER=$Compiler"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

cmake --build $build -j 2
exit $LASTEXITCODE
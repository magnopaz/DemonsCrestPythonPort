#!/usr/bin/env pwsh
# Build Demon's Crest - Fan Game on Windows (MinGW) against a local raylib.
#
# The default CMake path downloads raylib 5.5 with FetchContent, which needs
# network access and a working jobserver. This script instead points CMake at
# the raylib install that ships with the raylib Windows installer.
#
# Usage (from the repository root):
#   pwsh -File tools/build_windows.ps1
#   pwsh -File tools/build_windows.ps1 -RaylibRoot C:\raylib\raylib -Run
#   pwsh -File tools/build_windows.ps1 -Jobs 8           # Ninja only
#
# CMake is invoked in serial mode by default because some Windows shells
# restrict the named pipe that make/ninja jobservers use.

[CmdletBinding()]
param(
    [string]$RaylibRoot = "C:\raylib\raylib",
    [string]$BuildDir = "build",
    [ValidateSet("Release", "Debug", "RelWithDebInfo")]
    [string]$Config = "Release",
    [int]$Jobs = 1,
    [switch]$Run,
    [string]$Assets = "assets/generated"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $Root
try {
    if (-not (Test-Path (Join-Path $RaylibRoot "src\raylib.h"))) {
        throw "raylib not found at $RaylibRoot (expected src\raylib.h)"
    }
    $lib = Get-ChildItem -Path (Join-Path $RaylibRoot "src"), (Join-Path $RaylibRoot "lib") `
        -Filter "libraylib*.a" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $lib) {
        throw "no libraylib.a under $RaylibRoot; build raylib first"
    }

    $generator = "MinGW Makefiles"
    if (Get-Command ninja -ErrorAction SilentlyContinue) {
        # Ninja is preferred when a parallel build is requested; it is also
        # the generator used by the Linux instructions.
        $generator = "Ninja"
    }
    if ($Jobs -gt 1 -and $generator -ne "Ninja") {
        Write-Warning "parallel build needs Ninja; building serially"
        $Jobs = 1
    }

    $cmakeArgs = @(
        "-S", ".", "-B", $BuildDir,
        "-G", $generator,
        "-DCMAKE_BUILD_TYPE=$Config",
        "-DDC_RAYLIB_ROOT=$RaylibRoot"
    )
    if ($generator -eq "MinGW Makefiles" -and -not (Get-Command mingw32-make -ErrorAction SilentlyContinue)) {
        throw "MinGW Makefiles selected but mingw32-make is not on PATH"
    }
    Write-Host "configure: $generator ($Config)"
    & cmake @cmakeArgs
    if ($LASTEXITCODE -ne 0) { throw "cmake configure failed" }

    if ($Jobs -gt 1) {
        & cmake --build $BuildDir --config $Config --parallel $Jobs
    } else {
        & cmake --build $BuildDir --config $Config
    }
    if ($LASTEXITCODE -ne 0) { throw "cmake build failed" }

    $exe = Get-ChildItem -Path $BuildDir -Recurse -Filter "demonscrest.exe" |
        Select-Object -First 1
    if (-not $exe) { throw "build finished but demonscrest.exe was not found" }
    Write-Host "built: $($exe.FullName)"

    if ($Run) {
        if (-not (Test-Path (Join-Path $Root $Assets))) {
            throw "assets missing: run tools/dc_extract/extract.py first"
        }
        & $exe.FullName --assets (Join-Path $Root $Assets)
    }
}
finally {
    Pop-Location
}

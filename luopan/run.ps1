$ErrorActionPreference = 'Stop'
$CommandArgs = @($args)
$skillRoot = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path)).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$scriptsRoot = Join-Path $skillRoot 'scripts'
$runtimeRoot = if ($env:LUOPAN_RUNTIME_ROOT) { $env:LUOPAN_RUNTIME_ROOT } else { Join-Path $env:LOCALAPPDATA 'Luopan\runtime' }
$python = Join-Path $runtimeRoot 'Scripts\python.exe'
$stateFile = Join-Path $runtimeRoot 'luopan-runtime.json'
$requirements = Join-Path $skillRoot 'requirements-runtime.txt'
$bootstrapHint = 'powershell -ExecutionPolicy Bypass -File "{0}\bootstrap-runtime.ps1"' -f $skillRoot

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Luopan runtime is not initialized. Run: $bootstrapHint"
}
if (-not (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
    throw "Luopan runtime state is missing. Run: $bootstrapHint"
}
try {
    $state = Get-Content -Raw -Encoding UTF8 -LiteralPath $stateFile | ConvertFrom-Json
    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    if ($state.requirements_sha256 -ne $requirementsHash) {
        throw 'runtime requirements do not match this Skill release'
    }
} catch {
    throw "Luopan runtime state is invalid or stale. Run: $bootstrapHint"
}
if (-not $CommandArgs -or -not $CommandArgs[0]) {
    throw 'Usage: .\run.cmd <bundled-script.py> [arguments]'
}

$scriptArg = $CommandArgs[0]
$scriptPath = if ([IO.Path]::IsPathRooted($scriptArg)) {
    throw 'run.ps1 only executes Python scripts bundled in this Skill.'
} elseif ($scriptArg -match '[\\/]') {
    Join-Path $skillRoot $scriptArg
} else {
    Join-Path $scriptsRoot $scriptArg
}
$scriptPath = [IO.Path]::GetFullPath($scriptPath)
$scriptsPrefix = $scriptsRoot + [IO.Path]::DirectorySeparatorChar
if (-not $scriptPath.StartsWith($scriptsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'run.ps1 rejected a script path outside the bundled scripts directory.'
}
if ([IO.Path]::GetExtension($scriptPath) -ne '.py') {
    throw 'run.ps1 only executes bundled .py files.'
}
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Luopan script not found: $scriptPath"
}

$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
try {
    & $python -c "import sys, yaml, jsonschema, markdown; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)" 2>$null
} catch {
    throw "Luopan runtime is damaged. Re-run: $bootstrapHint"
}
if ($LASTEXITCODE -ne 0) {
    throw "Luopan runtime is damaged or uses Python older than 3.10. Re-run: $bootstrapHint"
}

$remainingArgs = @($CommandArgs | Select-Object -Skip 1)
& $python $scriptPath @remainingArgs
exit $LASTEXITCODE

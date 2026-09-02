param(
    [string]$RuntimeRoot,
    [string]$PythonVersion = '3.13',
    [string]$UvPath,
    [string]$Wheelhouse,
    [switch]$Offline
)

if (-not $RuntimeRoot) {
    $RuntimeRoot = if ($env:LUOPAN_RUNTIME_ROOT) { $env:LUOPAN_RUNTIME_ROOT } else { Join-Path $env:LOCALAPPDATA 'Luopan\runtime' }
}

$ErrorActionPreference = 'Stop'
# PowerShell 7.3+ 中若此开关为 $true，原生命令的 stderr 会被提升为错误记录，
# 与 EAP=Stop 叠加会把"预期失败 → 回退下载"的流程打断在 stderr 噪音上。
# 本脚本显式检查 $LASTEXITCODE，故在此关闭该提升（PS 5.1 下仅为无害变量）。
$PSNativeCommandUseErrorActionPreference = $false
$skillRoot = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path)).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$defaultRuntimeRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Luopan\runtime')).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$requirements = Join-Path $skillRoot 'requirements-runtime.txt'
$runtimePython = Join-Path $RuntimeRoot 'Scripts\python.exe'
$stateFile = Join-Path $RuntimeRoot 'luopan-runtime.json'
$uvCache = Join-Path (Split-Path -Parent $RuntimeRoot) 'uv-cache'

function Resolve-Uv {
    param([string]$RequestedPath)
    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "uv executable not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }
    $command = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in @(
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'uv\bin\uv.exe')
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw 'uv is required to bootstrap Luopan. Install uv from https://docs.astral.sh/uv/ or pass -UvPath.'
}

function Test-RuntimeInterpreter {
    if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
        return $false
    }
    try {
        $supported = & $runtimePython -c "import sys; print('true' if sys.version_info >= (3, 10) else 'false')" 2>$null
        return $LASTEXITCODE -eq 0 -and $supported -eq 'true'
    } catch {
        return $false
    }
}

function Test-RuntimeReady {
    param([string]$ExpectedRequirementsHash)
    if (-not (Test-RuntimeInterpreter) -or -not (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
        return $false
    }
    try {
        $state = Get-Content -Raw -Encoding UTF8 -LiteralPath $stateFile | ConvertFrom-Json
        if ($state.requirements_sha256 -ne $ExpectedRequirementsHash) {
            return $false
        }
        & $runtimePython -c "import sys, yaml, jsonschema, markdown; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "Runtime requirements file is missing: $requirements"
}

$skillPrefix = $skillRoot + [IO.Path]::DirectorySeparatorChar
if (
    $RuntimeRoot.Equals($skillRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $RuntimeRoot.StartsWith($skillPrefix, [StringComparison]::OrdinalIgnoreCase)
) {
    throw 'RuntimeRoot must be outside the skill directory so upgrades cannot delete the environment.'
}
$runtimeParent = Split-Path -Parent $RuntimeRoot
if (-not (Test-Path -LiteralPath $runtimeParent)) {
    New-Item -ItemType Directory -Path $runtimeParent -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $uvCache)) {
    New-Item -ItemType Directory -Path $uvCache -Force | Out-Null
}
$env:UV_CACHE_DIR = $uvCache
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$mutex = New-Object System.Threading.Mutex($false, 'Local\LuopanRuntimeBootstrap-v1')
$mutexAcquired = $false
try {
    try {
        $mutexAcquired = $mutex.WaitOne([TimeSpan]::FromMinutes(5))
    } catch [Threading.AbandonedMutexException] {
        $mutexAcquired = $true
    }
    if (-not $mutexAcquired) {
        throw 'Timed out waiting for another Luopan runtime initialization to finish.'
    }

$requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash

if (Test-RuntimeReady $requirementsHash) {
    Write-Output "Luopan runtime already ready: $runtimePython"
    return
}

$uv = Resolve-Uv $UvPath
$runtimeExists = Test-Path -LiteralPath $RuntimeRoot -PathType Container
$runtimeHasFiles = $runtimeExists -and $null -ne (Get-ChildItem -Force -LiteralPath $RuntimeRoot | Select-Object -First 1)
$runtimeMarked = Test-Path -LiteralPath $stateFile -PathType Leaf
$runtimeIsDefault = $RuntimeRoot.Equals($defaultRuntimeRoot, [StringComparison]::OrdinalIgnoreCase)
$needsVenv = -not (Test-RuntimeInterpreter)

if ($needsVenv) {
    $canClear = $runtimeMarked -or $runtimeIsDefault
    if ($runtimeHasFiles -and -not $canClear) {
        throw "Refusing to clear an unmarked non-default directory: $RuntimeRoot. Choose an empty -RuntimeRoot or move the existing directory first."
    }

    $findArgs = @('--no-config')
    if ($Offline) {
        $findArgs += '--offline'
    }
    $findArgs += @('python', 'find', '--no-project', '--managed-python', '--no-python-downloads', $PythonVersion)
    # PS 5.1 下 EAP=Stop 会把原生命令 stderr 在重定向前转成终止错误；预期失败的原生命令
    # 周围临时降为 Continue，显式依赖 $LASTEXITCODE 判断（成功路径与失败回退都走显式检查）。
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $basePython = (& $uv @findArgs 2>$null | Select-Object -Last 1)
    $ErrorActionPreference = $prevEAP
    if ($LASTEXITCODE -ne 0 -or -not $basePython) {
        if ($Offline) {
            throw "Python $PythonVersion is not available locally and -Offline forbids downloading it."
        }
        Write-Host "Python $PythonVersion is not installed in uv; downloading it now."
        $ErrorActionPreference = 'Continue'
        & $uv --no-config python install $PythonVersion
        $installExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($installExit -ne 0) {
            throw "uv could not install Python $PythonVersion"
        }
        $ErrorActionPreference = 'Continue'
        $basePython = (& $uv --no-config python find --no-project --managed-python --no-python-downloads $PythonVersion | Select-Object -Last 1)
        $ErrorActionPreference = $prevEAP
    }

    $venvArgs = @('--no-config', 'venv', '--no-project', '--python', ([string]$basePython).Trim())
    if ($runtimeHasFiles) {
        $venvArgs += '--clear'
    }
    $venvArgs += $RuntimeRoot
    & $uv @venvArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'uv could not create the Luopan runtime.'
    }
}

if (-not (Test-RuntimeInterpreter)) {
    throw 'Luopan requires a working Python 3.10 or newer runtime.'
}

$installArgs = @('--no-config')
if ($Offline) {
    $installArgs += '--offline'
}
$installArgs += @(
    'pip', 'install',
    '--python', $runtimePython,
    '--requirement', $requirements,
    '--strict',
    '--only-binary', ':all:'
)
if ($Wheelhouse) {
    if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
        throw "Wheelhouse does not exist: $Wheelhouse"
    }
    $installArgs += @('--no-index', '--find-links', (Resolve-Path -LiteralPath $Wheelhouse).Path)
}
& $uv @installArgs
if ($LASTEXITCODE -ne 0) {
    if ($Offline) {
        throw 'Luopan offline initialization failed because the uv cache or wheelhouse is incomplete.'
    }
    throw 'Luopan runtime dependency installation failed.'
}

& $runtimePython (Join-Path $skillRoot 'scripts\runtime_smoke.py')
if ($LASTEXITCODE -ne 0) {
    throw 'Luopan runtime strict validation smoke test failed.'
}

$state = [ordered]@{
    runtime_root = $RuntimeRoot
    python = $runtimePython
    python_version = (& $runtimePython -c 'import platform; print(platform.python_version())')
    requirements_sha256 = $requirementsHash
    uv = $uv
    updated_at = (Get-Date).ToString('o')
}
$state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
Write-Output "Luopan runtime ready: $runtimePython"
} finally {
    if ($mutexAcquired) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}

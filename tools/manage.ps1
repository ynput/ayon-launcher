<#
.SYNOPSIS
  Helper script create virtual environment using Poetry.

.DESCRIPTION
  This script will detect Python installation, create venv with Poetry
  and install all necessary packages from `poetry.lock` or `pyproject.toml`
  needed by AYON launcher to be included during application freeze on Windows.

.EXAMPLE

PS> .\manage.ps1

.EXAMPLE

Print verbose information from Poetry:
PS> .\manage.ps1 create-env --verbose

#>

$FunctionName=$ARGS[0]
$arguments=@()
if ($ARGS.Length -gt 1) {
    $arguments = $ARGS[1..($ARGS.Length - 1)]
}
$disable_submodule_update=""

if($arguments -eq "--no-submodule-update") {
    $disable_submodule_update=$true
}

$current_dir = Get-Location
$script_dir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$repo_root = (Get-Item $script_dir).parent.FullName
$app_logo = "$repo_root/common/ayon_common/resources/AYON.png"

& git submodule update --init --recursive
# Install PSWriteColor to support colorized output to terminal
$env:PSModulePath = $env:PSModulePath + ";$($repo_root)\tools\modules\powershell"

$art = @"

                    ▄██▄
         ▄███▄ ▀██▄ ▀██▀ ▄██▀ ▄██▀▀▀██▄    ▀███▄      █▄
        ▄▄ ▀██▄  ▀██▄  ▄██▀ ██▀      ▀██▄  ▄  ▀██▄    ███
       ▄██▀  ██▄   ▀ ▄▄ ▀  ██         ▄██  ███  ▀██▄  ███
      ▄██▀    ▀██▄   ██    ▀██▄      ▄██▀  ███    ▀██ ▀█▀
     ▄██▀      ▀██▄  ▀█      ▀██▄▄▄▄██▀    █▀      ▀██▄

     ·  · - =[ by YNPUT ]:[ http://ayon.ynput.io ]= - ·  ·

"@

function Write-AsciiArt() {
    Write-Host $art -ForegroundColor DarkGreen
}

function Set-Cwd() {
    Set-Location -Path $repo_root
}

function Set-ShimCwd() {
    Set-Location -Path "$($repo_root)\shim"
}

function Restore-Cwd() {
    $tmp_current_dir = Get-Location
    if ("$tmp_current_dir" -ne "$current_dir") {
        Write-Color -Text ">>> ", "Restoring current directory" -Color Green, Gray
        Set-Location -Path $current_dir
    }
}

function Exit-WithCode($exitcode) {
   # Only exit this host process if it's a child of another PowerShell parent process...
   $parentPID = (Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$PID" | Select-Object -Property ParentProcessId).ParentProcessId
   $parentProcName = (Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$parentPID" | Select-Object -Property Name).Name
   if ('powershell.exe' -eq $parentProcName) { $host.SetShouldExit($exitcode) }

   exit $exitcode
}

function Show-PSWarning() {
    if ($PSVersionTable.PSVersion.Major -lt 7) {
        Write-Color -Text "!!! ", "You are using old version of PowerShell - ",  "$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)" -Color Red, Yellow, White
        Write-Color -Text "    Please update to at least 7.0 - ", "https://github.com/PowerShell/PowerShell/releases" -Color Yellow, White
        Exit-WithCode 1
    }
}

function Get-AyonVersion() {
    $ayon_version = Invoke-Expression -Command "python -c ""import os;import sys;content={};f=open(r'$($repo_root)\version.py');exec(f.read(),content);f.close();print(content['__version__'])"""
    if (-not $ayon_version) {
      Write-Color -Text "!!! ", "Cannot determine AYON version." -Color Yellow, Gray
      return $null
    }
    return $ayon_version
}

function Install-Uv() {
    Write-Color -Text ">>> ", "Installing uv ... " -Color Green, Gray
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
}

function Test-Python() {
    Write-Color -Text ">>> ", "Detecting host Python ... " -Color Green, Gray -NoNewline
    $python = "python"
    if (Get-Command "pyenv" -ErrorAction SilentlyContinue) {
        $pyenv_python = & pyenv which python
        if (Test-Path -PathType Leaf -Path "$($pyenv_python)") {
            $python = $pyenv_python
        }
    }
    if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
        Write-Host "!!! Python not detected" -ForegroundColor red
        Restore-Cwd
        Exit-WithCode 1
    }
    $version_command = @'
import sys
print('{0}.{1}'.format(sys.version_info[0], sys.version_info[1]))
'@

    $p = & $python -c $version_command
    $env:PYTHON_VERSION = $p
    $m = $p -match '(\d+)\.(\d+)'
    if(-not $m) {
      Write-Host "!!! Cannot determine version" -ForegroundColor red
      Restore-Cwd
      Exit-WithCode 1
    }
    # We are supporting python 3.9 only
    if (([int]$matches[1] -lt 3) -or ([int]$matches[2] -lt 9)) {
      Write-Color -Text "FAILED ", "Version ", "[ ", $p ," ]",  " is old and unsupported" -Color Red, Yellow, Cyan, White, Cyan, Yellow
      Restore-Cwd
      Exit-WithCode 1
    } elseif (([int]$matches[1] -eq 3) -and ([int]$matches[2] -gt 9)) {
        Write-Color -Text "WARNING Version ", "[ ",  $p, " ]",  " is unsupported, use at your own risk." -Color Yellow, Cyan, White, Cyan, Yellow
        Write-Color -Text "*** ", "AYON launcher supports only Python 3.11" -Color Yellow, White
    } else {
        Write-Color "OK ", "[ ",  $p, " ]" -Color Green, Cyan, White, Cyan
    }
}

function Get-Container($build_dir) {
    if (-not (Test-Path -PathType Leaf -Path "$($build_dir)\docker-image.id")) {
        Write-Color -Text "!!! ", "Docker command failed, cannot find image id." -Color Red, Yellow
        Restore-Cwd
        Exit-WithCode 1
    }
    $id = Get-Content "$($build_dir)\docker-image.id"
    Write-Color -Text ">>> ", "Creating container from image id ", "[", $id, "]" -Color Green, Gray, White, Cyan, White
    $cid = docker create $id bash
    if ($LASTEXITCODE -ne 0) {
        Write-Color -Text "!!! ", "Cannot create container." -Color Red, Yellow
        Restore-Cwd
        Exit-WithCode 1
    }
    return $cid
}

function Get-BuildLog($build_dir) {
    $cid = Get-Container($build_dir)
    Write-Color -Text ">>> ", "Copying build log to", "$($build_dir)\build.log" -Color Green, Gray, White
    docker cp "$($cid):/opt/ayon-launcher/build/build.log" "$($build_dir)\build.log"
    if ($LASTEXITCODE -ne 0) {
        Write-Color -Text "!!! ", "Cannot copy log from container." -Color Red, Yellow
        Restore-Cwd
        Exit-WithCode 1
    }
}

function New-DockerBuild {
    Set-Cwd
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))
    Write-Color -Text ">>> ", "Building AYON using Docker ..." -Color Green, Gray, White
    $variant = $args[0]
    if ($null -eq $variant) {
        $variant = "ubuntu"
    }
    if ($variant -eq "ubuntu") {
        $dockerfile = "$($repo_root)\Dockerfile"
    } else {
        $dockerfile = "$($repo_root)\Dockerfile.$variant"
    }

    if (-not (Test-Path -PathType Leaf -Path $dockerfile)) {
        Write-Color -Text "!!! ", "Dockerfile for specifed platform ", "[", $variant, "]", "doesn't exist." -Color Red, Yellow, Cyan, White, Cyan, Yellow
        Restore-Cwd
        Exit-WithCode 1
    }

    Write-Color -Text ">>> ", "Using Dockerfile for ", "[ ", $variant, " ]" -Color Green, Gray, White, Cyan, White
    Write-Color -Text "--- ", "Cleaning build directory ..." -Color Yellow, Gray

    $build_dir = "$($repo_root)\build_$($variant)"
    $qtbindingValue = ""
    if ($arguments -contains "--use-pyside2") {
        $qtbindingValue = "pyside2"
        $build_dir = "$($build_dir)_pyside2"
    }

    if (Test-Path $build_dir) {
        try {
            Remove-Item -Recurse -Force "$($build_dir)\*"
        }
        catch {
            Write-Color -Text "!!! ", "Cannot clean build directory, possibly because process is using it." -Color Red, Gray
            Write-Color -Text $_.Exception.Message -Color Red
            Exit-WithCode 1
        }
    } else {
        New-Item -ItemType Directory -Path $build_dir
    }

    Write-Color -Text ">>> ", "Running Docker build ..." -Color Green, Gray, White

    docker build --pull --iidfile $build_dir/docker-image.id --build-arg CUSTOM_QT_BINDING=$($qtbindingValue) --build-arg BUILD_DATE=$(Get-Date -UFormat %Y-%m-%dT%H:%M:%SZ) --build-arg VERSION=$(Get-AyonVersion) -t ynput/ayon-launcher:$(Get-AyonVersion) -f $dockerfile .
    if ($LASTEXITCODE -ne 0) {
        Write-Color -Text "!!! ", "Docker command failed.", $LASTEXITCODE -Color Red, Yellow, Red
        Restore-Cwd
        Exit-WithCode 1
    }
    Write-Color -Text ">>> ", "Copying build from container ..." -Color Green, Gray, White
    $cid = Get-Container($build_dir)

    docker cp "$($cid):/opt/ayon-launcher/build/output" $build_dir
    docker cp "$($cid):/opt/ayon-launcher/build/build.log" $build_dir
    docker cp "$($cid):/opt/ayon-launcher/build/metadata.json" $build_dir
    docker cp "$($cid):/opt/ayon-launcher/build/installer" $build_dir

    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON build complete!", "All done in $( $endTime - $startTime ) secs. You will find AYON and build log in build directory."
    } catch {}
    Write-Color -Text "*** ", "All done in ", $($endTime - $startTime), " secs. You will find AYON and build log in ", "'.\build'", " directory." -Color Green, Gray, White, Gray, White, Gray
}

function Write-DefaultFunc {
    $ayon_version = Get-AyonVersion
    Write-Host ""
    Write-Host "Ayon desktop application tool"
    Write-Color -Text "    version ", "$($ayon_version)" -Color White, Cyan
    Write-Host ""
    Write-Color -Text "Usage: ", "./manage.ps1 ", "[target]" -Color Gray, White, Cyan
    Write-Host ""
    Write-Host "Runtime targets:"
    Write-Color -text "  create-env                    ", "Install Poetry and update venv by lock file" -Color White, Cyan
    Write-Color -text "  install-runtime-dependencies  ", "Install runtime dependencies (Qt binding)" -Color White, Cyan
    Write-Color -text "      --use-pyside2                 Install ", "PySide2", " instead of ", "PySide6", "." -Color White, Cyan, White, Cyan, White
    Write-Color -text "  install-runtime               ", "Alias for '", "install-runtime-dependencies", "'" -Color White, Cyan, White, Cyan
    Write-Color -text "  build                         ", "Build desktop application" -Color White, Cyan
    Write-Color -text "  make-installer                ", "Make desktop application installer" -Color White, Cyan
    Write-Color -text "  build-make-installer          ", "Build desktop application and make installer" -Color White, Cyan
    Write-Color -text "  upload                        ", "Upload installer to server" -Color White, Cyan
    Write-Color -text "  run                           ", "Run desktop application from code" -Color White, Cyan
    Write-Color -text "  docker-build ","[variant]        ", "Build AYON using Docker. Variant can be '", "ubuntu", "', '", "debian", "', '", "rocky8", "' or '", "rocky9", "'" -Color White, Yellow, Cyan, Yellow, Cyan, Yellow, Cyan, Yellow, Cyan, Yellow, Cyan
    Write-Color -text "      --use-pyside2                 Use ", "PySide2", " instead of ", "PySide6", "." -Color White, Cyan, White, Cyan, White
    Write-Host ""
}

function New-UvEnv {
    Set-Cwd
    Write-Color -Text ">>> ", "Test if UV is installed ... " -Color Green, Gray -NoNewline
    if (Get-Command "uv" -ErrorAction SilentlyContinue)
    {
        Write-Color -Text "OK" -Color Green
    } else {
        if (Test-Path -PathType Leaf -Path "$($USERPROFILE)/.cargo/bin/uv") {
            $env:PATH += ";$($env:USERPROFILE)/.cargo/bin"
            Write-Color -Text "OK" -Color Green
        } else {
            Write-Color -Text "NOT FOUND" -Color Yellow
            Install-Uv
            Write-Color -Text "INSTALLED" -Color Cyan
        }
    }
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))

    # note that uv venv can use .python-version marker file to determine what python version to use
    # so you can safely use pyenv to manage python versions
    Write-Color -Text ">>> ", "Creating and activating venv ... " -Color Green, Gray
    & uv venv --allow-existing .venv
    # Do we need this? Maybe we can just do uv sync --all-extras
    # Write-Color -Text ">>> ", "Compiling dependencies ... " -Color Green, Gray
    # & uv pip compile pyproject.toml -o requirements.txt --no-strip-extras
    # Write-Color -Text ">>> ", "Installing dependencies ... " -Color Green, Gray
    # & uv pip install -r requirements.txt
    & uv sync --all-extras

    Install-PrecommitHook
    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    Restore-Cwd
    try
    {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON", "Virtual environment created.", "All done in $( $endTime - $startTime ) secs."
    } catch {}
    Write-Color -Text ">>> ", "Virtual environment created." -Color Green, White
}

function Install-PrecommitHook {
    if (Test-Path -PathType Container -Path "$($repo_root)\.git") {
        Write-Color -Text ">>> ", "Installing pre-commit hooks ..." -Color Green, White
        & uv run pre-commit install
        if ($LASTEXITCODE -ne 0)
        {
            Write-Color -Text "!!! ", "Installation of pre-commit hooks failed." -Color Red, Yellow
        }
    }
}

function Invoke-AyonBuild($MakeInstaller = $false) {
    Set-Cwd
    $ayon_version = Get-AyonVersion
    if (-not $ayon_version) {
        Exit-WithCode 1
    }
    # Create build directory if not exist
    if (-not (Test-Path -PathType Container -Path "$($repo_root)\build")) {
        New-Item -ItemType Directory -Force -Path "$($repo_root)\build"
    }
    if (-not (Test-Path -PathType Container -Path "$($repo_root)\shim\dist")) {
        New-Item -ItemType Directory -Force -Path "$($repo_root)\shim\dist"
    }

    Write-Color -Text "--- ", "Cleaning build directory ..." -Color Yellow, Gray
    try {
        Remove-Item -Recurse -Force "$($repo_root)\build\*"
    }
    catch {
        Write-Color -Text "!!! ", "Cannot clean build directory, possibly because process is using it." -Color Red, Gray
        Write-Color -Text $_.Exception.Message -Color Red
        Exit-WithCode 1
    }
    try {
        Remove-Item -Recurse -Force "$($repo_root)\shim\dist\*"
    }
    catch {
        Write-Color -Text "!!! ", "Cannot clean shim directory, possibly because process is using it." -Color Red, Gray
        Write-Color -Text $_.Exception.Message -Color Red
        Exit-WithCode 1
    }

    if (-not $disable_submodule_update) {
        Write-Color -Text ">>> ", "Making sure submodules are up-to-date ..." -Color Green, Gray
        & git submodule update --init --recursive
    } else {
        Write-Color -Text "*** ", "Not updating submodules ..." -Color Green, Gray
    }
    $ayon_version = Get-AyonVersion
    Write-Color -Text ">>> ", "AYON [ ", $ayon_version, " ]" -Color Green, White, Cyan, White

    Write-Color -Text ">>> ", "Testing venv presence ... " -Color Green, Gray -NoNewline
    if (-not (Test-Path -PathType Container -Path "$($repo_root)\bin")) {
        Write-Color -Text "NOT FOUND" -Color Yellow
        Write-Color -Text "*** ", "We need to create virtual env first ..." -Color Yellow, Gray
        New-UvEnv
    } else {
        Write-Color -Text "OK" -Color Green
    }

    Write-Color -Text ">>> ", "Cleaning cache files ... " -Color Green, Gray -NoNewline
    Get-ChildItem $repo_root -Filter "*.pyc" -Force -Recurse | Where-Object { $_.FullName -inotmatch 'build' } | Remove-Item -Force
    Get-ChildItem $repo_root -Filter "*.pyo" -Force -Recurse | Where-Object { $_.FullName -inotmatch 'build' } | Remove-Item -Force
    Get-ChildItem $repo_root -Filter "__pycache__" -Force -Recurse | Where-Object { $_.FullName -inotmatch 'build' } | Remove-Item -Force -Recurse
    Write-Color -Text "OK" -Color green

    $startTime = [int][double]::Parse((Get-Date -UFormat %s))

    Write-Color -Text ">>> ", "Building AYON shim ..." -Color Green, White
    Set-ShimCwd
    $out = & uv run python setup.py build 2>&1
    Set-Content -Path "$($repo_root)\shim\build.log" -Value $out
    if ($LASTEXITCODE -ne 0)
    {
        Write-Color -Text "------------------------------------------" -Color Red
        Get-Content "$($repo_root)\shim\build.log"
        Write-Color -Text "------------------------------------------" -Color Yellow
        Write-Color -Text "!!! ", "Build failed. Check the log: ", ".\shim\build.log" -Color Red, Yellow, White
        Exit-WithCode $LASTEXITCODE
    }

    Set-Cwd
    Write-Color -Text ">>> ", "Building AYON ..." -Color Green, White
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))

    $FreezeContent = & uv --no-color pip freeze
    & uv run python "$($repo_root)\tools\_venv_deps.py"
    # Make sure output is UTF-8 without BOM
    $Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding $False
    [System.IO.File]::WriteAllLines("$($repo_root)\build\requirements.txt", $FreezeContent, $Utf8NoBomEncoding)

    $out = & $repo_root\.venv\Scripts\python setup.py build 2>&1
    Set-Content -Path "$($repo_root)\build\build.log" -Value $out
    if ($LASTEXITCODE -ne 0)
    {
        Write-Color -Text "------------------------------------------" -Color Red
        Get-Content "$($repo_root)\build\build.log"
        Write-Color -Text "------------------------------------------" -Color Yellow
        Write-Color -Text "!!! ", "Build failed. Check the log: ", ".\build\build.log" -Color Red, Yellow, White
        Exit-WithCode $LASTEXITCODE
    }

    Set-Content -Path "$($repo_root)\build\build.log" -Value $out
    & uv run python "$($repo_root)\tools\build_post_process.py" "build"

    if ($MakeInstaller) {
        New-AyonInstallerRaw
    }

    Restore-Cwd

    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON build complete!", "All done in $( $endTime - $startTime ) secs. You will find AYON and build log in build directory."
    } catch {}
    Write-Color -Text "*** ", "All done in ", $($endTime - $startTime), " secs. You will find AYON and build log in ", "'.\build'", " directory." -Color Green, Gray, White, Gray, White, Gray
}

function Invoke-InstallerPostProcess() {
    & uv run python "$($repo_root)\tools\installer_post_process.py" @args
}

function New-AyonInstallerRaw() {
    Set-Content -Path "$($repo_root)\build\build.log" -Value $out
    & uv run python "$($repo_root)\tools\build_post_process.py" "make-installer"
}

function New-AyonInstaller() {
    Set-Cwd
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))

    Make-Ayon-Installer-Raw

    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON build complete!", "All done in $( $endTime - $startTime ) secs. You will find AYON and build log in build directory."
    } catch {}
    Write-Color -Text "*** ", "All done in ", $($endTime - $startTime), " secs. You will find AYON and build log in ", "'.\build'", " directory." -Color Green, Gray, White, Gray, White, Gray
}

function Install-RuntimeDependencies() {
    Write-Color -Text ">>> ", "Testing venv ... " -Color Green, Gray -NoNewline
    if (-not (Test-Path -PathType Container -Path "$repo_root\.venv")) {
        Write-Color -Text "NOT FOUND" -Color Yellow
        Write-Color -Text "*** ", "We need to  create virtual env first ..." -Color Yellow, Gray
        New-UvEnv
    } else {
        Write-Color -Text "OK" -Color Green
    }
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))
    & uv run python "$($repo_root)\tools\runtime_dependencies.py" @args
    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON", "Dependencies downloaded", "All done in $( $endTime - $startTime ) secs."
    } catch {}
}

function Start-FromCode() {
    Set-Cwd
    & uv run python "$($repo_root)\start.py" @arguments
}

function Main {
    if ($null -eq $FunctionName) {
        Write-DefaultFunc
        return
    }
    $FunctionName = $FunctionName.ToLower() -replace "\W"
    if ($FunctionName -eq "run") {
        Start-FromCode
    } elseif ($FunctionName -eq "createenv") {
        New-UvEnv
    } elseif (($FunctionName -eq "installruntimedependencies") -or ($FunctionName -eq "installruntime")) {
        Install-RuntimeDependencies @arguments
    } elseif ($FunctionName -eq "build") {
        Invoke-AyonBuild
    } elseif ($FunctionName -eq "makeinstaller") {
        Invoke-AyonInstaller
    } elseif ($FunctionName -eq "buildmakeinstaller") {
        Invoke-AyonBuild -MakeInstaller true
    } elseif ($FunctionName -eq "upload") {
        Invoke-InstallerPostProcess "upload" @arguments
    } elseif ($FunctionName -eq "dockerbuild") {
        New-DockerBuild @arguments
    } else {
        Write-Host "Unknown function ""$FunctionName"""
        Write-DefaultFunc
    }
}

# Enable if PS 7.x is needed.
# Show-PSWarning

Write-AsciiArt
Test-Python
try {
    Main
} finally {
    Restore-Cwd
}

<#
.SYNOPSIS
  Helper script create virtual environment using Poetry.

.DESCRIPTION
  This script will detect Python installation, create venv with Poetry
  and install all necessary packages from `poetry.lock` or `pyproject.toml`
  needed by OpenPype to be included during application freeze on Windows.

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
$poetry_verbosity=$null
$disable_submodule_update=""
if($arguments -eq "--verbose") {
    $poetry_verbosity="-vvv"
}
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


             . .   ..     .    ..
        _oOOP3OPP3Op_. .
     .PPpo~.   ..   ~2p.  ..  ....  .  .
    .Ppo . .pPO3Op.. . O:. . . .
   .3Pp . oP3'. 'P33. . 4 ..   .  .   . .. .  .  .
  .~OP    3PO.  .Op3    : . ..  _____  _____  _____
  .P3O  . oP3oP3O3P' . . .   . /    /./    /./    /
   O3:.   O3p~ .       .:. . ./____/./____/ /____/
   'P .   3p3.  oP3~. ..P:. .  . ..  .   . .. .  .  .
  . ':  . Po'  .Opo'. .3O. .  o[ by Pype Club ]]]==- - - .  .
    . '_ ..  .    . _OP3..  .  .https://openpype.io.. .
         ~P3.OPPPO3OP~ . ..  .
           .  ' '. .  .. . . . ..  .


"@

function Print-AsciiArt() {
    Write-Host $art -ForegroundColor DarkGreen
}

function Change-Cwd() {
    Set-Location -Path $repo_root
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

function Get-Ayon-Version() {
    $version_file = Get-Content -Path "$($repo_root)\version.py"
    $result = [regex]::Matches($version_file, '__version__ = "(?<version>\d+\.\d+.\d+.*)"')
    $ayon_version = $result[0].Groups['version'].Value
    if (-not $ayon_version) {
      Write-Color -Text "!!! ", "Cannot determine AYON version." -Color Yellow, Gray
      return $null
    }
    return $ayon_version
}

function Install-Poetry() {
    Write-Color -Text ">>> ", "Installing Poetry ... " -Color Green, Gray
    $python = "python"
    if (Get-Command "pyenv" -ErrorAction SilentlyContinue) {
        if (-not (Test-Path -PathType Leaf -Path "$($repo_root)\.python-version")) {
            $result = & pyenv global
            if ($result -eq "no global version configured") {
                Write-Color -Text "!!! ", "Using pyenv but having no local or global version of Python set." -Color Red, Yellow
                Exit-WithCode 1
            }
        }
        $python = & pyenv which python

    }

    $env:POETRY_HOME="$repo_root\.poetry"
    $env:POETRY_VERSION="1.3.2"
    (Invoke-WebRequest -Uri https://install.python-poetry.org/ -UseBasicParsing).Content | & $($python) -
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
      Write-Color -Text "FAILED ", "Version ", "[", $p ,"]",  "is old and unsupported" -Color Red, Yellow, Cyan, White, Cyan, Yellow
      Restore-Cwd
      Exit-WithCode 1
    } elseif (([int]$matches[1] -eq 3) -and ([int]$matches[2] -gt 9)) {
        Write-Color -Text "WARNING Version ", "[",  $p, "]",  " is unsupported, use at your own risk." -Color Yellow, Cyan, White, Cyan, Yellow
        Write-Color -Text "*** ", "OpenPype supports only Python 3.9" -Color Yellow, White
    } else {
        Write-Color "OK ", "[",  $p, "]" -Color Green, Cyan, White, Cyan
    }
}

function Default-Func {
    Write-Host ""
    Write-Host "Ayon desktop application tool"
    Write-Host ""
    Write-Host "Usage: ./manage.ps1 [target]"
    Write-Host ""
    Write-Host "Runtime targets:"
    Write-Host "  create-env                    Install Poetry and update venv by lock file"
    Write-Host "  install-runtime-dependencies  Install runtime dependencies (Qt binding)"
    Write-Host "  install-runtime               Alias for 'install-runtime-dependencies'"
    Write-Host "  build                         Build desktop application"
    Write-Host "  make-installer                Make desktop application installer"
    Write-Host "  build-make-installer          Build desktop application and make installer"
    Write-Host "  upload                        Upload installer to server"
    Write-Host "  run                           Run desktop application from code"
    Write-Host ""
}

function Create-Env {
    Write-Color -Text ">>> ", "Reading Poetry ... " -Color Green, Gray -NoNewline
    if (-not (Test-Path -PathType Container -Path "$($env:POETRY_HOME)\bin")) {
        Write-Color -Text "NOT FOUND" -Color Yellow
        Install-Poetry
        Write-Color -Text "INSTALLED" -Color Cyan
    } else {
        Write-Color -Text "OK" -Color Green
    }

    if (-not (Test-Path -PathType Leaf -Path "$($repo_root)\poetry.lock")) {
        Write-Color -Text ">>> ", "Installing virtual environment and creating lock." -Color Green, Gray
    } else {
        Write-Color -Text ">>> ", "Installing virtual environment from lock." -Color Green, Gray
    }
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))
    & "$env:POETRY_HOME\bin\poetry" config virtualenvs.in-project true --local
    & "$env:POETRY_HOME\bin\poetry" config virtualenvs.create true --local
    & "$env:POETRY_HOME\bin\poetry" install --no-root $poetry_verbosity --ansi
    if ($LASTEXITCODE -ne 0) {
        Write-Color -Text "!!! ", "Poetry command failed." -Color Red, Yellow
        Restore-Cwd
        Exit-WithCode 1
    }
    Write-Color -Text ">>> ", "Installing pre-commit hooks ..." -Color Green, White
    & "$env:POETRY_HOME\bin\poetry" run pre-commit install
    if ($LASTEXITCODE -ne 0) {
        Write-Color -Text "!!! ", "Installation of pre-commit hooks failed." -Color Red, Yellow
        Restore-Cwd
        Exit-WithCode 1
    }

    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    Restore-Cwd
    try
    {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON", "Virtual environment created.", "All done in $( $endTime - $startTime ) secs."
    } catch {}
    Write-Color -Text ">>> ", "Virtual environment created." -Color Green, White
}


function Build-Ayon($MakeInstaller = $false) {
    $ayon_version = Get-Ayon-Version
    if (-not $ayon_version) {
        Exit-WithCode 1
    }

    # Create build directory if not exist
    if (-not (Test-Path -PathType Container -Path "$($repo_root)\build")) {
        New-Item -ItemType Directory -Force -Path "$($repo_root)\build"
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
    if (-not $disable_submodule_update) {
        Write-Color -Text ">>> ", "Making sure submodules are up-to-date ..." -Color Green, Gray
        & git submodule update --init --recursive
    } else {
        Write-Color -Text "*** ", "Not updating submodules ..." -Color Green, Gray
    }

    Write-Color -Text ">>> ", "AYON [ ", $ayon_version, " ]" -Color Green, White, Cyan, White

    Write-Color -Text ">>> ", "Reading Poetry ... " -Color Green, Gray -NoNewline
    if (-not (Test-Path -PathType Container -Path "$($env:POETRY_HOME)\bin")) {
        Write-Color -Text "NOT FOUND" -Color Yellow
        Write-Color -Text "*** ", "We need to install Poetry create virtual env first ..." -Color Yellow, Gray
        Create-Env
    } else {
        Write-Color -Text "OK" -Color Green
    }

    Write-Color -Text ">>> ", "Cleaning cache files ... " -Color Green, Gray -NoNewline
    Get-ChildItem $repo_root -Filter "*.pyc" -Force -Recurse | Where-Object { $_.FullName -inotmatch 'build' } | Remove-Item -Force
    Get-ChildItem $repo_root -Filter "*.pyo" -Force -Recurse | Where-Object { $_.FullName -inotmatch 'build' } | Remove-Item -Force
    Get-ChildItem $repo_root -Filter "__pycache__" -Force -Recurse | Where-Object { $_.FullName -inotmatch 'build' } | Remove-Item -Force -Recurse
    Write-Color -Text "OK" -Color green

    Write-Color -Text ">>> ", "Building AYON ..." -Color Green, White
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))

    & "$($env:POETRY_HOME)\bin\poetry" run python -m pip freeze > "$($repo_root)\build\requirements.txt"
    $out = & "$($env:POETRY_HOME)\bin\poetry" run python setup.py build 2>&1
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
    & "$($env:POETRY_HOME)\bin\poetry" run python "$($repo_root)\tools\build_post_process.py" "build"

    if ($MakeInstaller) {
        Make-Ayon-Installer-Raw
    }

    Restore-Cwd

    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON build complete!", "All done in $( $endTime - $startTime ) secs. You will find AYON and build log in build directory."
    } catch {}
    Write-Color -Text "*** ", "All done in ", $($endTime - $startTime), " secs. You will find AYON and build log in ", "'.\build'", " directory." -Color Green, Gray, White, Gray, White, Gray
}

function Upload-To-Server() {
    & "$($env:POETRY_HOME)\bin\poetry" run python "$($repo_root)\tools\upload_to_server.py"  @args
}

function Make-Ayon-Installer-Raw() {
    Set-Content -Path "$($repo_root)\build\build.log" -Value $out
    & "$($env:POETRY_HOME)\bin\poetry" run python "$($repo_root)\tools\build_post_process.py" "make-installer"
}

function Make-Ayon-Installer() {
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))

    Make-Ayon-Installer-Raw

    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON build complete!", "All done in $( $endTime - $startTime ) secs. You will find AYON and build log in build directory."
    } catch {}
    Write-Color -Text "*** ", "All done in ", $($endTime - $startTime), " secs. You will find AYON and build log in ", "'.\build'", " directory." -Color Green, Gray, White, Gray, White, Gray
}

function Install-Runtime-Dependencies() {
    Write-Color -Text ">>> ", "Reading Poetry ... " -Color Green, Gray -NoNewline
    if (-not (Test-Path -PathType Container -Path "$($env:POETRY_HOME)\bin")) {
        Write-Color -Text "NOT FOUND" -Color Yellow
        Write-Color -Text "*** ", "We need to install Poetry create virtual env first ..." -Color Yellow, Gray
        Create-Env
    } else {
        Write-Color -Text "OK" -Color Green
    }
    $startTime = [int][double]::Parse((Get-Date -UFormat %s))
    & "$($env:POETRY_HOME)\bin\poetry" run python "$($repo_root)\tools\runtime_dependencies.py"
    $endTime = [int][double]::Parse((Get-Date -UFormat %s))
    try {
        New-BurntToastNotification -AppLogo "$app_logo" -Text "AYON", "Dependencies downloaded", "All done in $( $endTime - $startTime ) secs."
    } catch {}
}

function Run-From-Code() {
    & "$($env:POETRY_HOME)\bin\poetry" run python "$($repo_root)\start.py"
}

function Main {
    if ($FunctionName -eq $null) {
        Default-Func
        return
    }
    $FunctionName = $FunctionName.ToLower() -replace "\W"
    if ($FunctionName -eq "run") {
        Run-From-Code
    } elseif ($FunctionName -eq "createenv") {
        Change-Cwd
        Create-Env
    } elseif (($FunctionName -eq "installruntimedependencies") -or ($FunctionName -eq "installruntime")) {
        Change-Cwd
        Install-Runtime-Dependencies
    } elseif ($FunctionName -eq "build") {
        Change-Cwd
        Build-Ayon
    } elseif ($FunctionName -eq "makeinstaller") {
        Change-Cwd
        Make-Ayon-Installer
    } elseif ($FunctionName -eq "buildmakeinstaller") {
        Change-Cwd
        Build-Ayon -MakeInstaller true
    } elseif ($FunctionName -eq "upload") {
        Change-Cwd
        Upload-To-Server "upload" @arguments
    } else {
        Write-Host "Unknown function ""$FunctionName"""
        Default-Func
    }
}

if (-not (Test-Path 'env:POETRY_HOME')) {
    $env:POETRY_HOME = "$repo_root\.poetry"
}

# Enable if PS 7.x is needed.
# Show-PSWarning

Print-AsciiArt
Test-Python
Main

Restore-Cwd

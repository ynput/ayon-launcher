<#
.SYNOPSIS
  Helper script to update submodules.

.EXAMPLE

PS> .\update_submodules.ps1

#>

$current_dir = Get-Location
$script_dir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$repo_root = (Get-Item $script_dir).parent.FullName

Set-Location -Path $repo_root

git submodule update --recursive --remote

Set-Location -Path $current_dir

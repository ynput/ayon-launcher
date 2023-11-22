goto comment
DESCRIPTION
  This script is usually used as a replacement for building when tested farm integration like Deadline.

EXAMPLE

cmd> .\ayon_console.bat path/to/python_script.py
:comment

cd "%~dp0\.."
.poetry\bin\poetry.exe run python start.py %*

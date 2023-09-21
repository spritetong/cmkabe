@echo off
setlocal

cd "%~dp0"
wsl --shell-type login "cmake/rmake.sh" %*

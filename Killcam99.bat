@echo off
setlocal
rem ===================================================================================
rem  Killcam '99 - turns Unreal Tournament demos and recordings into kill clips.
rem
rem  Double-click:      opens the Killcam '99 window (the first time: a short setup).
rem  Drop files on it:  demos (.dem) are turned into clips, recordings (.mp4/.mkv) are read
rem                     for clips. The window does not have to be open.
rem  Killcam99.bat menu      a text menu       Killcam99.bat --help   every option
rem ===================================================================================
rem  Everything except this file, README.txt and the Clips folder lives in the (hidden) app folder.
cd /d "%~dp0"
if exist "%~dp0app\killcam_app.py" (
  attrib +h "%~dp0app" >nul 2>nul
  cd /d "%~dp0app"
)
set "PY=python"
if exist "python\python.exe" (
  set PY="%CD%\python\python.exe"
) else (
  where py >nul 2>nul && set "PY=py -3"
)

if "%~1"=="" (
  echo Opening Killcam '99 ...
  %PY% killcam_app.py
  if errorlevel 1 (
    echo.
    echo The window could not start ^(see above^). Here is the text menu instead.
    goto menu
  )
  goto :eof
)
if /i "%~1"=="menu" goto menu
set "A1=%~1"
if "%A1:~0,1%"=="-" (
  %PY% ut99_dem2video.py %*
  goto end
)
rem files dropped on the bat: write them to a list (quoted, so odd characters survive)
chcp 65001 >nul
set "DROPLIST=%TEMP%\killcam99_dropped.txt"
break > "%DROPLIST%"
:dropnext
if "%~1"=="" goto dropgo
>>"%DROPLIST%" echo "%~1"
shift
goto dropnext
:dropgo
%PY% ut99_dem2video.py --dropped-list "%DROPLIST%"
del "%DROPLIST%" >nul 2>nul
goto end

:menu
echo.
echo   Killcam '99
echo   -----------------------------------------------------------------------
echo   1  Find kills in new demos       (fast, nothing is recorded)
echo   2  Make clips from new demos     (find kills first, then record the moments)
echo   3  Make clips from recordings    (OBS / Streamlabs, no game needed)
echo   4  Refresh packages
echo   5  Search online for missing packages
echo   W  Open the Killcam '99 window   (setup, options, review)
echo   Q  Quit
echo.
set "CH="
set /p "CH=Choice: "
if /i "%CH%"=="1" %PY% ut99_dem2video.py --scan & goto menu
if /i "%CH%"=="2" %PY% ut99_dem2video.py --clips-only --scan-first & goto menu
if /i "%CH%"=="3" %PY% ut99_dem2video.py --obs & goto menu
if /i "%CH%"=="4" %PY% ut_library.py build & goto menu
if /i "%CH%"=="5" %PY% ut_library.py fetch & goto menu
if /i "%CH%"=="w" %PY% killcam_app.py & goto menu
if /i "%CH%"=="q" goto :eof
goto menu

:end
pause

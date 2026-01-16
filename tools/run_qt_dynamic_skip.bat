@echo off
setlocal

REM ==== project root ====
cd /d "D:\23_detector"

REM ==== optional: activate conda env (uncomment if you want) ====
REM call "D:\13anaconda3\Scripts\activate.bat" detector_env

REM ==== usage: drag a video onto this bat, or pass path as %1 ====
if "%~1"=="" (
  echo Usage:
  echo   %~nx0 "D:\path\to\video.mp4"
  echo Or drag-and-drop a video file onto this .bat
  pause
  exit /b 1
)

python -m src.app_qt --dynamic-skip --target-ratio 1.2 --max-allowed-step 12 --display-fps 15 --source "%~1"

pause
endlocal

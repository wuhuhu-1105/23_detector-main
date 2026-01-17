Smoke Tests (Local)
===================

Goal: allow any developer to run A/B regressions locally without a repo-provided mp4.

Prereqs
-------
- ffmpeg installed and available on PATH.
- Any input video file (mp4/avi/mov).

1) Create a 10s sample (outputs/smoke_short.mp4)
-------------------------------------------------

Example (Windows PowerShell):

```powershell
ffmpeg -y -ss 00:00:00 -t 10 -i "D:\path\to\your_video.mp4" -c:v libx264 -preset veryfast -crf 23 -an "D:\23_detector\outputs\smoke_short.mp4"
```

Notes:
- This keeps the sample out of git. Ensure `outputs/` is in `.gitignore`.

2) A: Realtime headless (1s)
----------------------------

```powershell
python -m src.app_qt --headless --source "D:\23_detector\outputs\smoke_short.mp4" --end-sec 1
```

3) B: Report export (json only)
-------------------------------

```powershell
python -m src.cli.report_gen --source "D:\23_detector\outputs\smoke_short.mp4" --format json
```

Optional: One-click runner (guard + A + B)
------------------------------------------

You can also run:

```powershell
python tools\smoke_local.py
```

By default it uses `outputs/smoke_short.mp4`. Override with:

```powershell
$env:SMOKE_VIDEO="D:\path\to\your_video.mp4"
python tools\smoke_local.py
```

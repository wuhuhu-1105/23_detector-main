# 23_detector

## Run (PyQt6 UI default)
```
python runner.py --source path/to/video.mp4
python -m src.app_qt --source path/to/video.mp4
python -m src.app_qt --source path/to/video.mp4 --dynamic-skip
```

## Run (headless pipeline)
```
python runner.py --headless --source path/to/video.mp4 --save-video out/demo.mp4
```

## Import self-check
```
python -c "import importlib; importlib.import_module('src.app_qt'); print('IMPORT OK')"
```

## Module path self-check
```
python -c "import src.app_qt,inspect,os; print(os.path.abspath(inspect.getfile(src.app_qt)))"
```

## Notes
- Install deps: `pip install -r requirements.txt`
- Recommended entry: `python -m src.app_qt ...`
- UI panel shows current state and duration.
- UI options: `--infer-every N`, `--max-fps FPS`, `--no-overlay`
- Display options: `--display-fps 15` (smooth UI refresh; repeats latest frame if infer is slower)
- Real-time metric: `RealTime Ratio` shows video-time / wall-time speed (closer to 1.0 is real-time).
- Scheduler tuning: `--target-ratio 1.0` (1.0 = aim real-time; 0.8 = smoother/slower; 1.2 = more aggressive catch-up)
- Save size: `--save-size 1280,720` or `--save-size 1280x720`

## Dynamic frame skipping tool
```
python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"
```

## FrameScheduler (model-speed adaptive)
FrameScheduler adapts frame stepping based on measured inference time, so you do not need to change code when the model or hardware speed changes.
Example:
```
python tools/dynamic_skip_infer.py --video "D:\20_Pose-Action-System\6F_1-cut2.mp4"
```

from __future__ import annotations

from typing import Optional


def pick_video_path() -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[
                ("Video files", "*.mp4;*.avi"),
                ("All files", "*.*"),
            ],
        )
    finally:
        root.destroy()
    return path or None

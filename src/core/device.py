from __future__ import annotations

from typing import Tuple


def cuda_availability_reason() -> Tuple[bool, str]:
    try:
        import torch
    except Exception:
        return False, "torch_unavailable"
    try:
        if not torch.cuda.is_available():
            return False, "cuda_not_available"
        if torch.cuda.device_count() <= 0:
            return False, "cuda_device_missing"
    except Exception:
        return False, "cuda_check_failed"
    return True, "ok"


def resolve_device(mode: str) -> Tuple[str, bool, str]:
    mode_norm = (mode or "auto").lower()
    cuda_ok, reason = cuda_availability_reason()
    if mode_norm == "cpu":
        return "cpu", cuda_ok, reason
    if mode_norm == "gpu":
        return ("cuda" if cuda_ok else "cpu"), cuda_ok, reason
    return ("cuda" if cuda_ok else "cpu"), cuda_ok, reason

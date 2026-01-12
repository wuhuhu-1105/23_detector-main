from __future__ import annotations

from src.core.config import AppConfig, OffMode
from src.runtime.cli import parse_args
from src.runtime.config_overrides import apply_cli_overrides
from src.runtime.runner import run_headless
from src.runtime.source_utils import resolve_source, validate_source, write_last_source


def main() -> None:
    args = parse_args()
    source = resolve_source(args)
    if args.no_view:
        args.view = False
    cfg = AppConfig()
    apply_cli_overrides(cfg, args)

    if cfg.off_mode_b == OffMode.REPLAY or cfg.off_mode_c == OffMode.REPLAY or cfg.off_mode_d == OffMode.REPLAY:
        raise NotImplementedError("REPLAY is not enabled yet.")

    validate_source(source)
    write_last_source(source)
    run_headless(args, cfg, source)


if __name__ == "__main__":
    main()

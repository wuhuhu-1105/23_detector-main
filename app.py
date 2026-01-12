from __future__ import annotations

from src.app_qt import main as app_main
from src.runtime.cli import build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    app_main(args)


if __name__ == "__main__":
    main()

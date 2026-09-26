"""Double-click for GUI; command-line arguments preserve script functionality."""
import os
import sys


def main():
    if sys.argv[1:] == ["--self-test-gui"]:
        from aicu.gui import MainWindow
        window = MainWindow()
        try:
            window.update_idletasks()
        finally:
            window.destroy()
        return 0
    if len(sys.argv) > 1:
        # Windowed PyInstaller builds have no console streams.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        from aicu.cli import main as cli_main
        return cli_main(sys.argv[1:])
    from aicu.gui import launch
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

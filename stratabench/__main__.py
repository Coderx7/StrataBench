"""Launch the GUI by default, or pass arguments to the optional command line."""
import sys

if __name__ == '__main__':
    if len(sys.argv) == 1:
        from .gui import launch
        launch()
    else:
        from .cli import main
        raise SystemExit(main())

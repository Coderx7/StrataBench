#!/usr/bin/python3
"""Desktop entry point: no terminal window and no package installation."""
from stratabench.gui import launch, notify_error

if __name__ == '__main__':
    try:
        launch()
    except Exception as error:
        notify_error(str(error))
        raise SystemExit(1)

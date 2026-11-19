"""Double-click entry point for Windows with Python installed."""
from stratabench.gui import launch, notify_error

if __name__ == '__main__':
    try:
        launch()
    except Exception as error:
        notify_error(str(error))

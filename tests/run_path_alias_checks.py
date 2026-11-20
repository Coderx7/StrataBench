"""Run the suite with an aliased temp folder to expose path-spelling assumptions."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    project = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix='stratabench-path-check-') as workspace:
        base = Path(workspace).resolve()
        real = base / 'long temporary folder'
        real.mkdir()
        alias = base / 'short-alias'
        alias.symlink_to(real, target_is_directory=True)
        env = dict(os.environ, TMPDIR=str(alias), TEMP=str(alias), TMP=str(alias))
        print('Running tests with an aliased temporary folder.', flush=True)
        return subprocess.call([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                               cwd=project, env=env)


if __name__ == '__main__':
    sys.exit(main())

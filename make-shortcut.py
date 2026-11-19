"""Create a Linux desktop launcher for the current checkout."""
from pathlib import Path
import os
import shutil
import sys

if __name__ == '__main__':
    if os.name == 'nt':
        raise SystemExit('On Windows, create a shortcut to StrataBench.pyw or start.bat.')
    root = Path(__file__).resolve().parent
    python = shutil.which('python3') or sys.executable
    def quoted(value):
        return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
    content = '\n'.join(['[Desktop Entry]','Version=1.0','Type=Application','Name=StrataBench',
        'Comment=Compare local Strata models and engine versions',
        'Exec='+quoted(python)+' '+quoted(root / 'launch-gui.py'),
        'Path='+str(root),'Icon='+str(root / 'stratabench/web/icon.svg'),
        'Terminal=false','Categories=Development;Science;','StartupNotify=false',''])
    target = root / 'StrataBench.desktop'
    target.write_text(content,encoding='utf-8');target.chmod(0o755)
    print('Created '+str(target)+'. Move or copy it to your Desktop, then allow launching if prompted.')

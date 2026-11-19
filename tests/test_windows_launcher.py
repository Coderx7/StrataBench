"""Check the Windows entry points and exercise batch dispatch on Windows runners."""
import io
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class WindowsLauncherTests(unittest.TestCase):
    def test_windows_entry_points_are_present_at_the_project_root(self):
        for name in ('start.bat','StrataBench.pyw','launch-gui.py'):
            self.assertTrue((ROOT/name).is_file(),f'{name} must be included in the extracted project folder')

    @unittest.skipUnless(shutil.which('git') and (ROOT/'.git').exists(), 'Source ZIPs do not include Git metadata')
    def test_repository_archive_includes_windows_launchers(self):
        result = subprocess.run(['git','archive','--format=tar','HEAD','start.bat','StrataBench.pyw','launch-gui.py'],
            cwd=ROOT,capture_output=True,check=True)
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            self.assertEqual(set(archive.getnames()),{'start.bat','StrataBench.pyw','launch-gui.py'})

    def test_windowless_entry_point_starts_the_gui(self):
        with mock.patch('stratabench.gui.launch') as launch, mock.patch('stratabench.gui.notify_error') as error:
            runpy.run_path(str(ROOT/'StrataBench.pyw'),run_name='__main__')
        launch.assert_called_once_with();error.assert_not_called()

    def test_windowless_entry_point_shows_startup_errors(self):
        with mock.patch('stratabench.gui.launch',side_effect=RuntimeError('Test startup error')), \
                mock.patch('stratabench.gui.notify_error') as error:
            runpy.run_path(str(ROOT/'StrataBench.pyw'),run_name='__main__')
        error.assert_called_once_with('Test startup error')

    @unittest.skipUnless(os.name=='nt','Native batch dispatch requires Windows; covered by Windows CI')
    def test_batch_dispatch_handles_paths_with_spaces_and_console_fallbacks(self):
        for launcher in ('pyw','pythonw','py','python'):
            with self.subTest(launcher=launcher), tempfile.TemporaryDirectory(prefix='StrataBench launcher ') as directory:
                folder=Path(directory)
                shutil.copy2(ROOT/'start.bat',folder/'start.bat')
                (folder/'StrataBench.pyw').write_text('# test entry point; not executed\n',encoding='utf-8')
                capture=folder/'captured arguments.txt'
                (folder/(launcher+'.cmd')).write_text('@echo off\n> "%STRATABENCH_TEST_CAPTURE%" echo %*\nexit 0\n',encoding='ascii')
                env=dict(os.environ,PATH=str(folder)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32'),
                         STRATABENCH_TEST_CAPTURE=str(capture))
                result=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(folder/'start.bat')],
                    cwd=folder,env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                deadline=time.monotonic()+5
                while not capture.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(capture.exists(),f'{launcher} was not invoked')
                arguments=capture.read_text().strip()
                self.assertIn(str(folder/'StrataBench.pyw'),arguments)
                if launcher in ('py','pyw'):self.assertTrue(arguments.startswith('-3 '))

    @unittest.skipUnless(os.name=='nt','Native batch error handling requires Windows; covered by Windows CI')
    def test_batch_reports_an_incomplete_download(self):
        with tempfile.TemporaryDirectory(prefix='StrataBench missing files ') as directory:
            folder=Path(directory);shutil.copy2(ROOT/'start.bat',folder/'start.bat')
            result=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(folder/'start.bat')],
                cwd=folder,input='\n',capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,1)
            self.assertIn('Extract the complete StrataBench download',result.stdout)


if __name__=='__main__': unittest.main()

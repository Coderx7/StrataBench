import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

from stratabench import acquisition as a, platforms, versions
from stratabench.common import write_json


def make_tar(path, files):
    with tarfile.open(path,'w:gz') as stream:
        for name,content in files.items():
            member=tarfile.TarInfo(name);member.size=len(content);member.mode=0o755
            stream.addfile(member,io.BytesIO(content))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.state={'strata_root':'','versions':{}}
        self.patches=[mock.patch.object(a,'ROOT',self.root),mock.patch.object(versions,'ROOT',self.root),
            mock.patch.object(a,'settings',side_effect=lambda:self.state),
            mock.patch.object(versions,'settings',side_effect=lambda:self.state),
            mock.patch.object(a,'save_settings'),mock.patch.object(versions,'save_settings')]
        for patch in self.patches:patch.start()
    def tearDown(self):
        for patch in reversed(self.patches):patch.stop()
        self.tmp.cleanup()
    def config(self,**extra):
        return {**a.preferences(self.state),**extra}
    def tree(self,base,new=False):
        runtime=base/'terminal' if new else base
        (runtime/'serve').mkdir(parents=True);(runtime/'tools').mkdir()
        (runtime/'serve/server.py').write_text('# test server\n',encoding='utf-8')
        (runtime/'tools/strata_tokenizer.py').write_text('# test tokenizer\n',encoding='utf-8')
        return runtime
    def test_clean_defaults_and_existing_installation_migration(self):
        cfg=a.preferences(self.state)
        self.assertEqual(cfg['method'],'release');self.assertEqual(cfg['folder'],'')
        self.assertEqual(cfg['python_mode'],'managed');self.assertEqual(cfg['cuda_architectures'],'native')
        self.state.update(strata_root=str(self.root),versions={'v1':{}})
        cfg=a.preferences(self.state)
        self.assertEqual(cfg['method'],'local');self.assertEqual(cfg['folder'],str(self.root))
        self.assertEqual(cfg['python_mode'],'existing')
    def test_preferences_validate_before_saving(self):
        for data in ({'repository':'file:///etc/passwd'},{'repository':'https://user:secret@github.com/a/b'},
                {'method':'oops'},{'cuda_architectures':'86;--bad'},{'build_jobs':0},
                {'build_jobs':True},{'asset':'../engine.zip'},{'allow_unverified':'yes'},
                {'cmake_args':['--help']},{'method':'release','repository':'https://example.com/a/b.git'}):
            with self.subTest(data=data),self.assertRaises(ValueError):a.configure(data)
        a.save_settings.assert_not_called()
        cfg=a.configure({'cuda_architectures':'86;89','build_jobs':3})
        self.assertEqual(cfg['build_jobs'],3);a.save_settings.assert_called_once()
    def test_original_and_terminal_server_layouts(self):
        old=self.root/'old';new=self.root/'new';self.tree(old);self.tree(new,True)
        self.assertEqual(a.runtime_source(old),old);self.assertEqual(a.runtime_source(new),new/'terminal')
        a.copy_runtime(new,self.root/'normalized')
        self.assertTrue((self.root/'normalized/serve/server.py').exists())
        self.assertTrue((self.root/'normalized/tools/strata_tokenizer.py').exists())
    def test_windows_executable_and_helper_library_discovery(self):
        base=self.root/'install';(base/'engine').mkdir(parents=True)
        (base/'engine/strata.exe').write_bytes(b'test');(base/'engine/helper.dll').write_bytes(b'dll')
        with mock.patch.object(platforms,'windows',return_value=True):
            engine=a.local_engine(base);self.assertEqual(engine.name,'strata.exe')
            target=a.copy_engine(engine,self.root/'runtime/engine')
            self.assertEqual(target.name,'strata.exe')
        self.assertTrue((self.root/'runtime/engine/helper.dll').exists())
    def test_release_matching_never_substitutes_another_platform_or_backend(self):
        names=['strata-engine-1-linux-x86_64-cuda-cuda12.tar.gz','strata-engine-1-linux-x86_64-cuda-cuda13.tar.gz',
            'strata-engine-1-windows-x86_64-cuda-cuda12.tar.gz','strata-engine-1-linux-aarch64-cuda-cuda12.tar.gz',
            'Strata-windows-x64-setup.exe','strata-control-1-linux-x86_64.tar.gz','strata-windows-x64-cuda12.zip']
        release={'assets':[{'name':n} for n in names]}
        self.assertEqual([x['name'] for x in a.compatible_assets(release,self.config(),('linux','x86_64'))],[names[0]])
        self.assertEqual([x['name'] for x in a.compatible_assets(release,self.config(),('windows','x86_64'))],[names[2],names[6]])
    def test_safe_extraction_rejects_cross_platform_traversal_and_links(self):
        for i,name in enumerate(('../outside','top/../../outside','C:\\outside','top\\..\\outside','/absolute','top/file:stream')):
            path=self.root/f'{i}.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr(name,b'bad')
            with self.subTest(name=name),self.assertRaises(ValueError):a.unpack(path,self.root/'out')
        path=self.root/'link.tar'
        with tarfile.open(path,'w') as tf:
            member=tarfile.TarInfo('link');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';tf.addfile(member)
        with self.assertRaises(ValueError):a.unpack(path,self.root/'out')
        self.assertFalse((self.root/'outside').exists())
    def test_internal_shared_library_links_are_materialized_without_symlinks(self):
        path=self.root/'libraries.tar'
        with tarfile.open(path,'w') as tf:
            data=b'library';member=tarfile.TarInfo('package/lib.so.1');member.size=len(data);tf.addfile(member,io.BytesIO(data))
            member=tarfile.TarInfo('package/lib.so');member.type=tarfile.SYMTYPE;member.linkname='lib.so.1';tf.addfile(member)
            member=tarfile.TarInfo('package/alias.so');member.type=tarfile.LNKTYPE;member.linkname='package/lib.so.1';tf.addfile(member)
        out=self.root/'out';a.unpack(path,out,strip_top=True)
        for name in ('lib.so.1','lib.so','alias.so'):
            self.assertEqual((out/name).read_bytes(),b'library');self.assertFalse((out/name).is_symlink())
        with tarfile.open(path,'w') as tf:
            member=tarfile.TarInfo('package/cycle');member.type=tarfile.SYMTYPE;member.linkname='cycle';tf.addfile(member)
        with self.assertRaises(ValueError):a.unpack(path,self.root/'cycle')

    def test_source_build_commands_use_configured_architecture_and_release_configuration(self):
        source=self.root/'source';source.mkdir();(source/'CMakeLists.txt').write_text('project(test)')
        dest=self.root/'version';dest.mkdir();cfg=self.config(cuda_architectures='89')
        def command(cmd,**kwargs):
            if '--build' in cmd:
                (dest/'build/Release').mkdir(parents=True)
                (dest/'build/Release'/platforms.executable()).write_bytes(b'compiled')
        with mock.patch.object(a.shutil,'which',side_effect=lambda name:'/tools/'+name),mock.patch.object(a.subprocess,'run',side_effect=command) as run:
            binary,flags=a.build_source(source,dest,cfg,3,())
        self.assertTrue(binary.exists());self.assertIn('-DCMAKE_CUDA_ARCHITECTURES=89',flags)
        self.assertIn('--config',run.call_args.args[0]);self.assertIn('Release',run.call_args.args[0])
        self.assertIn('--parallel',run.call_args.args[0]);self.assertIn('3',run.call_args.args[0])
    @unittest.skipUnless(shutil.which('git'),'Git is needed only for this source-export test')
    def test_local_git_export_is_pinned_and_never_checks_out_the_user_repository(self):
        repo=self.root/'repo';repo.mkdir()
        def git(*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
        git('init');(repo/'tracked.txt').write_text('committed')
        git('add','tracked.txt');git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','Test fixture')
        commit=git('rev-parse','HEAD');(repo/'tracked.txt').write_text('uncommitted')
        dest=self.root/'export/source';dest.parent.mkdir()
        actual=a.source_tree(self.config(method='folder',folder=str(repo)),commit,dest)
        self.assertEqual(actual,commit);self.assertEqual((dest/'tracked.txt').read_text(),'committed')
        self.assertEqual((repo/'tracked.txt').read_text(),'uncommitted')
    def release_fixture(self,bad=False):
        package=self.root/'engine.tar.gz';source=self.root/'source.tar.gz'
        make_tar(package,{'package/'+platforms.executable():b'test engine','package/helper.dll':b'library','package/tuning/table.dat':b'tuning'})
        make_tar(source,{'repo/terminal/serve/server.py':b'# matching server\n','repo/terminal/tools/strata_tokenizer.py':b'# tokenizer\n'})
        sha=hashlib.sha256(package.read_bytes()).hexdigest()
        asset={'name':f'strata-engine-1-{platforms.platform_id()[0]}-{platforms.platform_id()[1]}-cuda-cuda12.tar.gz',
            'browser_download_url':'https://example.invalid/engine.tar.gz','digest':'sha256:'+('0'*64 if bad else sha),'size':package.stat().st_size}
        release={'tag_name':'v1','assets':[asset]}
        def download(url,dest):shutil.copyfile(source if 'codeload.github.com' in url else package,dest)
        return release,download
    def test_portable_preparation_verifies_package_and_records_matching_source_without_git_or_cmake(self):
        release,download=self.release_fixture();self.state['strata_source']=self.config(python_mode='existing')
        def remote(url):return {'sha':'a'*40} if '/commits/' in url else release
        with mock.patch.object(a,'get_json',side_effect=remote),mock.patch.object(versions,'download',side_effect=download),\
                mock.patch.object(a,'capture',return_value={'ok':True}),mock.patch.object(a.subprocess,'run') as run:
            info=a.prepare('latest')
        run.assert_not_called();self.assertEqual(info['name'],'v1');self.assertTrue(info['checksum_verified'])
        self.assertEqual(info['git'],'a'*40);self.assertEqual(info['fingerprint']['engine_sha256'],hashlib.sha256(b'test engine').hexdigest())
        self.assertTrue((Path(info['root'])/'serve/server.py').exists())
        self.assertIn('v1',self.state['versions'])
        self.assertEqual((Path(info['exe']).parent/'tuning/table.dat').read_bytes(),b'tuning')
    def test_checksum_mismatch_never_registers_or_runs_a_package(self):
        release,download=self.release_fixture(bad=True);self.state['strata_source']=self.config(python_mode='existing')
        with mock.patch.object(a,'get_json',return_value=release),mock.patch.object(versions,'download',side_effect=download),\
                mock.patch.object(a.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'checksum did not match'):
            a.prepare('latest')
        run.assert_not_called();self.assertFalse(self.state['versions']);self.assertFalse((self.root/'versions/v1').exists())
        self.assertFalse(list((self.root/'versions/_downloads').glob('*')))
    def test_interrupted_app_owned_preparation_is_preserved_and_can_be_retried(self):
        release,download=self.release_fixture();self.state['strata_source']=self.config(python_mode='existing')
        stale=self.root/'versions/v1';stale.mkdir(parents=True)
        write_json(stale/'.preparing.json',{'name':'v1','schema':1});(stale/'build.log').write_text('interrupted')
        with mock.patch.object(a,'get_json',side_effect=lambda url:{'sha':'a'*40} if '/commits/' in url else release),\
                mock.patch.object(versions,'download',side_effect=download),mock.patch.object(a,'capture',return_value={'ok':True}):
            info=a.prepare('latest')
        self.assertEqual(info['name'],'v1');self.assertFalse((stale/'.preparing.json').exists())
        logs=list((self.root/'versions/_failed').glob('v1-*/build.log'))
        self.assertEqual(len(logs),1);self.assertEqual(logs[0].read_text(),'interrupted')

    def test_failed_clone_does_not_leave_an_unusable_repository_cache(self):
        cfg=self.config(method='repository');dest=self.root/'version/source';dest.parent.mkdir()
        def fail(command,**kwargs):
            if 'clone' in command:
                Path(command[-1]).mkdir();raise subprocess.CalledProcessError(1,command)
        with mock.patch.object(a.shutil,'which',return_value='/git'),mock.patch.object(a.subprocess,'run',side_effect=fail),\
                self.assertRaises(subprocess.CalledProcessError):
            a.source_tree(cfg,'v1',dest)
        self.assertFalse(list((self.root/'versions/_git').iterdir()))
    def test_missing_checksum_requires_explicit_opt_in(self):
        release,_=self.release_fixture();release['assets'][0].pop('digest')
        with self.assertRaisesRegex(ValueError,'no published SHA-256'):
            a.prepare_release(self.config(),release,self.root/'source',self.root/'dest')
    def test_release_checksum_file_matches_the_exact_asset_filename(self):
        release,download=self.release_fixture();asset=release['assets'][0]
        expected=asset.pop('digest')[7:]
        release['assets'].append({'name':'SHA256SUMS.txt','browser_download_url':'https://example.invalid/SHA256SUMS.txt'})
        dest=self.root/'dest';dest.mkdir()
        def files(url,path):
            if url.endswith('SHA256SUMS.txt'):
                Path(path).write_text('0'*64+'  '+asset['name']+'.wrong\n'+expected+'  '+asset['name']+'\n',encoding='utf-8')
            else:download(url,path)
        with mock.patch.object(versions,'download',side_effect=files),mock.patch.object(a,'get_json',return_value={'sha':'a'*40}):
            info=a.prepare_release(self.config(),release,dest/'source',dest)
        self.assertTrue(info['checksum_verified']);self.assertEqual(info['asset_sha256'],expected)

    def test_python_dependencies_are_installed_only_inside_the_version_environment(self):
        source=self.root/'source';self.tree(source);(source/'requirements.txt').write_text('numpy\n')
        dest=self.root/'version';dest.mkdir()
        with mock.patch.object(a.subprocess,'run') as run:
            py=a.python_runtime(self.config(python_mode='managed'),source,dest)
        calls=[c.args[0] for c in run.call_args_list]
        self.assertEqual(calls[0][1:3],['-m','venv']);self.assertEqual(Path(calls[0][-1]),dest/'.venv')
        self.assertEqual(calls[1][0],py);self.assertIn('pip',calls[1]);self.assertIn(str(source/'requirements.txt'),calls[1])


class PlatformTests(unittest.TestCase):
    def test_windows_workers_have_no_console_window_and_owned_tree_stop(self):
        process=mock.Mock(pid=1234);process.poll.return_value=None
        with mock.patch.object(platforms,'windows',return_value=True),mock.patch.object(platforms.subprocess,'run') as run:
            options=platforms.process_options();platforms.stop_tree(process)
        self.assertIn('creationflags',options);self.assertNotIn('start_new_session',options)
        self.assertEqual(run.call_args.args[0],['taskkill','/PID','1234','/T','/F'])
    def test_lock_contention_and_release_on_this_host(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock';path.write_bytes(b'0')
            self.assertFalse(platforms.is_locked(path))
            with path.open('r+b') as stream:
                platforms.lock_file(stream);self.assertTrue(platforms.is_locked(path));platforms.lock_file(stream,unlock=True)
            self.assertFalse(platforms.is_locked(path))


if __name__=='__main__':unittest.main()

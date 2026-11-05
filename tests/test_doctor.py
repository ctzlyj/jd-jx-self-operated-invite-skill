import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]/'scripts/invite.py'
spec=importlib.util.spec_from_file_location('invite',MODULE)
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

def make_home(tmp, helper_rel=None):
    home=Path(tmp)/'home'
    (home/'venv'/'Scripts').mkdir(parents=True)
    exe=home/'venv'/'Scripts'/'o2.exe';exe.write_bytes(b'x')
    python=home/'venv'/'python.exe';python.write_bytes(b'x')
    helper=None
    if helper_rel:
        helper=home/helper_rel;helper.parent.mkdir(parents=True,exist_ok=True);helper.write_bytes(b'x')
    return home,exe,python,helper

class LauncherTests(unittest.TestCase):
    def run_tmp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        return self.temp.name

    def test_falls_back_to_plain_o2_when_helper_missing(self):
        tmp=self.run_tmp();home,exe,python,_=make_home(tmp)
        with patch.object(runner.shutil,'which',return_value=str(exe)):
            self.assertEqual(runner.launcher(home=home),[str(exe),'launch','webcli'])

    def test_helper_found_under_multiple_agent_roots(self):
        for rel in ('.joycode/skills/o2/scripts/windows_launch.py',
                    '.codex/skills/o2/scripts/windows_launch.py',
                    '.agents/skills/o2/scripts/windows_launch.py'):
            with self.subTest(rel=rel):
                tmp=self.run_tmp();home,exe,python,helper=make_home(tmp,rel)
                with patch.object(runner.shutil,'which',return_value=str(exe)):
                    self.assertEqual(runner.launcher(home=home),
                        [str(python),'-X','utf8',str(helper),'launch','webcli'])

    def test_helper_identified_in_skillhub_skill_id_directory(self):
        tmp=self.run_tmp();home,exe,python,_=make_home(tmp)
        skill=home/'.codex'/'skills'/'skill-42';(skill/'scripts').mkdir(parents=True)
        (skill/'SKILL.md').write_text('---\nname: o2\ndescription: x\n---\n',encoding='utf-8')
        helper=skill/'scripts'/'windows_launch.py';helper.write_bytes(b'x')
        with patch.object(runner.shutil,'which',return_value=str(exe)):
            self.assertEqual(runner.launcher(home=home),
                [str(python),'-X','utf8',str(helper),'launch','webcli'])

    def test_foreign_helper_with_same_filename_is_ignored(self):
        tmp=self.run_tmp();home,exe,python,_=make_home(tmp)
        skill=home/'.joycode'/'skills'/'skill-42';(skill/'scripts').mkdir(parents=True)
        (skill/'SKILL.md').write_text('---\nname: other-skill\n---\n',encoding='utf-8')
        (skill/'scripts'/'windows_launch.py').write_bytes(b'x')
        with patch.object(runner.shutil,'which',return_value=str(exe)):
            self.assertEqual(runner.launcher(home=home),[str(exe),'launch','webcli'])

    def test_missing_o2_gives_colleague_friendly_install_hint(self):
        with patch.object(runner.shutil,'which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'pip install -U --index-url https://artifactory.jd.com/artifactory/api/pypi/libs-py-local/simple o2'):
                runner.launcher(home=Path(self.run_tmp()))

class Completed:
    def __init__(self,returncode=0,stdout=''):
        self.returncode=returncode;self.stdout=stdout;self.stderr=''

class DoctorCheckTests(unittest.TestCase):
    def run_tmp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        return self.temp.name

    def test_python_check_passes_and_has_next_field(self):
        c=runner.check_python()
        self.assertEqual(c['check'],'python');self.assertTrue(c['ok']);self.assertTrue('next' in c)

    def test_webcli_failure_recommends_install(self):
        with patch.object(runner.subprocess,'run',return_value=Completed(1,'')):
            c=runner.check_webcli(['o2','launch','webcli'],'jx-doctor')
        self.assertEqual(c['check'],'webcli');self.assertFalse(c['ok'])
        self.assertIn('o2 install webcli',c['next'])

    def test_webcli_success_requires_json_output(self):
        with patch.object(runner.subprocess,'run',return_value=Completed(0,'not json')):
            c=runner.check_webcli(['o2','launch','webcli'],'jx-doctor')
        self.assertFalse(c['ok'])
        with patch.object(runner.subprocess,'run',return_value=Completed(0,'[]')):
            c=runner.check_webcli(['o2','launch','webcli'],'jx-doctor')
        self.assertTrue(c['ok'])

    def test_task_dir_check_writes_and_removes_probe(self):
        directory=Path(self.run_tmp())/'tasks'
        c=runner.check_task_dir(directory)
        self.assertEqual(c['check'],'task-dir');self.assertTrue(c['ok'])
        self.assertTrue(directory.is_dir())
        self.assertFalse((directory/'.doctor-probe').exists())

    def test_task_dir_failure_reports_next_step(self):
        directory=Path(self.run_tmp())/'tasks'
        directory.mkdir()
        with patch.object(runner.Path,'write_text',side_effect=OSError('denied')):
            c=runner.check_task_dir(directory)
        self.assertFalse(c['ok']);self.assertIn('next',c)

class FakeLoginClient:
    def __init__(self,erp='employee-a'):self.erp=erp
    def call(self,q):
        if q.get('op')=='identity':return {'erp':self.erp,'role':4}
        raise AssertionError(q)

class LoginCheckTests(unittest.TestCase):
    def test_login_check_opens_background_page_and_releases_it(self):
        calls=[]
        def fake_run(cmd,**kw):
            calls.append(cmd)
            if cmd[-2]=='open':return Completed(0,json.dumps({'page':'TAB1'}))
            return Completed(0,'{}')
        with patch.object(runner,'Client',return_value=FakeLoginClient()), \
             patch.object(runner.subprocess,'run',side_effect=fake_run):
            c=runner.check_login(['o2','launch','webcli'],'jx-doctor')
        self.assertEqual(c['check'],'erp-login');self.assertTrue(c['ok'])
        self.assertIn('employee-a',c['detail'])
        self.assertTrue(any('--window' in x for x in calls[0]))
        self.assertTrue(any(x=='close' for x in calls[-1]))

    def test_login_failure_tells_user_to_log_in_first(self):
        def fake_run(cmd,**kw):
            if cmd[-2]=='open':return Completed(0,json.dumps({'page':'TAB1'}))
            return Completed(0,'{}')
        class Boom:
            def call(self,q):raise RuntimeError('Browser operation failed')
        with patch.object(runner,'Client',return_value=Boom()), \
             patch.object(runner.subprocess,'run',side_effect=fake_run):
            c=runner.check_login(['o2','launch','webcli'],'jx-doctor')
        self.assertFalse(c['ok']);self.assertIn('登录',c['next'])

class DoctorFlowTests(unittest.TestCase):
    def test_doctor_summarizes_all_checks_and_exit_code(self):
        checks=[{'check':'python','ok':True,'detail':'x','next':''},
                {'check':'o2','ok':True,'detail':'x','next':''},
                {'check':'webcli','ok':True,'detail':'x','next':''},
                {'check':'task-dir','ok':True,'detail':'x','next':''},
                {'check':'erp-login','ok':True,'detail':'x','next':''}]
        with patch.object(runner,'check_python',return_value=checks[0]), \
             patch.object(runner,'launcher',return_value=['o2','launch','webcli']), \
             patch.object(runner,'find_o2_helper',return_value=None), \
             patch.object(runner,'check_webcli',return_value=checks[2]), \
             patch.object(runner,'check_task_dir',return_value=checks[3]), \
             patch.object(runner,'check_login',return_value=checks[4]):
            code=runner.doctor(None)
        self.assertEqual(code,0)

    def test_doctor_failing_check_returns_nonzero(self):
        checks=[{'check':'python','ok':True,'detail':'x','next':''},
                {'check':'o2','ok':False,'detail':'x','next':'install'},
                {'check':'webcli','ok':False,'detail':'skipped','next':'install o2 first'}]
        with patch.object(runner,'check_python',return_value=checks[0]), \
             patch.object(runner,'launcher',side_effect=RuntimeError('O2 未安装')), \
             patch.object(runner,'check_webcli',return_value=checks[2]), \
             patch.object(runner,'check_task_dir',return_value=checks[3] if len(checks)>3 else {'check':'task-dir','ok':True,'detail':'x','next':''}), \
             patch.object(runner,'check_login',return_value={'check':'erp-login','ok':False,'detail':'skipped','next':'install o2 first'}):
            code=runner.doctor(None)
        self.assertEqual(code,1)

if __name__=='__main__':unittest.main()

import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES=('__pycache__/','.pyc','.pytest_cache/','.venv/','snapshot.json','state.json',
                 'result.json','result.csv','failures.csv','run.lock','.env','.DS_Store')
FORBIDDEN_CONTENT=re.compile(r'caotong\.888|D:[/\\]caotong|C:[/\\]Users[/\\][A-Za-z0-9_.-]+[/\\]|Miniconda3|:58126',re.I)

class PublishPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (REPO/'.git').exists():
            raise unittest.SkipTest('publish archive check requires a git checkout')
        cls.temp=tempfile.TemporaryDirectory()
        cls.archive=Path(cls.temp.name)/'publish.zip'
        subprocess.run(['git','-C',str(REPO),'archive','--format=zip','HEAD','-o',str(cls.archive)],
                       check=True,capture_output=True)
        cls.z=zipfile.ZipFile(cls.archive)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'z'):cls.z.close()
        if hasattr(cls,'temp'):cls.temp.cleanup()

    def test_archive_contains_skill_md(self):
        self.assertTrue(any(n.rstrip('/').endswith('/SKILL.md') or n=='SKILL.md' for n in self.z.namelist()))

    def test_archive_excludes_caches_artifacts_and_state(self):
        bad=[n for n in self.z.namelist() if any(f in n for f in FORBIDDEN_NAMES)]
        self.assertEqual(bad,[],f'publish archive must not contain caches/artifacts: {bad}')

    def test_archive_has_no_personal_paths_or_fixed_ports(self):
        for n in self.z.namelist():
            if n.endswith('/'):continue
            data=self.z.read(n)
            text=data.decode('utf-8',errors='ignore')
            m=FORBIDDEN_CONTENT.search(text)
            self.assertIsNone(m,f'{n} contains personal path/port marker: {m.group(0) if m else ""}')

    def test_skill_md_declares_semver_version(self):
        name=next(n for n in self.z.namelist() if n.rstrip('/').endswith('SKILL.md'))
        text=self.z.read(name).decode('utf-8')
        self.assertRegex(text[:400],r'(?m)^version:\s*\d+\.\d+\.\d+\s*$')

if __name__=='__main__':unittest.main()

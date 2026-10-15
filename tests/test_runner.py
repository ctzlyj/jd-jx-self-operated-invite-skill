import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]/'scripts/invite.py'
spec=importlib.util.spec_from_file_location('invite',MODULE)
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class FakePlatform:
    def __init__(self,count=12037,erp='employee-a'):
        self.erp=erp
        self.rows=[{'spuId':str(100000+i),'venderId':str(700+i%17),'shopId':str(900+i%17),
                    'erp':erp,'canOperate':True,'productName':'synthetic','shopName':'synthetic'} for i in range(count)]
        self.sent=[];self.active=set();self.failed=set();self.hidden=set();self.lose_response=False;self.corrupt_identity=False

    def call(self,q):
        if q.get('expectedErp',self.erp)!=self.erp:raise RuntimeError('identity changed')
        if q['op']=='identity':return {'erp':self.erp,'role':4}
        if q['op']=='capture':return {'erp':self.erp,'query':{'accessContext':{},'queryParam':{'dataSource':2,'pageNum':1,'pageSize':100,'lastCategoryIdList':['1'],'dept3IdList':['2']}},'total':len(self.rows)}
        if q['op']=='pages':return [{'pageNum':n,'total':len(self.rows),'rows':self.rows[(n-1)*100:n*100],'trace':'synthetic'} for n in q['pages']]
        if q['op']=='records':
            result=[]
            for ids in q['groups']:
                rows=[{k:r[k] for k in ('spuId','venderId','shopId')} for r in self.rows if r['spuId'] in ids and r['spuId'] in self.active and r['spuId'] not in self.hidden]
                if self.corrupt_identity and rows:rows[0]['shopId']='99999'
                result.append({'rows':rows,'trace':'synthetic','statuses':q['statuses'],'verifiedAt':'synthetic'})
            return result
        if q['op']=='invite':
            results=[]
            for group in q['groups']:
                assert 1<=len(group)<=100
                result=[]
                for sid,vender,shop in group:
                    if sid in self.sent:raise AssertionError('Duplicate invitation')
                    self.sent.append(sid)
                    if sid not in self.failed:self.active.add(sid)
                    result.append({'spuId':sid,'state':'rejected' if sid in self.failed else 'accepted','code':410 if sid in self.failed else 200,'msg':'synthetic'})
                results.append({'items':result,'stop':False,'trace':'synthetic'})
            if self.lose_response:self.lose_response=False;raise RuntimeError('CLI response lost after all writes committed')
            return results
        if q['op']=='board':return {'total':len(self.rows)-len(self.active),'trace':'synthetic','verifiedAt':'synthetic'}
        raise AssertionError(q['op'])

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)
        self.silent=contextlib.redirect_stdout(io.StringIO());self.silent.__enter__()
    def tearDown(self):
        self.silent.__exit__(None,None,None);self.temp.cleanup()
    def prepare(self,platform):return runner.prepare(platform,self.directory)

    def test_12037_spus_complete_without_truncation(self):
        p=FakePlatform();s,t=self.prepare(p);result=runner.run(p,self.directory,s,t)
        self.assertEqual(s['total'],12037);self.assertEqual(len(p.sent),12037)
        self.assertEqual(len(t['batches']),121);self.assertEqual(result['verifiedSpus'],12037)
        self.assertTrue(result['complete']);self.assertEqual(result['board']['total'],0)

    def test_another_colleague_does_not_inherit_authors_erp(self):
        p=FakePlatform(12,erp='employee-b');s,t=self.prepare(p)
        self.assertEqual(s['erp'],'employee-b');self.assertTrue(runner.run(p,self.directory,s,t)['complete'])

    def test_committed_write_with_lost_response_resumes_without_replay(self):
        p=FakePlatform(537);s,t=self.prepare(p);p.lose_response=True
        with self.assertRaisesRegex(RuntimeError,'lost'):runner.run(p,self.directory,s,t)
        self.assertEqual(len(p.sent),400)
        # Simulate new interpreter and no browser temporary state.
        s,t=runner.load_task(self.directory)
        self.assertEqual(sum(x['state']=='unknown' for x in t['items'].values()),400)
        result=runner.run(p,self.directory,s,t)
        self.assertTrue(result['complete']);self.assertEqual(len(p.sent),537)

    def test_unknown_items_without_remote_proof_are_not_replayed(self):
        p=FakePlatform(8);s,t=self.prepare(p);p.lose_response=True;p.hidden.add(p.rows[0]['spuId'])
        with self.assertRaises(RuntimeError):runner.run(p,self.directory,s,t)
        s,t=runner.load_task(self.directory)
        result=runner.run(p,self.directory,s,t)
        self.assertFalse(result['complete']);self.assertEqual(result['counts']['unknown'],1);self.assertEqual(len(p.sent),8)

    def test_item_failure_isolated_and_retry_requires_explicit_option(self):
        p=FakePlatform(217);s,t=self.prepare(p);sid=p.rows[0]['spuId'];p.failed.add(sid)
        result=runner.run(p,self.directory,s,t)
        self.assertEqual(len(p.sent),217);self.assertEqual(result['counts']['rejected'],1);self.assertFalse(result['complete'])
        result=runner.run(p,self.directory,*runner.load_task(self.directory))
        self.assertEqual(len(p.sent),217);self.assertFalse(result['complete'])
        p.failed.clear();p.sent.remove(sid)
        result=runner.run(p,self.directory,*runner.load_task(self.directory),retry_failed=True)
        self.assertTrue(result['complete']);self.assertEqual(len(p.sent),217)

    def test_duplicate_or_short_page_rejected_before_writes(self):
        p=FakePlatform(237);p.rows[-1]=dict(p.rows[0])
        with self.assertRaisesRegex(RuntimeError,'duplicates'):self.prepare(p)
        self.assertFalse(p.sent)

    def test_expected_count_mismatch_does_not_authorize_more(self):
        p=FakePlatform(100)
        with self.assertRaisesRegex(RuntimeError,'does not match'):runner.prepare(p,self.directory,expected_count=99)
        self.assertFalse(p.sent)

    def test_identity_drift_and_wrong_remote_shop_do_not_pass(self):
        p=FakePlatform(5);s,t=self.prepare(p);p.erp='employee-b'
        with self.assertRaisesRegex(RuntimeError,'identity'):runner.run(p,self.directory,s,t)
        self.assertFalse(p.sent)
        p.erp='employee-a';p.active={r['spuId'] for r in p.rows};p.corrupt_identity=True
        with self.assertRaisesRegex(RuntimeError,'identity'):runner.run(p,self.directory,s,t)

    def test_stale_lock_is_not_silently_deleted(self):
        (self.directory/'run.lock').write_text('{"pid":12345}',encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'locked'):
            with runner.lock(self.directory):pass
        self.assertTrue((self.directory/'run.lock').exists())

    def test_empty_cli_output_cannot_look_like_success(self):
        class Proc:returncode=0;stdout='';stderr=''
        with patch.object(runner,'launcher',return_value=['synthetic-cli']),patch.object(runner.subprocess,'run',return_value=Proc()):
            client=runner.Client('task','tab')
            with self.assertRaisesRegex(RuntimeError,'response missing'):client.call({'op':'identity'})

    def test_local_preflight_failure_leaves_items_unsubmitted(self):
        p=FakePlatform(8);s,t=self.prepare(p)
        def too_big(q):raise RuntimeError('Command is too large')
        p.preflight=too_big
        with self.assertRaisesRegex(RuntimeError,'too large'):runner.run(p,self.directory,s,t)
        _,saved=runner.load_task(self.directory)
        self.assertTrue(all(x['state']=='pending' for x in saved['items'].values()));self.assertFalse(p.sent)

    def test_query_credentials_cannot_be_saved(self):
        p=FakePlatform(1)
        with self.assertRaisesRegex(RuntimeError,'credential'):
            runner.prepare(p,self.directory,query={'queryParam':{'dataSource':2,'token':'synthetic-secret'}})
        self.assertFalse((self.directory/'snapshot.json').exists());self.assertFalse(p.sent)

if __name__=='__main__':unittest.main()

"""Authenticated OSW invitations through a task-owned WebCLI page; no stored credentials."""
import argparse
import collections
import contextlib
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ALL_STATES = [30, 40, 99, 71, 72, 80, 90]
LABELS = {'pending': '未提交', 'submitting': '提交中', 'accepted': '接口成功待回查',
          'rejected': '业务失败', 'unknown': '结果未知', 'verified': '已邀约待升级', 'existing': '已有升级流程'}

def chunks(items, size):
    return [items[i:i+size] for i in range(0, len(items), size)]

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)

def launcher(override=None):
    if override:
        cmd = json.loads(override)
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
            raise ValueError('--launcher-json must be a nonempty JSON argv array')
        return cmd
    exe = shutil.which('o2')
    if not exe:
        raise RuntimeError('O2 not found; use the installed browser router and --launcher-json')
    helper = Path.home()/'.joycode/skills/o2/scripts/windows_launch.py'
    python = Path(exe).parent.parent/'python.exe'
    if os.name == 'nt' and helper.is_file() and python.is_file():
        return [str(python), '-X', 'utf8', str(helper), 'launch', 'webcli']
    return [exe, 'launch', 'webcli']

class Client:
    def __init__(self, session, tab, command=None, profile=None):
        if not session or not tab:
            raise ValueError('A task-owned --session and --tab are required')
        self.prefix = launcher(command)
        self.session, self.tab, self.profile = session, tab, profile
        self.engine = (ROOT/'scripts/api.js').read_text(encoding='utf-8')

    def command(self, request):
        script = '(async()=>{'+self.engine+'\nreturn await JXInvite.dispatch('+json.dumps(request, separators=(',', ':'), ensure_ascii=True)+');})()'
        cmd = self.prefix + (['--profile', self.profile] if self.profile else []) + ['browser', self.session, 'eval', script, '--tab', self.tab]
        if os.name == 'nt' and len(subprocess.list2cmdline(cmd)) > 30000:
            raise RuntimeError('Command is too large; reduce --group-size or inspect a compact current query')
        return cmd

    def preflight(self, request):
        self.command(request)

    def call(self, request):
        cmd = self.command(request)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=55, shell=False)
        if p.returncode:
            # Never print raw CLI diagnostics that may contain a request/header dump.
            raise RuntimeError('Browser operation failed; inspect login/connection and reconcile before retrying')
        if not p.stdout.strip():
            raise RuntimeError('Browser response missing; reconcile before retrying writes')
        try:
            result = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise RuntimeError('Browser response is not JSON; reconcile before retrying writes') from None
        if isinstance(result, dict) and ('error' in result or result.get('ok') is False):
            raise RuntimeError('Browser operation returned an error; inspect the task-owned page')
        return result

@contextlib.contextmanager
def lock(directory):
    path = directory/'run.lock'
    try:
        fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError('Task is locked; verify the recorded PID before clearing a stale run.lock') from None
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'pid': os.getpid(), 'started': time.time()}, f)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)

def validate_snapshot(pages, total, owner):
    rows = []
    expected_pages = (total+99)//100
    if len(pages) != expected_pages:
        raise RuntimeError('Incomplete page collection')
    for n, page in enumerate(pages, 1):
        expected = min(100, total-(n-1)*100)
        if page['pageNum'] != n or page['total'] != total or len(page['rows']) != expected:
            raise RuntimeError('Page count/size/total changed; capture a fresh scope')
        rows.extend(page['rows'])
    if len(rows) != total or len({r['spuId'] for r in rows}) != total:
        raise RuntimeError('SPU duplicates or pagination gaps')
    if any(r['erp'] != owner for r in rows):
        raise RuntimeError('ERP scope mismatch')
    return sorted(rows, key=lambda r:r['spuId'])

def prepare(client, directory, expected_count=None, query=None, group_size=4):
    if (directory/'snapshot.json').exists() or (directory/'state.json').exists():
        raise RuntimeError('Task already exists; resume it or use a new state directory')
    ident = client.call({'op': 'identity'})
    owner = ident['erp']
    if query is None:
        capture = client.call({'op': 'capture', 'expectedErp': owner})
        query = capture['query']
    if query.get('queryParam', {}).get('dataSource') != 2:
        raise RuntimeError('Current Jingxi query with dataSource=2 required')
    def credential_keys(value):
        if isinstance(value,dict):
            return any(any(word in str(k).lower() for word in ('cookie','token','password','authorization','apikey','device','signature')) or credential_keys(v) for k,v in value.items())
        return isinstance(value,list) and any(credential_keys(v) for v in value)
    if credential_keys(query): raise RuntimeError('Query contains credential/device fields; do not persist it')
    query = {'accessContext': {}, 'queryParam': query['queryParam']}
    query = json.loads(json.dumps(query)); query['queryParam'].update(pageNum=1, pageSize=100)
    first = client.call({'op': 'pages', 'expectedErp': owner, 'query': query, 'pages': [1]})[0]
    total = first['total']
    if expected_count is not None and expected_count != total:
        raise RuntimeError(f'Current count {total} does not match requested count {expected_count}')
    pages = [first] if total else []
    for nums in chunks(list(range(2, (total+99)//100+1)), group_size):
        pages.extend(client.call({'op': 'pages', 'expectedErp': owner, 'query': query, 'pages': nums}))
        emit({'phase': 'prepare', 'read': sum(len(p['rows']) for p in pages), 'total': total})
    rows = validate_snapshot(pages, total, owner)
    final = client.call({'op': 'pages', 'expectedErp': owner, 'query': query, 'pages': [1]})[0]
    if final['total'] != total or {r['spuId'] for r in final['rows']} != {r['spuId'] for r in first['rows']}:
        raise RuntimeError('Board changed during enumeration; prepare a fresh task')
    snapshot = {'schema': 'jx-invite-snapshot/v1', 'erp': owner, 'total': total, 'query': query,
                'createdAt': time.time(), 'rows': rows, 'pageTraces': [p['trace'] for p in pages]}
    state = {'schema': 'jx-invite-state/v1', 'erp': owner, 'items': {r['spuId']: {'state': 'pending'} for r in rows}, 'batches': []}
    write(directory/'snapshot.json', snapshot); write(directory/'state.json', state)
    emit({'phase': 'prepared', 'erp': owner, 'spuCount': total, 'canOperate': sum(r['canOperate'] for r in rows)})
    return snapshot, state

def load_task(directory):
    snapshot, state = read(directory/'snapshot.json'), read(directory/'state.json')
    if snapshot.get('schema') != 'jx-invite-snapshot/v1' or state.get('schema') != 'jx-invite-state/v1':
        raise RuntimeError('Unsupported task schema')
    ids = {r['spuId'] for r in snapshot['rows']}
    if len(ids) != snapshot['total'] or ids != set(state['items']) or snapshot['erp'] != state['erp']:
        raise RuntimeError('Snapshot/state scope mismatch')
    return snapshot, state

def reconcile(client, directory, snapshot, state, group_size=4):
    originals = {r['spuId']: r for r in snapshot['rows']}
    remaining = []
    proofs = []
    groups = chunks(list(originals), 100)
    for group in chunks(groups, group_size):
        rs = client.call({'op': 'records', 'expectedErp': snapshot['erp'], 'groups': group, 'statuses': [40, 99]})
        if not isinstance(rs, list) or len(rs) != len(group): raise RuntimeError('Record groups incomplete')
        for wanted, proof in zip(group, rs):
            found = set()
            for row in proof['rows']:
                sid = row['spuId']
                if sid not in wanted or sid in found or row['venderId'] != originals[sid]['venderId'] or row['shopId'] != originals[sid]['shopId']:
                    raise RuntimeError('Verification identity or filter mismatch')
                found.add(sid)
                state['items'][sid].update(state='verified', msg='', verifiedAt=proof['verifiedAt'], trace=proof['trace'])
            remaining.extend(s for s in wanted if s not in found)
            proofs.append({'ids': sorted(found), 'statuses': [40, 99], 'trace': proof['trace'], 'verifiedAt': proof['verifiedAt']})
        write(directory/'state.json', state)
    for group in chunks(chunks(remaining,100), group_size):
        rs = client.call({'op': 'records', 'expectedErp': snapshot['erp'], 'groups': group, 'statuses': ALL_STATES})
        if not isinstance(rs, list) or len(rs) != len(group): raise RuntimeError('Record groups incomplete')
        for wanted, proof in zip(group, rs):
            found = set()
            for row in proof['rows']:
                sid = row['spuId']
                if sid not in wanted or sid in found or row['venderId'] != originals[sid]['venderId'] or row['shopId'] != originals[sid]['shopId']:
                    raise RuntimeError('Verification identity or filter mismatch')
                found.add(sid)
                state['items'][sid].update(state='existing', msg='', verifiedAt=proof['verifiedAt'], trace=proof['trace'])
            proofs.append({'ids': sorted(found), 'statuses': ALL_STATES, 'trace': proof['trace'], 'verifiedAt': proof['verifiedAt']})
        write(directory/'state.json', state)
    confirmed = {sid for p in proofs for sid in p['ids']}
    for sid, row in state['items'].items():
        if sid not in confirmed and row['state'] in ('submitting', 'accepted', 'verified', 'existing'):
            row['state'] = 'unknown'
    state['verification'] = {'checkedAt': time.time(), 'count': len(confirmed), 'proofs': proofs}
    write(directory/'state.json', state)
    return confirmed

def report(directory, snapshot, state, board=None):
    counts = dict(collections.Counter(r['state'] for r in state['items'].values()))
    result = {'erp': snapshot['erp'], 'originalSpus': snapshot['total'], 'counts': counts,
              'verifiedSpus': state.get('verification', {}).get('count', 0),
              'complete': state.get('verification', {}).get('count', -1) == snapshot['total'],
              'board': board, 'batches': len(state['batches'])}
    write(directory/'result.json', result)
    fields = ['spuId','venderId','shopId','erp','shopName','productName','state','message']
    rows = [{**{k:r.get(k,'') for k in fields[:6]},'state':LABELS[state['items'][r['spuId']]['state']],
             'message':state['items'][r['spuId']].get('msg','')} for r in snapshot['rows']]
    for name, selected in [('result.csv',rows),('failures.csv',[r for r in rows if r['state'] in ('业务失败','结果未知','未提交','提交中')])]:
        with (directory/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(selected)
    emit(result)
    return result

def run(client, directory, snapshot, state, retry_failed=False, group_size=4):
    reconcile(client,directory,snapshot,state,group_size)
    rows = [r for r in snapshot['rows'] if state['items'][r['spuId']]['state']=='pending' or
            (retry_failed and state['items'][r['spuId']]['state']=='rejected')]
    eligible=[]
    for r in rows:
        if r['canOperate']: eligible.append(r)
        else: state['items'][r['spuId']].update(state='rejected',msg='Current board item is not operable')
    write(directory/'state.json',state)
    for groups in chunks(chunks(eligible,100),group_size):
        request={'op':'invite','expectedErp':snapshot['erp'],'groups':[[[r['spuId'],r['venderId'],r['shopId']] for r in g] for g in groups]}
        if hasattr(client,'preflight'): client.preflight(request)
        for r in sum(groups,[]): state['items'][r['spuId']].update(state='submitting',submittedAt=time.time())
        write(directory/'state.json',state)
        try:
            results=client.call(request)
            if not isinstance(results,list) or not results or len(results)>len(groups): raise RuntimeError('Invalid receipt group')
            returned_ids=set()
            for group,receipt in zip(groups,results):
                wanted={r['spuId'] for r in group}
                items=receipt.get('items',[])
                if {x['spuId'] for x in items}!=wanted or len(items)!=len(wanted): raise RuntimeError('Receipt IDs incomplete')
                for item in items:
                    if item['state'] not in ('accepted','rejected','unknown'): raise RuntimeError('Invalid receipt state')
                    state['items'][item['spuId']].update(item)
                    returned_ids.add(item['spuId'])
                state['batches'].append(receipt)
            for r in sum(groups,[]):
                if r['spuId'] not in returned_ids: state['items'][r['spuId']]['state']='pending'
            write(directory/'state.json',state)
            emit({'phase':'inviting','processed':sum(x['state']!='pending' for x in state['items'].values()),'total':snapshot['total']})
            if any(r.get('stop') for r in results): break
        except Exception:
            for r in sum(groups,[]):
                if state['items'][r['spuId']]['state']=='submitting':
                    state['items'][r['spuId']].update(state='unknown',msg='Response unavailable; reconciliation required')
            write(directory/'state.json',state)
            # Abort further writes if browser/account status cannot be established.
            raise
    reconcile(client,directory,snapshot,state,group_size)
    board=client.call({'op':'board','expectedErp':snapshot['erp'],'query':snapshot['query']})
    return report(directory,snapshot,state,board)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','run','verify','status'])
    p.add_argument('--state-dir',required=True);p.add_argument('--session');p.add_argument('--tab')
    p.add_argument('--profile');p.add_argument('--launcher-json');p.add_argument('--expected-count',type=int)
    p.add_argument('--query-file');p.add_argument('--apply',action='store_true');p.add_argument('--retry-failed',action='store_true')
    p.add_argument('--group-size',type=int,choices=range(1,5),default=4)
    a=p.parse_args();directory=Path(a.state_dir).expanduser().resolve()
    if directory==ROOT or ROOT in directory.parents: p.error('Task data must stay outside the public Skill folder')
    if a.action=='run' and not a.apply: p.error('run requires --apply after the user authorizes invitations')
    directory.mkdir(parents=True,exist_ok=True)
    with lock(directory):
        if a.action=='status':
            s,t=load_task(directory);report(directory,s,t);return 0
        client=Client(a.session,a.tab,a.launcher_json,a.profile)
        if a.action=='prepare':prepare(client,directory,a.expected_count,read(a.query_file) if a.query_file else None,a.group_size);return 0
        s,t=load_task(directory)
        if a.action=='run':result=run(client,directory,s,t,a.retry_failed,a.group_size)
        else:
            reconcile(client,directory,s,t,a.group_size)
            board=client.call({'op':'board','expectedErp':s['erp'],'query':s['query']})
            result=report(directory,s,t,board)
        return 0 if result['complete'] else 2

if __name__=='__main__':
    try: sys.exit(main())
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as e:
        emit({'ok':False,'error':str(e),'next':'Inspect the task-owned page and saved state; reconcile before another write.'})
        sys.exit(1)

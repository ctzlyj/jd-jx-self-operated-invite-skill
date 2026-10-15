const {test} = require('node:test');
const assert = require('node:assert/strict');
const api = require('../scripts/api.js');

function environment(handler, erp='employee-a') {
  global.location = {href:'https://osw.jd.com/cz/bundling/pop2Self/jxCenter'};
  global.fetch = async (url, init) => {
    assert.equal(init.credentials,'include');
    assert.equal(init.headers['dsm-platform'],'erp');
    assert.ok(!Object.keys(init.headers).some(x=>/cookie|authorization/i.test(x)));
    const name=new URL(url).searchParams.get('api');
    const payload=JSON.parse(init.body);
    let b;
    if(name.endsWith('getLoginUserInfo')) b={code:200,data:{erp}};
    else if(name.endsWith('queryCurrentRole')) b={code:200,data:4};
    else b=await handler(name,payload);
    return {status:200,json:async()=>b};
  };
}

test('a batch-level 200 does not hide an item failure or a missing result',()=>{
  const result=api.classify({code:200,data:{'101':{code:200},'102':{code:410,msg:'not configured'}}},['101','102','103']);
  assert.deepEqual(result.map(r=>r.state),['accepted','rejected','unknown']);
});

test('100-row contract keeps shop ID distinct from merchant ID',async()=>{
  let writes=0;
  environment((name,payload)=>{
    assert.ok(name.endsWith('batchInviteWareConvert'));writes++;
    assert.equal(payload.batchInviteWareParam.dataSource,2);
    const params=payload.batchInviteWareParam.inviteSpuParams;
    assert.equal(params.length,100);
    assert.equal(params[0].venderId,'77');assert.equal(params[0].shopId,'88');
    return {code:200,data:Object.fromEntries(params.map(r=>[r.spuId,{code:200,skuId:Number(r.spuId)}]))};
  });
  const group=Array.from({length:100},(_,i)=>[String(10000+i),'77','88']);
  const result=await api.dispatch({op:'invite',expectedErp:'employee-a',groups:[group]});
  assert.equal(writes,1);assert.equal(result[0].items.filter(x=>x.state==='accepted').length,100);
});

test('no hardcoded ERP: another colleague succeeds, identity drift prevents writes',async()=>{
  let writes=0;
  environment(()=>{writes++;return {code:200,data:{'101':{code:200}}};},'employee-b');
  const okay=await api.dispatch({op:'invite',expectedErp:'employee-b',groups:[[['101','77','88']]]});
  assert.equal(okay[0].items[0].state,'accepted');
  await assert.rejects(api.dispatch({op:'invite',expectedErp:'employee-a',groups:[[['102','77','88']]]}),/identity changed/);
  assert.equal(writes,1);
});

test('lost write response is unknown and remaining groups do not run',async()=>{
  let writes=0;
  environment(()=>{writes++;throw Error('lost response');});
  const result=await api.dispatch({op:'invite',expectedErp:'employee-a',groups:[[['101','77','88']],[['102','77','88']]]});
  assert.equal(writes,1);assert.equal(result[0].items[0].state,'unknown');assert.equal(result[0].stop,true);
});

test('batch over 100 or duplicate SPUs cannot be sent',async()=>{
  let writes=0;environment(()=>{writes++;return {code:200};});
  await assert.rejects(api.dispatch({op:'invite',expectedErp:'employee-a',groups:[Array.from({length:101},(_,i)=>[String(i+1),'7','8'])]}),/exceeds 100/);
  await assert.rejects(api.dispatch({op:'invite',expectedErp:'employee-a',groups:[[['101','7','8']],[['101','7','8']]]}),/Duplicate/);
  assert.equal(writes,0);
});

test('record filter must exclude unrequested IDs and truncated pages',async()=>{
  environment(()=>({code:200,data:{totalCount:2,data:[{productId:'101',venderId:7,venderShopId:8}]}}));
  await assert.rejects(api.dispatch({op:'records',expectedErp:'employee-a',groups:[['101']],statuses:[40,99]}),/Incomplete/);
  environment(()=>({code:200,data:{totalCount:1,data:[{productId:'999',venderId:7,venderShopId:8}]}}));
  await assert.rejects(api.dispatch({op:'records',expectedErp:'employee-a',groups:[['101']],statuses:[40,99]}),/filter mismatch/);
});

test('business failure is not treated as an empty store',async()=>{
  environment(()=>({code:201,msg:'try later',data:{data:[],totalCount:0,pageNo:1}}));
  await assert.rejects(api.dispatch({op:'pages',expectedErp:'employee-a',query:{queryParam:{dataSource:2}},pages:[1]}),/201/);
});

test('invitations only run on the Jingxi task page and source=2',async()=>{
  environment(()=>({code:200,data:{}}));
  global.location.href='https://osw.jd.com/cz/bundling/pop2Self/other';
  await assert.rejects(api.dispatch({op:'identity'}),/Jingxi OSW page/);
});

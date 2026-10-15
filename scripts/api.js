const JXInvite = (() => {
  const APIS = {
    identity: 'dsm.grow.shop.api.loginService.getLoginUserInfo',
    role: 'dsm.convert.api.ConvertRoleService.queryCurrentRole',
    pool: 'dsm.pop2self.ware.WareSmartSelectPoolService.pageSmartSelectSpu',
    invite: 'dsm.convert.ware.wareConvertWriteService.batchInviteWareConvert',
    records: 'dsm.pop2self.ware.WareConvertProcessService.pageConvertProcessSpu'
  };
  const text = value => String(value ?? '').slice(0, 500);
  const id = value => {
    if (!/^\d+$/.test(String(value ?? ''))) throw Error('Invalid business ID');
    return String(value);
  };
  const valid = b => b && Number(b.code) === 200;
  async function post(api, body, strict = true) {
    const r = await fetch('https://sff.jd.com/api?v=1.0&appId=KIDYWFCXF5QDE5TW3S0L&api=' + api, {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json', 'dsm-platform': 'erp'},
      body: JSON.stringify(body), signal: AbortSignal.timeout(14000)
    });
    const b = await r.json();
    if (r.status !== 200 || (strict && !valid(b))) {
      throw Error(JSON.stringify({http: r.status, code: b.code, msg: text(b.msg)}));
    }
    return b;
  }
  async function identity(expected) {
    const b = await post(APIS.identity, {request: {}});
    const erp = text(b.data?.erp);
    if (!erp || (expected && erp !== expected)) throw Error('ERP login missing or identity changed');
    return erp;
  }
  function page(b, pageNum, owner) {
    if (!valid(b) || !Array.isArray(b.data?.data)) throw Error('Invalid page response');
    const d = b.data;
    if ((d.pageNo ?? d.pageNum) !== pageNum || !Number.isInteger(d.totalCount) || d.totalCount < 0) {
      throw Error('Invalid page number/total');
    }
    const rows = d.data.map(r => {
      if (r.operAcctErp !== owner) throw Error('SPU belongs to another ERP');
      return {spuId: id(r.productId), venderId: id(r.venderId), shopId: id(r.venderShopId),
        erp: r.operAcctErp, canOperate: r.canOperate === true, skuNum: r.skuNum,
        pointDeductionState: r.pointDeductionState, productName: text(r.productName), shopName: text(r.venderShopName)};
    });
    return {pageNum, total: d.totalCount, rows, trace: text(b['dsm-trace-id'])};
  }
  async function capture(owner) {
    return await new Promise((resolve, reject) => {
      const proto = XMLHttpRequest.prototype, oldOpen = proto.open, oldSend = proto.send;
      const oldFetch = window.fetch;
      let finished = false;
      const cleanup = () => {proto.open = oldOpen; proto.send = oldSend; window.fetch = oldFetch; clearTimeout(timer);};
      const finish = (payload, b) => {
        if (finished) return;
        finished = true; cleanup();
        try {
          if (payload?.queryParam?.dataSource !== 2) throw Error('Not a Jingxi query');
          page(b, payload.queryParam.pageNum, owner);
          resolve({erp: owner, query: payload, total: b.data.totalCount});
        } catch(e) {reject(e);}
      };
      const fail = () => {if (!finished) {finished = true; cleanup(); reject(Error('Query capture unavailable; inspect current page request'));}};
      const timer = setTimeout(fail, 14000);
      proto.open = function(method, url) {this.__jxCaptureUrl = String(url); return oldOpen.apply(this, arguments);};
      proto.send = function(body) {
        if (this.__jxCaptureUrl?.includes(APIS.pool)) {
          let payload; try {payload = JSON.parse(body);} catch {}
          this.addEventListener('load', () => {try {finish(payload, JSON.parse(this.responseText));} catch {fail();}});
        }
        return oldSend.apply(this, arguments);
      };
      window.fetch = function(input, init) {
        const wanted = String(input).includes(APIS.pool);
        return oldFetch.apply(this, arguments).then(r => {
          if (wanted) r.clone().json().then(b => {try {finish(JSON.parse(init.body), b);} catch {fail();}}).catch(fail);
          return r;
        });
      };
      const query = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '\u67e5\u8be2');
      if (!query) {fail(); return;}
      query.click();
    });
  }
  async function records(ids, statuses) {
    if (ids.length > 100) throw Error('Record batch exceeds 100');
    ids = ids.map(id);
    const b = await post(APIS.records, {accessContext: {}, queryParam: {
      spuIdList: ids, pageNum: 1, pageSize: 100, dataSource: 2, convertStatusList: statuses
    }});
    if (!Array.isArray(b.data?.data) || b.data.totalCount !== b.data.data.length) throw Error('Incomplete record page');
    const rows = b.data.data.map(r => ({spuId: id(r.productId), venderId: id(r.venderId), shopId: id(r.venderShopId)}));
    if (rows.some(r => !ids.includes(r.spuId)) || new Set(rows.map(r=>r.spuId)).size !== rows.length) {
      throw Error('Record filter mismatch or duplicates');
    }
    return {rows, statuses, trace: text(b['dsm-trace-id']), verifiedAt: new Date().toISOString()};
  }
  function classify(b, ids) {
    const map = b.data && typeof b.data === 'object' && !Array.isArray(b.data) ? b.data : {};
    return ids.map(spuId => {
      const r = map[spuId];
      return {spuId, state: r && Number(r.code) === 200 ? 'accepted' : r && r.code != null ? 'rejected' : 'unknown',
        code: r?.code ?? b.code, msg: text(r?.msg ?? b.msg)};
    });
  }
  async function dispatch(q) {
    const url = new URL(location.href);
    if (url.hostname !== 'osw.jd.com' || !/\/cz\/bundling\/pop2self\/jxcenter\/?$/i.test(url.pathname)) {
      throw Error('Use a task-owned Jingxi OSW page');
    }
    const erp = await identity(q.expectedErp);
    if (q.op === 'identity') {
      const role = await post(APIS.role, {param2: {source: 2}});
      return {erp, role: role.data};
    }
    if (q.op === 'capture') return await capture(erp);
    if (q.op === 'pages') {
      if (q.query?.queryParam?.dataSource !== 2 || !q.pages?.length || q.pages.length > 4) throw Error('Invalid scan request');
      return await Promise.all(q.pages.map(async n => {
        const query = JSON.parse(JSON.stringify(q.query)); query.queryParam.pageNum = n; query.queryParam.pageSize = 100;
        return page(await post(APIS.pool, query), n, erp);
      }));
    }
    if (q.op === 'records') {
      if (!q.groups?.length || q.groups.length > 4) throw Error('Invalid record groups');
      return await Promise.all(q.groups.map(ids => records(ids, q.statuses)));
    }
    if (q.op === 'board') {
      if (q.query?.queryParam?.dataSource !== 2) throw Error('Invalid board scope');
      const b = await post(APIS.pool, q.query);
      return {total: b.data?.totalCount, trace: text(b['dsm-trace-id']), verifiedAt: new Date().toISOString()};
    }
    if (q.op === 'invite') {
      if (!q.expectedErp || !q.groups?.length || q.groups.length > 4) throw Error('Invalid authorized invitation');
      const all = q.groups.flat().map(row => id(row[0]));
      if (new Set(all).size !== all.length || q.groups.some(g => !g.length || g.length > 100)) throw Error('Duplicate IDs or batch exceeds 100');
      const results = [];
      for (const group of q.groups) {
        await identity(q.expectedErp);
        const params = group.map(([spuId,venderId,shopId]) => ({spuId:id(spuId),venderId:id(venderId),shopId:id(shopId)}));
        let b;
        try {
          b = await post(APIS.invite, {accessContext: {}, batchInviteWareParam: {
            inviteSpuParams: params, inviteSkuParams: null, dataSource: 2
          }}, false);
        } catch(e) {
          results.push({items: params.map(r=>({spuId:r.spuId,state:'unknown',msg:'Response unavailable; reconcile first'})), stop:true});
          break;
        }
        results.push({items: classify(b, params.map(r=>r.spuId)), code:b.code, bCode:b.bCode,
          trace:text(b['dsm-trace-id']), stop:!valid(b), finished:new Date().toISOString()});
        if (!valid(b)) break;
      }
      return results;
    }
    throw Error('Unknown operation');
  }
  return {dispatch, classify, page};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = JXInvite;

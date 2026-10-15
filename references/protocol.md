# 已验证接口合约

统一请求：页面 `fetch` POST `https://sff.jd.com/api?v=1.0&appId=KIDYWFCXF5QDE5TW3S0L&api=<api>`，`credentials: include`，JSON 请求体，`Content-Type: application/json`、`dsm-platform: erp`。只在 `osw.jd.com/cz/bundling/pop2Self/jxCenter` 任务页执行。该页面 `dataSource=2` 表示京喜自营；不得套用普通自营的 `1`。

|用途|api|请求|
|---|---|---|
|ERP 身份|`dsm.grow.shop.api.loginService.getLoginUserInfo`|`{"request":{}}`；`data.erp` 为当前 ERP|
|权限角色|`dsm.convert.api.ConvertRoleService.queryCurrentRole`|`{"param2":{"source":2}}`；不要硬编码角色值|
|SPU 选品分页|`dsm.pop2self.ware.WareSmartSelectPoolService.pageSmartSelectSpu`|`accessContext:{}`、当前页面的 `queryParam`，仅修改 `pageNum`/`pageSize`|
|邀请升级|`dsm.convert.ware.wareConvertWriteService.batchInviteWareConvert`|`accessContext:{}`、`batchInviteWareParam:{inviteSpuParams:[{spuId,venderId,shopId}],inviteSkuParams:null,dataSource:2}`|
|升级记录|`dsm.pop2self.ware.WareConvertProcessService.pageConvertProcessSpu`|`accessContext:{}`、`queryParam:{spuIdList,pageNum:1,pageSize:100,dataSource:2,convertStatusList:[...]}`|

读接口必须同时验证 HTTP 200、业务 `code=200`、完整分页、`totalCount` 和原始 SPU 集合。SPU 列表 `data.data` 包含 `productId`、`venderId`、`venderShopId`、`operAcctErp`、`canOperate`、`skuNum`。`shopId` 来自 `venderShopId`，不能用 `venderId` 替代；两者可能相等，但不普遍相等。

邀请响应顶层可能为 `code=200,msg=邀请转品处理完成`，`data` 则是以请求 SPU 编码为键的逐项 `{code,msg,skuId}`。其中 `skuId` 字段名字不能用于重定义本次 SPU 范围。仅对应键 `code=200` 的项记作接口成功；缺项、无法解析或响应丢失记作未知，逐项业务非 200 记作失败。不得因顶层成功忽略逐项失败。`410` 可能涉及扣点未配置，记录真实反馈，不代改扣点。

升级记录状态：`30` 审核中；`40/99` 待升级；`71/72` 升级中；`80/90` 已升级。回查优先 `[40,99]`；不在待升级集合的，再查询全部上述状态以识别已有流程，避免重复邀请。记录页中没有状态字段时，只报告查询过滤器能证明的阶段，不推断商家已接受。

全量邀约验收：所有原始 SPU 都匹配到远端升级记录，且 `venderId/venderShopId` 与原始清单一致，漏项和未知均为 0。全看板任务再读取原筛选，报告剩余总数；即使期间新增 SPU 使看板不为 0，也不能把新商品自动纳入已经冻结的原始范围。

页面临时变量会随刷新消失。清单、每次提交前状态、逐项回执均在本机任务目录原子保存；不依赖 `window.__job`。本合约来自一次实际运行，不保证平台永不更新。

# 后端接口 v6 调试实测记录(2026-08-13,curl 直接探测)

> 前缀 http://10.120.132.36:8005/ai-test;envelope 兼容 {code,msg} 与 {success,message}。
> 注(2026-08-19): 脚本前缀已改为 Nacos 动态发现(nacos-sdk-python,BACKEND_SERVICE_NAME 默认 ai-test),
> 失败回退固定地址 10.120.7.97:8005/ai-test;可 --prefix 显式覆盖。本页实测记录为历史调试依据,保持原样。
> 本文件是 v6.0 改版设计(两场景:AI 生成测试脚本 / AI 执行并修复已有脚本)的接口依据;


## GET /api/v1/web-test/config/detail
- 参数:sessionId 必填(用 $HERMES_SESSION_ID);**重复 resourceList=<resourceUid> 可选,按 resourceUid 过滤(OR 语义)**
- 实测:传 1234/7890(无效 uid)→ resourceList 空数组;不传 → 项目全部资源(35 项);传真实 uid → 仅匹配项
- 响应 data 字段(实测 keys):`playwrightConfig` / `globalSetup` / `resourceList:[{resourceUid, fileName, filePath}]`
- ⚠️ **不再有 baseUrl/configUid/projectUid 字段**(v5 的 fetch_config.py 打印它们会得到 None,需修)
- A05010 = 会话未绑定项目;设计/调试会话的 SID 通常未绑定(属正常),任务会话由前端创建才绑定

## GET /api/v1/web-test/function/resources?functionUid=<uid>(v6 新接口,修复场景用)
- 响应 data:`{functionUid, scriptList[], testPlanList[], testReportList[]}`
- 每项 `{webResourceUid, functionUid, resourceType(2脚本/3计划/4报告), resourceUid, fileName, filePath}`
- filePath 是 MinIO URL(`.../ai-test/webtest/resources/<functionUid>/<name>`),**直接 GET 可下载,无鉴权**(实测 200:spec 5.2K/plan 2K/report 5.7K)
- 无资源的 function 返回空数组,不是报错

## 上传:两个端点并存,形态不同(关键)
1. **POST /file/upload —— v6 新裸 MinIO 上传**
   - **只认 multipart `file` 一个 form 字段**;type/sessionId/functionUid 放 query 或 form 都返回 00001
   - 响应 data:`{status:"SUCCESS", uploadedFileName, minioObjectName, previewUrl, fileSizeByte, type:1}`
   - previewUrl = `http://...:9000/ai-test/file/<日期>/<hash>/<name>`;**无业务绑定**(不自动入库,需 function/save 同步)
2. **POST /api/v1/file/upload —— v5 业务上传(现技能在用)**
   - query: type/sessionId/functionUid + multipart file
   - 响应 data:`{sessionId, fileName, relativePath, url, type}`(字段是 `url` 不是 previewUrl)
   - **自动绑定 functionUid**:上传后立即出现在 function/resources 对应列表;实测**同名也追加不覆盖**(scriptList 会出新旧两条)

## POST /api/v1/web-test/function/save(v6 新接口,纯创建)
- JSON body;必填 folderUid、displayName(校验顺序 folderUid→displayName);projectUid 文档必填(未单独验证)
- relativePath/description/selectedTestCaseUids/selectedResourceUids/resourceList 均可选(空数组可)
- **body 带 functionUid 被忽略 —— 每次调用新建记录**,响应 data = 新 functionUid(前端预创建 vs save 创建的关系待业务确认)
- resourceList 项 `{resourceType:2|3|4, fileName, filePath}` 真实入库(实测 resourceType=2 → 出现在 scriptList)
- **无删除端点**:DELETE /function、POST/GET /function/delete 均 00001(路由不存在)→ 误建记录只能前端手动删

## envelope 语义(路由探测法)
- GET 一个 POST-only 路径:00002 "HTTP request method invalid" = **路由存在**(已进 handler);00001 = 路由不存在或 handler 内部错误;404 = 路径错
- 00001 可能是后端故障也可能是参数问题:换已知正确的调用形态(如 /api/v1/file/upload query 形态)对比定位

## 调试教训(重要)
- probe CREATE 类接口(如 function/save):校验错误(00004)= **未写入**;一旦 body 通过校验即**真写入**。探必填字段顺序从空 body 逐步加字段,出现 success 立即停
- 本次调试误建 4 条 displayName="调试" 的记录(2087800446231609344 / 2087800446441324544 / 2087800446617485312 / 2087800573679730688),且真实 function 2084556509673521152 的 scriptList 被塞入 22 字节 upload-probe.spec.ts —— 已向用户披露,等前端手动清理

# Playwright E2E 踩坑记录

> 由 SKILL.md「已知坑(必读)」独立而来(2026-08-13)。写定位器、排查失败前必读。

## 已知坑(必读)

### 页面探索与登录(方案 B 视角)
- **CLI 全流程是中文界面(实测)**:login.mjs 强制切简体中文,auth.json 的登录态是中文 UI("新增"/"确 定");probe 直接看到的就是中文界面,写测试定位器**不需要做中英文翻译**。个别选项 title 双语不同——设备类型 EN=`Three-phase Meter_V1.0.0`、CN=`三相电表_V1.0.0-标准`,设备模型 title 两种语言都是中文;拿不准时 probe 里 dump `.chint-select-item-option` 的 title 核对再写死。**标签页(tab)文案也可能不是直译**(设备类型页 CN=`私有设备类型`/`公共设备类型`——注意是"公共"不是"公有",CN 下新增按钮是 `button:has-text("新增")`)。写测试前用 probe dump 中文界面的 tab 文本/placeholder/分页文本,别按英文直译猜。
- **login.mjs v6.3 起 账号/项目空间从 global-setup.ts 读取(勿再硬编码/自动选空间)**:login.mjs 不再写死 dylinzl、也不再「选第一个 项目/ 开头的空间」——它在物化后的 `global-setup.ts`(后端下发,唯一事实来源)里解析账号(fill 字面量)与目标空间(`text=项目/...` 点击字面量),下拉只选该确切空间;目标空间不在可选列表就抛错退出(绝不回退到第一个选项,防误操作其他空间)。解析正则:`placeholder="请输入用户名"[\s\S]*?\.fill\('([^']+)'\)` / 密码同理 / 空间 `locator\('text=(项目/[^']+)'\)\s*\.click`。⚠️ 中间通配必须用 `[\s\S]*?`,不能用 `[^)]` 或 `[^']`——fill 前是 `"]').fill(`(含 `)` 和 `'`),排除字符类会把 `]` 后紧跟的 `)` 拦掉导致解析失败(2026-08-18 实测)。global-setup.ts 里账号/空间缺失或与账号归属不匹配时,login 会中止并列出可用空间,按提示核对,不要自动改选。
- **login.mjs 登录失败排查(2026-08-12 实测)**:登录页默认英文(placeholder "Please enter your account"、按钮 "Login"),login.mjs 先切中文再按中文 placeholder 填——若失败(URL 停在 /infraWeb/login),写调试脚本 dump 页面:`input` 的 id/placeholder、`button` innerText、`.rc-slider-captcha-button` 数量、语言切换项,确认实际状态再改脚本。稳定做法:按 `#userName`/`#password` ID 填(语言无关);切中文后提交按钮是 `button:has-text("登 录")`(不是 Login,写脚本时别混);滑块拖 ~500px 带随机 y 抖动(比 490px 直线更易过);登录成功标志 `text=个人信息`。⚠️ 多会话并发同账号时,登录态可能被其他实例顶掉(单点登录),登录后立即跑测试,被顶就重登。
- **global-setup.ts 判定 auth invalid 会 unlink auth.json**(CLI 冒烟报 "auth invalid and no DISPLAY" 即 token 被顶,重登即可)。
- **模块级路由 404 陷阱(/aiot 实测)**:顶层模块入口路径(如 `/aiot`、`/iotWeb/aiot`)可能只是**菜单壳**,主内容区渲染 "404";真实功能页在侧边 chint 菜单的子项下(如 `/iotWeb/physicalModel/deviceType`)。用户给的页面路径直接访问 404 时,先点 `.chint-menu-submenu-title` 展开子菜单,逐个 `.chint-menu-item` 探索找真实功能页,再设计测试。⚠️ `/aiot` 可能重定向到 `/infraWeb/aiot`(**平台级壳**:菜单只剩 平台日志/消息中心,主内容"镜像仓库(旧)"),那不是业务模块——AIOT 业务菜单要访问 `/iotWeb/aiot`。AIOT 模块菜单结构与设备类型页定位器见 `references/aiot-device-type-page.md`(2026-08-13 实测沉淀);更早历史可 session_search(2026-08-11 /aiot 会话)。

### 平台组件(chint)通用交互坑(与具体功能无关,任何表单/列表测试都适用)
- 下拉菜单项是 `.chint-select-item-option`(在 rc-virtual-list 内),`role=null`,`getByRole('option')` 匹配不到;选项用 `title` 属性定位。
- **选中值渲染在 input 的父容器 `.chint-select-content` 上,input.value 恒为空**——`getByRole('combobox')` + `toContainText` 断言必失败。正确断言:`page.locator('#<inputId>').locator('xpath=..')` 再 `toContainText`。
- **关闭的下拉面板选项残留在 DOM(display:none)**:选项 title 同名时全局定位会 strict violation。正确做法:`.chint-select-dropdown:has(#<inputId>_list) .chint-select-item-option[title="..."]`(每个 select 的面板含 role=listbox 且 id=<inputId>_list)。`filter({ visible: true })` 在面板开关动画瞬间不可靠,别用。
- 面板打开瞬间选项在虚拟列表里渲染有延迟,面板关联定位 + Playwright 自动等待即可,无需手工 sleep。
- **超长下拉虚拟滚动只渲染前几项**:选项上百时面板打开 DOM 里只有前几项,不滚动定位不到目标。正确做法:先对 input `fill()` 搜索关键字过滤出唯一选项,再点面板关联的 `.chint-select-item-option[title="..."]`。短列表则无需过滤。
- **下拉无搜索输入框时靠滚动定位(2026-08-13 数据洞察页设备选择实测)**:部分 select 面板没有搜索框(对 input fill 直接超时),只能滚动虚拟列表:循环 `holder.scrollTop += 300`(`.chint-select-dropdown:not([style*="display: none"]) .rc-virtual-list-holder`)直到 `[title="目标"]` 渲染,`scrollIntoView({block:'center'})` 后点击;scrollTop 不再变化即到底。另:该 select 选中后文本变为选项值(如设备名),重选时**勿**用 `filter({hasText:'设备选择'})` 定位(会超时),改用序号(`.chint-select` 第 N 个)或 input id。
- 工具栏按钮可能是下拉菜单(新增/导入等入口),点击后若跳转新页面,目标元素瞬间销毁要 waitForURL。
- 表单必填校验错误:`.chint-form-item-has-error`,错误文本在 `.chint-form-item-explain-error`(如 请输入xxx/请选择xxx)。多字段同时报错时裸断言会 strict violation,按 `.chint-form-item:has(#<inputId>) .chint-form-item-explain-error` 逐字段限定。
- **虚拟滚动表格(chint-table-tbody-virtual,antd/chint 大列表默认)**:数据行是 `div.chint-table-row`(在 `.chint-table-tbody-virtual-holder-inner` 内),**不是 tr**;`.chint-table-tbody tr` 只能匹配隐藏测量行(chint-table-measure-row)和占位行(chint-table-placeholder/"暂无数据")。probe 的 accessibility 快照把虚拟行显示为平铺文本,**掩盖真实 DOM 结构**——按直觉写 tr 定位器必挂。写不出定位器时在 probe 里用 `page.evaluate` dump 元素 class 名/祖先路径,再反推选择器(设备管理页实测定位:`.chint-table-tbody-virtual .chint-table-row`)。
- **并非所有大列表都走虚拟滚动(2026-08-13 设备类型页实测)**:该页是普通 tr 表格(`page.evaluate` 数得 plainTrs=11、virtualRows=0),`.chint-table-tbody tr`(排除 `.chint-table-measure-row`)= 表头+数据行,tr 定位器直接可用。写定位器前先用 probe 的 `page.evaluate` 数两种行数确认结构,别按"大列表默认虚拟"想当然。
- **分页器(chint-pagination)定位坑(设备类型页实测)**:总数文本在 `.chint-pagination-total-text`(如 "第 1-10 条/总共 17 条");上/下一页是 `<li title="上一页|下一页">` 的 `.chint-pagination-prev|next`,内部才是 `.chint-pagination-item-link` 按钮。**点击用 `.chint-pagination-next` / `.chint-pagination-prev`,不要用 `button:has(img[alt="right"])`**(箭头图标是 svg 不是 img,选择器匹配不到→超时)。总数断言用 `.chint-pagination-total-text` 的 innerText,不要依赖整个分页器容器的文本。
- **搜索 0 结果/无数据状态**:无结果时表格显示"暂无数据",且**分页器可能整体不渲染**(没有 .chint-pagination-total-text)——**不要断言 "总共 0 条"**(会等超时)。正确断言:`.chint-table-placeholder`(虚拟表格)或 `tr:has-text("暂无数据")`;裸 `text=暂无数据` 可能因文本重复或隐藏元素断言失败,用 `page.locator('text=暂无数据').first()` 仍可能踩 hidden/strict 坑,优先占位行类名定位。
- **chint 空态占位是 tr 且 innerText 文本重复(2026-08-13 设备类型功能库/列表搜索实测)**:空态占位是 `<tr class="chint-table-placeholder">`,单元格内含 `img[alt="暂无数据"]` + 文本"暂无数据",`innerText` = **"暂无数据暂无数据"**——`toHaveText('暂无数据')` 必失败,必须用 `toContainText('暂无数据')`。另外该占位 tr 在 tbody 内,断言"无数据行"时选择器要排除它(`tr:not(.chint-table-measure-row):not(.chint-table-placeholder)`),且**表头在 thead 不在 tbody**(功能库表格 tbody 仅 measure + placeholder 两行,计数为 0 才是无数据行)。
- **搜索回车后结果行异步渲染(2026-08-13 设备类型页实测)**:按 Enter 后分页总数先更新(约 1.5s),数据行稍后才渲染(约 3s)——用 `toContainText`/`toBeVisible` 等自动等待断言即可,不要手写固定 sleep 后同步读 DOM。
- **chint pro-table 表格多选(2026-08-13 设备类型页实测,任何带行选表格通用)**:行 checkbox `.chint-table-tbody tr:not(.chint-table-measure-row) .chint-checkbox-input`(点击要 force:true);表头全选是 `input[aria-label="Select all"]`(**中文界面 aria-label 仍是英文**);部分行选中时表头 span 带 `chint-checkbox-indeterminate` class(input.indeterminate=true),全选变 `chint-checkbox-checked`——半选断言用 `toHaveClass(/chint-checkbox-indeterminate/)`。选中提示条:`已选择/计数/项` 分属子元素,容器 `.chint-pro-table-alert-info-content` 的 innerText **无空格**(实测 \"已选择1项\"),断言用正则 `toContainText(/已选择\s*1\s*项/)` 或对 `.chint-pro-table-alert-info` 容器级文本,勿写带空格的 '已选择 1 项'(必挂)。「取消选择」按钮 `button:has-text(\"取消选择\")` 批量清空;清空后提示条整体不渲染,断言 `toHaveCount(0)`。

### 测试脚本编写(写/调试 spec 时的通用坑)
- **CSS 里 `:has-text(/regex/)` 行内正则报 "Unexpected token /"**:必须用对象形式 `locator('button', { hasText: /确\s*定/ })` 传 JS 正则,不要写进 CSS 字符串 `'button:has-text(/.../)'` —— 行内 `/regex/` 会被当纯 CSS 解析而抛 `Unexpected token "/" while parsing css selector`。(2026-08-18 实测)按钮文本带空格(「确 定」「取 消」)用 `{ hasText: /确\s*定/ }` 最稳。
- **别给关键成功断言套 `.catch(() => {})`(吞断言 = 隐藏失败)**:给「导入成功」这类关键判据加 `.catch(()=>{})` 会静默通过,后续断言变成唯一关卡,失败时报错很隐晦(如 toast 没出现却被卡在「弹窗未关」)。判据顺序应 = 先等成功态真的出现(真实 timeout 直接 `expect`),再断言后续 DOM(弹窗关闭/列表出现),让失败能精确归因。

### 物化/运行环境
- **工程师配置可能是 CR-only 行尾**(不是 CRLF):prepare 归一化必须 `.replace(/\r\n/g,'\n').replace(/\r/g,'\n')`,只处理 \r\n 会残留孤立 \r(JS 里能解析但产物脏,且破坏后续字符串替换)。
- **无本地 node_modules 时配置加载报 MODULE_NOT_FOUND('@playwright/test')**:playwright 配置加载器从配置目录向上解析,找不到全局安装。prepare.mjs 已内置 linkNodeModules():软链全局 @playwright/test、playwright、playwright-core 到会话 node_modules;共享根 `/opt/data/e2e/node_modules` 由 preflight 初始化同样命中(配置加载器向上解析,会话目录缺省时自动命中共享根)。
- **config 是 CJS 转译加载**:`import.meta` 不可用,用 `__dirname`。
- **下发配置可能指定非本机浏览器**(`browserName: 'msedge'` / `channel: 'msedge'` 等):本机只有 chromium,prepare.mjs 自动移除 browserName(非 chromium)与 channel 字段,统一用本机浏览器跑,不要尝试安装其他浏览器。
- **storageState 相对路径按 cwd 解析**,必须绝对路径——prepare 已注入 `path.join(CONFIG_DIR, 'auth.json')`。
- **auth.json 归属**:`$E2E_DIR/auth.json` 是 Playwright 的(每会话独立);/opt/data/auth.json 是 Hermes 的,混用会互相毁。
- **global-setup 自动登录分支**:无 DISPLAY 时已打补丁抛错指引,不要试图在无 X 时跑它。
- **cli 加 --reporter=list 会覆盖 json reporter**,报告不生成。
- **物化产物可能被"迟到的兄弟会话 cleanup"删掉(2026-08-13 实测)**:terminal 进程跨会话持久,`$HERMES_SESSION_ID` 可能是**上一次会话**的 sid(与当前对话 sessionId 不同),preflight 会直接复用旧会话工作区(auth/template 仍有效,通常无碍);但旧会话收尾的 cleanup.mjs 若在本次会话中途才跑完,会删掉 root 的 playwright.config.ts/global-setup.ts(甚至 tests/specs/report/),probe 突然 ENOENT。对策:probe/测试报配置文件缺失时先 `ls` 工作区核对,缺了直接 `node scripts/prepare.mjs` 重新物化(幂等),不要手工拼配置、不要以为是环境坏了。

### 后端接口相关
- `sessionId` 直接用环境变量 `$HERMES_SESSION_ID`(后端创建并认可,不关心格式),不要问用户、不要手工拼。
- `functionUid` 从用户输入消息中获取;消息未给或为 `xxxxxxxxxxxx` 等占位符时必须询问确认,不要猜测。
- 响应 envelope 有两种(`code/msg` 与 `success/message`),成功判定 `code=="200"` 或 `success==true`;后端 500 时统一返回 `{"success":false,"code":"00001","message":"System internal error"}`(探测/文档路径也可能命中,不代表端点存在)。
- **upload 业务失败形态(实测)**:缺参/坏参/会话未绑定时后端返回 HTTP 200 + `00001` 通用错误,不是 4xx;脚本 4xx 降级 form 模式仅按需保留。⚠️ **00001 ≠ 一定是客户端参数问题**——2026-08 实测对所有请求(用已注册的 configUid/projectUid 当 functionUid、缺文件 POST、text/plain 与 octet-stream 等)都返回同一 00001,属后端侧故障。上传遇 00001 按此排查:① GET 同一上传路径——返回 `00002 HTTP request method invalid` = 路由存在(已进 handler),404 才是路径不对;② 同 sessionId 调 config/detail 成功 = 会话绑定无碍;③ 用 config/detail 响应里的 configUid/projectUid(必然已注册)当 functionUid 重试,仍 00001 即排除 UID 问题 → 结论:后端存储/服务故障(如 MinIO 不可用),如实报告、不伪造 url、不跑 cleanup(保留 tests/specs/report 待后端恢复后重传)。
- config/detail 返回 `A05010 未找到该会话绑定的项目数据` = 会话未绑定项目,如实报告并停下询问用户。
- 静态资源 `filePath` 是完整 URL(MinIO,端口 9000),可直接 GET 下载(v6 **本地不下载**——URL 写进测试脚本,运行时由脚本下载到自身同目录,多环境通用;只有场景 B 的 fetch_resources.py 会下载后端产物到工作区)。
- **双上传端点并存(v6 实测)**:① `/file/upload` = 裸 MinIO 上传,**只认 file 一个 form 字段**(带 type/sessionId/functionUid 等任何业务参数都返回 00001),响应 `data.previewUrl`(无 sessionId/relativePath/url 字段),无业务绑定 → 场景 A 用,之后 function/save 建库;② `/api/v1/file/upload` = 业务上传(query: type/sessionId/functionUid + multipart file),响应 `data.url`(含 relativePath 形如 /webtest/resources/<functionUid>/...),**自动绑定 functionUid**(上传后立即出现在 function/resources 对应列表),**按类型整表替换**(实测:type=TEST_SCRIPT 上传即清空替换整个 scriptList,与文件名无关;TEST_PLAN/TEST_REPORT 各自隔离)→ 场景 B 用,修复后同名上传即覆盖,无需 function/save。新文档 curl 示例(/file/upload + previewUrl 形态)为真,但示例里"URL 带参数"是 Apifox 导出误导,参数一个都不能带。
- **function/save 纯创建(v6 实测)**:body 里的 functionUid 被忽略(传已存在的 uid 也新建),每次调用返回新 functionUid;必填 folderUid/displayName(校验顺序 folderUid→displayName),projectUid 文档必填,其余字段可选;参数校验失败(00004)不创建记录,**只有成功才创建** → 失败重试安全,不会重复建记录。无删除端点(/function/delete、DELETE method 均 00001 路由不存在),误建记录只能前端手动清。
- **config/detail 的 resourceList 查询参数 = 按 resourceUid 过滤(v6 实测)**:重复 `resourceList=<uid>` 是 OR 语义,传占位符/无效 uid 返回空数组(不是报错),不传返回项目全部资源;响应 data 只有 playwrightConfig/globalSetup/resourceList 三字段(**无 baseUrl/configUid/projectUid**),baseURL 需从 playwrightConfig 文本提取。
- **function/resources 新接口(v6 实测)**:`GET .../function/resources?functionUid=<uid>`,响应 data{functionUid, scriptList, testPlanList, testReportList}(resourceType 2/3/4),filePath 是 MinIO 公开 URL 可直接 GET 下载;无资源的 function 返回空数组(非报错);**scriptList 为空时场景 B 无法修复**,如实报告让用户确认 functionUid。
- **后端交互统一用技能 scripts/ 下的 Python 脚本**(fetch_config.py / fetch_resources.py / publish_artifacts.py / upload_artifact.py),不用 curl/heredoc;解释器固定 `/opt/hermes/.venv/bin/python3`。
- **config/detail 响应形态已变(v6,2026-08-13 实测)**:data 只有 playwrightConfig/globalSetup/resourceList,**不再有 baseUrl/configUid/projectUid**;重复 `resourceList=<resourceUid>` query 参数 = 按 resourceUid 过滤(OR),不传返回项目全部资源。
- **两个上传端点并存(v6 实测)**:`/file/upload` 是裸 MinIO 上传——**只认 file 一个 form 字段**,多余参数一律 00001,响应 `data.previewUrl`(无业务绑定);`/api/v1/file/upload` 是业务上传——query 带 type/sessionId/functionUid,响应 `data.url`,**自动绑定 functionUid 且同名追加不覆盖**。按场景选端点,别混。
- **function/save 是纯创建(v6 实测)**:必填 folderUid/displayName,body 里 functionUid 被忽略,每次调用新建记录并返回新 functionUid;resourceList{resourceType:2/3/4,fileName,filePath} 真实入库。**无删除端点**——探参时 body 一旦通过校验就真建记录(2026-08-13 误建 4 条"调试"记录只能前端手动删);探必填字段从空 body 逐步加,见 success 立即停。
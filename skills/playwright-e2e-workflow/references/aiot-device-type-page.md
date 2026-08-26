# AIOT 设备类型页(/iotWeb/physicalModel/deviceType)— 2026-08-13 实测沉淀

## 入口与路由
- `/aiot` → 重定向 `/infraWeb/aiot`:那是**平台级壳**(侧边菜单只有 平台日志/消息中心,主内容"镜像仓库(旧)"),不是 AIOT 业务模块。
- AIOT 业务模块访问 `/iotWeb/aiot`:侧边菜单结构 = 子菜单组 物模型/设备接入/数据存储/OTA升级 + 顶层直链项 设备类型/设备模型/设备管理/软网关/SD-Edge接入/设备模拟/规约中心/存储策略/数据洞察/固件管理/OTA任务。
- 设备类型页:标题"设备类型",中文界面。

## 已验证定位器(2026-08-13 本会话 probe + CLI 测试全绿)
- 标签:`page.locator('.chint-tabs-tab', { hasText: '私有设备类型' })` / `公共设备类型`;默认选中私有(断言用 `toHaveClass(/chint-tabs-tab-active/)`)。私有 17 条,公共 80 条(2026-08-13 多次实测稳定)。
- 搜索框:`page.getByPlaceholder('请输入名称 / 标识符')`(input[type=search],无 id)。**回车触发搜索**,无需点搜索按钮。清空后回车恢复全量。⚠️ 结果行异步渲染:分页先更新(≈1.5s),数据行后到(≈3s),断言用自动等待(toContainText/toBeVisible),勿 sleep 后同步读 DOM。
- 表格:**普通 tr 表格,非虚拟滚动**(实测 plainTrs=11、virtualRows=0;11 = 1 表头 + 10 数据行)。数据行 `.chint-table-tbody tr`(排除 `.chint-table-measure-row` 隐藏测量行);表头在 thead,不在 tbody。
- 无结果:`.chint-table-placeholder` 是 **tr 且 innerText="暂无数据暂无数据"**(img alt + 文本重复),**断言用 toContainText('暂无数据')**,勿用 toHaveText;**分页器整体不渲染**(勿断言"总共 0 条")。
- 分页:总数 `.chint-pagination-total-text`("第 1-10 条/总共 17 条");翻页 `.chint-pagination-next` / `.chint-pagination-prev`。末页时下一页带 `chint-pagination-disabled` class,边界断言用 `toHaveClass(/chint-pagination-disabled/)`(2026-08-13 CLI 测试已验证)。
- 按钮:新增 / 导出设备类型(会写库,功能测试默认不覆盖)。

## 设备类型详情页(/iotWeb/physicalModel/deviceType/detail?typeUid=<id>)
- 顶层 tabs:基础信息 / 设备类型功能库 / 设备模型列表 / 接入映射模板库。
- **设备类型功能库** 子标签(2026-08-13 实测,typeUid=1904038281829085184 即 privatewiweuie/www):`属性（1）`(默认激活)/`测点（0）`/`事件（0）`/`服务（0）`——注意**全角括号**。
- 点击空子标签(如 `测点（0）`)→ 表格 `.chint-table-placeholder` 显示"暂无数据"、无分页器、出现「新增测点」按钮(仅测点标签有)。
- 属性（1）标签计数 1 但实测表格 0 行(计数与行不一致,勿依赖属性行做断言)。
- 「点击无历史数据指标」用例落点 = 点击「测点（0）」空标签:本应用无「指标」元素、无「暂无历史数据」文案,空态统一「暂无数据」(2026-08-13 全模块扫描结论)。

## 已知数据(搜索/断言可复用)
- `privatewiweuie` → 名称 www,typeUid=1904038281829085184;搜索"总共 1 条"(2026-08-13 实测可用,详情页功能库 属性(1)/测点(0)/事件(0)/服务(0))。
- `privateMCB_NB2_1PN` → 名称"微型断路器(单相)_ln(测试)(1)"(全角括号);⚠️ 2026-08-13 二次实测搜索无结果(可能已不在私有列表),断言前先验证,勿直接复用。
- 公共标签首行:`public_testwzq` / 名称 testwzq。
- 无结果关键字:`zzz_not_exist_xxx_000`。

## 设备类型详情页(/iotWeb/physicalModel/deviceType/detail?typeUid=<uid>)(2026-08-13 实测)
- 入口:列表行操作列唯一按钮 `tr:not(.chint-table-measure-row) td:last-child button`(icon 为 icon-kejian 查看)→ **跳转新页面**(非弹窗/抽屉),URL 带 `typeUid=`。行点击本身无反应。
- 顶部 tabs(chint-tabs-tab):基础信息 / 设备类型功能库 / 设备模型列表 / 接入映射模板库。
- 基础信息:标识符/父类型/名称/领域/分类/创建时间/创建人/最后更新时间/变更人/描述 + 编辑按钮(渲染文本可能带空格,断言用 hasText 勿用全文匹配)。
- 功能库:子标签是 chint-tabs-tab,文案带**全角括号计数**「属性（N） 测点（N） 事件（N） 服务（N）」,默认激活属性;点 测点（0）/事件（0）/服务（0）空标签 → 空表「暂无数据」+ 对应新增按钮(新增测点/新增事件/新增服务)。属性/测点行**不可点击**(cursor:auto,行内无操作按钮)。示例类型 privatewiweuie(www,typeUid=1904038281829085184):属性1/测点0/事件0/服务0。
- 模型列表 tab:表头 标识符/名称/品牌/型号/ProductKey/设备数/最后更新时间;类型无模型 →「暂无数据」。
- 映射模板库 tab:「新增模板」按钮 +「暂无数据」。

## 列表多选交互(「树状图-多选+独立取消」用例落点,2026-08-13 实测)
- **AIOT 模块无 checkable 树组件**:全模块扫描 + 逐个弹窗/详情 tab 验证,唯一树形控件是「新增设备类型」弹窗的「领域」tree-select(`#control-hooks_domain`),但它是**单选**(class 含 `chint-select-single`,无 checkbox,节点 电力/水务/供热/公共,电力/水务 disabled)。「树状图-多选+独立取消」类用例在设备类型页的最接近落点 = **列表表格多选**(行含「父类型」列=层级语义)。
- 行 checkbox:`.chint-table-tbody tr:not(.chint-table-measure-row) .chint-checkbox-input`(10 个=当前页行数),点击需 `force: true`。
- 表头全选:`.chint-table-thead .chint-checkbox-input[aria-label="Select all"]`(**中文界面但 aria-label 是英文 Select all**);表头外层 span `.chint-table-thead .chint-checkbox`。
- 半选态:勾选 1~9 行时表头 span 带 `chint-checkbox-indeterminate` class(input.indeterminate=true),全选后变 `chint-checkbox-checked`;断言用 `toHaveClass(/chint-checkbox-indeterminate/)`。
- 选中计数:`.chint-pro-table-alert-info-content` innerText = **"已选择1项"无空格**(已选择/计数/项分属子元素),断言用 `toContainText(/已选择\s*1\s*项/)` 或 `.chint-pro-table-alert-info` 容器级文本,勿直接 toContainText('已选择 1 项')带空格(必挂)。
- 取消选择:`button:has-text("取消选择")` 批量清除;全部取消后 alert 容器**整体不渲染**(计数+按钮都消失,断言用 toHaveCount(0))。
- 空选态:无「已选择」文案、无「取消选择」按钮、表头无半选 class。

## 全模块扫描结论(2026-08-13)
- AIOT 全部 11 页(deviceType/equipmentModel/deviceManage/softGateway/edgeAccess/simulation/protocolCenter/policy/insights/firmwareList/tasks)**均无「指标」文本、无「暂无历史数据」文案**;空态统一为「暂无数据」。用例「点击无历史数据指标」在本模块无对应 UI——接这类用例先跑 `scripts/probe-sweep.mjs` 拿证据,别凭直觉猜页面。
- 设备详情(/iotWeb/deviceManage/deviceDetail?deviceKey=...,设备名 span 点击进入):tabs=基础信息/属性/测点/事件/服务;属性表 6 行 STRING 无值(安装位置/硬件版本号/软件版本号/产品系列/产品分类/设备SN),行不可点击;未激活设备测点 0 行;设备管理列表是虚拟滚动 `.chint-table-tbody-virtual .chint-table-row`(data-row-key=DeviceKey),设备名是 `.chint-typography chint_link` span。
- 数据洞察(/iotWeb/dataStorage/insights):设备选择=普通 .chint-select(选项 title=设备名);「数据选择」是 `<p>` 标签不是 select,测点面板需先选设备;聚合粒度 .chint-select;空态「暂无数据」。
- 菜单路径提取技巧:子菜单**展开后**才渲染 `data-menu-id="rc-menu-uuid-<path>"`;先逐个点 `.chint-menu-submenu-title` 展开,再从 DOM 提取路径直接 goto——比逐个点菜单项导航稳(点菜单项导航后菜单折叠,后续点击会 "element is not visible")。
- ⚠️ **设备接入子页真实路径是 `/iotWeb/deviceAccess/*`**(softGateway/edgeAccess/simulation/protocolCenter,2026-08-13 菜单 data-menu-id 实测);`/iotWeb/access/*` 是 404 猜测路径,勿用。数据存储/OTA 子页同理:`/iotWeb/dataStorage/*`、`/iotWeb/otaUpdate/*`(tasks 在 otaUpdate 下,不是 ota)。

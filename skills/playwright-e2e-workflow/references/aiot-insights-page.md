# AIOT 数据洞察页(/iotWeb/dataStorage/insights)— 2026-08-13 实测沉淀

> 「指标节点展示历史数据/点击无历史数据指标」类用例在本模块的唯一真实落点:整个 AIOT 模块无「指标」字样,「指标节点」= 本页左侧测点标签(`.chint-tag-checkable`),「点击指标」= 点测点 tag,「右侧曲线/标题/坐标轴」= 右侧图表区。接这类用例先读本文件 + `probe-sweep.mjs` 证据,再写 plan。

## 入口与布局
- 菜单:数据存储 → 数据洞察;页面标题「数据存储 / 数据洞察」,中文界面。
- 顶部:时间选择 radio(`.chint-radio-button-wrapper`:1h / 1D / 3D / 自定义)、设备选择(.chint-select)、重置。
- 中部配置列:「数据选择」是 `<p>` 标签**不是 select**(点击无面板);聚合算法 .chint-select(默认 none);聚合粒度 .chint-select(选测点前 disabled)。
- 左栏测点面板 **`.point-select`**(w-320px):搜索框 placeholder「输入测点进行搜索」+「已选择测点（0 / 5）」+ 重置按钮(chint-btn-link);下方 chint-collapse 每设备一项,header 含 设备名+DeviceKey。
- 右侧图表区:点测点后显示所选测点信息(chint-typography:设备名 / DeviceKey / 测点中文名如「A相电压」/ 标识符 Ua / 单位 V);无数据显示「暂无数据」+ 提示「针对单设备单测点,图表只能展示最多20000条数据。请确保选择的测点已配置存储策略并且是数值类型的。」(提示文案在无数据时始终存在)。
- 最下方「最新数据」表:表头 设备名称/DeviceKey/测点名称/测点标识符/测点值/单位/最后更新时间。

## 已验证定位器(交互链)
1. 选设备:`page.locator('.chint-select').first()`(页面第 0 个 select)点击 → 选项 `[title="设备名"]` 点击。⚠️ 选中后 select 文本变为设备名,重选时**勿**用 `filter({hasText:'设备选择'})`(超时),用序号定位。
2. 设备下拉虚拟滚动且**无搜索输入框**(实测 fill 超时):循环 `holder.scrollTop += 300`(`.rc-virtual-list-holder`)直到 `[title="目标"]` 渲染,`scrollIntoView({block:'center'})` 后 click;scrollTop 不再变化即到底。
3. 展开设备:`page.locator('.point-select .chint-collapse-header').first()`(aria-expanded=false 时点击)。
4. 点测点(指标节点):`page.locator('.point-select .chint-tag-checkable', { hasText: 'Ua' })`;选中后 class 含 `chint-tag-checkable-checked`;「已选择测点」计数递增(上限 5,全角括号 `（N / 5）`)。
5. 重置测点:`.point-select button`,hasText '重置'。

## 已知数据(2026-08-13)
- 设备共 15 个(下拉 title):E2E自动测试设备_26967102 / _26948478 / _26919691 / _26842832、e2e_新增设备_1786526839696 / _1786526823742、e2e_手动添加_设备_*×若干、协议网关001、MVP-Edge设备-勿删除、透传网关。
- **当前环境全部设备点测点后图表区均为「暂无数据」**(1h/1D/3D 时间窗都试过),无 canvas/svg 曲线——「展示曲线/标题坐标轴正确」的正常路径无法实机断言,只能落「点击后图表区出现测点信息」或空态断言;若用例必须验证曲线,需环境提供有历史数据的设备。
- 协议网关001 仅 3 个测点:test / tyy1231tyy / @online_status(其余 E2E 设备 100+ 测点)。
- 空态文案是「暂无数据」**不是**「暂无历史数据」——断言用真实文案,勿照抄用例预期。

## 相关
- 设备类型详情-功能库「测点（0）」空标签交互见 `references/aiot-device-type-page.md`(那是设备类型页,无曲线,别混淆)。
- 全模块「指标」扫描结论:AIOT 11 页均无「指标」/「暂无历史数据」文本。

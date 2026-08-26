# 设备管理页(/iotWeb/deviceManage)— 2026-08-14 实测沉淀

> 沉淀来源:2026-08-14 probe + CLI 测试 4/4 全绿(正常路径/校验失败/取消边界,两次运行均绿:06:30 与 07:17)。

## 入口与路由

- 模块 /iotWeb 下,页面标题「设备管理」,中文界面。
- 列表按钮(probe 实测):查询 / 重置 / 新增 / 导出设备。
- 列表搜索框(id 实测):`#deviceTypeName`(search)、`#deviceModelName`(search)、`#deviceName`(text,placeholder 请输入关键词搜索)。查询按钮触发搜索。
- 列表是**虚拟滚动表格** `.chint-table-tbody-virtual .chint-table-row`(data-row-key=DeviceKey);设备名是 `.chint-typography chint_link` span,点击进设备详情 `/iotWeb/deviceManage/deviceDetail?deviceKey=...`(详情页 tabs=基础信息/属性/测点/事件/服务,2026-08-13 已记于 aiot-device-type-page.md)。
- 分页:`第 1-10 条/总共 44 条`(2026-08-14 实测 44 条);翻页 `.chint-pagination-next/.prev`,页码链接 1-5。

## 新增设备流程(下拉入口,非直接弹窗)

- 点 `button:has-text("新增").first()` → 弹 `.chint-dropdown`,菜单项含「手动添加」(实测;是否还有其他菜单项未验证,勿写死)。
- 点 `.chint-dropdown-menu-item:has-text("手动添加")` → **跳转独立路由页** `/iotWeb/deviceManage/addDevice`(`page.waitForURL('**/iotWeb/deviceManage/addDevice')`),不是弹窗/抽屉。

## 添加设备页表单(/iotWeb/deviceManage/addDevice)— 定位器全部 CLI 实测

| 字段 | 定位器 | 说明 |
|---|---|---|
| 设备名称 | `input[placeholder="请输入设备名称，50以内的字符"]` | 无 id |
| 设备类型 | `#control-hooks_deviceTypeUid` | 普通 select;选项 `.chint-select-dropdown:has(#control-hooks_deviceTypeUid_list) .chint-select-item-option[title="三相电表_V1.0.0-标准"]` |
| 设备模型 | `#control-hooks_deviceModelUid` | **与类型联动**:先选类型才加载选项,点击前 `waitForTimeout(1500)`;选项 title 与类型同名(三相电表_V1.0.0-标准) |
| 时区 | `#control-hooks_timeZone` | **虚拟滚动大列表**,先 `fill('+08')` 搜索过滤,再点 `.chint-select-item-option[title="UTC+08:00"]` |
| 厂家 | `#control-hooks_manufacturer` | |
| SN | `#control-hooks_serialCode` | 唯一化:`TEST-SN-<时间戳后6位>` |
| 经度/纬度 | `#control-hooks_longitude` / `#control-hooks_latitude` | 如 120.123456 / 30.123456 |
| 描述 | `#control-hooks_description` | textarea |

- 下拉选项通用写法:`.chint-select-dropdown:has(#<控件id>_list) .chint-select-item-option[title="<选项>"]`(chint 控件选项带 title 属性)。
- 选中值断言:`page.locator('#<控件id>').locator('xpath=..')`(input 父容器)toContainText 选项文本。
- 按钮:**「确 定」/「取 消」带空格**,用 `button:has-text("确 定")` / `button:has-text("取 消")`。
- 提交成功:`.chint-message` 首个 toContainText('添加成功')(timeout 15s),随后 `waitForURL('**/iotWeb/deviceManage')` 回列表。
- 列表新增断言:首行 `.chint-table-tbody-virtual .chint-table-row` 首个 toContainText 设备名 + 未激活 + 设备类型。
- 必填校验(空表单点确定):4 个必填项各自 `.chint-form-item:has(<控件>) .chint-form-item-explain-error`,文案依次 请输入设备名称 / 请选择设备类型 / 请选择设备模型 / 请选择时区;页面不跳转、无成功 toast。

## 已知数据(2026-08-14 实测)

- 设备类型选项:三相电表_V1.0.0-标准(可选);时区:UTC+08:00。
- 列表共 44 条;无结果空态 `.chint-table-placeholder`(未见实测,沿用 chint 通用「暂无数据」)。
- 设备名称唯一化惯例:`E2E自动测试设备_<Date.now()后8位>`,避免与历史数据冲突。

## 注意

- **正常路径会真实写库**(添加设备),功能测试默认覆盖;取消/校验失败场景不写库。
- 设备详情页沉淀见 aiot-device-type-page.md「全模块扫描结论」条目,不在此重复。
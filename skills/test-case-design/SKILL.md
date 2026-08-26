---
name: test-case-design
description: 本技能用于功能测试用例全流程设计。基于业务方方法论，从需求分析、测试点提取、用例编写到用例评审，涵盖 API JSON 上传与文档生成。仅专注于编写测试用例，不涉及测试计划、测试策略或自动化脚本。
---

## 概述

本 skill 服务于功能测试用例生成全流程，通过 `sessionId` 串联多轮对话。当前会话的 `sessionId` 可以通过环境变量`HERMES_SESSION_ID`查询到。

---

## ⚠️ 安全规则（最高优先级，必须遵守）

> **这些规则适用于整个 skill 执行过程，任何情况下不得违反。**

1. **禁止输出环境变量值**：任何时候都**不得**向用户展示以下环境变量的值：
   - `NACOS_USERNAME`、`NACOS_PASSWORD`、`NACOS_SERVER_ADDRESSES`、`NACOS_NAMESPACE`
   - 任何包含 `TOKEN`、`PASSWORD`、`SECRET`、`KEY`、`CREDENTIAL` 的环境变量
   - 如调试需要提及，仅可说"已从环境变量读取"，不得展示具体值

2. **脚本输出过滤**：执行 Python/Shell 脚本后，如果脚本输出中包含敏感变量值，**必须在展示给用户前过滤或截断**（仅保留前 4 个字符 + `***`）。

3. **curl 命令脱敏**：如果必须展示 curl 或 API 调用命令，将 Token/密码/认证信息替换为 `{REDACTED}`。

4. **日志脱敏**：Python 脚本中打印环境变量时，仅打印变量名，不打印值；如需打印值做调试，仅打印前 4 字符 + `***`。

5. **API 响应过滤**：后端接口返回的响应中如包含 Token、密码、密钥等敏感字段，展示给用户前必须脱敏。

6. **禁止输出业务ID**：例如 `sessionId` `project_id` `user_id` `business_user_id` 不允许展示给用户。

---

## 临时文件管理规范

> **所有临时文件必须统一存放在 `/opt/data/tmp/test-case-design/{sessionId}/` 目录下，流程结束后统一清理。**

### 目录结构

```
/opt/data/tmp/test-case-design/{sessionId}/
├── requirements.pdf                     # 阶段一下载的需求文档
├── requirements.docx                    # 阶段一下载的需求文档（DOCX 格式时）
├── test_points_{batchNo}.md             # 阶段二输出的测试点清单
├── test_cases_{batchNo}.md              # 阶段三输出的测试用例（供阶段四评审用）
├── cases_payload.json                   # 阶段三生成的用例 JSON（持久化，评审通过后上传）
├── 待澄清需求清单_{batchNo}.md          # 阶段四生成的待澄清需求清单（Markdown 源文件）
├── 待澄清需求清单_{batchNo}.pdf         # 阶段四生成的待澄清需求清单（PDF）
├── 测试用例评审报告_{batchNo}.md        # 阶段四生成的测试用例评审报告（Markdown 源文件）
├── 测试用例评审报告_{batchNo}.pdf       # 阶段四生成的测试用例评审报告（PDF）
└── scripts/                             # 临时 Python 脚本（如有，必须放在此子目录下）
```

### 关键规则

- **严禁**在 `/opt/data/tmp/test-case-design/{sessionId}/` **以外的位置**创建临时文件或脚本
- 如确需创建临时脚本，必须写入 `{sessionId}/scripts/` 子目录
- 阶段五执行 `rm -rf "/opt/data/tmp/test-case-design/{sessionId}/"` 统一清理，确保不残留任何文件
- 能够执行本skill的脚本，尽量用terminal工具执行脚本，不要自己写脚本执行
---

## 入口判断

根据用户请求内容，自动识别当前处于哪个阶段：
- **阶段一（需求分析）**：用户提供 PDF/DOCX 下载链接 + "分析需求"/"理解需求"等关键词
- **阶段二（测试点提取）**：用户已确认需求 + "提取测试点"/"开始提取"等关键词
- **阶段三（用例编写）**：用户确认测试点 + "编写用例"/"生成用例"等关键词
- **阶段四（用例评审与上传）**：用户确认用例已完成 + "评审"/"上传"等关键词

## ⚠️ 反向排除规则（最高优先级，先于阶段识别执行）

本技能专注"功能测试用例"设计，**不接收也不处理 UI 测试平台的元数据字段**，不生成可自动运行的测试脚本。出现以下任一情况，**立即判定不属于本技能，转 `playwright-e2e-workflow`（场景A/B）**，不要进入本技能任何阶段：

1. 用户消息携带 UI 测试平台元数据字段（任一即为强信号）：
   - `projectUid` / `folderUid` / `displayName` / `relativePath` / `selectedTestCaseUids` / `selectedResourceUids` / `functionUid`
   - 或页面相对路径以 `/iotWeb`、`/webtest` 等平台路径开头
2. 用户句式明确指向自动化脚本生成，例如：
   - 「请帮我创建Web功能测试」
   - 「请帮我创建Web测试脚本」
   - 「请帮我执行并修改Web测试脚本」
   - 以及任何"创建/执行/编写/修复 Playwright 测试脚本"的表述
3. 需求产出物是可自动运行的脚本，而非供评审的功能用例

> 判别要点：先看消息是否携带 UI 平台元数据字段或"创建Web功能测试/Web测试脚本"句式，命中则直接转 playwright-e2e-workflow；只有用户明确要求"生成[功能]测试用例""提取测试点""用例评审"且需提供/分析需求文档时，才进入本技能流程。

---

## 阶段一：需求分析

### 1.1 提取关键参数
从环境变量`HERMES_SESSION_ID`获取`sessionId`,但是不要输入让用户看见。

从用户请求中提取：
- `docUrl`：需求文档的下载链接（通常在"下载"后面或 HTTP 链接格式）
- `fileFormat`：根据 URL 后缀自动识别文件格式（`.pdf` 或 `.docx`），如无后缀以用户说明为准

### 1.2 下载需求文档

**执行标准下载脚本,禁止直接使用curl下载命令**：

```bash
# 创建临时目录
rm -rf "/opt/data/tmp/test-case-design/{sessionId}/"
mkdir -p "/opt/data/tmp/test-case-design/{sessionId}/"

# 确定输出文件名（根据 URL 后缀）
OUTPUT_FILE="/opt/data/tmp/test-case-design/{sessionId}/requirements.{pdf或docx}"

# 执行下载脚本
python /opt/data/skills/test-case-design/scripts/download_requirements.py \
  --url "{docUrl}" \
  --output "$OUTPUT_FILE" \
  --session-id "{sessionId}"
```

### 1.3 解析需求文档

根据文件格式选择对应的解析方式：

**PDF 文件（`requirements.pdf`）**

```bash
python -c "
import fitz
doc = fitz.open('/opt/data/tmp/test-case-design/{sessionId}/requirements.pdf')
for page in doc:
    print(page.get_text())
"
```

**DOCX 文件（`requirements.docx`）**

```bash
python -c "
from docx import Document
doc = Document('/opt/data/tmp/test-case-design/{sessionId}/requirements.docx')
for para in doc.paragraphs:
    print(para.text)
# 同时提取表格内容
for table in doc.tables:
    for row in table.rows:
        print('\t'.join(cell.text for cell in row.cells))
"
```

### 1.4 需求分析（8维度框架）

按以下8个维度系统检查需求文档，标记每项：✅ 明确 / ⚠️ 模糊 / ❌ 缺失

| 维度 | 检查项 |
|------|--------|
| 1️⃣ 功能完整性 | 输入/输出/流程是否明确？前置/后置条件是否完整？ |
| 2️⃣ 逻辑一致性 | 需求间是否矛盾？同一概念定义是否一致？条件分支是否完整？ |
| 3️⃣ 边界清晰度 | 边界值是否明确？异常场景是否完整？超界处理是否明确？ |
| 4️⃣ 可测试性 | 需求是否可量化？验收标准是否明确？是否存在模糊词汇？ |
| 5️⃣ 数据完整性 | 字段定义是否完整？类型/长度/格式是否明确？约束是否明确？ |
| 6️⃣ 异常处理 | 异常场景是否完整？处理方式是否明确？容错机制是否明确？ |
| 7️⃣ 依赖关系 | 是否有外部依赖？前置条件是否明确？是否存在循环依赖？ |
| 8️⃣ 性能要求 | 响应时间/吞吐量/并发要求是否明确？（仅需求明确时检查） |

### 1.5 输出需求分析结果

向用户输出以下格式：

**第一部分：维度评估**

| 维度 | 评估 | 说明 |
|------|------|------|
| 功能完整性 | ✅/⚠️/❌ | 简要说明 |
| 逻辑一致性 | ✅/⚠️/❌ | 简要说明 |
| 边界清晰度 | ✅/⚠️/❌ | 简要说明 |
| 可测试性 | ✅/⚠️/❌ | 简要说明 |
| 数据完整性 | ✅/⚠️/❌ | 简要说明 |
| 异常处理 | ✅/⚠️/❌ | 简要说明 |
| 依赖关系 | ✅/⚠️/❌ | 简要说明 |
| 性能要求 | ✅/⚠️/❌/N/A | 简要说明 |

**第二部分：关键信息提取**

- 关键业务规则列表
- 约束条件列表

**第三部分：待澄清问题（如有）**

| 编号 | 维度 | 问题 | 我的理解 |
|------|------|------|---------|
| Q-001 | 边界清晰度 | ... | ... |

### 1.6 ⚠️ 强制停止与等待确认

**有待澄清问题时必须**：
1. ❌ 禁止自动进入下一步（测试点提取）
2. ❌ 禁止假设答案继续分析
3. ✅ 强制停止，等待用户确认
4. ✅ 用户回复前，不得执行任何后续操作

**用户回复后**：
- "是"/"继续" → 进入阶段二（测试点提取）
- "解释"/回答某个问题 → 补充需求后继续
- 部分回答、部分未回答 → 记录已澄清和未澄清状态，已确认的需求进入下一阶段，未澄清的标注为待定

---

## 阶段二：测试点提取

### 2.1 提取参数

- `sessionId`：会话Id,通过环境变量提取
- `batchNo`：生成 `yyyyMMddHHmmssSSS`（17位数字字符串）
- 已确认的需求内容（含用户已澄清的部分）
- 需求澄清状态：记录每个 Q-xxx 的处理结果
  - ✅ 已澄清：按澄清后的内容提取测试点
  - ❓ 未澄清：该需求点的测试点标注"待用户澄清"

### 2.2 按8维度提取测试点

按以下8个维度逐段阅读需求文档，提取测试点：

| 维度 | 检查项 |
|------|--------|
| 1️⃣ 功能维度 | 核心功能、辅助功能、业务规则 |
| 2️⃣ 数据维度 | 有效/无效范围、边界值、字段属性、格式限制 |
| 3️⃣ 场景维度 | 正向、异常、边界、特殊场景 |
| 4️⃣ 非功能维度 | 性能、安全、兼容性、易用性（仅需求明确时） |
| 5️⃣ 组合维度 | 多条件/多字段组合、正交设计 |
| 6️⃣ 状态转换维度 | 合法/非法转换、前置/后置条件 |
| 7️⃣ 并发维度 | 多用户并发、操作顺序、超时重试（仅需求明确时） |
| 8️⃣ 依赖维度 | 外部系统、模块间依赖、数据一致性 |

### 2.3 优先级与风险评估

| 优先级 | 定义 | 风险等级 | 定义 |
|--------|------|---------|------|
| 0 | 核心功能、主流程、数据安全、关键边界值 | 高 | 涉及金额、数据安全、核心业务 |
| 1 | 常用功能、关键分支、异常处理、重要边界场景 | 中 | 影响用户体验、可能导致数据错误 |
| 2 | 辅助功能、非关键边界场景、优化项、兼容性 | 低 | 界面显示、提示信息、优化项、兼容性问题 |

### 2.4 ⚠️ 强制约束

1. **严格基于需求文档提取** — 每个测试点必须标注来源（需求第X段），禁止猜测
2. **完整性检查** — 覆盖所有需求点（100%），提取后逐一对照需求文档
3. **数据验证规则** — 仅提取需求明确的规则，未明确时标注为"需求未明确"

### 2.5 输出测试点清单

按需求文档模块顺序输出，同一模块内按优先级排序（0 → 1 → 2）：

```markdown
## [模块名称]

1. [测试点名称]（0，高风险）
   来源：需求第X段
   - [子测试点1]
   - [子测试点2]

2. [测试点名称]（1，中风险）
   来源：需求第X段
   ...
```

输出后持久化到临时目录：

```bash
cat > "/opt/data/tmp/test-case-design/{sessionId}/test_points_{batchNo}.md" << 'EOF'
... (测试点清单内容) ...
EOF
```

最后向用户展示测试点清单并确认，用户确认后进入阶段三。

---

## 阶段三：用例编写

### 3.1 提取参数

- `sessionId`：会话标识
- `batchNo`：与阶段二相同的批次号
- 测试点清单：从 `/opt/data/tmp/test-case-design/{sessionId}/test_points_{batchNo}.md` 读取

### 3.2 应用8种测试设计方法

| 方法 | 说明 |
|------|------|
| 1️⃣ 等价类划分 | 有效等价类至少1个代表值，每个无效等价类至少1个用例 |
| 2️⃣ 边界值分析 | 最小值、最小值-1、最大值、最大值+1 |
| 3️⃣ 判定表法 | 多条件组合场景 |
| 4️⃣ 因果图法 | 输入条件与输出结果的因果关系 |
| 5️⃣ 状态迁移测试 | 覆盖所有合法状态转换路径 |
| 6️⃣ 场景法 | 基于用户真实使用场景 |
| 7️⃣ 正交试验设计 | 减少组合场景用例数量 |
| 8️⃣ 错误推测法 | 基于需求中明确提到的易错点进行测试 |

### 3.3 应用表单场景设计规则

当需求涉及新增/编辑表单时，必须按以下规则设计用例：

**① 完整正例用例（优先级:0）— 优先设计**

必须有一条用例逐字段列举具体数据：
- 新增表单：所有字段填写具体值 → 提交成功
- 编辑表单：修改所有字段为具体值 → 保存成功

```markdown
用例编号：TC-User-001
用例标题：新增用户-完整填写所有字段成功
所属模块：用户管理
优先级：0

前置条件：
- 系统已登录
- 打开新增用户表单

测试步骤：
1. 在姓名字段输入"张三"
2. 在邮箱字段输入"zhangsan@qq.com"
3. 在电话字段输入"13800138000"
4. 在地址字段输入"北京市朝阳区"
5. 在备注字段输入"VIP客户"
6. 点击提交按钮

预期结果：
- 页面提示"新增成功"
- 用户列表中出现新记录：姓名="张三"，邮箱="zhangsan@qq.com"，电话="13800138000"
```

**② 其他验证用例（优先级:1/2）— 可使用语义化描述**

必填字段验证、格式验证、边界值等用例：

```markdown
用例编号：TC-User-002
用例标题：新增用户-姓名为空提示必填
优先级：1

测试步骤：
1. 打开新增用户表单
2. 不填写姓名字段，填写其他必填字段
3. 点击提交按钮

预期结果：
- 页面提示"姓名为必填项"
- 表单不提交
```

**③ 编辑清除非必填项（优先级:2）— 仅编辑表单**

如果表单存在非必填项字段，必须设计一条清除所有非必填项并保存成功的用例。

### 3.4 应用集成场景设计

当多个模块/功能协同工作时，必须设计集成场景用例：

| 场景类型 | 检查项 |
|---------|--------|
| 数据流转 | 模块A输出→模块B输入是否正确？ |
| 状态同步 | 模块A状态变化是否同步到模块B？ |
| 异常处理 | 模块A异常时模块B如何处理？是否有回滚？ |
| 顺序依赖 | 操作顺序是否有要求？反向操作是否支持？ |
| 并发冲突 | 多个模块同时操作同一数据时是否有冲突？ |

**设计原则**：
- 每个集成用例验证一条数据流或状态转换
- 标注涉及的模块（如：订单模块+支付模块+库存模块）
- 前置条件包含各模块的初始状态
- 预期结果验证所有模块的最终状态

### 3.5 用例字段定义

每个用例包含以下8个字段：

| 字段 | 说明 | 必填 |
|------|------|------|
| 序号 | 用例在清单中的序号 | 是 |
| 用例编号 | 格式 `TC-[模块]-[序号]`，如 `TC_User_001` | 是 |
| 用例标题 | [动词+对象+预期]，如"验证用户名为空时提示必填" | 是 |
| 所属模块 | 功能模块名称 | 是 |
| 优先级 | 0/1/2 | 是 |
| 前置条件 | 具体的预置条件，编号列表 | 是 |
| 测试步骤 | 编号列表，每步一个具体操作。**必须给出具体输入值** | 是 |
| 预期结果 | 可观察、可验证的具体结果，与步骤对应 | 是 |

### 3.6 ⚠️ 输出规则

**规则一：必须为所有测试点设计用例（设计阶段覆盖率100%）**
- 禁止跳过任何测试点
- 一个测试点可能需要多个用例（如边界值的最小值、最大值、最小值-1、最大值+1）

### 3.7 持久化到临时目录

**生成 Markdown 格式用例文件（供评审用）**

```markdown
用例编号：TC-[模块]-[序号]
用例标题：[动词+对象+预期]
所属模块：[模块名称]
优先级：0/1/2

前置条件：
- [具体条件1]
- [具体条件2]

测试步骤：
1. [具体操作]
2. [具体操作]

预期结果：
- [可观察、可验证的具体结果]

---
```

持久化路径：`/opt/data/tmp/test-case-design/{sessionId}/test_cases_{batchNo}.md`

> ⚠️ **此时仅保存 md 文件，不用生成json文件和上传到后端。** json生成和上传在阶段四评审通过后执行。

### 3.8 用例自查

- [ ] 是否为所有测试点都设计了用例？（覆盖率目标 100%）
- [ ] 是否覆盖了正向 + 异常 + 边界场景？
- [ ] 每条用例的步骤是否使用了具体数据值（禁止"合法数据""正常输入"等模糊描述）？
- [ ] 预期结果是否可观察、可验证、可判定？
- [ ] 是否覆盖了所有优先级（0、1、2）？
- [ ] 是否设计了关键的集成场景用例？
- [ ] 是否有冗余用例（多个用例验证同一测试点）？
- [ ] 有表单时是否设计了完整正例用例？

### 3.9 并行用例编写（子 agent 加速 + 深度提升）
    
当测试点覆盖 2 个以上模块 或 用例总数预估 ≥ 25 条 时，建议启用并行模式以提升编写效率和质量。
    
####  3.9.1 触发条件
    
满足以下任一条件即可启用：
- 测试点清单涉及 ≥ 2 个功能模块（如"用户管理"+"订单管理"+"支付模块"）
- 预估用例数 ≥ 25 条
- 用户明确要求"加速"/"并行"（视用户意愿而定，不强求）
    
####  3.9.2 模块拆分规则
    
1. 按模块拆分：按 `/opt/data/tmp/test-case-design/{sessionId}/test_points_{batchNo}.md` 中的 ## [模块名称] 标题拆分子任务
2. 并行上限：同时 spawn 的子 agent 不超过 3 个（超出的串行排队执行）
3. 每个子任务的 context 中必须包含：
    - 该模块对应的需求原文片段
    - 该模块的测试点清单（含优先级 + 来源标注）
    - 8 种测试设计方法（3.2 节）+ 表单场景规则（3.3 节）+ 集成场景规则（3.4 节）
    - 用例字段定义（3.5 节）
    - "每个用例的测试步骤必须给出具体输入值/参数，禁止'输入合法数据''输入正常内容'等模糊描述"
    - 语言要求：respond in Chinese
    
####  3.9.3 用例编号防冲突
    
由于用例编号通过模块标识可以防止冲突，每个子agent把用例写入到独立的md文件中，后续由main agent执行汇总
    
    
####  3.9.4 合并后校验（main agent 执行）
    
合并后的完整用例清单必须通过以下检查：

| 检查项         | 说明                                             |
|----------------|--------------------------------------------------|
| ✅ 编号唯一    | 无重复编号                                       |
| ✅ 覆盖率 100% | 原测试点清单的每个点都有用例覆盖                 |
| ✅ 无冗余      | 同一测试点不应被多个用例重复覆盖                 |
| ✅ 模块完整性  | 所有模块的测试点都已编写                         |
| ✅ 具体数据    | 抽查各模块用例，测试步骤使用了具体值而非模糊描述 |

> 当不满足并行条件（单模块 / 用例少）= 走原有串行流程（3.2 → 3.7），无需启用子 agent。

---

## 阶段四：用例评审与上传

### 4.1 评审准备

- 读取阶段三的测试用例 MD 文件：`/opt/data/tmp/test-case-design/{sessionId}/test_cases_{batchNo}.md`
- 读取阶段二的测试点 MD 文件：`/opt/data/tmp/test-case-design/{sessionId}/test_points_{batchNo}.md`

### 4.2 独立评审（reviewer 子 agent）
    
####  4.2.1 为什么要用独立的 reviewer
  
main agent 自己评审自己编写的用例存在固有盲区：
- 编写时的思维惯性会带入评审（"我这么写是因为我当时考虑了 X"）
- 容易忽略"测试步骤使用了模糊描述"、"前置条件不够具体"等可执行性问题
- 覆盖率的"自己数"容易自我安慰
  
独立 reviewer 子 agent 的优势：
- reviewer 的 context 里只有"需求 + 用例"，没有"我当时为什么这么写"的负担
- 天然地从"执行者"的角度审视用例，更容易发现步骤模糊、数据缺失
- 角色反差更接近真实团队中的 QA Lead 评审 Tester
  
####  4.2.2 操作步骤
  
Step 1：整理 reviewer 输入
- 需求文档原文（关键片段）
- 测试点清单：/opt/data/tmp/test-case-design/{sessionId}/test_points_{batchNo}.md
- 待评审用例：/opt/data/tmp/test-case-design/{sessionId}/test_cases_{batchNo}.md

Step 2：spawn reviewer 子 agent

python
main agent 使用 delegate_task 派发独立的 reviewer

delegate_task(
    goal="""对以下测试用例进行 4 维度严格评审。

你的角色：独立测试用例评审专家 (Reviewer Lead)
你的任务：严格按 4 个维度（完整性、准确性、有效性、可执行性）评审，
          找出每个维度的具体问题，给出覆盖率数据和明确的"通过/不通过"结论。

特别注意：
1. 覆盖率 = (已覆盖测试点数 / 总测试点数) × 100%，≥98% 才算通过
2. "可执行性"维度 — 重点检查步骤是否用了具体输入值，
    禁止"输入合法数据""输入正常内容"等模糊描述
3. "有效性"维度 — 重点检查是否存在冗余用例，
    同一测试点不应被多个用例重复覆盖
4. 不要自我审查 — 严格按评审标准挑问题

输出格式要求：
不通过时（简化）：
- 覆盖率数据
- 缺失/问题场景列表（每条含：场景描述、优先级、建议用例标题、测试数据示例）
- 评审结论

通过时（完整）：
- 覆盖率数据
- 4 维度逐项评估 + 状态（✅/⚠️/❌）+ 说明
- 用例统计（按优先级分布）
- 豁免测试点说明（如有）
- 评审结论""",
    context=f"""## 需求片段
{requirements_snippet}

测试点清单
{test_points_content}

待评审用例
{test_cases_content}

评审标准
- 完整性: 覆盖率≥98%, 包含正+异+边, 所有P0/P1/P2
- 准确性: 预期结果与需求一致, 数据具体, 编号规范
- 有效性: 能发现缺陷, 无冗余, 原子性原则
- 可执行性: 步骤清晰, 有具体值, 前置可验证, 可独立执行

respond in Chinese
"""
)


Step 3：main agent 处理 reviewer 结果

| reviewer 结论            | main agent 动作                                                |
|--------------------------|----------------------------------------------------------------|
| ✅ 通过                  | 进入 4.6 上传环节                                              |
| ❌ 不通过 + 缺失场景清单 | 根据缺失场景补充用例 → 重新 spawn reviewer 复查 → 循环直到通过 |

> 注意：reviewer 子 agent 的 context 不能包含"main agent 写用例时的推理过程"，必须只有"需求原文 + 测试点清单 + 待评审用例"三样东西，保证 reviewer 无偏见。
  
####  4.2.3 reviewer 的 4 维度检查清单
  
| 维度            | 检查项                                                                   |
|-----------------|--------------------------------------------------------------------------|
| 1️⃣ 完整性检查   | 是否覆盖所有测试点？是否包含正向、异常、边界场景？覆盖率≥98%？           |
| 2️⃣ 准确性检查   | 预期结果是否与需求一致？测试数据是否合理、具体？用例编号是否规范？       |
| 3️⃣ 有效性检查   | 用例是否能发现缺陷？是否存在冗余用例？是否遵循原子性原则？               |
| 4️⃣ 可执行性检查 | 步骤是否清晰、无歧义？步骤是否给出了具体输入值？前置条件是否具体可验证？ |

> 关键区别：原 4.2 → 4.5 节（评审维度、覆盖率计算、判定循环、评审输出）改为由 reviewer 子 agent 执行，main agent 不再自己评审自己写的用例。4.6 以后的上传和文档生成流程不变。

### 4.3 覆盖率计算

```
覆盖率 = (已覆盖测试点数 / 总测试点数) × 100%
```

- 总测试点数：从 `test_points_{batchNo}.md` 中提取
- 已覆盖测试点数：逐用例核对，统计覆盖到的测试点

### 4.4 判定与循环

| 覆盖率 | 结果 | 动作 |
|--------|------|------|
| ≥ 98% | ✅ **评审通过** | 进入 4.6 上传环节 |
| < 98% | ❌ **评审不通过** | 列出缺失场景，回到阶段三补充 |

**循环流程**：
1. ❌ 评审不通过 → 列出缺失场景（每个场景含：测试点描述、优先级、建议用例标题、测试数据示例）
2. 回到阶段三 → 根据缺失场景补充用例，更新 `test_cases_{batchNo}.md` 和 `cases_payload.json`
3. 重新评审
4. 循环直到通过

**豁免机制**：剩余 < 2% 可豁免（极难构造环境、极低概率场景、需求未明确），但必须说明豁免原因。

### 4.5 评审输出

**评审不通过时（简化输出）：**

```markdown
【评审结果】：❌ 不通过
【覆盖率】：XX% (已覆盖 X/Y 个测试点)
【豁免测试点】：X 个
【评审次数】：第 N 次评审

**缺失场景：**
1. [场景描述]（0，边界场景）
   建议用例标题：验证...
   测试数据示例：...
```

**评审通过时（完整输出）：**

```markdown
## ✅ 评审结果

【评审结果】：✅ 通过
【覆盖率】：XX%
【豁免测试点】：X 个（如有）
【评审次数】：第 N 次评审

## 评审历史记录

| 评审轮次 | 覆盖率 | 用例数 | 结果 | 缺失场景 |
|---------|--------|--------|------|---------|
| 第1次 | XX% | X个 | ❌ | ... |
| 第2次 | XX% | X个 | ✅ | — |

## 测试用例统计

| 指标 | 数值 |
|------|------|
| 用例总数 | X 条 |
| 0（高） | X 条 |
| 1（中） | X 条 |
| 2（低） | X 条 |

## 测试覆盖分析

| 维度 | 状态 | 说明 |
|------|------|------|
| 完整性 | ✅/⚠️/❌ | 覆盖了所有功能点，包含正向+异常+边界 |
| 准确性 | ✅/⚠️/❌ | 预期结果与需求一致，数据具体 |
| 有效性 | ✅/⚠️/❌ | 无冗余用例，遵循原子性原则 |
| 可执行性 | ✅/⚠️/❌ | 步骤清晰，前置条件可验证 |

## 豁免测试点说明（如有）

| 测试点 | 豁免原因 |
|--------|---------|
| ... | 极难构造环境 / 极低概率场景 / 需求未明确 |
```

### 4.6 ✅ 通过后：上传用例到后端

**根据评审修改后的md文件生成 API JSON 文件，注意不要忘记batchNo字段**

按 `references/examples/format-spec.md` 中的 JSON 格式生成 `cases_payload.json`：

```bash
# 使用 Python 脚本生成 JSON 文件（推荐，避免手动拼接 JSON）
python -c "
import json
# ... 组装用例 JSON ...
with open('/opt/data/tmp/test-case-design/{sessionId}/cases_payload.json', 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print(f'用例已持久化: {len(cases)} 条')
"
```

**使用标准上传脚本**（自动完成 Nacos 服务发现 + API 调用）：
```bash
python /opt/data/skills/test-case-design/scripts/upload_cases.py \
  --payload-file "/opt/data/tmp/test-case-design/{sessionId}/cases_payload.json"
```

> **脚本说明**：`scripts/upload_cases.py` 自动完成：
> - 从环境变量读取 Nacos 配置
> - 通过 Nacos 发现健康的后端服务实例
> - 读取本地 JSON 文件并 POST 到 `/api/v1/testcase/save`
> - 打印上传结果
>
> **上传失败处理**：检查错误信息后可直接重新执行上述命令（JSON 文件仍存在），无需重新生成用例。

### 4.7 PDF 文档生成（两步法）

按以下两步法生成 PDF 文档。

---

#### 4.7.1 工作流程

```
Step A: Agent 用 Python（textwrap.dedent + .replace()）生成 .md 文件
    ↓
Step B: 调用 /opt/data/skills/test-case-design/scripts/md_to_pdf.py 将 .md 转换为 .pdf
```

---

#### Step A：生成 Markdown 文件

按对应的模板结构，用 Python **安全模式**生成 Markdown 字符串并写入文件。

##### ⚠️ 安全模式规则（禁止使用 f-string 拼接模板）

```python
# ✅ 正确做法：textwrap.dedent + .replace()
import textwrap
from pathlib import Path

# 1) 用普通字符串定义模板，所有 {xxx} 只是普通字符
md_content = textwrap.dedent("""\
# 待澄清需求清单

## 基本信息

| 项目 | 内容 |
|------|------|
| 批次号 | {batchNo} |
| Session ID | {sessionId} |
""")

# 2) 用显式 .replace() 填充——只有写了的 {xxx} 才会被替换
md_content = md_content.replace("{batchNo}", batch_no)
md_content = md_content.replace("{sessionId}", session_id)

# 3) 输出 .md 文件到临时目录
output_path = Path("/opt/data/tmp/test-case-design/{sessionId}/待澄清需求清单_{batchNo}.md")
output_path.write_text(md_content, encoding="utf-8")
```

```python
# ❌ 错误做法（禁止）：f-string 拼接模板
# 下面的代码极易出现未定义变量、漏转义 {} 等问题：
md_content = f"""
| 批次号 | {batchNo} |     ← 如果 batchNo 变量名拼错 → NameError
"""

# ❌ 错误做法（禁止）：内联 python -c 执行带大量特殊字符的代码
```

**注意**：涉及时间，一律转成东八区的时间。用 `datetime.now(timezone.utc)` 加上 8 小时。

##### 文档命名规范

| 文档类型 | MD 文件名 | PDF 文件名 |
|---------|----------|-----------|
| 待澄清需求清单 | `待澄清需求清单_{batchNo}.md` | `待澄清需求清单_{batchNo}.pdf` |
| 测试用例评审报告 | `测试用例评审报告_{batchNo}.md` | `测试用例评审报告_{batchNo}.pdf` |

---

#### Step B：调用固化脚本转换 PDF

```bash
# 转换待澄清需求清单
python /opt/data/skills/test-case-design/scripts/md_to_pdf.py \
  --input-md "/opt/data/tmp/test-case-design/{sessionId}/待澄清需求清单_{batchNo}.md" \
  --output-pdf "/opt/data/tmp/test-case-design/{sessionId}/待澄清需求清单_{batchNo}.pdf" \
  --css "references/templates/pdf-style.css"

# 转换测试用例评审报告
python /opt/data/skills/test-case-design/scripts/md_to_pdf.py \
  --input-md "/opt/data/tmp/test-case-design/{sessionId}/测试用例评审报告_{batchNo}.md" \
  --output-pdf "/opt/data/tmp/test-case-design/{sessionId}/测试用例评审报告_{batchNo}.pdf" \
  --css "references/templates/pdf-style.css"
```

> **脚本说明**：`scripts/md_to_pdf.py` 自动完成：
> - 校验输入 `.md` 文件是否存在
> - 自动创建输出目录（如不存在）
> - 校验 CSS 文件（不存在则 warn 回退到无样式渲染，不阻断流程）
> - 调用 md2pdf 转换，带完整的异常捕获和错误提示
> - Exit code 0=成功，1=参数/文件错误，2=转换异常

#### PDF样式

默认 CSS 样式文件 `references/templates/pdf-style.css`，已配置好中文排版、表格样式、页眉页脚等。如果 `--css` 指定的文件不存在，脚本会自动降级并打印警告。

---

### 4.8 上传文档到后端

**使用标准上传脚本**（自动完成 Nacos 服务发现 + 文件上传）：

```bash
# 上传待澄清需求清单（用户没有澄清或者新发现的需求和测试点，整理成清单，必须有）
if [ -f "/opt/data/tmp/test-case-design/{sessionId}/待澄清需求清单_{batchNo}.pdf" ]; then
  python /opt/data/skills/test-case-design/scripts/upload_file.py \
    --file "/opt/data/tmp/test-case-design/{sessionId}/待澄清需求清单_{batchNo}.pdf" \
    --session-id "{sessionId}" \
    --batch-no "{batchNo}" \
    --type CHECKLIST
fi

# 上传测试用例评审报告
python /opt/data/skills/test-case-design/scripts/upload_file.py \
  --file "/opt/data/tmp/test-case-design/{sessionId}/测试用例评审报告_{batchNo}.pdf" \
  --session-id "{sessionId}" \
  --batch-no "{batchNo}" \
  --type REPORT
```

> **重要**：记录上传接口返回的 `data.url`，后续总结中需要展示给用户。

---

## 阶段五：清理与总结

### 5.1 清理临时文件
清理临时文件之前做一个简单的自我审查
1. 是否正常上传了所有生成的用例？
2. 是否正常上传了待澄清需求和评审报告两个pdf文件？格式是否渲染正常

```bash
rm -rf "/opt/data/tmp/test-case-design/{sessionId}/"
```

> **目标**：统一清理 `/opt/data/tmp/test-case-design/{sessionId}/` 整个目录，确保不残留 PDF、DOCX、JSON、MD 和临时脚本文件，保持本地环境干净。

### 5.2 返回总结

向用户输出以下格式的总结：

```markdown
## 功能测试用例生成完成

| 项目 | 详情 |
|------|------|
| 批次号 | {batchNo} |
| Session ID | {sessionId} |
| 用例总数 | X 条 |

### 用例分布
| 维度 | 分布 |
|------|------|
| 按优先级 | 0(X), 1(X), 2(X) |
| 按模块 | 模块A(X), 模块B(X), ... |

### 用例上传
| 项目 | 状态 |
|------|------|
| 上传用例 | ✅ 成功 / ❌ 失败（{原因}） |

### 文档上传
| 文档 | 状态 | 链接 |
|------|------|------|
| 待澄清需求清单 | ✅ 已上传 | [查看]({url}) |
| 测试用例评审报告 | ✅ 已上传 | [查看]({url}) |
```

---

## 能力边界

✅ 可生成：功能测试（含表单验证、状态流转、业务规则、集成场景、边界值、异常场景）
❌ 不可生成：接口测试、AI Agent 测试、性能测试、兼容性测试、渗透测试、测试方案、测试策略、测试计划、自动化脚本

> ⚠️ 若用户请求含 UI 平台元数据字段（projectUid/folderUid/relativePath/displayName 等），或表述为「请帮我创建Web功能测试」/「请帮我创建Web测试脚本」等 Playwright 脚本相关，应转 `playwright-e2e-workflow`，详见顶部「反向排除规则」。

---

## 关键规则速查

| 规则 | 说明 | 参考文件 |
|------|------|---------|
| 安全规则 | 禁止输出 NACOS_* 等环境变量值，敏感字段必须脱敏 | 见顶部 ⚠️ 安全规则 |
| 临时文件 | 所有临时文件统一放在 `/opt/data/tmp/test-case-design/{sessionId}/`，流程结束统一清理 | 见顶部 临时文件管理规范 |
| 步骤必须具体 | 测试步骤中必须给出具体输入值/参数，不得使用描述性语言 | 3.5 用例字段定义 |
| 编号规则 | 用例编号 `TC-[模块]-[序号]`，如 `TC_User_001` | 3.5 用例字段定义 |
| 优先级 | 0=核心功能、1=常用功能、P2=辅助功能、优化项 | 2.3 优先级与风险评估 |
| 覆盖率要求 | 设计阶段 100%，评审阶段 ≥98%（<2% 可豁免） | 阶段三/四 |
| 分阶段输出 | 用例数≥25时，每25-30个用例输出一次进度 | 3.6 输出规则 |
| 评审循环 | 覆盖率<98%时循环补充，直到通过 | 4.4 判定与循环 |
| 用例持久化 | 阶段三同时输出 MD（供评审）和 JSON（备上传）到临时目录 | 3.7 持久化 |
| 上传时机 | 评审通过后才上传用例到后端，失败可重试 | 4.6 |
| JSON 格式 | 按 API JSON Schema 输出，type固定为1（功能测试） | `references/examples/format-spec.md` |
| 文档下载脚本 | 使用 `scripts/download_requirements.py`（内置重试+URL编码） | `scripts/download_requirements.py` |
| 用例上传脚本 | 使用 `scripts/upload_cases.py`（Nacos服务发现） | `scripts/upload_cases.py` |
| 文件上传脚本 | 使用 `scripts/upload_file.py`（multipart/form-data） | `scripts/upload_file.py` |
| PDF 生成脚本 | 使用 `scripts/md_to_pdf.py`（两步法：MD→PDF） | `scripts/md_to_pdf.py` |

## 参考文件索引

### 脚本文件
| 文件 | 用途 |
|------|------|
| `scripts/download_requirements.py` | 统一的需求文档下载脚本（内置重试 + 中文 URL 编码） |
| `scripts/md_to_pdf.py` | 稳定的 Markdown → PDF 转换脚本 |
| `scripts/discover_and_call.py` | Nacos 服务发现 + REST API 调用通用模块（可导入复用） |
| `scripts/upload_cases.py` | 用例上传脚本（从 JSON 文件读取，自动发现服务） |
| `scripts/upload_file.py` | 文件上传脚本（multipart/form-data，自动发现服务） |

### 模板与规范
| 文件 | 用途 |
|------|------|
| `references/templates/pdf-style.css` | PDF 默认样式（配合 md2pdf 使用） |
| `references/examples/format-spec.md` | API JSON 输出格式规范（type 固定为 1） |
| `references/templates/clarification-checklist.md` | 待澄清需求清单模板 |
| `references/templates/review-report.md` | 测试用例评审报告模板（含 4 维度评审 + 覆盖率 ≥98%） |

### 运行环境
| 文件 | 用途 |
|------|------|
| `references/runtime-setup.md` | 脚本依赖安装（nacos-sdk-python 2.0.x + md2pdf/weasyprint）与 venv 执行方式 |
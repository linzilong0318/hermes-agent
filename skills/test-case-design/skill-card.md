## Description

这项技能帮助用户完成功能测试用例全流程设计：从 PDF/DOCX 需求文档下载与解析、8 维度需求分析、测试点提取、用例编写与评审，到 API JSON 上传与文档生成。全程基于业务方方法论，涵盖需求分析 8 维度检查、测试点提取 8 维度扫描、8 种测试设计方法、表单场景设计规则、集成场景设计，以及 4 维度用例评审（覆盖率 ≥98% 循环通过）。仅专注于编写测试用例，不涉及测试计划、测试策略或自动化脚本。

This skill is ready for commercial/non-commercial use.

## Publisher

[cassianran](https://clawhub.ai/user/cassianran)

### License/Terms of Use

MIT-0

## Use Case

- 从 PDF/DOCX 需求文档下载到最终测试用例上传的全流程自动化
- 需求分析阶段：8 维度系统检查（功能完整性、逻辑一致性、边界清晰度、可测试性、数据完整性、异常处理、依赖关系、性能要求），有待澄清问题时强制停止等待确认
- 测试点提取阶段：8 维度提取测试点，P0-P3 优先级 + 风险等级评估，严格标注需求来源
- 用例编写阶段：8 种测试设计方法 + 表单规则（完整正例、清空非必填等）+ 集成场景设计
- 用例评审阶段：4 维度评审（完整性、准确性、有效性、可执行性），覆盖率 ≥98%，循环直到通过，支持豁免机制
- API JSON 上传至后端服务，MD 转 PDF 文档生成与上传
- 统一临时文件管理和安全脱敏

## Features

- PDF/DOCX 需求文档下载与解析（内置重试+中文 URL 编码）
- 8 维度需求分析框架 + 强制停止确认机制
- 8 维度测试点提取 + P0-P3 优先级/风险评估
- 8 种测试设计方法（等价类、边界值、判定表、因果图、状态迁移、场景法、正交试验、错误推测）
- 表单场景设计规则（完整正例、编辑清空等）+ 集成场景设计
- 4 维度用例评审 + 覆盖率 ≥98% + 循环通过 + 豁免机制
- API JSON 格式输出 + Nacos 服务发现上传
- 两步法 PDF 文档生成（MD → md2pdf 转换，消除 f-string 错误）
- Session 串联多轮对话，批量加解密 sessionId
- 严格的安全脱敏规则（环境变量、Token、业务 ID）
- Hermes Agent 环境兼容

## FAQ

### 必须确认的需求？
有，需求分析阶段的待澄清问题必须经用户确认后才能进入下一阶段。

### 能否同时处理多个会话？
能，通过 sessionId 区分。

### Hermes Agent 下使用有什么注意事项？
必须先加载 hermes-env-pitfalls skill，否则可能出现写文件拒绝等问题。本项目已默认使用 `/opt/data/tmp/` 解决 `/tmp/` 权限问题。

## Dependency

- pymupdf（PDF 解析）
- python-docx（DOCX 解析）
- md2pdf + weasyprint（PDF 生成）
- Nacos SDK（服务发现）
- Python 3.10+

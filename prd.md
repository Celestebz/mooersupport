# MOOER 客服系统 PRD

## 1. 文档目的

本文档用于定义 MOOER 客服系统的产品需求。

系统目标不是单纯做“AI 自动回邮件”，而是建立一套可追踪、可复核、可统计、可协同的客服工作台，覆盖从邮件接入、AI 分类、草稿生成、人工审核、售后问题归并、内部汇报、研发协同、模板管理到批量统一回复的完整流程。

## 2. 背景与问题

当前售后邮箱中存在大量用户咨询和问题反馈，包括技术支持、固件升级、连接问题、保修维修、配件购买、注册解绑、商务合作、投诉等。

现有处理方式存在以下问题：

- 邮件数量多，人工逐封判断和回复效率低
- AI 分类结果不稳定，容易把技术问题误判为商务合作、感谢或无需回复
- 产品型号识别不稳定，标题中有产品名但数据库中显示未识别
- 回复模板有错误知识时风险很高，例如错误固件步骤会误导用户
- 同一个产品问题被多个用户重复反馈，但系统没有稳定的问题归并和统计
- 内部汇报需要人工整理用户邮箱、问题描述、证据片段和影响范围
- 研发提供解决方案后，无法方便地统一通知所有相关用户
- 已解决问题没有沉淀为可复用知识，后续同类邮件仍需重复处理

## 3. 产品目标

### 3.1 核心目标

1. 提高客服处理效率，减少重复劳动
2. 保证 AI 回复可审核、可追溯、可纠错
3. 对用户邮件进行稳定分类和产品识别
4. 对同类售后问题进行归并统计
5. 支持客服向内部研发/销售/售后团队生成结构化汇报
6. 支持研发方案沉淀为统一回复模板
7. 支持同一问题批量通知关联用户
8. 建立用户邮箱维度的售后跟进记录

### 3.2 非目标

MVP 阶段不追求完全无人值守自动发送。AI 可以生成建议、草稿和分类，但高风险场景必须允许人工审核。

## 4. 用户角色

### 4.1 客服人员

主要使用系统处理邮件、审核 AI 草稿、修正分类、归并问题、建立模板、生成内部报告、批量回复用户。

### 4.2 客服主管

主要查看统计报表、高频问题、未处理邮件、AI 误判情况、模板质量和团队处理进度。

### 4.3 研发人员

主要接收结构化问题报告，查看用户证据，确认问题原因，提供解决方案。

### 4.4 销售/经销商团队

主要处理购买渠道、库存、经销商、商务合作和区域售后转交问题。

## 5. 系统总览

```text
邮箱同步
  -> 邮件解析
  -> AI 分类与产品识别
  -> 邮件收件箱
  -> AI 草稿生成
  -> 人工审核/发送
  -> 售后问题归并
  -> 问题待解决队列
  -> 内部报告/通知研发
  -> 研发方案
  -> 统一回复模板
  -> 批量通知用户
  -> 知识库沉淀
```

## 6. 功能模块

## 6.1 邮件同步模块

### 功能说明

系统从客服邮箱同步邮件，保存到本地数据库，并记录邮件状态。

### 需求

- 支持 IMAP 同步
- 支持读取发件人、主题、正文、时间、附件
- 支持识别已读/未读
- 支持去重
- 支持同步失败日志
- 支持重复邮件标记
- 支持手动重新同步

### 邮件状态

| 状态 | 说明 |
|---|---|
| `new` | 新邮件，尚未处理 |
| `drafted` | 已生成草稿 |
| `skipped` | 已跳过或无需自动处理 |
| `human_review` | 需要人工审核 |
| `no_reply_needed` | 明确无需回复，仅限垃圾/无关等低风险场景 |
| `failed_retry` | 处理失败，待重试 |
| `sent` | 已发送 |

## 6.2 邮件解析模块

### 功能说明

将原始邮件正文整理成适合 AI 分析的内容。

### 需求

- 清理 HTML 标签
- 提取当前用户新写内容
- 保留必要历史引用
- 识别附件
- 提取用户邮箱
- 提取可能的订单号、序列号、产品型号
- 支持多语言邮件

### 注意

不能完全丢弃历史引用，因为很多用户回复只写 “still not working”，真正的问题在历史邮件中。

## 6.3 AI 分类模块

### 功能说明

AI 对每封邮件输出结构化分类结果。

### 输出字段

```json
{
  "product_model": "Prime P2",
  "mail_category": "technical_support",
  "issue_category": "app_usb_bluetooth_connection",
  "reply_template_category": "troubleshooting_steps",
  "confidence": 0.86,
  "evidence_snippet": "I can't connect my device to the Mooer Prime iOS app.",
  "matched_reason": "The user mentions Prime P2 and app connection failure.",
  "needs_human_review": false
}
```

### 邮件一级分类 mail_category

| 分类值 | 中文名称 | 说明 |
|---|---|---|
| `technical_support` | 技术支持 | 连接、使用、功能、设备异常 |
| `firmware_update` | 固件升级 | 升级失败、升级后异常、版本问题 |
| `warranty_repair` | 保修维修 | 维修、退换、硬件损坏 |
| `parts_purchase` | 配件购买 | 配件、备件、报价、运费 |
| `registration_account` | 注册账号 | 注册、解绑、序列号、账号 |
| `sales_stock` | 售前库存 | 购买渠道、库存、产品咨询 |
| `feedback_suggestion` | 反馈建议 | 功能建议、产品反馈 |
| `complaint` | 投诉不满 | 强烈负面、投诉、服务升级 |
| `customer_followup_ack` | 用户跟进或确认 | 用户补充信息、确认、感谢，不能默认无需回复 |
| `business_media` | 商务媒体 | 合作、评测、经销商、媒体 |
| `spam_irrelevant` | 垃圾无关 | 垃圾邮件、无关推广 |
| `unclassified` | 未分类 | AI 无法稳定判断，报告中放最后 |

### 纠偏规则

- 用户说谢谢，不代表无需回复
- 商务合作类中如果明确出现产品故障、连接失败、固件失败，应纠偏为技术支持或固件升级
- 标题和正文有产品名时，不能显示产品未识别
- AI 分类必须保存依据和证据片段

## 6.4 产品识别模块

### 功能说明

识别邮件中的 MOOER 产品型号，并统一为官方名称。

### 需求

- 支持官方产品名
- 支持别名和不规范写法
- 支持大小写、空格、连字符差异
- 支持标题和正文共同识别
- 支持人工修正产品型号
- 支持别名表维护

### 示例别名

| 用户写法 | 标准产品 |
|---|---|
| `GE150Pro` | `GE150 Pro` |
| `GE 150 Pro` | `GE150 Pro` |
| `Prime 2` | `Prime P2` |
| `Mooer P2` | `Prime P2` |
| `GS1000 Li` | `GS1000Li` |
| `Gs1000` | `GS1000` |
| `gente 250` | `GE250` |

## 6.5 AI 草稿生成模块

### 功能说明

根据邮件内容、产品型号、问题类型、模板和说明书知识生成客服回复草稿。

### 需求

- 生成英文客服邮件
- 支持引用产品说明书
- 支持引用保修政策
- 支持引用配件报价
- 支持模板辅助生成
- 支持生成失败重试
- 支持坏草稿检测
- 支持人工编辑后发送

### 草稿安全规则

- 不允许输出 JSON、工具调用、分析过程
- 不允许编造产品功能
- 不允许引用错误模板
- 不允许把不适用某产品的按键步骤写给用户
- 涉及退款、法律、强烈投诉、大额赔偿必须人工审核

## 6.6 回复模板模块

### 功能说明

管理客服常用回复模板。

### 模板字段

- 模板 ID
- 模板名称
- 模板大类
- 产品型号
- 问题分类
- 语言
- 模板正文
- 状态
- 更新时间

### 模板分类

| 模板大类 | 用途 |
|---|---|
| `Technical/Usage Question` | 技术和使用问题 |
| `Firmware Update` | 固件升级 |
| `Repair/Warranty` | 维修保修 |
| `Parts/Accessories Purchase` | 配件购买 |
| `Registration Unbinding` | 注册解绑 |
| `Software Installation` | 软件安装 |
| `Amazon Purchase Issues` | Amazon 购买问题 |
| `Feedback/Suggestion` | 反馈建议 |
| `Complaint/Frustration` | 投诉安抚 |

### 错误模板规则

明确错误模板必须删除，不只是停用。

示例：

Prime 系列没有 `SELECT` 键，因此包含 `Hold the "SELECT" button and turn on the "POWER."` 的 Prime 固件模板必须删除。

### 模板审核要求

- 涉及固件步骤的模板必须绑定具体产品
- 涉及按键组合的模板必须确认产品确实有该按键
- 通用模板不能包含具体产品专属操作
- 模板被 AI 命中时必须记录模板 ID

## 6.7 售后问题归并模块

### 功能说明

将多封用户邮件归并为同一个售后问题。

### 示例场景

100 个用户反馈：

```text
GS1000 - balance output issue
```

系统处理逻辑：

1. AI 识别产品为 `GS1000`
2. AI 识别问题为 `audio_output_noise`
3. 生成问题签名 `gs1000_balance_output_issue`
4. 将 100 个用户邮箱挂到同一个问题下
5. 先发送首次安抚邮件
6. 问题进入待解决队列
7. 客服通知研发
8. 研发提供解决方案
9. 客服建立统一回复模板
10. 系统批量回复这 100 个用户
11. 后续同类问题直接复用解决方案

### 问题状态

| 状态 | 说明 |
|---|---|
| `new_detected` | 新发现 |
| `collecting_reports` | 正在收集反馈 |
| `waiting_rnd` | 等待研发 |
| `rnd_in_progress` | 研发处理中 |
| `solution_ready` | 解决方案已就绪 |
| `bulk_replying` | 批量回复中 |
| `resolved` | 已解决 |
| `monitoring` | 已解决但继续观察 |
| `duplicate` | 合并到其他问题 |

### 用户-问题状态

| 状态 | 说明 |
|---|---|
| `linked` | 已关联 |
| `initial_ack_pending` | 待首次安抚 |
| `initial_ack_sent` | 已首次安抚 |
| `waiting_solution` | 等待方案 |
| `final_reply_pending` | 待最终回复 |
| `final_reply_sent` | 已最终回复 |
| `manual_followup` | 人工跟进 |
| `excluded_from_bulk` | 排除批量回复 |
| `bounced` | 邮件发送失败 |

## 6.8 问题待解决队列

### 功能说明

客服和主管查看所有高频、未解决、待研发的问题。

### 列表字段

- 问题标题
- 产品型号
- 问题分类
- 影响用户数
- 关联邮件数
- 首次出现时间
- 最近反馈时间
- 状态
- 优先级
- 研发状态
- 是否已有最终模板

### 操作

- 查看详情
- 合并问题
- 修改优先级
- 修改状态
- 通知研发
- 创建最终回复模板
- 批量回复用户

## 6.9 问题详情页

### 功能说明

查看单个售后问题的完整上下文。

### 页面内容

- 问题摘要
- 产品型号
- 问题分类
- 状态和优先级
- 关联用户邮箱
- 关联邮件主题
- 证据片段
- AI 判断理由
- 置信度
- 低置信度待复核列表
- 首次安抚模板
- 研发方案
- 最终回复模板
- 发送记录

## 6.10 内部汇报模块

### 功能说明

自动生成给研发、销售、管理层看的结构化报告。

### 报告必须包含

- 问题名称
- 产品型号
- 问题分类
- 影响用户数
- 关联邮件数
- 具体用户邮箱
- 邮件主题
- 证据片段
- AI 置信度
- 首次出现时间
- 最近反馈时间
- 当前客服动作
- 需要内部确认的问题

### 示例

```text
产品：GS1000
问题：Balance output issue
影响用户数：100
关联邮件数：112
状态：等待研发
优先级：高

典型证据：
1. user1@example.com - balanced output stopped working after update
2. user2@example.com - XLR output has no signal
3. user3@example.com - GS1000 balanced output no sound

需要研发确认：
1. 是否为固件问题？
2. 是否与最近版本升级有关？
3. 是否有临时解决方案？
4. 是否需要发布新固件？
5. 是否可以给用户统一回复？
```

## 6.11 批量回复模块

### 功能说明

当某个问题已有解决方案后，客服可批量通知所有关联用户。

### 需求

- 预览回复内容
- 查看待发送用户邮箱列表
- 支持排除部分用户
- 支持标记已单独处理用户
- 支持发送后记录状态
- 支持失败重试
- 支持发送前人工确认

## 6.12 用户邮箱管理模块

### 功能说明

以用户邮箱为维度管理售后记录。

### 页面内容

- 用户邮箱
- 首次来信时间
- 最近来信时间
- 历史邮件
- 关联问题
- 当前待处理事项
- 是否已发送首次安抚
- 是否已发送最终方案
- 是否需要人工跟进

## 6.13 报表 Dashboard

### 功能说明

面向客服主管和管理层的数据看板。

### 指标

- 今日新增邮件
- 未处理邮件
- 已生成草稿
- 人工审核数
- 高频问题
- 产品问题排行
- 邮件类型分布
- 问题类型分布
- 模板使用情况
- 产品未识别数量
- AI 误判待修正数量

## 7. 数据库建议

### 7.1 emails 表新增字段

```sql
ALTER TABLE emails ADD COLUMN mail_category TEXT;
ALTER TABLE emails ADD COLUMN issue_category TEXT;
ALTER TABLE emails ADD COLUMN reply_template_category TEXT;
ALTER TABLE emails ADD COLUMN classification_confidence REAL;
ALTER TABLE emails ADD COLUMN needs_human_review BOOLEAN DEFAULT 0;
ALTER TABLE emails ADD COLUMN evidence_snippet TEXT;
ALTER TABLE emails ADD COLUMN matched_reason TEXT;
ALTER TABLE emails ADD COLUMN normalized_product_model TEXT;
```

### 7.2 issue_user_links 表

```sql
CREATE TABLE issue_user_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER,
    email_id TEXT,
    customer_email TEXT,
    product_model TEXT,
    mail_category TEXT,
    issue_category TEXT,
    matched_reason TEXT,
    evidence_snippet TEXT,
    confidence REAL,
    user_issue_status TEXT,
    first_reply_sent_at TIMESTAMP,
    final_reply_sent_at TIMESTAMP,
    excluded_from_bulk BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.3 product_aliases 表

```sql
CREATE TABLE product_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    official_model TEXT,
    alias TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 8. AI 安全与复核规则

### 8.1 分类置信度

| 置信度 | 处理 |
|---|---|
| `>= 0.85` | 可自动归并 |
| `0.65 - 0.85` | 归并但标记待抽查 |
| `< 0.65` | 不自动归并，进入人工复核 |

### 8.2 强制人工复核场景

- 产品型号冲突
- 邮件类型和问题分类明显冲突
- 用户强烈不满
- 涉及退款、法律、大额赔偿
- 涉及固件失败导致设备不可用
- 模板中包含高风险操作步骤
- AI 判断理由和证据片段不匹配

## 9. MVP 范围

第一阶段优先实现：

1. 邮件同步和基础收件箱
2. AI 分类结果落库
3. 产品别名识别
4. AI 草稿生成和人工审核
5. 回复模板管理
6. 售后问题归并
7. 问题待解决队列
8. 问题详情页展示用户邮箱和证据
9. 内部报告生成
10. 错误模板删除/禁用机制

后续阶段实现：

- 批量最终回复
- 研发协作账号
- 模板使用统计
- 知识库自动复用
- 多语言支持
- 邮件发送失败重试

## 10. 成功指标

- 产品识别率提升到 95% 以上
- 高频问题归并准确率达到 85% 以上
- 内部周报整理时间减少 70%
- AI 草稿人工修改率逐步下降
- 错误模板命中率为 0
- 同类问题最终批量通知覆盖率达到 90% 以上

## 11. 总结

这个客服系统的核心不是让 AI 替代客服，而是让 AI 帮客服完成以下工作：

- 快速理解邮件
- 稳定识别产品和问题
- 生成可审核草稿
- 归并重复售后问题
- 保留用户邮箱和证据
- 生成内部汇报
- 沉淀最终解决方案
- 在问题解决后统一通知用户

最终系统应从“单封邮件处理工具”升级为“客服工作台 + 售后问题管理系统 + 内部协同系统 + 知识库”。

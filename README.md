# StoryFlow AI

> 本地优先的 AI 小说写作平台 — 用流程图设计故事，一键生成完整章节。

## 特性

- **流程图式创作**：拖拽节点编排情节，可视化故事走向
- **多模型支持**：Ollama / LM Studio（本地）+ DeepSeek / OpenAI / 通义千问（云端 BYOK）
- **反 AI 味引擎**：内置去 AI 味提示词，输出更自然
- **一键续写**：不满意？自动从断点处续写，保持风格一致
- **项目/模板管理**：保存所有项目，预设模板快速启动
- **License 激活**：买断制，一次付费永久使用

## 版本对比

| 功能 | 免费版 | 标准版 (¥69) | 专业版 (¥199) |
|------|--------|-------------|-------------|
| 流程图节点 | 1 | 5 | 无限 |
| 每日生成（自备Key） | 3 次 | 50 次 | 无限 |
| 平台 API | ❌ | ✅ 100 万 Token | ✅ 500 万 Token |
| 写作风格 | 2 种 | 4 种 | 5 种 |
| 去 AI 味 | 基础 | 完整 | 增强自定义 |
| 导出格式 | txt | txt / PDF | txt / PDF / EPUB / DOCX |
| 本地模型 | ✅ | ✅ | ✅ |

## 快速开始

### 一键安装

**macOS：** 打开终端，粘贴运行：

```bash
git clone https://github.com/tzhkai/storyflow-ai.git
cd storyflow-ai
bash install.sh
```

**Windows：** 确保已安装 Python 3.10+，然后双击 `install.bat`

脚本会自动完成：环境检测 → 安装依赖 → 启动服务 → 开机自启 → 打开写作页面。

**之后每次开机自动启动，无需手动操作。**

```bash
# 卸载（macOS）
bash uninstall.sh
```
Windows 用户双击 `uninstall.bat` 即可。

### 配置 AI 模型

#### 方式一：本地模型（免费）

**Ollama：**
```bash
# 安装 Ollama: https://ollama.com
ollama pull qwen2.5:7b
# 然后在界面中选择 Ollama → qwen2.5:7b
```

**LM Studio：**
```bash
# 下载 LM Studio: https://lmstudio.ai
# 加载模型 → 开启 Local Server（默认 http://127.0.0.1:1234）
# 然后在界面中选择 LM Studio 即可
```

#### 方式二：云端模型（自带 Key）

在页面右上角点 **🔑 API 设置**，填入：

| 模型 | 获取 Key |
|------|---------|
| DeepSeek | https://platform.deepseek.com |
| OpenAI | https://platform.openai.com |
| 通义千问 | https://dashscope.aliyun.com |

> 费用由模型厂商直接收取，与 StoryFlow 无关。DeepSeek 目前最便宜，约 ¥1/百万 Token。

## License 激活

升级标准版或专业版：

1. 打开软件，点击右上角的版本标识
2. 输入购买获得的 License Key（格式 `SF-STD-xxxx` 或 `SF-PRO-xxxx`）
3. 点击激活，即时生效

> 购买地址：<a href="https://mbd.pub/search?q=StoryFlow">面包多搜索「StoryFlow」</a>（审核中）
> 
> 审核通过前如需购买，请联系：**36843155@qq.com**（注明：StoryFlow 标准版/专业版）

## 使用技巧

- **先建流程图再生成**：拖拽节点编排故事线，效果远好于直接 prompt
- **善用续写**：生成长文时，写一段点"继续"，比一次生成全部质量高
- **调整推理参数**：在模型设置中调高 `temperature` 增加创意，调低增加连贯性
- **切换写作风格**：不同风格对应不同的系统提示词，试试看哪个适合你

## 常见问题

**Q: 本地模型效果不好？**  
A: 建议使用 7B+ 参数模型。Qwen2.5-7B-Instruct 是个不错的起点。

**Q: DeepSeek 报错？**  
A: 确认 Key 正确，且账户有余额。DeepSeek 需要先充值才能调用 API。

**Q: License Key 丢失？**  
A: 去购买平台（面包多）查看订单记录，Key 会保留在购买记录中。

**Q: 怎么切换电脑？**  
A: 在新电脑安装软件，输入同一个 License Key 激活即可（一 Key 一设备）。

## 项目结构

```
storyflow/
├── server.py          # 后端主程序（Flask, 端口 8505）
├── static/
│   └── index.html     # 前端单页应用
├── data/              # 用户数据（项目、模板、License）
├── generate_key.py    # License Key 生成工具
└── requirements.txt
```

# auto_answerer —— 网页自动答题工具（ITEST / 学习通 / 问卷类通用）

自动识别网页上的题目文字 → 调用 DeepSeek 生成答案 → 自动点选/填入，
支持一页多题与分页翻页；**默认只答不交，提交前留人工检查**。

> ⚠️ 请仅用于**允许自动化的练习/作业场景**，遵守平台规则与学校规定；
> 切勿用于正式考试作弊（后果自负）。本工具定位是提高效率，不是包办。

## 图形界面（推荐，所有功能已整合）

双击 **`ui.bat`** 打开桌面窗口，四个按钮走完全流程：

1. **① 启动调试浏览器** —— 关闭并重启你的 Edge（带调试端口，书签/登录都在，首次自动复制配置）
2. **② 连接浏览器** —— 连接调试端口并自动刷新标签页
3. 在浏览器里打开要作答的任务页
4. **③ 开始答题** —— 全自动逐题作答，右侧实时日志，随时可点 **⏹ 停止**

界面选项：
- `跳过无题干题(听力等)`：默认勾选，听不到音频的题不瞎猜；
- `回退到第1题再开始`：默认勾选，答题前先回到本卷第 1 题；
- `答完自动交卷(谨慎!)`：默认不勾选，答完由你人工检查后手动交卷；
- `探查页面`：导出当前页题目结构+截图（用于适配新平台）。

命令行入口仍然可用：`probe.bat` / `run.bat`（等价于旧版 CLI 用法）。

## 功能

| 能力 | 说明 |
|---|---|
| 读题 | 直接读网页文字（含 iframe），无需 OCR |
| 题型 | 单选/判断、多选、下拉、填空（文本框）、问答题、作文（大文本框） |
| 出答案 | DeepSeek API（OpenAI 兼容，`deepseek-chat`） |
| 登录 | 浏览器手动登录一次，会话保存在 `profiles/`，之后自动复用 |
| 节奏 | 逐页自动答题并翻页；答完停下等你人工检查（可开 `auto_submit`） |
| 记录 | 每题题干与答案存到 `out/运行时间/`，方便核对 |
| 适配 | `--probe` 探查模式导出页面结构 JSON，用于对新平台精调 |

## 快速开始（Windows）

```bat
cd /d path\to\auto_answerer

:: 1) 建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

:: 2) 配置 API Key
copy .env.example .env        :: 然后编辑 .env，填入你的 DEEPSEEK_API_KEY

:: 3) 先探查一个真实任务页的结构（把结果发回给我做精调）
python main.py --probe

:: 4) 正式答题
python main.py
```

说明：第 3/4 步会弹出浏览器 → 你**手动登录**并导航到具体任务页（可先点“开始答题”）→
回到终端按回车，程序开始自动读题答题。答题结束**不要直接关**，先人工检查再提交。

常用参数：
```bat
python main.py --no-pause          :: 已登录且已在任务页，跳过回车等待
python main.py --url https://...   :: 指定任务地址
python main.py --auto-submit       :: 答完自动点提交（慎用，默认关闭）
python main.py --max-pages 20      :: 限制翻页数
```

## 目录结构

```
auto_answerer/
├─ main.py              入口（run / probe）
├─ config.json          网址、翻页/提交按钮关键字、LLM 参数
├─ .env.example         复制为 .env 并填入所选模型服务的 API Key
├─ answerer/
│  ├─ reader.py         读题（DOM/iframe 启发式采集）
│  ├─ llm.py            DeepSeek 调用，返回严格 JSON 答案
│  ├─ filler.py         把答案点选/回填到控件
│  └─ nav.py            浏览器持久会话、翻页/提交按钮
├─ profiles/            本地浏览器登录态（不会提交到 Git）
└─ out/                 本地运行记录与探查结果（不会提交到 Git）
```

## 适配新平台/页面结构

通用启发式对标准 HTML 表单有效；平台 DOM 特殊时需要精调。
方法：跑一次 `python main.py --probe`，把 `out/probe_*/raw_frames.json` 和
`page.png` 发回给我，我据此改 `reader.py` 的选择策略即可。

## 常见问题

- 打开报“未找到 API Key”：确认已把 `.env.example` 复制为 `.env` 并填了 Key。
- 识别到 0 题：可能没停在题目页，或题目在特殊容器里——先跑 `--probe`。
- 个别题没填上：程序会打印 ❌ 原因并跳过，最后人工补即可。

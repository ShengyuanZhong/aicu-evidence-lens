# Aicu Evidence Lens · 发言观察 v2.1

这是一个本地运行的公开发言分析工具。输入 UID，采集 Aicu 评论、视频弹幕、直播弹幕；逐条保存原文与来源；标注需要核查的表达并生成交互报告。Windows 用户可以使用发布页的打包程序；从源码运行需要 Python 3.10+，日常使用不需要第三方 Python 包。

## Windows 桌面版

1. 从 [Releases](https://github.com/ShengyuanZhong/aicu-evidence-lens/releases) 下载 `AicuEvidenceLens-windows-x64.zip`，完整解压后双击其中的 `AicuEvidenceLens.exe`。
2. 输入 Bilibili UID，选择报告目录，点击“开始分析”。也可以选已有 `.json` / `.jsonl` 数据文件，或点击“生成演示报告”查看合成样本。
3. 完成后点击“打开报告”。报告与原始记录保存在所选目录下的 `<UID>` 子文件夹。

“模型配置”区可开启逐条语义审核，填写完整 Chat Completions URL、模型名称与 API Key，并先点“测试模型连接”。密钥只在当前进程内使用，不写入设置文件。开启后，发言原文与取得的来源上下文会发送给所填服务。没有模型时保持离线检索模式；报告会区分待核查、未审核与模型判断。

界面可设置每类采集页数、来源核查上限、模型最多审核条数，运行时可停止并保存已取得的数据。报告里有两个独立圆环：**内容分区**仅显示话题，**负面表达筛选**仅显示风险类别。扇区面积、条形长度和百分比按本图标签计数计算；点击标签可联动证据，两个圆环的筛选可叠加。

> 可执行文件未进行代码签名；需要自行核验时可对照发布页的 SHA-256。请保留解压后目录中的 `_internal` 文件夹。

## 先看演示

```powershell
python .\aicu_profile.py --demo
```

打开 `output/demo/report.html`。演示使用 32 条合成数据，不访问网络，也不调用模型。页面包括双圆环、占比条形、时间累积播放、来源/状态/日期/关键词筛选、点击标签联动证据和导出当前筛选记录。

## 输入 UID

```powershell
python .\aicu_profile.py 你的UID
```

结果保存在 `output/<UID>/report.html`。默认每页 100 条，间隔 1 秒，直到接口声明结束；用 `--max-pages 5` 限制每类抓取页数。Aicu 缺失或失败的数据在报告中标明，不算成零风险。

默认会对模糊且优先级较高的候选，最多核查 30 条 Bilibili 来源。使用 `--source-limit 0` 关闭；`--source-limit 50 --source-priority 3` 则提高核查阈值并扩大数量上限。只允许访问明确的 Bilibili 域名，不读取浏览器登录信息。

## 两种审核模式

- **离线检索**：没有模型时，规则产生“待核查”线索，未命中保持“未作语义审核”。已删除旧版积极词打分，不再把 `[喜欢]` 或 `[doge]` 当作友好证据。你指出的原句在本地回归案例中标为性化冒犯候选。
- **语义审核**：配置兼容 Chat Completions 的模型后，对全部记录分批审核，包括规则未命中的记录。模型必须输出对象、类别、原文证据及上下文需求；验证通过才计入模型审核。可用来源会触发第二次审核，并保留更改轨迹。最终再生成一段账号发言评述。

目前未安装本地神经网络模型，也没有配置真实模型服务。离线规则不能理解所有新梗、隐喻或反讽；方法比较与边界见 [docs/method.md](docs/method.md)。

## 模型配置

外部服务需要完整 Chat Completions URL、模型名和 API Key 环境变量：

```powershell
$env:AICU_LLM_URL = "https://你的服务/v1/chat/completions"
$env:AICU_LLM_MODEL = "你的模型名称"
$env:MY_LLM_KEY = "你的密钥"
python .\aicu_profile.py 你的UID --llm-api-key-env MY_LLM_KEY
```

本机兼容服务可使用 `http://127.0.0.1:端口/v1/chat/completions`，不强制要求密钥。也可以直接使用 `--llm-url`、`--llm-model`，不设置环境变量。

配置模型后会发送发言文本及取得的来源上下文给该服务。默认全量逐条审核；`--llm-record-limit 200` 限制本次最多审核前 200 条，未覆盖记录仍保持未审核或规则候选状态。`--llm-batch-size 12` 设置批次大小。`--llm-evidence-limit 80` 只限制最终评述中的证据数量。有效模型结果有本地缓存，文本、模型或提示词变化时会重新审核。

## 重用已有数据

无需再次爬取，直接用之前的原始记录：

```powershell
python .\aicu_profile.py 你的UID --input-records .\output\你的UID\records.jsonl --source-limit 0
```

也支持 `--input-json data.json`：格式可以是包含 `records` 数组的 JSON、规范化记录数组或旧版 Aicu 接口分页对象（`comment`、`video`、`live`）。完全离线运行时不要配置模型，并设置 `--source-limit 0`。

## 结果文件

| 文件 | 用途 |
| --- | --- |
| `report.html` | 可离线打开的交互报告，无 CDN 依赖 |
| `report.json` | v2 全量记录、标签、状态、来源上下文、审核轨迹和覆盖统计 |
| `records.jsonl` | 采集或导入的原始规范化记录，便于重跑 |
| `risk_findings.json` | 全部带风险标签的记录，包含待核查和模型判断 |
| `llm_requests.jsonl` | 按批导出的模型请求，不含 API Key；无模型时也生成 |
| `llm_review.txt` | 模型评述；未生成或失败时明确标注 |
| `review_cache.json` | 已通过结构校验的模型结果缓存 |

v1 的 `llm_input.json` 已由逐批 `llm_requests.jsonl` 替代；v2 不使用旧文件。HTML 中显示“风险”仍是内容分析结果，不能等同于现实人格。涉政作为话题单列，不推断政治立场或心理状态。

## 从源码启动与构建

```powershell
python .\launcher.py
```

构建 Windows 程序时，先安装构建依赖，再运行脚本：

```powershell
python -m pip install "pyinstaller>=6.22,<7"
.\build_windows.ps1
```

生成的文件是 `dist/AicuEvidenceLens-windows-x64.zip`。打包脚本将报告的本地 CSS、JavaScript 和合成演示数据一并包含；构建产物与用户报告已在 `.gitignore` 中排除。

## 项目结构与验证

`aicu/collector.py` 负责采集；`detection.py` 负责离线召回；`semantic.py` 负责模型协议及验证；`context.py` 负责来源；`pipeline.py` 串起流程；`gui.py` 是桌面界面；`report.py` 与 `assets/` 生成交互报告。

```powershell
python -m unittest -v
node tests/dashboard.test.cjs
```

测试范围见 [tests/README.md](tests/README.md)。来源页面可能被删除、限流或需要登录；抓取失败时保留失败状态，不会把记录判成无风险。抓取或模型失败时退出码为 2，已有数据和可生成的报告仍保留。

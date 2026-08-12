# 招标/中标公告聚合采集工具

一个面向个人使用的低频率招标信息采集工具：配置若干关键词，定时向招标网站提交关键词搜索，对返回结果做解析、去重、变更检测与导出。不需要针对单个网站做大规模数据刺探，聚焦"关键词搜索 + 后处理"这一条轻量路线。

## 功能特性

- **关键词搜索采集**：按站点配置关键词，定时执行搜索并抓取详情；
- **SQLite 存储**：URL 去重、字段变更检测（`items` / `changes` / `tasks` 三张表）；
- **Web 管理后台**：站点配置、任务调度、立即执行、数据查询/归档/批量操作、日志查看；
- **定时调度**：APScheduler + Cron 表达式，站点间串行执行、单站任务总时长上限；
- **AI 辅助提取**：可选 DeepSeek / OpenAI 兼容 LLM，解析结果列表与详情页（CSS 解析优先，LLM 兜底）；
- **Excel / JSON 导出**：按站点、日期、类型、新增过滤导出报告；
- **交互式登录**：手动运行打开可见浏览器，支持微信扫码等登录场景，会话保存复用。

## 站点支持现状

| 状态 | 站点 | 说明 |
| --- | --- | --- |
| ✅ 可采集 | 中国政府采购网 | 使用搜索 URL 模板，已跑通 |
| ✅ 可采集 | 上海政府采购网 | 政采云适配器（`sites/zcy.py`），多关键词逐词搜索、列表级直接入库，已跑通 |
| 🔧 适配中 | 山东政府采购网 | Vue SPA，走 `:8087` API + 验证码，待适配 |
| 🚫 已停用 | 乙方宝 | 详情页强制微信扫码登录，无法无人值守 |
| 📋 已入库 | 全国公共资源交易平台、中国招标投标公共服务平台、采招网、中国采购与招标网、比地招标网 | 聚合型，免费关键词搜索，需逐个适配 |
| 📋 已入库 | 中石油/中石化/中海油、山东能源、华能、中煤、国家能源集团 | 企业招标平台，多为登录/反爬，待适配 |
| 📋 已入库 | 北京/天津/江苏/浙江/山东/广东/福建/河北/辽宁政府采购网 | 东部十省市地方招标网站（上海已完成，浙江同为政采云体系可复用适配器） |

> 完整清单见 `scripts/seed_sites.py`，运行后可导出 Excel 站点清单。

## 技术栈

Python 3.12 · Playwright（Chromium + Stealth）· APScheduler · Flask / Flask-Admin · SQLite · DeepSeek（OpenAI 兼容 API）· pandas / openpyxl · loguru

## 快速开始

```powershell
# 1) 安装依赖与浏览器
python -m pip install -r requirements.txt
python -m playwright install chromium

# 2) 配置环境变量
Copy-Item .env.example .env
#    编辑 .env：至少填写 LLM_API_KEY（DeepSeek）

# 3) 初始化站点配置（可选：从 Excel 导入）
python run.py init
python run.py seed --file config/template.xlsx

# 4) 启动 Web 管理后台
python run.py web
#    访问 http://localhost:5000/admin （默认账号 admin / admin123）

# 5) 手动爬取某个站点
python run.py crawl --site "中国政府采购网"
```

## 常用命令

| 用途 | 命令 |
| --- | --- |
| 启动 Web 后台 | `python run.py web` |
| 启动定时调度 | `python run.py schedule` |
| 爬全部站点 | `python run.py crawl --all` |
| 爬单个站点 | `python run.py crawl --site "站点名"` |
| 查看统计 | `python run.py report` |
| 导出 Excel / JSON | `python run.py export --format excel` / `--format json` |
| 交互式登录 | `python run.py login --site "站点名"` |
| 环境自检 | `python debug_test.py` |

详细说明（环境准备、调度行为、停止方式、常见问题）见 [运行说明.md](运行说明.md)。

## 项目结构

```text
zbcaiji/
├── run.py                  # CLI 入口（web / crawl / schedule / export ...）
├── core/                   # 爬虫引擎、浏览器、提取器、搜索分析、存储、调度
├── sites/                  # 站点适配器框架（按站点定制解析逻辑）
├── utils/                  # Excel 读取、站点配置管理、日志、工具函数
├── web/                    # Flask 管理后台 + 任务调度 API
├── export/                 # 报告导出
├── config/                 # 全局配置、Excel 模板
├── scripts/seed_sites.py   # 站点清单（聚合站/能源企业/东部十省市）入库脚本
├── data/                   # 运行数据（数据库、日志、会话，已 gitignore）
└── 运行说明.md              # 完整运行文档
```

## 重要说明

- **合规使用**：本项目仅用于个人合法合规的信息收集；请遵守目标网站的访问频率限制与相关法律法规，控制采集频率。
- **安全**：`.env` 中的 API Key 不会被提交；请勿将密钥外泄。仓库默认建议保持 Private。
- **适配现状**：大多数聚合站与省级平台是 SPA 或带验证码/登录墙，通用爬虫不能直接跑通，需要按 `sites/` 适配器逐个接入（当前优先处理中国政府采购网与全国公共资源交易平台）。

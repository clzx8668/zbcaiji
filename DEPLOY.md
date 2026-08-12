# Windows 任务计划程序配置说明

## 方法 1: 使用 Python 内置 APScheduler（推荐）

直接运行调度模式，程序会持续在后台运行：
```powershell
python run.py schedule
```

可以让它开机自启：
- 按 Win+R，输入 `shell:startup`
- 创建一个快捷方式指向 `pythonw.exe run.py schedule`

## 方法 2: Windows 任务计划程序

适合不常驻内存的场景：

1. 打开"任务计划程序"（Win+R → taskschd.msc）
2. 创建基本任务 → 名称: "招标公告爬虫"
3. 触发器: 每天 → 设置时间
4. 操作: 启动程序
   - 程序: `python.exe`
   - 参数: `run.py crawl --all`
   - 起始于: `E:\Dev\zbcaiji`

## 方法 3: 使用 nssm 注册为 Windows 服务

```powershell
# 下载 nssm: https://nssm.cc/download
nssm install BidScraper "python.exe" "run.py schedule"
nssm set BidScraper AppDirectory "E:\Dev\zbcaiji"
nssm start BidScraper
```

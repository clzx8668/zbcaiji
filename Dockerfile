# 招标公告爬虫 Docker 部署

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright 浏览器
RUN playwright install chromium --with-deps

# 复制项目文件
COPY . .

# 创建数据目录
RUN mkdir -p data/logs data/output data/cache

ENV BROWSER_ENGINE=playwright
ENV HEADLESS=true

ENTRYPOINT ["python", "run.py"]
CMD ["schedule"]

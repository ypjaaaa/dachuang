# 会议知识库 · 本地 RAG —— 应用镜像
# 模型与数据通过 volume 挂载(不入镜像),镜像只含代码与依赖
FROM python:3.12-slim

# 系统依赖:ffmpeg(音视频处理)+ 编译工具(llama-cpp-python 需编译)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层(利用 Docker 缓存,代码变更无需重装依赖)
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 应用代码
COPY app ./app
COPY README.md .

ENV PYTHONPATH=/app
EXPOSE 7860

CMD ["python", "-m", "app.ui"]

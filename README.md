app/
├── config.py          # 全局配置(路径、模型、向量库参数)
├── asr.py             # faster-whisper 转写(带时间戳)
├── chunk.py           # 智能分块(保留时间戳元数据)
├── embed.py           # bge-large-zh-v1.5 向量嵌入
├── retriever.py       # 混合检索:BM25+向量 RRF 融合 + bge-reranker 精排
├── ingest.py          # 入库管道:音频→转写→分块→嵌入→Milvus
├── query.py           # RAG 问答:混合检索→Prompt→LLM→引用
├── llm.py             # llama-cpp 加载 Qwen GGUF(本地生成)
├── download_models.py # 从 ModelScope 下载全部模型
└── ui.py              # Gradio 交互界面

数据/模型目录(自动创建):
models/    # 模型文件(whisper / bge / Qwen gguf)
data/
├── audio/         # 测试音频
├── transcripts/   # 转写结果存档
└── milvus_lite/   # Milvus Lite 向量库文件(meeting.db)

使用流程:
1. python -m app.download_models        # 下载模型(约 9GB,已下载完成 ✅)
2. python -m app.ingest data/audio/xxx.mp3 "组会-0822" "2026-08-22"  # 入库
3. python -m app.query "向量库选了哪个方案?"                          # 命令行问答
4. python -m app.ui                      # 启动图形界面(浏览器打开 127.0.0.1:7860)
5. python -m app.server                  # 启动现代 Web 页面(推荐,打开 127.0.0.1:7860)

页面功能(static/index.html + app/server.py,参考 meeting-ai-master 实现):
- 🎬 MOV/MP4 录屏导入:支持 .mov/.mp4/.webm/.mkv 等录屏视频与 mp3/wav/m4a 音频,
  视频自动用 ffmpeg 提取 16kHz 单声道音轨再转写;本人已传过的同文件 MD5 自动去重
- 📹 页面内置「现场录屏」:浏览器共享屏幕/窗口/标签页 + 声音直接录制(仿"现场录音"),
  停止后自动提取音轨转写入库
- 📄 查看会议原文:导入即登记会议库(meetings.json + data/transcripts/{id}.txt),
  可切换「原始转写稿 / 清洗稿(知识库内容)」并下载
- 📝 生成文档:把某场会议内容整理成结构化 Markdown 纪要(长文本自动分段逐章生成);
  默认本地 Qwen 7B 全本地,配置 DEEPSEEK_API_KEY(.env)后自动改用 DeepSeek 云端
- 🗑️ 会议删除:同步清除该会议的知识块 + 转写稿 + 注册表条目

业务系统(登录 / 注册 / 普通用户 / 管理员后台,V2.0):
- 访问 http://127.0.0.1:7860 → 未登录显示登录/注册页(浅蓝 + 淡粉渐变、光斑与毛玻璃卡片);
  注册即普通用户,自动登录
- 普通用户:只能看到/问答/删除**自己**上传的会议(数据按用户隔离);
  可修改自己密码;右上方显示账号
- 文件导出(页面上的两个新按钮):
  - ⬇ **源文件导出**:会议条目上的「源文件」按钮导出该会议的原始录音/录屏
    (上传时已保存为 `data/audio/{会议id}.{后缀}`);普通用户只能导出自己的,
    **管理员可导出所有人的**(主页面与 /admin 管理后台都有)
  - ⬇ **聊天导出**:问答区右上角「导出聊天」把本次问答记录(含来源引用)导出为
    Markdown 文件;**仅普通用户显示,管理员不显示**(管理员用管理后台)
- 管理员(默认 admin/admin123,首次启动自动创建,登录后请立即改密):
  - 主页面同普通用户(能看到全部会议,带归属)
  - /admin 管理后台:系统统计、用户管理(禁用/启用/设管理员/重置密码/删除,
    删除用户级联删除其会议)、跨用户会议查看/删除
- 认证实现:PBKDF2-SHA256 密码哈希 + HMAC-SHA256 签名令牌(纯标准库,无新依赖);
  密钥取环境变量 AUTH_SECRET_KEY,未设置时自动生成并持久化到 data/.secret_key
- 可在项目根目录 .env 配置(参考 .env.example):
  ADMIN_USERNAME / ADMIN_PASSWORD(默认管理员)
  ACCESS_TOKEN_EXPIRE_MINUTES(令牌有效期,默认 720 分钟)
  DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL(文档生成走云端)
- 注意:V2.0 之前导入的历史测试知识块没有归属者,普通用户不可见(仅管理员问答/统计可见)

已验证 ✅(2026-08-22~23):
- whisper large-v3 转写(带时间戳)
- bge-large-zh-v1.5 嵌入(1024 维)
- Milvus Lite 建库/插入/检索/删除(字符串主键 + 时间戳元数据)
- 端到端入库管道(转写→分块→嵌入→入库)
- **混合检索(BM25+jieba + 向量 RRF 融合)+ bge-reranker-v2-m3 精排**
  (复合问题完整召回"原因+修复方案",噪声段落 score≈0 全部滤除)
- llama-cpp-python 0.3.35(源码编译,CPU 版)
- **完整 RAG 问答**(检索→本地 Qwen-7B 生成→带引用回答,防幻觉生效)
- **多轮对话 query rewriting**(2026-08-23):
  - 追问自动补全上下文:"那修复方案呢?" → 重写为 "HBase查询变慢的修复方案是什么?"
  - 实测:重写后检索相关性显著提升(CPU 重写耗时约 21 秒)
  - Gradio 界面已接入对话历史
- Gradio 界面(127.0.0.1:7860)

计算设备(2026-08-23 GPU 恢复后):
- config.py 启动时自动检测:GPU 可用 → cuda;不可用 → cpu 兜底
- 当前配置(稳定优先):**ASR 固定 CPU、LLM 固定 CPU、嵌入/重排自动 GPU**
  (原因:ctranslate2 需 CUDA12 库而环境为 CUDA13;llama-cpp 为 CPU 编译版)
- 若要 ASR/LLM 也用 GPU:装 nvidia-cublas-cu12 或重编译 CUDA 版(可选优化)

排障记录(2026-08-23):
1. GPU 恢复后转写崩溃 → ctranslate2 缺 libcublas.so.12 → ASR 固定 CPU
2. 问答崩溃 → llama-cpp CPU 版收到 GPU 层数参数 → LLM 固定 CPU
3. Gradio 6 消息格式错误 → Chatbot 回调需返回 role/content 字典列表
4. 多轮重写模板错误 → rewrite_query 改用与单轮相同的拼接路径
5. Milvus Lite 单进程锁 → 界面/命令行勿同时访问数据库
6. 提示文案:区分"知识库为空"与"未检索到相关内容"

Docker 化:
- Dockerfile + docker-compose.yml + .dockerignore 已就绪
- models/ 与 data/ 通过 volume 挂载(镜像不含 9GB 模型)
- 构建命令:DOCKER_CONFIG=$PWD/.docker docker compose -p meeting-kb build
- 启动命令:docker compose up -d → http://localhost:7860
- GPU 直通:需先装 nvidia-container-toolkit(国内源暂无,标记为可选优化)
- ✅ 已实测:容器启动、端口映射、模型/数据挂载、容器内检索全部正常(CPU 模式)

待办:
- [ ] 真实多场会议入库,跨会议检索测试(等你录 2-3 段不同主题会议)
- [ ] 扩充评估集(50-100 题),持续量化检索准确率
- [ ] (可选)装 CUDA toolkit 重编译 llama-cpp → LLM 生成 GPU 化
- [ ] (可选)装 nvidia-container-toolkit → Docker 容器 GPU 直通

检索评测(2026-08-23, 6 题):
- 混合检索 + Rerank 准确率 83.3%(5/6)≥ 80% 达标 ✅
- 命令: python -m app.evaluate
- 已知短板:转写质量差的段落影响 rerank 打分(待 query rewriting 优化)

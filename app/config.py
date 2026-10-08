"""全局配置:路径、模型、向量库参数"""
import ctypes
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # ~/大创
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
MILVUS_DIR = DATA_DIR / "milvus_lite"  # Milvus Lite 数据文件

for d in (MODELS_DIR, AUDIO_DIR, TRANSCRIPT_DIR, MILVUS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 可选 .env(项目根目录):加载后再读下面的环境变量(如 DEEPSEEK_API_KEY / ADMIN_PASSWORD)
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except Exception:
    pass

# ---------- 用户体系 ----------
USER_DB = DATA_DIR / "users.db"        # 用户表(SQLite)
SECRET_FILE = DATA_DIR / ".secret_key"  # 令牌签名密钥(未配置 AUTH_SECRET_KEY 时自动生成)
# 令牌有效期(分钟);默认管理员(首次启动自动创建,可在 .env 覆盖)
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")


def get_auth_secret() -> str:
    """令牌签名密钥:优先环境变量 AUTH_SECRET_KEY,否则持久化到 data/.secret_key"""
    env = os.environ.get("AUTH_SECRET_KEY", "").strip()
    if env:
        return env
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    import secrets
    key = secrets.token_hex(32)
    SECRET_FILE.write_text(key, encoding="utf-8")
    return key

# GPU 转写支持:ctranslate2(faster-whisper 底层)链接 CUDA 12 的 libcublas.so.12,
# 而环境里 torch 自带的是 CUDA 13。若已安装 nvidia-cublas-cu12,则预加载 .so.12
# 到全局命名空间,ctranslate2 即可解析依赖 → GPU 转写可用。
_CUBLAS12_DIR = BASE_DIR / "venv" / "lib" / "python3.12" / "site-packages" / "nvidia" / "cublas" / "lib"
if _CUBLAS12_DIR.exists():
    for _lib in ("libcublas.so.12", "libcublasLt.so.12"):
        _p = _CUBLAS12_DIR / _lib
        if _p.exists():
            try:
                ctypes.CDLL(str(_p), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

# ---------- 模型 ----------
# 直接指向 ModelScope 已下载的本地 snapshot 目录(faster-whisper 支持本地路径,避免联网)
ASR_MODEL = str(MODELS_DIR / "whisper" / "models" / "Systran--faster-whisper-large-v3" / "snapshots" / "master")
EMBED_MODEL = str(MODELS_DIR / "embed" / "models" / "BAAI--bge-large-zh-v1.5" / "snapshots" / "master")
RERANK_MODEL = str(MODELS_DIR / "reranker" / "models" / "BAAI--bge-reranker-v2-m3" / "snapshots" / "master")
# 7B 模型(CPU 推理):3B 理解能力弱会误报"未找到";7B 回答质量可靠。
# 显存放不下 7B → 用 CPU 推理(约 30-60 秒/问,功能正确优先)
LLM_GGUF = MODELS_DIR / "llm" / "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
LLM_REPO = "Qwen/Qwen2.5-7B-Instruct-GGUF"       # ModelScope 仓库

# 计算设备:启动时自动检测,GPU 可用 → cuda;不可用 → cpu 兜底
try:
    import torch
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
except ImportError:
    DEVICE = "cpu"

# 显存分工(关键!):5.6GB 显存放不下 3 个模型。
# GPU 只留给 LLM(最慢的环节);嵌入/重排放 CPU(本身很快,对速度影响小)。
EMBED_DEVICE = "cpu"
RERANK_DEVICE = "cpu"

# LLM 层数:7B 显存放不下 → 固定 CPU 推理(0);功能正确优先
LLM_GPU_LAYERS = 0

# ASR 设备:ctranslate2 支持 CUDA 时用 GPU(需配合 CUDA_VISIBLE_DEVICES=0,
# 双显卡机器上避免枚举到 AMD 核显导致 invalid device ordinal)
try:
    import ctranslate2
    ASR_DEVICE = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
except Exception:
    ASR_DEVICE = "cpu"

# ---------- 向量库(Milvus Lite) ----------
COLLECTION = "meeting_kb"
VECTOR_DIM = 1024          # bge-large-zh-v1.5 的维度
EMBED_BATCH = 32

# ---------- 检索 ----------
TOP_K = 6                 # 给 LLM 更多上下文(反问句等干扰段可被后续正确段覆盖)
VEC_TOP_K = 20            # 向量召回数
BM25_TOP_K = 20           # BM25 召回数
RERANK_TOP = 30           # 进 rerank 的候选数;0 = 关闭 rerank
# 阈值刻意调低:泛问题(如"会议讲了什么")与段落匹配分天然低,
# 阈值过高会全滤掉 → "未找到";LLM 会基于最相关内容做总结,噪声由提示词约束
MIN_SCORE = 0.002

# ---------- LLM ----------
LLM_CTX = 4096   # 6GB 显存下 8192 的 KV cache 会超显存;4096 兼顾容量与速度
# LLM_GPU_LAYERS 已由上方自动检测决定(cuda 时 -1,CPU 时 0)

# ---------- 文档生成(仿 meeting-ai-master 的可切换设计) ----------
# 默认走本地 Qwen GGUF(全本地);若在 .env/环境变量里配置了 DEEPSEEK_API_KEY,
# 则自动改用 DeepSeek 云端生成(OpenAI 兼容协议,需已安装 openai 包)。
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/") or "https://api.deepseek.com"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"

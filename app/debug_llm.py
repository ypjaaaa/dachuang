"""诊断:在 GPU 模式下加载 LLM,把完整原始错误保存到 llm_debug.txt"""
import sys, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from llama_cpp import Llama
    from . import config
    print(f"GPU 层数: {config.LLM_GPU_LAYERS}, 上下文: {config.LLM_CTX}")
    print("加载 Qwen 模型(verbose=True 捕获原始错误)...")
    llm = Llama(
        model_path=str(config.LLM_GGUF),
        n_ctx=config.LLM_CTX,
        n_gpu_layers=config.LLM_GPU_LAYERS,
        verbose=True,   # 关键:打印 llama.cpp 原始日志
    )
    print("✅ 模型加载成功!")
except Exception:
    out = Path("llm_debug.txt")
    with open(out, "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    print(f"❌ 加载失败,完整错误已保存: {out.resolve()}")

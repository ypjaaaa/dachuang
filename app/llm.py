"""本地 LLM:llama-cpp-python 加载 GGUF,走 Qwen2.5 官方 chat 模板"""
import threading
from pathlib import Path

from . import config


_llm = None
_gen_lock = threading.Lock()   # llama.cpp 模型非线程安全:问答/重写/文档生成须串行


def load_llm():
    """懒加载 GGUF 模型;文件不存在时给出下载指引"""
    global _llm
    if _llm is not None:
        return _llm
    if not Path(config.LLM_GGUF).exists():
        raise FileNotFoundError(
            f"GGUF 模型不存在: {config.LLM_GGUF}\n"
            f"请先从 ModelScope 下载: {config.LLM_REPO} 中的 q4_k_m 分片,\n"
            f"或运行 python -m app.download_models llm"
        )
    try:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=str(config.LLM_GGUF),
            n_ctx=config.LLM_CTX,
            n_gpu_layers=config.LLM_GPU_LAYERS,   # 0=CPU;-1=全部上 GPU
            verbose=False,
        )
    except ImportError:
        raise ImportError("缺少 llama-cpp-python,请: pip install llama-cpp-python")
    return _llm


def generate(system: str, user: str, max_tokens: int = 512) -> str:
    """走 chat 模板生成,输出为纯回答(不再回显 prompt)"""
    llm = load_llm()
    with _gen_lock:   # 串行推理,避免多线程同时调用同一模型实例
        out = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
    return out["choices"][0]["message"]["content"].strip()


REWRITE_SYSTEM = (
    "你是检索查询重写器。用户正在进行多轮对话,他提出的问题可能是省略了上下文的追问"
    "(如\"那修复方案呢\"\"然后呢\"\"它是什么\")。"
    "请结合对话历史,把当前问题改写成一个**独立、完整、可直接用于检索**的查询语句,"
    "包含必要的人名、术语和上下文。只输出改写后的查询本身,不要任何解释。"
)


def rewrite_query(history: list[dict], question: str) -> str:
    """结合对话历史,把追问改写为独立完整的检索查询(多轮对话支持)"""
    if not history:
        return question
    # 只取最近 3 条"用户问题"作为上下文:
    # 助手回答(尤其"未找到相关信息")会污染重写结果,必须过滤掉。
    user_msgs = [m["content"] for m in history
                 if m.get("role") == "user" and m.get("content")][-3:]
    if not user_msgs:
        return question
    context = "\n".join(f"用户问: {u}" for u in user_msgs)
    user = f"对话历史:\n{context}\n\n当前问题:{question}"
    rewritten = generate(REWRITE_SYSTEM, user, max_tokens=80)
    # 兜底:结果异常(含杂音/过短/过长)时退回原问题
    rewritten = rewritten.replace("\n", " ").strip()
    if not (4 <= len(rewritten) <= 100):
        return question
    # 消毒:重写结果里混入"未找到""会议内容"等说明性杂音时,退回原问题
    for noise in ("未找到", "没有找到", "无法", "相关信息", "根据会议", "会议内容"):
        if noise in rewritten and noise not in question:
            return question
    return rewritten


def unload():
    """问答结束后释放显存/内存,给转写让路"""
    global _llm
    if _llm is not None:
        del _llm
        _llm = None

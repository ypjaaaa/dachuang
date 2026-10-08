"""模型下载:从 ModelScope 下载 faster-whisper / bge / Qwen GGUF 到本地"""
import os

from modelscope import snapshot_download

from . import config

# ModelScope SDK 目录/缓存全部放进项目内(避免写入 ~/.modelscope 受限)
os.environ.setdefault("MODELSCOPE_HOME", str(config.MODELS_DIR / ".modelscope_home"))
os.environ.setdefault("MODELSCOPE_CACHE", str(config.MODELS_DIR / ".modelscope_cache"))

REPOS = {
    "asr": ("Systran/faster-whisper-large-v3", "whisper"),
    "embed": ("BAAI/bge-large-zh-v1.5", "embed"),
    "llm": ("Qwen/Qwen2.5-7B-Instruct-GGUF", "llm"),
}


def download_llm_gguf():
    """下载 Qwen GGUF(Q4_K_M 分片,共约 4.7GB)"""
    print("下载 Qwen2.5-7B-Instruct GGUF(Q4_K_M,约 4.7GB)...")
    path = snapshot_download(
        REPOS["llm"][0], cache_dir=str(config.MODELS_DIR / "llm"),
        allow_file_pattern=["*q4_k_m*.gguf"],   # 注意:文件名是小写
    )
    # 把分片文件集中到 models/llm/ 下,便于 llama.cpp 自动识别分片
    import shutil
    from pathlib import Path
    src = Path(path)
    target_dir = config.MODELS_DIR / "llm"
    target_dir.mkdir(parents=True, exist_ok=True)
    found = sorted(src.rglob("*q4_k_m*.gguf"))
    if found:
        for f in found:
            dst = target_dir / f.name
            if not dst.exists():
                shutil.copy(f, dst)
            print(f"  ✓ {f.name} ({f.stat().st_size/1024**3:.2f} GB)")
        print(f"完成: {len(found)} 个分片已就位,首分片 = {found[0].name}")
    else:
        print("未找到 q4_k_m 文件,请手动处理")


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("asr", "all"):
        print("下载 faster-whisper-large-v3 ...")
        snapshot_download(REPOS["asr"][0], cache_dir=str(config.MODELS_DIR / "whisper"))
    if which in ("embed", "all"):
        print("下载 bge-large-zh-v1.5 ...")
        snapshot_download(REPOS["embed"][0], cache_dir=str(config.MODELS_DIR / "embed"))
    if which in ("llm", "all"):
        download_llm_gguf()
    print("全部下载完成")

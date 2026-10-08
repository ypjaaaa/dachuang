"""ASR 转写:faster-whisper,输出带时间戳的段落列表"""
import threading

from faster_whisper import WhisperModel

from . import config


_model = None
_lock = threading.Lock()   # whisper 模型非线程安全,并发转写必须串行


def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(
            config.ASR_MODEL,
            device=config.ASR_DEVICE,  # ASR 单独检测:cuda(ctranslate2 支持时)/ cpu
            compute_type="int8",
            download_root=str(config.MODELS_DIR),
        )
    return _model


def transcribe(audio_path: str) -> list[dict]:
    """转写音频,返回 [{start, end, text}] 段落列表(秒为单位);并发时排队串行"""
    with _lock:
        segments, info = get_model().transcribe(
            audio_path,
            language="zh",
            vad_filter=True,          # 过滤静音
            beam_size=5,
        )
        result = []
        for seg in segments:
            result.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            })
        return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m app.asr <音频文件>")
        sys.exit(1)
    for seg in transcribe(sys.argv[1]):
        print(f"[{seg['start']:.1f}-{seg['end']:.1f}] {seg['text']}")

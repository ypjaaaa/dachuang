"""文档生成模块(仿 meeting-ai-master/modules/docgen.py,可切换 LLM)

把会议的转写/清洗文本,整理成结构化会议纪要/笔记文档(Markdown 格式)。

引擎选择(config.py):
- 默认: 本地 Qwen GGUF(全本地,CPU 生成较慢,长文本自动分段逐章生成)
- 若配置了 DEEPSEEK_API_KEY(环境变量/.env): 改用 DeepSeek 云端
  (OpenAI 兼容协议,需要 pip install openai;速度更快、长度上限更高)
"""

import time

from . import config
from .llm import generate as local_generate

# 单段最大字符数(超过就按段落拆成多个章节分别生成再合并)
MAX_CHUNK_DEEPSEEK = 4000   # 云端上下文大,可喂更多
MAX_CHUNK_LOCAL = 1400      # 本地 7B 上下文 4096 token:提示词+输出都要留余量
MAX_TOKENS_LOCAL = 1400


def _use_deepseek() -> bool:
    return bool(config.DEEPSEEK_API_KEY)


def generate_document(text: str) -> str:
    """把一段会议内容整理成结构化 Markdown 文档(自动选择引擎)"""
    if not text.strip():
        return ""
    if _use_deepseek():
        return _generate_deepseek(text)
    return _generate_local(text)


# ================= DeepSeek(云端,OpenAI 协议) =================

def _chat_deepseek(prompt: str, max_tokens: int) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "已配置 DEEPSEEK_API_KEY,但缺少 openai 包。"
            "请运行: pip install openai  (或改用默认本地 Qwen 生成)"
        )
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    last_err = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=max_tokens,
                timeout=120,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1)
    raise last_err


def _generate_deepseek(text: str) -> str:
    parts = _split_by_paragraph(text, MAX_CHUNK_DEEPSEEK)
    if len(parts) == 1:
        return _chat_deepseek(_prompt_full(parts[0]), 8000)
    sections = [_chat_deepseek(_prompt_section(p), 4000) for p in parts]
    return "\n\n".join(s for s in sections if s.strip())


# ================= 本地 Qwen(全本地) =================

def _generate_local(text: str) -> str:
    parts = _split_by_paragraph(text, MAX_CHUNK_LOCAL)
    if len(parts) == 1:
        return local_generate(
            "你是会议纪要/课堂笔记整理专家。请把用户提供的会议转写内容整理成一篇结构清晰、逻辑通顺的文档。",
            _prompt_full(parts[0]),
            max_tokens=MAX_TOKENS_LOCAL,
        )
    sections = []
    for p in parts:
        sections.append(local_generate(
            "你是会议纪要/课堂笔记整理专家。请把用户提供的一段会议内容整理成一个文档章节。",
            _prompt_section(p),
            max_tokens=MAX_TOKENS_LOCAL,
        ))
    return "\n\n".join(s for s in sections if s.strip())


# ================= 提示词与切分(与 meeting-ai-master 一致) =================

def _prompt_full(text: str) -> str:
    return f"""请把下面的会议转写内容，整理成一篇结构清晰、逻辑通顺的文档。

要求：
1. 给文档起一个准确的标题，用「# 标题」格式
2. 根据内容划分章节，每章用「## 章节名」作为标题
3. 每章下用要点或段落组织，提炼核心信息，删掉重复、废话和语气词
4. 保留所有关键技术术语、数字、名称、代码
5. 用 Markdown 格式输出
6. 语言简洁、专业、逻辑连贯

内容：
{text}"""


def _prompt_section(text: str) -> str:
    return f"""请把下面这段会议内容整理成一个文档章节。

要求：
1. 用「## 章节名」作为本章标题
2. 提炼核心信息，用要点或段落组织
3. 保留关键技术术语、数字、名称
4. 删掉重复、废话和语气词
5. 用 Markdown 格式输出

内容：
{text}"""


def _split_by_paragraph(text: str, max_chunk: int) -> list[str]:
    """按段落把长文本切成若干段，每段不超过 max_chunk 字"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    parts = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 1 > max_chunk and current:
            parts.append(current)
            current = para
        else:
            current = para if not current else current + "\n" + para

    if current:
        parts.append(current)
    return parts


if __name__ == "__main__":
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else "今天开会确定了用 FastAPI 做后端,向量库用 FAISS,下周出原型。"
    print(generate_document(sample))

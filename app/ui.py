"""Gradio 交互界面:上传音频入库 + 自然语言问答(带引用时间戳)—— 美化版"""
# 必须先清除代理环境变量,再 import gradio:
# 系统残留的 socks 代理(如 Clash)会让 gradio/httpx 启动崩溃
import os as _os
for _k in ("http_proxy", "https_proxy", "all_proxy",
           "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "no_proxy"):
    _os.environ.pop(_k, None)

import gradio as gr

from . import config
from .ingest import ingest
from .query import answer

# ---------------- 主题与样式 ----------------
CUSTOM_CSS = """
:root {
  --brand: #2563eb;
  --brand-dark: #1d4ed8;
  --brand-light: #dbeafe;
  --ink: #0f172a;
  --muted: #64748b;
  --card: #ffffff;
  --bg: #f1f5f9;
}

/* 全局 */
body {
  background: var(--bg) !important;
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif !important;
}

/* Hero 头部 */
.hero {
  background: linear-gradient(135deg, #2563eb 0%, #4f46e5 55%, #7c3aed 100%);
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 18px;
  color: #fff;
  box-shadow: 0 8px 24px rgba(37, 99, 235, .25);
}
.hero h1 {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px 0;
  letter-spacing: .5px;
}
.hero .sub {
  font-size: 14px;
  opacity: .92;
  margin: 0;
}
.hero .badges { margin-top: 10px; }
.hero .badge {
  display: inline-block;
  background: rgba(255,255,255,.18);
  border: 1px solid rgba(255,255,255,.35);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 12px;
  margin-right: 8px;
}

/* 卡片容器 */
.card {
  background: var(--card);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, .06);
  border: 1px solid #e2e8f0;
}
.card .card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card .card-title .dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--brand);
  display: inline-block;
}

/* 按钮 */
button.primary {
  background: linear-gradient(135deg, #2563eb, #4f46e5) !important;
  border: none !important;
  border-radius: 10px !important;
  color: #fff !important;
  font-weight: 600 !important;
  box-shadow: 0 4px 12px rgba(37, 99, 235, .3) !important;
  transition: transform .12s ease, box-shadow .12s ease !important;
}
button.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(37, 99, 235, .4) !important;
}

/* 输入区 */
input, textarea {
  border-radius: 10px !important;
  border-color: #e2e8f0 !important;
}
input:focus, textarea:focus {
  border-color: var(--brand) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, .15) !important;
}

/* 结果框 */
.result-box { font-size: 14px; }
.result-ok { color: #16a34a; font-weight: 600; }
.result-info { color: var(--muted); font-size: 13px; }

/* Tab 样式 */
.tab-nav button { border-radius: 10px 10px 0 0 !important; font-weight: 600; }
.tab-nav button.selected { color: var(--brand) !important; border-color: var(--brand) !important; }

/* 页脚 */
.footer {
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid #e2e8f0;
}

/* 移动端适配 */
@media (max-width: 640px) {
  .hero { padding: 20px; }
  .hero h1 { font-size: 20px; }
  .card { padding: 14px; }
}
"""

HERO_HTML = """
<div class="hero">
  <h1>🎙️ 会议知识库</h1>
  <p class="sub">基于 RAG 的会议知识沉淀 · 转写 → 检索 → 问答 → 可溯源</p>
  <div class="badges">
    <span class="badge">🔒 全本地部署</span>
    <span class="badge">🧠 混合检索 + Rerank</span>
    <span class="badge">📍 秒级定位</span>
  </div>
</div>
"""


def do_ingest(audio_path, title, date):
    if not audio_path:
        return '<span class="result-info">请先上传音频文件</span>'
    meta = ingest(audio_path, title or "会议", date or "")
    return f'<span class="result-ok">✅ 入库完成:{meta["chunks"]} 个知识块,现在可以提问了</span>'


def _format_citations(citations) -> str:
    if not citations:
        return ""
    lines = ["", "---", "**📍 来源引用:**"]
    for i, c in enumerate(citations, 1):
        lines.append(f"> **[{c['start']}-{c['end']}秒]** · {c['title']} · 相关度 {c['score']}")
    return "\n".join(lines)


def do_answer(question, history):
    # 兼容 gradio 6.x 两种历史格式
    chat_history = []
    if history:
        for msg in history:
            if isinstance(msg, dict) and msg.get("content"):
                chat_history.append({"role": msg.get("role", "user"), "content": msg["content"]})
            elif isinstance(msg, (list, tuple)) and len(msg) == 2:
                u, b = msg
                if u:
                    chat_history.append({"role": "user", "content": u})
                if b:
                    chat_history.append({"role": "assistant", "content": b})
    r = answer(question, history=chat_history)
    bot_content = f"{r['answer']}{_format_citations(r['citations'])}"

    # gradio 6.x:必须返回"消息字典列表"(role/content)
    new_history = [m for m in history or [] if isinstance(m, dict)]
    if not new_history or new_history[-1].get("content") != question:
        new_history.append({"role": "user", "content": question})
    new_history.append({"role": "assistant", "content": bot_content})
    return new_history


# ---------------- 界面 ----------------
with gr.Blocks(title="会议知识库 · 本地 RAG") as demo:
    gr.HTML(HERO_HTML)

    with gr.Row():
        with gr.Column(scale=5):
            with gr.Group(elem_classes=["card"]):
                gr.HTML('<div class="card-title"><span class="dot"></span>① 导入会议</div>')
                audio = gr.Audio(type="filepath", label="会议音频(MP3/WAV/M4A)")
                with gr.Row():
                    title = gr.Textbox(label="会议标题", placeholder="如:组会-2026-08-22")
                    date = gr.Textbox(label="会议日期", placeholder="如:2026-08-22")
                btn = gr.Button("🚀 转写入库", variant="primary", elem_classes=["primary"])
                out = gr.HTML(label="结果", elem_classes=["result-box"])
                btn.click(do_ingest, [audio, title, date], out)

        with gr.Column(scale=7):
            with gr.Group(elem_classes=["card"]):
                gr.HTML('<div class="card-title"><span class="dot"></span>② 智能问答</div>')
                chatbot = gr.Chatbot(label="对话", height=420, elem_classes=["chatbot"])
                q = gr.Textbox(
                    label="你的问题",
                    placeholder="如:组会里 HBase 查询变慢的原因是什么?",
                    lines=2,
                )
                q.submit(do_answer, [q, chatbot], chatbot)

    gr.HTML('<div class="footer">多模态会议内容转化与向量知识库 V1.0 · 数据全程本地存储,不上传云端</div>')


if __name__ == "__main__":
    # 0.0.0.0:容器内 Docker 端口映射需要;本地直接运行也兼容
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        css=CUSTOM_CSS,
        theme=gr.themes.Soft(primary_hue=gr.themes.colors.blue),
    )

"""Web 服务:FastAPI 后端 + 现代前端(业务系统版)

启动: ./venv/bin/python -m app.server   →  http://127.0.0.1:7860

功能(登录 / 注册 / 普通用户 / 管理员后台):
- 普通用户:注册后登录,上传录音/录屏(自动提音轨转写),拥有**自己**的知识库,
  可查看会议原文、生成文档、删除自己的会议,只能在**自己的会议**里问答。
- 管理员:除上述全部能力外,可在「管理后台 /admin」查看/删除任意会议、
  管理用户(启用/禁用/改角色/重置密码/删除,级联删除其会议),并查看系统统计。
- 首次启动自动创建默认管理员(config.ADMIN_USERNAME/ADMIN_PASSWORD,可 .env 覆盖)。

API:
  公开:
    GET    /                         登录页/主页面(前端按登录态切换)
    GET    /admin                    管理后台页面(需管理员角色)
    GET    /api/status               健康检查(公开)
    POST   /api/auth/login           登录 → {token, user}
    POST   /api/auth/register        注册(普通用户)→ 自动登录
  登录用户:
    GET    /api/auth/me              当前用户
    POST   /api/auth/change_password 修改自己的密码
    POST   /api/ingest               上传音频/录屏(归属当前用户)
    POST   /api/answer               在本用户会议内问答
    GET    /api/meetings             会议列表(用户=自己的;管理员=全部)
    GET    /api/meetings/{id}/raw    原始转写稿(本人/管理员)
    GET    /api/meetings/{id}/cleaned 清洗稿(本人/管理员)
    GET    /api/meetings/{id}/source  导出原始录音/录屏文件(本人/管理员)
    POST   /api/generate_doc         生成文档(本人/管理员)
    DELETE /api/meetings/{id}        删除会议(本人/管理员)
  仅管理员:
    GET    /api/admin/users          用户列表(含各自会议数)
    POST   /api/admin/users/{uid}/disable|enable|reset_password|role
    DELETE /api/admin/users/{uid}    删除用户(级联删会议;不能删自己)
    GET    /api/admin/stats          系统统计
"""
# 清除代理环境变量,避免 httpx/uvicorn 受 socks 代理影响
import os as _os
for _k in ("http_proxy", "https_proxy", "all_proxy",
           "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "no_proxy"):
    _os.environ.pop(_k, None)

import hashlib
import subprocess
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, meetings
from . import auth as auth_mod
from . import userdb
from .docgen import generate_document
from .ingest import ingest
from .query import answer as rag_answer

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="会议知识库 · 本地 RAG(业务系统)")

# 浏览器现场录音输出 webm/录屏输出 webm|mp4;.mov/.mp4 等为录屏视频文件。
# 统一用 ffmpeg 抽出 16kHz 单声道 wav 再转写(同 meeting-ai-master 的提音轨思路)
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".webm", ".mkv", ".avi", ".flv",
              ".ts", ".wmv", ".mpg", ".mpeg", ".3gp", ".ogg", ".weba"}

ROLE_ADMIN = userdb.ROLE_ADMIN
ROLE_USER = userdb.ROLE_USER


# ================= 认证与鉴权 =================

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RoleRequest(BaseModel):
    role: str


class ResetPasswordRequest(BaseModel):
    password: str


class QARequest(BaseModel):
    question: str
    history: list[dict] = []


class DocRequest(BaseModel):
    meeting_id: str


def _bearer_user(authorization: str | None = Header(default=None)) -> dict:
    """从 Authorization: Bearer xxx 解析令牌 → 数据库里的用户(以库为准,含最新角色)"""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    claims = auth_mod.decode_token(token or "")
    if not claims:
        raise PermissionError("401")   # 占位,下方统一转换
    user = userdb.get_user_by_id(claims.get("uid"))
    if not user:
        raise PermissionError("401")
    if user["disabled"]:
        raise PermissionError("403DISABLED")
    return user


def require_login(user: dict = Depends(_bearer_user)) -> dict:
    return user


def require_admin(user: dict = Depends(_bearer_user)) -> dict:
    if user["role"] != ROLE_ADMIN:
        raise PermissionError("403")
    return user


def _meeting_access(meeting_id: str, user: dict) -> dict | None:
    """返回会议记录;无权访问抛 403;不存在返回 None"""
    rec = meetings.get_meeting(meeting_id)
    if rec is None:
        return None
    if user["role"] == ROLE_ADMIN or rec.get("owner") == user["id"]:
        return rec
    raise PermissionError("403")


def _meeting_or_404(meeting_id: str, user: dict) -> JSONResponse | None:
    """鉴权辅助:无权抛 403;会议不存在返回 404 JSON;正常返回 None"""
    rec = _meeting_access(meeting_id, user)
    if rec is None:
        return JSONResponse({"ok": False, "error": "会议不存在或已被删除"}, status_code=404)
    return None


# PermissionError → 统一 JSON(401/403),避免 fastapi 内部 500
def _register_errors(app):
    @app.exception_handler(PermissionError)
    async def _perm_handler(request, exc):
        msg = str(exc)
        if msg == "403DISABLED":
            return JSONResponse({"ok": False, "error": "账号已被禁用,请联系管理员"},
                                status_code=403)
        if msg == "401":
            return JSONResponse({"ok": False, "error": "未登录或登录已过期,请重新登录"},
                                status_code=401)
        return JSONResponse({"ok": False, "error": "没有权限执行该操作"}, status_code=403)


# ================= 页面 =================

@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return (STATIC_DIR / "admin.html").read_text(encoding="utf-8")


# ================= 认证(公开) =================

def _token_payload(user: dict) -> dict:
    token = auth_mod.create_token(user["id"], user["username"], user["role"])
    return {"ok": True, "token": token,
            "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


@app.post("/api/auth/login")
def api_login(req: LoginRequest):
    user = userdb.authenticate(req.username, req.password)
    if not user:
        return JSONResponse({"ok": False, "error": "用户名或密码错误"}, status_code=401)
    return _token_payload(user)


@app.post("/api/auth/register")
def api_register(req: RegisterRequest):
    """注册普通用户(管理员由默认种子或管理员后台创建)"""
    try:
        user = userdb.create_user(req.username, req.password, role=ROLE_USER)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return _token_payload(user)


@app.get("/api/auth/me")
def api_me(user: dict = Depends(require_login)):
    return {"ok": True,
            "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


@app.post("/api/auth/change_password")
def api_change_password(req: ChangePasswordRequest, user: dict = Depends(require_login)):
    cur = userdb.get_user_by_id(user["id"])
    if not cur or not auth_mod.verify_password(req.old_password, cur["password_hash"]):
        return JSONResponse({"ok": False, "error": "原密码不正确"}, status_code=400)
    try:
        userdb.set_password(user["id"], req.new_password)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "message": "密码已修改,下次登录请使用新密码"}


# ================= 会议业务(登录用户;按用户隔离) =================

@app.get("/api/meetings")
def api_meetings(user: dict = Depends(require_login)):
    """会议列表:普通用户只看自己的;管理员看全部(附属主用户名)"""
    items = meetings.list_meetings(None if user["role"] == ROLE_ADMIN else user["id"])
    if user["role"] == ROLE_ADMIN:
        items = _with_owner_name(items)
    return {"meetings": items}


def _with_owner_name(items: list[dict]) -> list[dict]:
    ids = {i.get("owner") for i in items if i.get("owner")}
    names = {}
    for uid in ids:
        u = userdb.get_user_by_id(uid)
        if u:
            names[uid] = u["username"]
    for it in items:
        it["owner_name"] = names.get(it.get("owner")) or ""
    return items


def _extract_wav(src: Path) -> Path:
    """ffmpeg 抽取音轨(16kHz 单声道 wav),失败抛错"""
    wav = src.with_name(src.stem + ".wav")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn",
         "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(wav)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if r.returncode != 0 or not wav.exists():
        err = r.stderr.decode("utf-8", errors="replace")
        wav.unlink(missing_ok=True)
        raise RuntimeError(f"音轨提取失败(该录屏可能没有声音轨):{err[-300:]}")
    return wav


@app.post("/api/ingest")
def api_ingest(file: UploadFile = File(...), title: str = Form("会议"),
               date: str = Form(""), user: dict = Depends(require_login)):
    """上传音频/录屏视频 → 提音轨(视频) → 转写入库 → 登记为当前用户的会议

    支持 .mov/.mp4/.webm 等录屏与 mp3/wav/m4a 等录音;本人已传过的同文件(MD5)去重。
    """
    suffix = Path(file.filename or "audio.mp3").suffix.lower() or ".mp3"
    orig_name = file.filename or f"会议{suffix}"
    tmp = config.AUDIO_DIR / f"upload_{uuid.uuid4().hex[:8]}_{user['id']}{suffix}"

    md5 = hashlib.md5()
    with open(tmp, "wb") as f:
        while chunk := file.file.read(1 << 20):
            f.write(chunk)
            md5.update(chunk)
    md5 = md5.hexdigest()

    # 去重:仅看当前用户的库(业务系统按用户隔离)
    dup = meetings.find_by_md5(md5, owner=user["id"])
    if dup:
        return {"ok": True, "duplicate": True, "meeting_id": dup["id"],
                "title": dup["title"], "chunks": dup.get("chunks", 0)}

    asr_input = tmp
    try:
        if suffix in VIDEO_EXTS:
            asr_input = _extract_wav(tmp)

        meeting_id = meetings.new_id(Path(orig_name).stem or title)
        result = ingest(
            str(asr_input), title or "会议", date or "",
            meeting_id=meeting_id, file_name=orig_name, md5=md5,
        )
        # 把上传的原始录音/录屏改名成「会议 id + 原扩展名」长期保存,供「源文件导出」使用
        dest = config.AUDIO_DIR / f"{meeting_id}{suffix}"
        try:
            tmp.replace(dest)
        except OSError:
            dest = tmp
        rel = dest.resolve().relative_to(config.BASE_DIR.resolve()).as_posix()
        # 归属当前用户 + 记录源文件位置
        meetings.update_meeting(
            meeting_id,
            owner=user["id"],
            source_path=rel,
            source_name=orig_name,
            source_size=dest.stat().st_size if dest.exists() else None,
        )
        return {
            "ok": True, "duplicate": False,
            "chunks": result["chunks"], "title": result["title"],
            "meeting_id": result["meeting_id"], "file": orig_name,
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/answer")
def api_answer(req: QARequest, user: dict = Depends(require_login)):
    """RAG 问答:普通用户只检索自己的会议;管理员检索全部"""
    try:
        scope = None if user["role"] == ROLE_ADMIN else meetings.meeting_ids_of_owner(user["id"])
        r = rag_answer(req.question, history=req.history or None, meeting_ids=scope)
        return {"ok": True, "answer": r["answer"], "citations": r["citations"]}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/meetings/{meeting_id}/raw")
def api_meeting_raw(meeting_id: str, user: dict = Depends(require_login)):
    """某会议的原始转写稿(本人/管理员)"""
    err = _meeting_or_404(meeting_id, user)
    if err:
        return err
    raw = meetings.raw_text(meeting_id)
    if raw is None:
        return JSONResponse({"ok": False, "error": "未找到该会议的原始转写稿"}, status_code=404)
    return {"ok": True, "raw": raw}


@app.get("/api/meetings/{meeting_id}/cleaned")
def api_meeting_cleaned(meeting_id: str, user: dict = Depends(require_login)):
    """某会议的清洗稿(本人/管理员)"""
    err = _meeting_or_404(meeting_id, user)
    if err:
        return err
    cleaned = meetings.cleaned_text(meeting_id)
    if not cleaned:
        return JSONResponse({"ok": False, "error": "未找到该会议的知识库内容"}, status_code=404)
    return {"ok": True, "cleaned": cleaned}


@app.get("/api/meetings/{meeting_id}/source")
def api_meeting_source(meeting_id: str, user: dict = Depends(require_login)):
    """导出会议原始录音/录屏文件:普通用户只能导出自己的,管理员可导出所有人的"""
    err = _meeting_or_404(meeting_id, user)
    if err:
        return err
    path = meetings.source_file(meeting_id)
    if path is None:
        return JSONResponse(
            {"ok": False, "error": "该会议没有保存源文件(可能是升级前的历史会议)"},
            status_code=404)
    rec = meetings.get_meeting(meeting_id) or {}
    download_name = rec.get("source_name") or f"{rec.get('title') or '会议'}{path.suffix}"
    return FileResponse(str(path), filename=download_name)


@app.post("/api/generate_doc")
def api_generate_doc(req: DocRequest, user: dict = Depends(require_login)):
    """把某会议内容生成结构化 Markdown 文档(本人/管理员)"""
    err = _meeting_or_404(req.meeting_id, user)
    if err:
        return err
    text = meetings.cleaned_text(req.meeting_id)
    if not text:
        return JSONResponse(
            {"ok": False, "error": "找不到该会议的内容(可能已删除,或该会议没有知识库文本)"},
            status_code=404)
    try:
        doc = generate_document(text)
        return {"ok": True, "document": doc, "meeting_id": req.meeting_id}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"文档生成失败:{e}"}, status_code=500)


@app.delete("/api/meetings/{meeting_id}")
def api_delete_meeting(meeting_id: str, user: dict = Depends(require_login)):
    """删除会议(本人/管理员)"""
    err = _meeting_or_404(meeting_id, user)
    if err:
        return err
    ok = meetings.delete_meeting(meeting_id)
    return {"ok": ok, "meeting_id": meeting_id}


# ================= 管理员后台 =================

@app.get("/api/admin/users")
def api_admin_users(admin: dict = Depends(require_admin)):
    users = userdb.list_users()
    owners = meetings.list_meetings(None)
    cnt = {}
    for it in owners:
        o = it.get("owner")
        cnt[o] = cnt.get(o, 0) + 1
    out = []
    for u in users:
        item = {"id": u["id"], "username": u["username"], "role": u["role"],
                "disabled": u["disabled"], "created_at": u["created_at"],
                "meetings": cnt.get(u["id"], 0)}
        out.append(item)
    return {"users": out}


@app.post("/api/admin/users/{uid}/disable")
def api_admin_disable(uid: int, admin: dict = Depends(require_admin)):
    if uid == admin["id"]:
        return JSONResponse({"ok": False, "error": "不能禁用自己"}, status_code=400)
    userdb.set_disabled(uid, True)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/enable")
def api_admin_enable(uid: int, admin: dict = Depends(require_admin)):
    userdb.set_disabled(uid, False)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/role")
def api_admin_role(uid: int, req: RoleRequest, admin: dict = Depends(require_admin)):
    if uid == admin["id"]:
        return JSONResponse({"ok": False, "error": "不能修改自己的角色"}, status_code=400)
    target = userdb.get_user_by_id(uid)
    if not target:
        return JSONResponse({"ok": False, "error": "用户不存在"}, status_code=404)
    if target["role"] == userdb.ROLE_ADMIN and req.role != userdb.ROLE_ADMIN \
            and userdb.count_admins() <= 1:
        return JSONResponse({"ok": False, "error": "至少要保留一名管理员"}, status_code=400)
    try:
        userdb.set_role(uid, req.role)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/reset_password")
def api_admin_reset(uid: int, req: ResetPasswordRequest, admin: dict = Depends(require_admin)):
    target = userdb.get_user_by_id(uid)
    if not target:
        return JSONResponse({"ok": False, "error": "用户不存在"}, status_code=404)
    try:
        userdb.set_password(uid, req.password)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
def api_admin_delete_user(uid: int, admin: dict = Depends(require_admin)):
    """删除用户 + 级联删除其全部会议(知识块/转写稿/注册表)"""
    if uid == admin["id"]:
        return JSONResponse({"ok": False, "error": "不能删除自己(可联系另一管理员)"}, status_code=400)
    target = userdb.get_user_by_id(uid)
    if not target:
        return JSONResponse({"ok": False, "error": "用户不存在"}, status_code=404)
    if target["role"] == ROLE_ADMIN and userdb.count_admins() <= 1:
        return JSONResponse({"ok": False, "error": "至少要保留一名管理员"}, status_code=400)
    for mid in meetings.meeting_ids_of_owner(uid):
        meetings.delete_meeting(mid)
    userdb.delete_user(uid)
    return {"ok": True}


@app.get("/api/admin/stats")
def api_admin_stats(admin: dict = Depends(require_admin)):
    users = userdb.list_users()
    meeting_list = meetings.list_meetings(None)
    docs = meetings.all_docs()
    return {"ok": True, "stats": {
        "users": len(users),
        "admins": sum(1 for u in users if u["role"] == ROLE_ADMIN),
        "disabled": sum(1 for u in users if u["disabled"]),
        "meetings": len(meeting_list),
        "chunks": len(docs),
        "chars": sum(len(d.get("text") or "") for d in docs),
    }}


# ================= 健康检查(公开) =================

@app.get("/api/status")
def status():
    return {"ok": True, "service": "meeting-kb", "device": config.DEVICE, "asr": config.ASR_DEVICE}


_register_errors(app)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 启动时确保用户表存在并含默认管理员(不会覆盖已改密码)
userdb.ensure_admin()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)

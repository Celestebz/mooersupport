"""
邮箱草稿与 IMAP 操作 API。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_db
from ..schemas import DraftDetail, DraftSendRequest

router = APIRouter(prefix="/drafts", tags=["邮箱草稿"])


def _get_imap_handler():
    """延迟初始化 IMAP，避免 API 启动时立即连接邮箱。"""
    from pathlib import Path
    from imap_handler import IMAPHandler

    config_path = str(Path(__file__).resolve().parent.parent.parent / "config.yml")
    handler = IMAPHandler(config_path=config_path)
    if not handler.connect_imap():
        raise RuntimeError("无法连接 IMAP")
    return handler


def _draft_to_detail(draft: dict) -> DraftDetail:
    body = str(draft.get("body", "") or "")
    uid = str(draft.get("uid") or draft.get("id") or "")
    return DraftDetail(
        uid=uid,
        id=uid,
        subject=draft.get("subject", "") or "",
        to=draft.get("to", "") or "",
        sender=draft.get("sender", "") or "",
        date=str(draft.get("date", "") or ""),
        body=body,
        body_preview=body[:200],
        message_id=draft.get("message_id", "") or "",
        in_reply_to=draft.get("in_reply_to", "") or "",
        references=draft.get("references", "") or "",
    )


@router.get("", response_model=list[DraftDetail])
def list_drafts():
    """通过 IMAP 读取邮箱草稿。"""
    handler = None
    try:
        handler = _get_imap_handler()
        return [_draft_to_detail(draft) for draft in handler.get_drafts(max_drafts=100)]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"邮箱 IMAP 不可用: {e}")
    finally:
        if handler:
            try:
                handler.disconnect_imap()
            except Exception:
                pass


@router.post("/{draft_uid}/send")
def send_draft(draft_uid: str, body: Optional[DraftSendRequest] = None):
    """处理邮箱草稿。"""
    handler = None
    try:
        handler = _get_imap_handler()
        draft = next(
            (item for item in handler.get_drafts(max_drafts=100) if str(item.get("id")) == str(draft_uid)),
            None,
        )
        if not draft:
            raise HTTPException(status_code=404, detail="草稿不存在")

        payload = body or DraftSendRequest()
        recipients = payload.to_addrs or []
        if not recipients and draft.get("to"):
            recipients = [draft.get("to")]
        if not recipients:
            raise HTTPException(status_code=400, detail="缺少收件人")

        success = handler.send_email(
            recipient=recipients[0],
            subject=payload.subject or draft.get("subject", ""),
            body=payload.body if payload.body is not None else draft.get("body", ""),
            original_sender=payload.original_sender,
            original_date=payload.original_date,
        )
        if success:
            handler.delete_draft(draft_uid)
        return {"ok": success}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"发送草稿失败: {e}")
    finally:
        if handler:
            try:
                handler.disconnect_imap()
            except Exception:
                pass


@router.delete("/{draft_uid}")
def delete_draft(draft_uid: str):
    """处理邮箱草稿。"""
    handler = None
    try:
        handler = _get_imap_handler()
        success = handler.delete_draft(draft_uid)
        return {"ok": success}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"删除草稿失败: {e}")
    finally:
        if handler:
            try:
                handler.disconnect_imap()
            except Exception:
                pass

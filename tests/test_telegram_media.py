from __future__ import annotations

from types import SimpleNamespace

from app.telegram.handlers import (
    _document_allowed,
    _is_forwarded,
    _normalize_media_filename,
    pick_media,
)


def _doc(*, file_name: str | None = None, mime_type: str | None = None):
    return SimpleNamespace(file_name=file_name, mime_type=mime_type)


def test_document_allowed_uppercase_extension() -> None:
    assert _document_allowed(_doc(file_name="clip.MP4", mime_type="application/octet-stream"))
    assert _document_allowed(_doc(file_name="CLIP.MOV", mime_type="video/quicktime"))


def test_document_rejected_unknown() -> None:
    assert not _document_allowed(_doc(file_name="readme.pdf", mime_type="application/pdf"))


def test_document_forwarded_octet_stream_without_name() -> None:
    assert _document_allowed(
        _doc(file_name=None, mime_type="application/octet-stream"),
        forwarded=True,
    )


def test_is_forwarded() -> None:
    msg = SimpleNamespace(forward_origin=object(), forward_date=None)
    assert _is_forwarded(msg)


def test_normalize_media_filename() -> None:
    assert _normalize_media_filename("My.MP4", default="video.mp4") == "My.mp4"


def test_pick_media_video_note() -> None:
    msg = SimpleNamespace(
        video=None,
        video_note=SimpleNamespace(file_id="vn1", file_size=1000),
        audio=None,
        voice=None,
        document=None,
    )
    assert pick_media(msg) == ("vn1", 1000, "video_note.mp4")

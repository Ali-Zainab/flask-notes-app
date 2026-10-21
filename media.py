"""Secure media-attachment helpers for NoteNest: content sniffing, size-limited streaming
storage on disk, filename sanitising and upload-root path safety.

Nothing here trusts a browser-supplied filename, extension or Content-Type.
Files live in a flat, app-owned upload root under random names (`<32 hex>.<ext>`).
"""

import logging
import os
import re
import secrets

log = logging.getLogger(__name__)

MIB = 1024 * 1024
MAX_IMAGE_BYTES = 10 * MIB
MAX_AUDIO_BYTES = 25 * MIB
CHUNK = 64 * 1024

# format -> (kind, verified MIME type, canonical stored extension, accepted original extensions)
FORMATS = {
    "png": ("image", "image/png", ".png", {".png"}),
    "jpeg": ("image", "image/jpeg", ".jpg", {".jpg", ".jpeg"}),
    "gif": ("image", "image/gif", ".gif", {".gif"}),
    "webp": ("image", "image/webp", ".webp", {".webp"}),
    "mp3": ("audio", "audio/mpeg", ".mp3", {".mp3"}),
    "wav": ("audio", "audio/wav", ".wav", {".wav"}),
    "ogg": ("audio", "audio/ogg", ".ogg", {".ogg", ".oga"}),
    "flac": ("audio", "audio/flac", ".flac", {".flac"}),
    "m4a": ("audio", "audio/mp4", ".m4a", {".m4a", ".m4b"}),
}
KEY_RE = re.compile(r"[0-9a-f]{32}\.(?:png|jpg|gif|webp|mp3|wav|ogg|flac|m4a)")


class _TooLarge(Exception):
    pass


def _is_mp3(h):
    if h[:3] == b"ID3":
        return True
    if len(h) >= 3 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:
        version, layer = (h[1] >> 3) & 3, (h[1] >> 1) & 3
        return version != 1 and layer != 0 and (h[2] >> 4) != 15 and ((h[2] >> 2) & 3) != 3
    return False


def detect_format(h):
    """Identify a supported format from the first bytes, or return None."""
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if h[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "wav"
    if h[:4] == b"OggS":
        return "ogg"
    if h[:4] == b"fLaC":
        return "flac"
    if h[4:8] == b"ftyp" and h[8:12] in (b"M4A ", b"M4B "):
        return "m4a"
    if _is_mp3(h):
        return "mp3"
    return None


def clean_filename(name):
    """Display-only filename: no directories, no control characters, bounded length."""
    name = re.split(r"[\\/]", name or "")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip().strip(".")
    return name[:120] or "attachment"


def upload_path(root, key):
    """Absolute path for a storage key; ValueError unless it is a well-formed key inside root."""
    if not KEY_RE.fullmatch(key or ""):
        raise ValueError("invalid storage key")
    real_root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(real_root, key))
    if os.path.dirname(path) != real_root:
        raise ValueError("path escapes upload root")
    return path


def save_stream(stream, original_name, root, limits=None):
    """Validate and store an upload. Returns (info, None) or (None, reason).

    The stream is copied in 64 KiB chunks and aborted as soon as the limit for its detected
    kind is exceeded, so oversized uploads are never held in memory or fully written to disk.
    """
    limits = limits or {"image": MAX_IMAGE_BYTES, "audio": MAX_AUDIO_BYTES}
    header = stream.read(32)
    if not header:
        return None, "is empty."
    fmt = detect_format(header)
    if fmt is None:
        return None, "is not a supported image or audio file."
    kind, mime, ext, allowed = FORMATS[fmt]
    if os.path.splitext(original_name or "")[1].lower() not in allowed:
        return None, f"has a file extension that does not match its {fmt.upper()} contents."
    limit = limits[kind]
    key = secrets.token_hex(16) + ext
    os.makedirs(root, exist_ok=True)
    path = upload_path(root, key)
    size = len(header)
    try:
        with open(path, "xb") as out:
            out.write(header)
            while True:
                if size > limit:
                    raise _TooLarge
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise _TooLarge
                out.write(chunk)
    except _TooLarge:
        _unlink(path)
        return None, f"is larger than the {limit // MIB} MiB limit for {kind} files."
    except OSError:
        log.exception("Could not store upload")
        _unlink(path)
        return None, "could not be saved on the server."
    return {"key": key, "kind": kind, "mime": mime, "size": size}, None


def _unlink(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def remove_files(root, keys):
    """Delete files by storage key. Returns the keys that could not be removed (and logs them)."""
    failed = []
    for key in keys:
        try:
            _unlink(upload_path(root, key))
        except (OSError, ValueError):
            log.error("Could not delete media file %r from %s", key, root, exc_info=True)
            failed.append(key)
    return failed


def cleanup_orphans(root, known_keys):
    """Remove well-formed media files in root that no database row references. Returns removed keys."""
    if not os.path.isdir(root):
        return []
    known, removed = set(known_keys), []
    for name in sorted(os.listdir(root)):
        if KEY_RE.fullmatch(name) and name not in known and not remove_files(root, [name]):
            removed.append(name)
    return removed


def human_size(n):
    for unit in ("B", "KiB", "MiB"):
        if n < 1024 or unit == "MiB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024

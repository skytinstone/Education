"""프로필 사진 — 올린 사진은 정사각형 256px WEBP 로 다시 만들어 저장한다.

다시 만들면서 사진 속 메타데이터(EXIF: 촬영 위치 GPS, 기기 정보 등)가 모두 사라진다.
Eureka 캐릭터(preset)는 화면에서 SVG 로 그리므로 서버는 이름만 저장한다.
"""

from __future__ import annotations

from io import BytesIO
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError

from education.config import ROOT

AVATAR_DIR = ROOT / "data" / "uploads" / "avatars"
PRESETS = ("spark", "cap", "glasses", "flask", "atom", "bulb", "book", "pencil", "star", "rocket", "headphones", "crown")
MAX_BYTES = 5 * 1024 * 1024
SIZE = 256


class AvatarError(ValueError):
    pass


def path_for(user_id: UUID):
    return AVATAR_DIR / f"{user_id}.webp"


def process_photo(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise AvatarError("사진은 5MB 까지 올릴 수 있어요")
    try:
        img = Image.open(BytesIO(data))
        if img.format not in {"PNG", "JPEG", "WEBP"}:
            raise AvatarError("PNG·JPG·WEBP 사진만 올릴 수 있어요")
        if img.width * img.height > 40_000_000:
            raise AvatarError("사진이 너무 커요")
        img = ImageOps.exif_transpose(img)  # 휴대폰 사진의 회전 정보를 반영한 뒤
        img = ImageOps.fit(img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB"), (SIZE, SIZE), Image.LANCZOS)
    except (UnidentifiedImageError, OSError) as e:
        raise AvatarError("사진을 열 수 없어요. 다른 파일로 올려 주세요") from e
    out = BytesIO()
    img.save(out, "WEBP", quality=85)  # 새로 저장하므로 EXIF 등 메타데이터는 남지 않는다
    return out.getvalue()


def save_photo(user_id: UUID, data: bytes) -> None:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    path_for(user_id).write_bytes(process_photo(data))


def delete_photo(user_id: UUID) -> None:
    path_for(user_id).unlink(missing_ok=True)

"""계정 정보(생년월일·학교·전공·주소)와 프로필 사진(사진·Eureka 캐릭터·이니셜)."""

from datetime import date, timedelta
from io import BytesIO

import pytest
from PIL import Image

from education.services import avatars


@pytest.fixture(autouse=True)
def tmp_avatars(monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "AVATAR_DIR", tmp_path)


def photo_bytes(fmt="JPEG", size=(1200, 800)) -> bytes:
    img = Image.new("RGB", size, (200, 120, 80))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # 기기 제조사
    exif[0x0110] = "PhoneModel"
    buf = BytesIO()
    img.save(buf, fmt, exif=exif.tobytes())
    return buf.getvalue()


def test_profile_fields_set_and_clear(client, auth):
    r = client.patch("/api/me", json={"birth_date": "2008-03-14", "school": " 유레카고등학교 ", "major": "자연계열",
                                      "address": "서울특별시 강남구"}, headers=auth).json()
    assert (r["birth_date"], r["school"], r["major"], r["address"]) == ("2008-03-14", "유레카고등학교", "자연계열", "서울특별시 강남구")
    r = client.patch("/api/me", json={"school": "", "birth_date": None}, headers=auth).json()
    assert r["school"] is None and r["birth_date"] is None and r["major"] == "자연계열"  # 보낸 것만 바뀜


def test_profile_validation(client, auth):
    future = (date.today() + timedelta(days=1)).isoformat()
    assert client.patch("/api/me", json={"birth_date": future}, headers=auth).status_code == 422
    assert client.patch("/api/me", json={"address": "가" * 201}, headers=auth).status_code == 422
    assert client.patch("/api/me", json={"avatar": "dragon"}, headers=auth).status_code == 422


def test_preset_and_initial(client, auth):
    r = client.patch("/api/me", json={"avatar": "rocket"}, headers=auth).json()
    assert (r["avatar_type"], r["avatar_preset"], r["avatar_url"]) == ("preset", "rocket", None)
    r = client.patch("/api/me", json={"avatar": "initial"}, headers=auth).json()
    assert (r["avatar_type"], r["avatar_preset"]) == ("initial", None)


def test_photo_upload_strips_metadata(client, auth, tmp_path):
    r = client.post("/api/me/avatar", files={"file": ("me.jpg", photo_bytes(), "image/jpeg")}, headers=auth)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["avatar_type"] == "photo" and me["avatar_url"].endswith("?v=1")

    img = client.get(me["avatar_url"])  # <img> 처럼 로그인 없이
    assert img.status_code == 200 and img.headers["content-type"] == "image/webp"
    out = Image.open(BytesIO(img.content))
    assert out.size == (256, 256)
    assert len(out.getexif()) == 0  # 기기·위치 정보가 남지 않음

    again = client.post("/api/me/avatar", files={"file": ("me.png", photo_bytes("PNG", (300, 900)), "image/png")}, headers=auth).json()
    assert again["avatar_url"].endswith("?v=2")  # 바꿀 때마다 주소가 바뀌어 캐시 무효화

    # 캐릭터로 바꾸면 사진 파일도 지운다
    client.patch("/api/me", json={"avatar": "cap"}, headers=auth)
    assert not avatars.path_for(me["id"]).exists()
    assert client.get(me["avatar_url"]).status_code == 404


def test_photo_rejects_non_images(client, auth):
    bad = client.post("/api/me/avatar", files={"file": ("x.png", b"not an image", "image/png")}, headers=auth)
    assert bad.status_code == 422
    gif = BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    assert client.post("/api/me/avatar", files={"file": ("x.gif", gif.getvalue(), "image/gif")}, headers=auth).status_code == 422


def test_sync_includes_profile(client, auth):
    client.patch("/api/me", json={"school": "유레카고", "avatar": "flask"}, headers=auth)
    user = client.get("/api/sync", headers=auth).json()["user"]
    assert user["school"] == "유레카고" and user["avatarType"] == "preset" and user["avatarPreset"] == "flask"

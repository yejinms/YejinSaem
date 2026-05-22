import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite:///./test_yejinsaem.db"
os.environ["UPLOAD_DIR"] = "./test_uploads"
os.environ["ADMIN_PASSWORD"] = ""
os.environ["KAKAO_CHANNEL_SECRET"] = ""

from fastapi.testclient import TestClient

import routers.admin as admin_router
import routers.kakao as kakao_router
from database import Base, Parent, SessionLocal, Submission, engine
from main import app


client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    shutil.rmtree("test_uploads", ignore_errors=True)
    Path("test_uploads").mkdir(exist_ok=True)


def teardown_module():
    Base.metadata.drop_all(bind=engine)
    Path("test_yejinsaem.db").unlink(missing_ok=True)
    shutil.rmtree("test_uploads", ignore_errors=True)


def create_parent(kakao_user_id="kakao-1", phone_number="01012345678"):
    db = SessionLocal()
    parent = Parent(
        kakao_user_id=kakao_user_id,
        phone_number=phone_number,
        child_name="민준",
        child_age=8,
        level="표현력",
    )
    db.add(parent)
    db.commit()
    db.refresh(parent)
    db.close()
    return parent.id


def submission_count():
    db = SessionLocal()
    count = db.query(Submission).count()
    db.close()
    return count


def kakao_payload(user_id, utterance=""):
    return {
        "userRequest": {
            "user": {"id": user_id},
            "utterance": utterance,
        }
    }


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_parent_create_and_update_phone_number():
    created = client.post(
        "/admin/parents",
        json={
            "phone_number": "010-1111-2222",
            "child_name": "서연",
            "child_age": 9,
            "level": "초등기초",
        },
    )
    assert created.status_code == 201
    parent_id = created.json()["id"]
    assert created.json()["phone_number"] == "01011112222"
    assert created.json()["kakao_user_id"] == "pending:01011112222"
    assert created.json()["kakao_linked"] is False

    updated = client.put(
        f"/admin/parents/{parent_id}",
        json={"phone_number": "01033334444", "child_name": "서연", "child_age": 10},
    )
    assert updated.status_code == 200
    assert updated.json()["phone_number"] == "01033334444"
    assert updated.json()["child_age"] == 10


def test_delete_parent_removes_submissions():
    parent_id = create_parent()
    db = SessionLocal()
    db.add(Submission(parent_id=parent_id, status="pending"))
    db.commit()
    db.close()
    assert submission_count() == 1

    res = client.delete(f"/admin/parents/{parent_id}")
    assert res.status_code == 204

    db = SessionLocal()
    assert db.query(Parent).filter(Parent.id == parent_id).first() is None
    assert db.query(Submission).count() == 0
    db.close()


def test_admin_auth_when_password_is_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "관리자-secret")
    assert client.get("/admin/parents").status_code == 401
    res = client.get(
        "/admin/parents",
        headers={"Authorization": "Bearer %EA%B4%80%EB%A6%AC%EC%9E%90-secret"},
    )
    assert res.status_code == 200
    monkeypatch.setenv("ADMIN_PASSWORD", "")


def test_kakao_webhook_unregistered_user_does_not_create_submission():
    res = client.post("/kakao/webhook", json=kakao_payload("unknown", "안녕"))
    assert res.status_code == 200
    assert submission_count() == 0
    text = res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert "생글방글입니다" in text
    assert "휴대폰" not in text


def test_kakao_webhook_unlinked_user_with_image_creates_guest_submission(monkeypatch):
    async def fake_download_image(url):
        return b"image-bytes", "image/jpeg"

    monkeypatch.setattr(kakao_router, "download_image", fake_download_image)
    res = client.post(
        "/kakao/webhook",
        json=kakao_payload("new-visitor-bot", "https://example.com/worksheet.jpg"),
    )
    assert res.status_code == 200
    assert "사진을 받았어요" in res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert submission_count() == 1

    db = SessionLocal()
    parent = db.query(Parent).filter(Parent.kakao_user_id == "new-visitor-bot").one()
    assert parent.child_name == "채널 미등록"
    assert parent.phone_number is None
    db.close()


def test_kakao_webhook_image_utterance_without_urls_prompts_secureimage():
    res = client.post(
        "/kakao/webhook",
        json=kakao_payload("visitor-no-url", "1장의 이미지를 보냈어요."),
    )
    assert res.status_code == 200
    text = res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert "사진 보내기" in text
    assert submission_count() == 0


def test_kakao_channel_messages_never_include_internal_name():
    create_parent("name-check-bot", phone_number="01088887777")
    db = SessionLocal()
    parent = db.query(Parent).filter(Parent.phone_number == "01088887777").one()
    parent.child_name = "비밀관리명"
    db.commit()
    db.close()

    res = client.post("/kakao/webhook", json=kakao_payload("name-check-bot", "첨삭"))
    text = res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert "비밀관리명" not in text
    assert "학부모님" not in text
    assert "생글방글입니다" in text


def test_admin_can_set_kakao_user_id_on_update():
    created = client.post(
        "/admin/parents",
        json={
            "phone_number": "01055556666",
            "child_name": "테스트",
            "level": "표현력",
        },
    )
    parent_id = created.json()["id"]
    updated = client.put(
        f"/admin/parents/{parent_id}",
        json={"kakao_user_id": "mom-bot-key-123"},
    )
    assert updated.status_code == 200
    assert updated.json()["kakao_user_id"] == "mom-bot-key-123"


def test_kakao_webhook_linked_user_accepts_image(monkeypatch):
    create_parent("real-bot-user", phone_number="01099998888")

    async def fake_download_image(url):
        return b"image-bytes", "image/jpeg"

    monkeypatch.setattr(kakao_router, "download_image", fake_download_image)

    image_res = client.post(
        "/kakao/webhook",
        json=kakao_payload("real-bot-user", "https://example.com/a.jpg"),
    )
    assert image_res.status_code == 200
    assert "사진을 받았어요" in image_res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert submission_count() == 1


def test_kakao_webhook_registered_text_uses_channel_greeting():
    create_parent("kakao-text")
    res = client.post("/kakao/webhook", json=kakao_payload("kakao-text", "선생님 첨삭 받기"))
    assert res.status_code == 200
    assert submission_count() == 0
    text = res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert "생글방글입니다" in text
    assert "워크시트" not in text


def test_kakao_webhook_registered_image_creates_pending_submission(monkeypatch):
    create_parent("kakao-image")

    async def fake_download_image(url):
        return b"image-bytes", "image/jpeg"

    monkeypatch.setattr(kakao_router, "download_image", fake_download_image)
    res = client.post("/kakao/webhook", json=kakao_payload("kakao-image", "https://example.com/a.jpg"))

    assert res.status_code == 200
    db = SessionLocal()
    submission = db.query(Submission).one()
    db.close()
    assert submission.status == "pending"
    assert submission.photo_path.endswith(".jpg")


def test_kakao_webhook_secureimage_plugin_creates_pending_submission(monkeypatch):
    create_parent("kakao-secure", phone_number="01077776666")

    async def fake_download_image(url):
        assert "secure.kakaocdn.net" in url
        return b"image-bytes", "image/jpeg"

    monkeypatch.setattr(kakao_router, "download_image", fake_download_image)
    secure_url = (
        "http://secure.kakaocdn.net/dna/test/img.jpg"
        "?credential=abc&expires=9999999999"
    )
    res = client.post(
        "/kakao/webhook",
        json={
            "userRequest": {"user": {"id": "kakao-secure"}, "utterance": ""},
            "action": {
                "name": "이미지보안",
                "detailParams": {
                    "secureimage": {
                        "origin": f"List({secure_url})",
                    }
                },
            },
        },
    )
    assert res.status_code == 200
    assert "사진을 받았어요" in res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert submission_count() == 1


def test_kakao_webhook_secureimage_multiple_images_in_one_payload(monkeypatch):
    create_parent("kakao-multi", phone_number="01066665555")

    downloaded_urls: list[str] = []

    async def fake_download_image(url):
        downloaded_urls.append(url)
        return b"image-bytes", "image/jpeg"

    monkeypatch.setattr(kakao_router, "download_image", fake_download_image)
    url_a = "http://secure.kakaocdn.net/dna/test/a.jpg?credential=abc"
    url_b = "http://secure.kakaocdn.net/dna/test/b.jpg?credential=def"
    res = client.post(
        "/kakao/webhook",
        json={
            "userRequest": {"user": {"id": "kakao-multi"}, "utterance": ""},
            "action": {
                "detailParams": {
                    "secureimage": {
                        "origin": f"List({url_a}, {url_b})",
                    }
                },
            },
        },
    )
    assert res.status_code == 200
    assert "2장" in res.json()["template"]["outputs"][0]["simpleText"]["text"]
    assert len(downloaded_urls) == 2

    db = SessionLocal()
    submission = db.query(Submission).one()
    paths = admin_router.get_submission_photo_paths(submission)
    db.close()
    assert len(paths) == 2


def test_kakao_webhook_registered_image_attachment_creates_pending_submission(monkeypatch):
    create_parent("kakao-attachment")

    async def fake_download_image(url):
        assert url == "https://example.com/image/12345"
        return b"image-bytes", "image/png"

    monkeypatch.setattr(kakao_router, "download_image", fake_download_image)
    res = client.post(
        "/kakao/webhook",
        json={
            "userRequest": {
                "user": {"id": "kakao-attachment"},
                "utterance": "사진을 보냈어요",
                "attachment": {
                    "type": "image",
                    "payload": {
                        "url": "https://example.com/image/12345",
                    },
                },
            }
        },
    )

    assert res.status_code == 200
    db = SessionLocal()
    submission = db.query(Submission).one()
    db.close()
    assert submission.status == "pending"
    assert submission.photo_path.endswith(".png")


def test_generate_requires_photo():
    parent_id = create_parent()
    db = SessionLocal()
    submission = Submission(parent_id=parent_id, status="pending")
    db.add(submission)
    db.commit()
    db.refresh(submission)
    submission_id = submission.id
    db.close()

    res = client.post(
        f"/admin/submissions/{submission_id}/generate",
        json={"level": "표현력", "stage": 1, "extra_instruction": ""},
    )
    assert res.status_code == 400


def test_generate_feedback_receives_all_submission_images(monkeypatch):
    parent_id = create_parent()
    image_paths = ["test_uploads/worksheet-1.png", "test_uploads/worksheet-2.jpg"]
    for image_path in image_paths:
        Path(image_path).write_bytes(b"image-bytes")

    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        photo_path=admin_router.serialize_photo_paths(image_paths),
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    submission_id = submission.id
    db.close()

    captured = {}

    def fake_generate_feedback(**kwargs):
        captured.update(kwargs)
        return "생성된 피드백입니다."

    monkeypatch.setattr(admin_router, "generate_feedback", fake_generate_feedback)
    res = client.post(
        f"/admin/submissions/{submission_id}/generate",
        json={"level": "표현력", "stage": 1, "extra_instruction": ""},
    )
    assert res.status_code == 200
    assert captured["image_path"] == image_paths


def test_approve_failure_preserves_feedback_and_sets_approved(monkeypatch):
    parent_id = create_parent(phone_number="01012345678")
    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        status="generated",
        feedback_draft="좋은 피드백입니다.",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    submission_id = submission.id
    db.close()

    monkeypatch.setattr(
        admin_router,
        "send_feedback_message",
        lambda **kwargs: {"success": False, "error": "send failed"},
    )
    res = client.put(
        f"/admin/submissions/{submission_id}/approve",
        json={"feedback_text": "수정한 피드백입니다."},
    )
    assert res.status_code == 502

    db = SessionLocal()
    saved = db.query(Submission).filter(Submission.id == submission_id).one()
    db.close()
    assert saved.status == "approved"
    assert saved.feedback_draft == "수정한 피드백입니다."


def test_mark_sent_manually_without_kakao():
    parent_id = create_parent(phone_number="01012345678")
    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        status="generated",
        feedback_draft="직접 보낸 피드백",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    submission_id = submission.id
    db.close()

    res = client.post(
        f"/admin/submissions/{submission_id}/mark-sent",
        json={"feedback_text": "최종 피드백 문구"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "sent"

    db = SessionLocal()
    saved = db.query(Submission).filter(Submission.id == submission_id).one()
    db.close()
    assert saved.status == "sent"
    assert saved.feedback_draft == "최종 피드백 문구"


def test_mark_sent_manually_rejects_already_sent():
    parent_id = create_parent()
    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        status="sent",
        feedback_draft="완료",
    )
    db.add(submission)
    db.commit()
    submission_id = submission.id
    db.close()

    res = client.post(f"/admin/submissions/{submission_id}/mark-sent", json={})
    assert res.status_code == 400


def test_retry_send_success_sets_sent(monkeypatch):
    parent_id = create_parent(phone_number="01012345678")
    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        status="approved",
        feedback_draft="다시 보낼 피드백입니다.",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    submission_id = submission.id
    db.close()

    monkeypatch.setattr(
        admin_router,
        "send_feedback_message",
        lambda **kwargs: {"success": True, "response": {"messageId": "ok"}},
    )
    res = client.post(f"/admin/submissions/{submission_id}/retry-send", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "sent"


def test_admin_upload_rejects_non_image():
    parent_id = create_parent()
    res = client.post(
        f"/admin/submissions/upload?parent_id={parent_id}",
        files={"photo": ("note.txt", b"not image", "text/plain")},
    )
    assert res.status_code == 400


def test_admin_upload_image_creates_pending_submission():
    parent_id = create_parent()
    res = client.post(
        f"/admin/submissions/upload?parent_id={parent_id}",
        files={"photo": ("worksheet.png", b"image-bytes", "image/png")},
    )
    assert res.status_code == 201
    assert res.json()["status"] == "pending"

    db = SessionLocal()
    submission = db.query(Submission).one()
    db.close()
    assert submission.parent_id == parent_id
    assert submission.status == "pending"
    assert submission.photo_path.endswith(".png")


def test_admin_upload_multiple_images_creates_one_submission():
    parent_id = create_parent()
    res = client.post(
        f"/admin/submissions/upload?parent_id={parent_id}",
        files=[
            ("photos", ("worksheet-1.png", b"image-bytes-1", "image/png")),
            ("photos", ("worksheet-2.jpg", b"image-bytes-2", "image/jpeg")),
        ],
    )
    assert res.status_code == 201
    assert res.json()["status"] == "pending"
    assert len(res.json()["photo_paths"]) == 2

    db = SessionLocal()
    submission = db.query(Submission).one()
    db.close()
    assert submission.parent_id == parent_id
    assert submission.status == "pending"
    assert len(admin_router.get_submission_photo_paths(submission)) == 2

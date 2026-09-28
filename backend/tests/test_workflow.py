import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite:///./test_yejinsaem.db"
os.environ["UPLOAD_DIR"] = "./test_uploads"
os.environ["ADMIN_PASSWORD"] = ""
os.environ["KAKAO_CHANNEL_SECRET"] = ""

from fastapi.testclient import TestClient

import routers.admin as admin_router
import routers.kakao as kakao_router
from database import Base, Parent, SessionLocal, Submission, WorkbookPurchase, WorkbookUse, engine
from workbook_service import seoul_date
from datetime import timedelta
from main import app
import storage_r2_archive
import storage_slack_alert


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


def test_r2_slack_capacity_alert_once_then_rearms(monkeypatch, tmp_path):
    sent = []

    class Response:
        text = "ok"

        def raise_for_status(self):
            pass

    monkeypatch.setenv("SLACK_R2_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setattr(storage_slack_alert, "_state_path", lambda: tmp_path / "alert.json")
    monkeypatch.setattr(storage_slack_alert.requests, "post",
                        lambda url, json, timeout: sent.append(json["text"]) or Response())

    assert storage_slack_alert.maybe_alert_r2_capacity(8_100_000_000)
    assert not storage_slack_alert.maybe_alert_r2_capacity(8_200_000_000)
    assert len(sent) == 1
    assert "8.10GB" in sent[0]
    assert not storage_slack_alert.maybe_alert_r2_capacity(7_900_000_000)
    assert storage_slack_alert.maybe_alert_r2_capacity(8_000_000_000)
    assert len(sent) == 2


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


def test_parent_create_international_phone_number():
    created = client.post(
        "/admin/parents",
        json={
            "phone_number": "+1 999-222-9333",
            "child_name": "해외학부모",
            "child_age": 9,
            "level": "초등기초",
        },
    )
    assert created.status_code == 201
    assert created.json()["phone_number"] == "19992229333"


def test_bulk_import_parents_from_paste():
    text = "테스트일괄\t010-9999-0001\t0\t태그\t카톡\t표현력\n"
    res = client.post("/admin/parents/bulk-import", json={"text": text})
    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1
    assert body["skipped"] == 0
    assert body["imported"] == 1

    listed = client.get("/admin/parents").json()
    assert any(p["child_name"] == "테스트일괄" for p in listed)

    res2 = client.post("/admin/parents/bulk-import", json={"text": text})
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["created"] == 0
    assert body2["skipped"] == 1


def test_parent_create_with_multiple_levels():
    created = client.post(
        "/admin/parents",
        json={
            "phone_number": "01088887777",
            "child_name": "복수레벨",
            "levels": ["초등심화", "표현력", "초등기초"],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["levels"] == ["표현력", "초등기초", "초등심화"]
    assert body["level"] == "표현력"


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


def test_delete_submission():
    parent_id = create_parent()
    image_path = "test_uploads/delete-me.png"
    Path(image_path).write_bytes(b"image-bytes")

    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        photo_path=image_path,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    submission_id = submission.id
    db.close()

    res = client.delete(f"/admin/submissions/{submission_id}")
    assert res.status_code == 204
    assert submission_count() == 0
    assert not Path(image_path).exists()


def test_storage_cleanup_removes_sent_photos():
    parent_id = create_parent()
    image_path = "test_uploads/sent-cleanup.jpg"
    Path(image_path).write_bytes(b"x" * 5000)

    db = SessionLocal()
    submission = Submission(
        parent_id=parent_id,
        photo_path=image_path,
        status="sent",
        feedback_draft="보낸 피드백",
    )
    db.add(submission)
    db.commit()
    submission_id = submission.id
    db.close()

    res = client.post(
        "/admin/storage/cleanup",
        json={
            "remove_sent_photos": True,
            "remove_orphans": True,
            "vacuum_database": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["removed_sent_submission_photos"] == 1
    assert body["freed_bytes"] >= 5000
    assert not Path(image_path).exists()

    db = SessionLocal()
    saved = db.query(Submission).filter(Submission.id == submission_id).one()
    db.close()
    assert saved.photo_path is None
    assert saved.feedback_draft == "보낸 피드백"


def test_storage_status_endpoint():
    res = client.get("/admin/storage/status")
    assert res.status_code == 200
    body = res.json()
    assert "upload_human" in body
    assert "database_human" in body


def test_storage_photos_backup_zip():
    parent_id = create_parent()
    image_path = "test_uploads/backup-photo.jpg"
    Path(image_path).write_bytes(b"photo-backup-bytes" * 100)

    db = SessionLocal()
    db.add(
        Submission(
            parent_id=parent_id,
            photo_path=image_path,
            status="sent",
            feedback_draft="피드백",
        )
    )
    db.commit()
    db.close()

    res = client.get("/admin/storage/backup/photos")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/zip")
    assert "yejinsaem-photos" in res.headers.get("content-disposition", "")
    assert len(res.content) > 100


def test_auto_archive_removes_only_verified_sent_photos(monkeypatch):
    parent_id = create_parent()
    sent_path = Path("test_uploads/auto-sent.jpg")
    pending_path = Path("test_uploads/auto-pending.jpg")
    sent_path.write_bytes(b"sent-photo" * 100)
    pending_path.write_bytes(b"pending-photo" * 100)
    db = SessionLocal()
    db.add_all([
        Submission(parent_id=parent_id, photo_path=str(sent_path), status="sent"),
        Submission(parent_id=parent_id, photo_path=str(pending_path), status="pending"),
    ])
    db.commit()
    monkeypatch.setenv("AUTO_ARCHIVE_ENABLED", "true")
    configure_test_archive(monkeypatch)

    uploaded = []
    def verified_upload(_client, path, key):
        uploaded.append(key)
        if key.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None
                assert len(archive.namelist()) == 3

    monkeypatch.setattr(storage_r2_archive, "upload_verified", verified_upload)
    result = storage_r2_archive.archive_if_needed(db)
    assert len(uploaded) == 2
    assert result["photos_archived"] == 2
    assert result["sent_photos_removed"] == 1
    assert not sent_path.exists()
    assert pending_path.exists()
    assert db.query(Submission).filter(Submission.status == "sent").one().photo_path is None
    db.close()


def test_manual_archive_runs_below_threshold(monkeypatch):
    parent_id = create_parent()
    photo = Path("test_uploads/manual-archive.jpg")
    photo.write_bytes(b"manual-photo" * 100)
    with SessionLocal() as db:
        db.add(Submission(parent_id=parent_id, photo_path=str(photo), status="sent"))
        db.commit()
        configure_test_archive(monkeypatch)
        monkeypatch.setattr(storage_r2_archive, "THRESHOLD_BYTES", 350_000_000)
        monkeypatch.setattr(storage_r2_archive, "upload_verified", lambda *_args: None)
        assert storage_r2_archive.archive_if_needed(db) is None
        result = storage_r2_archive.archive_if_needed(db, force=True)
        assert result["photos_archived"] == 1
        assert result["sent_photos_removed"] == 1
        assert not photo.exists()


def test_archive_success_notice_contains_backup_keys(monkeypatch):
    sent = []

    class Response:
        text = "ok"

        def raise_for_status(self):
            pass

    monkeypatch.setenv("SLACK_R2_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setattr(storage_slack_alert.requests, "post",
                        lambda url, json, timeout: sent.append(json["text"]) or Response())
    assert storage_slack_alert.notify_archive_success({
        "photos_key": "backups/photos.zip", "database_key": "backups/database.sqlite3",
        "photos_archived": 2, "sent_photos_removed": 1, "r2_used_bytes_after": 123_000_000,
    })
    assert "backups/photos.zip" in sent[0]
    assert "0.12GB" in sent[0]


def test_auto_archive_upload_failure_keeps_photos(monkeypatch):
    parent_id = create_parent()
    sent_path = Path("test_uploads/auto-failure.jpg")
    sent_path.write_bytes(b"must-remain" * 100)
    db = SessionLocal()
    db.add(Submission(parent_id=parent_id, photo_path=str(sent_path), status="sent"))
    db.commit()
    monkeypatch.setenv("AUTO_ARCHIVE_ENABLED", "true")
    configure_test_archive(monkeypatch)

    def failed_upload(*_args):
        raise RuntimeError("R2 unavailable")

    monkeypatch.setattr(storage_r2_archive, "upload_verified", failed_upload)
    try:
        storage_r2_archive.archive_if_needed(db)
        assert False, "Expected upload failure"
    except RuntimeError as exc:
        assert "R2 unavailable" in str(exc)
    assert sent_path.exists()
    assert db.query(Submission).filter(Submission.status == "sent").one().photo_path
    db.close()


def test_auto_archive_preserves_photo_changed_after_upload(monkeypatch):
    parent_id = create_parent()
    sent_path = Path("test_uploads/auto-changed.jpg")
    sent_path.write_bytes(b"original-photo" * 100)
    db = SessionLocal()
    db.add(Submission(parent_id=parent_id, photo_path=str(sent_path), status="sent"))
    db.commit()
    monkeypatch.setenv("AUTO_ARCHIVE_ENABLED", "true")
    configure_test_archive(monkeypatch)

    def changed_during_upload(_client, _path, key):
        if key.endswith(".zip"):
            sent_path.write_bytes(b"new-photo" * 100)

    monkeypatch.setattr(storage_r2_archive, "upload_verified", changed_during_upload)
    result = storage_r2_archive.archive_if_needed(db)
    assert result["sent_photos_removed"] == 0
    assert sent_path.read_bytes() == b"new-photo" * 100
    assert db.query(Submission).filter(Submission.status == "sent").one().photo_path
    db.close()


def configure_test_archive(monkeypatch):
    monkeypatch.setenv("AUTO_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("R2_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("R2_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(storage_r2_archive, "THRESHOLD_BYTES", 1)
    monkeypatch.setattr(storage_r2_archive, "_r2_client", lambda: object())
    monkeypatch.setattr(storage_r2_archive, "r2_used_bytes", lambda _client: 0)


def test_r2_upload_requires_matching_download(monkeypatch, tmp_path):
    monkeypatch.setenv("R2_BUCKET", "test-bucket")
    sample = tmp_path / "sample.zip"
    sample.write_bytes(b"verified-backup")

    class RemoteBody:
        def iter_chunks(self, chunk_size):
            yield b"corrupt-backup!"

        def close(self):
            pass

    class Remote:
        metadata = None

        def upload_file(self, _path, _bucket, _key, ExtraArgs):
            self.metadata = ExtraArgs["Metadata"]

        def head_object(self, **_kwargs):
            return {"ContentLength": sample.stat().st_size, "Metadata": self.metadata}

        def get_object(self, **_kwargs):
            return {"Body": RemoteBody()}

    try:
        storage_r2_archive.upload_verified(Remote(), sample, "sample.zip")
        assert False, "Expected remote checksum mismatch"
    except RuntimeError as exc:
        assert "원본과 일치하지 않습니다" in str(exc)


def test_auto_archive_capacity_limit_keeps_photos(monkeypatch):
    parent_id = create_parent()
    sent_path = Path("test_uploads/auto-capacity.jpg")
    sent_path.write_bytes(b"photo" * 100)
    db = SessionLocal()
    db.add(Submission(parent_id=parent_id, photo_path=str(sent_path), status="sent"))
    db.commit()
    configure_test_archive(monkeypatch)
    monkeypatch.setattr(storage_r2_archive, "r2_used_bytes", lambda _client: 9_000_000_000)
    try:
        storage_r2_archive.archive_if_needed(db)
        assert False, "Expected R2 capacity stop"
    except RuntimeError as exc:
        assert "9GB" in str(exc)
    assert sent_path.exists()
    db.close()


def test_get_submission_includes_last_selected_mission():
    parent_id = create_parent()
    db = SessionLocal()
    past = Submission(
        parent_id=parent_id,
        status="generated",
        level="표현력",
        stage=3,
        feedback_draft="지난 피드백",
    )
    current = Submission(parent_id=parent_id, status="pending")
    db.add_all([past, current])
    db.commit()
    db.refresh(current)
    submission_id = current.id
    db.close()

    res = client.get(f"/admin/submissions/{submission_id}")
    assert res.status_code == 200
    mission = res.json()["last_selected_mission"]
    assert mission["level"] == "표현력"
    assert mission["stage"] == 3
    assert mission["stage_title"] == "소재를 구체적으로 고르기"


def test_generate_does_not_inject_previous_mission_into_extra_instruction(monkeypatch):
    parent_id = create_parent()
    image_path = "test_uploads/current.png"
    Path(image_path).write_bytes(b"image-bytes")

    db = SessionLocal()
    past = Submission(
        parent_id=parent_id,
        status="sent",
        level="표현력",
        stage=3,
        feedback_draft="지난 피드백",
    )
    current = Submission(
        parent_id=parent_id,
        photo_path=image_path,
        status="pending",
    )
    db.add_all([past, current])
    db.commit()
    db.refresh(current)
    submission_id = current.id
    db.close()

    captured = {}

    def fake_generate_feedback(**kwargs):
        captured.update(kwargs)
        return "새 피드백"

    monkeypatch.setattr(admin_router, "generate_feedback", fake_generate_feedback)
    res = client.post(
        f"/admin/submissions/{submission_id}/generate",
        json={"level": "표현력", "stage": 4, "extra_instruction": ""},
    )
    assert res.status_code == 200
    assert captured["extra_instruction"] == ""
    assert "[지난 미션" not in captured["extra_instruction"]
    assert len(captured["previous_feedbacks"]) == 1


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


def test_workbook_import_links_existing_parent_without_changing_weekly_level():
    parent_id = create_parent()
    bought = seoul_date() - timedelta(days=2)
    expires = bought + timedelta(days=180)
    row = "\t".join([
        "구매자", "010-1234-5678", "알차게", "카톡", "8회권",
        bought.isoformat(), "TRUE", "TRUE", "8", "2", "6",
        expires.isoformat(), "FALSE", "FALSE", "",
    ])
    result = client.post("/admin/workbook-purchases/import", json={"text": row})
    assert result.status_code == 200
    assert result.json()["created"] == 1
    repeated = client.post("/admin/workbook-purchases/import", json={"text": row})
    assert repeated.json()["skipped"] == 1
    parent = client.get(f"/admin/parents/{parent_id}").json()
    assert parent["level"] == "표현력"
    assert parent["child_name"] == "민준"
    assert parent["workbook_purchases"][0]["remaining_uses"] == 6


def test_workbook_upload_prompt_and_manual_send_deduct_once(monkeypatch):
    parent_id = create_parent()
    db = SessionLocal()
    db.add(WorkbookPurchase(
        parent_id=parent_id, buyer_name="구매자", workbook_level="가볍게",
        channel="카톡", pass_type="교재만", purchase_date=seoul_date(),
        expires_on=seoul_date() + timedelta(days=60), total_uses=1, opening_used=0,
    ))
    db.add(Submission(parent_id=parent_id, product_type="weekly_words",
                      feedback_draft="매주 3단어의 이전 피드백", status="sent"))
    db.commit()
    db.close()

    upload = client.post(
        f"/admin/submissions/upload?parent_id={parent_id}&product_type=eight_week_workbook&workbook_level=가볍게",
        files={"photo": ("worksheet.png", b"image-bytes", "image/png")},
    )
    assert upload.status_code == 201
    submission_id = upload.json()["id"]
    assert client.get(f"/admin/submissions/{submission_id}").json()["workbook_level"] == "가볍게"

    captured = {}
    monkeypatch.setattr(admin_router, "generate_feedback",
                        lambda **kwargs: captured.update(kwargs) or "8주 완성 피드백")
    generated = client.post(f"/admin/submissions/{submission_id}/generate", json={})
    assert generated.status_code == 200
    assert captured["workbook_level"] == "가볍게"
    assert captured["previous_feedbacks"] == []

    sent = client.post(f"/admin/submissions/{submission_id}/mark-sent", json={})
    assert sent.status_code == 200
    assert client.post(f"/admin/submissions/{submission_id}/mark-sent", json={}).status_code == 400
    db = SessionLocal()
    assert db.query(WorkbookUse).count() == 1
    assert db.query(WorkbookPurchase).one().opening_used == 0
    db.close()
    parent = client.get(f"/admin/parents/{parent_id}").json()
    assert parent["workbook_purchases"][0]["remaining_uses"] == 0


def test_workbook_import_rejects_inconsistent_balance():
    row = "\t".join([
        "구매자", "010-2222-3333", "완벽하게", "문자", "8회권",
        "2026. 9. 22", "FALSE", "FALSE", "8", "2", "8",
        "2027. 3. 20", "FALSE", "FALSE", "",
    ])
    result = client.post("/admin/workbook-purchases/import", json={"text": row})
    assert result.status_code == 400
    db = SessionLocal()
    assert db.query(WorkbookPurchase).count() == 0
    db.close()


def test_workbook_revision_uses_original_pass_without_second_deduction():
    parent_id = create_parent()
    db = SessionLocal()
    purchase = WorkbookPurchase(
        parent_id=parent_id, buyer_name="구매자", workbook_level="가볍게",
        channel="카톡", pass_type="교재만", purchase_date=seoul_date(),
        expires_on=seoul_date() + timedelta(days=60), total_uses=1, opening_used=0,
    )
    db.add(purchase)
    db.flush()
    origin = Submission(parent_id=parent_id, product_type="eight_week_workbook",
                        workbook_level="가볍게", status="sent", feedback_draft="첫 첨삭")
    db.add(origin)
    db.flush()
    db.add(WorkbookUse(purchase_id=purchase.id, submission_id=origin.id))
    db.commit()
    origin_id = origin.id
    db.close()

    revision = client.post(
        f"/admin/submissions/upload?parent_id={parent_id}&product_type=eight_week_workbook"
        f"&workbook_level=가볍게&rework_of_submission_id={origin_id}",
        files={"photo": ("revision.png", b"image-bytes", "image/png")},
    )
    assert revision.status_code == 201
    revision_id = revision.json()["id"]
    sent = client.post(f"/admin/submissions/{revision_id}/mark-sent",
                       json={"feedback_text": "수정본 피드백"})
    assert sent.status_code == 200
    db = SessionLocal()
    assert db.query(WorkbookUse).count() == 1
    db.close()

"""Protect the unread-chat ledger and conservative automatic intake rules."""

import test_workflow as workflow

from database import Parent, SessionLocal, Submission


setup_function = workflow.setup_function


def _discover(key="room-1", room="안혜미"):
    response = workflow.client.post('/admin/channel-inbox/discover', json=[{
        'source_key': key,
        'chat_url': 'https://business.kakao.com/space/998603/channel/_Dqixdn/chats/123',
        'room_name': room,
    }])
    assert response.status_code == 200
    return response.json()[0]


def test_discovery_is_idempotent_and_no_photo_remains_open():
    first = _discover()
    assert _discover()['id'] == first['id']
    result = workflow.client.post(f"/admin/channel-inbox/{first['id']}/process", data={'message_text': '배송 문의드려요'})
    assert result.status_code == 200
    assert result.json()['category'] == 'cs'
    assert result.json()['submission_id'] is None
    assert workflow.client.get('/admin/channel-inbox').json()[0]['status'] == 'open'


def test_clear_worksheet_creates_one_pending_submission():
    db = SessionLocal()
    db.add(Parent(kakao_user_id='k-1', child_name='안혜미(다온)', level='표현력', weekly_words_enabled=True))
    db.commit()
    db.close()
    item = _discover()
    result = workflow.client.post(
        f"/admin/channel-inbox/{item['id']}/process",
        data={'message_text': '이번 주 단어 보내드립니다'},
        files=[('photos', ('one.jpg', b'image', 'image/jpeg'))],
    )
    assert result.status_code == 200
    assert result.json()['category'] == 'transferred'
    assert workflow.client.post(f"/admin/channel-inbox/{item['id']}/process", data={'message_text': '이번 주 단어 보내드립니다'}).json()['submission_id'] == result.json()['submission_id']
    db = SessionLocal()
    assert db.query(Submission).count() == 1
    db.close()


def test_photo_only_submission_uses_unique_buyer_name():
    db = SessionLocal()
    db.add(Parent(kakao_user_id='k-photo', child_name='안혜미(다온)', level='표현력', weekly_words_enabled=True))
    db.commit()
    db.close()
    item = _discover('photo-only')
    result = workflow.client.post(
        f"/admin/channel-inbox/{item['id']}/process",
        data={'message_text': ''},
        files=[('photos', ('one.jpg', b'image', 'image/jpeg'))],
    )
    assert result.status_code == 200
    assert result.json()['category'] == 'transferred'
    assert result.json()['submission_id'] is not None


def test_siblings_with_same_buyer_need_manual_review():
    db = SessionLocal()
    db.add_all([
        Parent(kakao_user_id='k-1', child_name='안혜미(다온)', level='표현력', weekly_words_enabled=True),
        Parent(kakao_user_id='k-2', child_name='안혜미(하린)', level='표현력', weekly_words_enabled=True),
    ])
    db.commit()
    db.close()
    item = _discover()
    result = workflow.client.post(
        f"/admin/channel-inbox/{item['id']}/process",
        data={'message_text': '이번 주 단어 보내드립니다'},
        files=[('photos', ('one.jpg', b'image', 'image/jpeg'))],
    )
    assert result.status_code == 200
    assert result.json()['category'] == 'match_failed'
    assert workflow.submission_count() == 0


def test_explicit_child_name_selects_one_sibling():
    db = SessionLocal()
    db.add_all([
        Parent(kakao_user_id='k-1', child_name='안혜미(다온)', level='표현력', weekly_words_enabled=True),
        Parent(kakao_user_id='k-2', child_name='안혜미(하린)', level='표현력', weekly_words_enabled=True),
    ])
    db.commit()
    expected = db.query(Parent).filter_by(kakao_user_id='k-2').one().id
    db.close()
    item = _discover()
    result = workflow.client.post(
        f"/admin/channel-inbox/{item['id']}/process",
        data={'message_text': '하린이 이번 주 단어 보내드립니다'},
        files=[('photos', ('one.jpg', b'image', 'image/jpeg'))],
    )
    assert result.status_code == 200
    assert result.json()['parent_id'] == expected

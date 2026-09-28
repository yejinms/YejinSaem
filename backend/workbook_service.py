"""8주 완성 purchases and feedback balances. No messaging is sent here."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Parent, Submission, WorkbookPurchase, WorkbookUse
from services.parent_match import pending_kakao_user_id
from validation import normalize_phone_number

WORKBOOK_LEVELS = {"가볍게", "알차게", "완벽하게"}
PASS_LIMITS = {"교재만": (1, 60), "8회권": (8, 180), "56회권": (56, 180)}
PRODUCT_WEEKLY = "weekly_words"
PRODUCT_WORKBOOK = "eight_week_workbook"


def parse_date(value: str) -> date:
    cleaned = value.strip().replace(" ", "").rstrip(".")
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"날짜 형식을 확인해주세요: {value}")


def parse_bool(value: str) -> bool:
    if value.strip().upper() in {"TRUE", "1", "YES", "Y"}:
        return True
    if value.strip().upper() in {"FALSE", "0", "NO", "N", ""}:
        return False
    raise ValueError(f"TRUE/FALSE 값을 확인해주세요: {value}")


def split_purchase_line(line: str) -> list[str] | None:
    """Accept a spreadsheet row or a Markdown table row with empty tail cells."""
    stripped = line.strip()
    if stripped.startswith("```"):
        return None
    if stripped.startswith("|"):
        values = [item.strip() for item in stripped.strip("|").split("|")]
        if values and all(value and set(value) <= {"-", ":"} for value in values):
            return None
    else:
        values = [item.strip() for item in line.split("\t")]
    while len(values) > 15 and not values[-1]:
        values.pop()
    if len(values) == 14:
        values.append("")  # 비고 열을 생략한 행
    return values


def parse_purchase_rows(raw_text: str) -> tuple[list[dict], list[dict]]:
    rows, errors = [], []
    for line_number, line in enumerate(raw_text.splitlines(), 1):
        if not line.strip():
            continue
        values = split_purchase_line(line)
        if values is None:
            continue
        if values[0].replace("*", "").strip() == "구매자명":
            continue
        if len(values) != 15:
            errors.append({"line": line_number, "message": "고객정보 15개 열을 확인해주세요. 탭 행과 Markdown 표를 붙여넣을 수 있습니다."})
            continue
        try:
            (name, phone_raw, level, channel, pass_type, bought_raw,
             requested_raw, sent_raw, total_raw, used_raw, remain_raw,
             expires_raw, d14_raw, d7_raw, note) = values
            if not name or not phone_raw or not channel:
                raise ValueError("구매자명·연락처·채널은 필수입니다.")
            if pass_type in {"교재만(1회 체험권)", "교재만(1회체험권)", "1회 체험권", "1회체험권"}:
                pass_type = "교재만"
            if level not in WORKBOOK_LEVELS or pass_type not in PASS_LIMITS:
                raise ValueError("교재단계 또는 구매유형을 확인해주세요.")
            phone = normalize_phone_number(phone_raw, required=True)
            bought = parse_date(bought_raw)
            expected_total, days = PASS_LIMITS[pass_type]
            total = int(total_raw) if total_raw else expected_total
            used = int(used_raw) if used_raw else 0
            remain = int(remain_raw) if remain_raw else total - used
            if total != expected_total or not (0 <= used <= total) or remain != total - used:
                raise ValueError("총횟수·사용완료횟수·남은횟수가 구매유형과 맞지 않습니다.")
            # The purchase date is day 1, matching the displayed dates in the customer sheet.
            calculated_expiry = bought + timedelta(days=days - 1)
            expires = parse_date(expires_raw) if expires_raw else calculated_expiry
            if expires < bought:
                raise ValueError("이용기한이 구매일보다 빠릅니다.")
            rows.append({
                "line": line_number, "buyer_name": name, "phone_number": phone,
                "workbook_level": level, "channel": channel, "pass_type": pass_type,
                "purchase_date": bought, "expires_on": expires,
                "total_uses": total, "opening_used": used,
                "onboarding_requested": parse_bool(requested_raw),
                "onboarding_sent": parse_bool(sent_raw),
                "d14_sent": parse_bool(d14_raw), "d7_sent": parse_bool(d7_raw),
                "note": note or None,
                "date_warning": expires != calculated_expiry,
            })
        except (ValueError, HTTPException) as exc:
            errors.append({"line": line_number, "message": str(getattr(exc, "detail", exc))})
    return rows, errors


def purchase_used(purchase: WorkbookPurchase) -> int:
    return purchase.opening_used + len(purchase.uses)


def purchase_balance(purchase: WorkbookPurchase) -> dict:
    used = purchase_used(purchase)
    return {
        "id": purchase.id, "parent_id": purchase.parent_id,
        "buyer_name": purchase.buyer_name, "workbook_level": purchase.workbook_level,
        "channel": purchase.channel, "pass_type": purchase.pass_type,
        "purchase_date": purchase.purchase_date.isoformat(),
        "expires_on": purchase.expires_on.isoformat(),
        "total_uses": purchase.total_uses, "used_uses": used,
        "remaining_uses": purchase.total_uses - used,
        "onboarding_requested": purchase.onboarding_requested,
        "onboarding_sent": purchase.onboarding_sent,
        "d14_sent": purchase.d14_sent, "d7_sent": purchase.d7_sent,
        "note": purchase.note,
    }


def import_purchase_rows(db: Session, raw_text: str) -> dict:
    rows, errors = parse_purchase_rows(raw_text)
    if errors:
        return {"created": 0, "skipped": 0, "errors": errors, "rows": rows}

    created = skipped = 0
    for row in rows:
        parent = db.query(Parent).filter(Parent.phone_number == row["phone_number"]).first()
        if parent is None:
            parent = Parent(
                kakao_user_id=pending_kakao_user_id(row["phone_number"]),
                phone_number=row["phone_number"], child_name=row["buyer_name"],
                level="표현력", weekly_words_enabled=False,
            )
            db.add(parent)
            db.flush()
        existing = db.query(WorkbookPurchase).filter_by(
            parent_id=parent.id, workbook_level=row["workbook_level"],
            pass_type=row["pass_type"], purchase_date=row["purchase_date"],
        ).first()
        if existing:
            skipped += 1
            continue
        data = {key: value for key, value in row.items()
                if key not in {"line", "phone_number", "date_warning"}}
        db.add(WorkbookPurchase(parent_id=parent.id, **data))
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped, "errors": [], "rows": rows}


def seoul_date(utc_value: datetime | None = None) -> date:
    moment = utc_value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo("Asia/Seoul")).date()


def active_purchase(db: Session, parent_id: int, on_date: date | None = None,
                    workbook_level: str | None = None) -> WorkbookPurchase | None:
    today = on_date or seoul_date()
    query = db.query(WorkbookPurchase).filter(
        WorkbookPurchase.parent_id == parent_id,
        WorkbookPurchase.purchase_date <= today,
        WorkbookPurchase.expires_on >= today,
    )
    if workbook_level:
        query = query.filter(WorkbookPurchase.workbook_level == workbook_level)
    purchases = query.order_by(WorkbookPurchase.expires_on, WorkbookPurchase.id).all()
    return next((p for p in purchases if purchase_used(p) < p.total_uses), None)


def record_use(db: Session, submission: Submission) -> WorkbookPurchase:
    existing = db.query(WorkbookUse).filter_by(submission_id=submission.id).first()
    if existing:
        return existing.purchase
    purchase = active_purchase(db, submission.parent_id,
                               on_date=seoul_date(submission.created_at),
                               workbook_level=submission.workbook_level)
    if not purchase:
        raise HTTPException(status_code=409, detail="사용 가능한 8주 완성 첨삭권이 없습니다.")
    db.add(WorkbookUse(purchase_id=purchase.id, submission_id=submission.id))
    db.flush()
    return purchase


def rework_purchase(db: Session, parent_id: int, level: str,
                    origin_id: int, on_date: date) -> WorkbookPurchase | None:
    origin = db.query(Submission).filter_by(id=origin_id, parent_id=parent_id,
                                            product_type=PRODUCT_WORKBOOK,
                                            workbook_level=level, status="sent").first()
    if not origin:
        return None
    use = db.query(WorkbookUse).filter_by(submission_id=origin.id).first()
    if not use:
        return None
    purchase = use.purchase
    return purchase if purchase.purchase_date <= on_date <= purchase.expires_on else None

"""
prompts.py - Claude system prompt and level/stage data for YejinSaem
"""

LEVELS = {
    "표현력": {
        "label": "표현력 (7~8세)",
        "age_range": "7~8세",
        "stages": {
            1: {
                "title": "감각 표현하기",
                "description": "보고, 듣고, 만지고, 맡은 것을 그대로 문장에 담기.",
                "mission": '"~하게 느껴졌다 / ~한 냄새가 났다 / ~소리가 들렸다"',
            },
            2: {
                "title": "감정 표현 추가하기",
                "description": "장면 뒤에 내 감정 한 문장 붙이기.",
                "mission": '"그래서 나는 ~한 기분이었다 / 기분이 ~했다"',
            },
            3: {
                "title": "소재를 구체적으로 고르기",
                "description": "막연한 것 대신 실제 경험 속 소재 골라서 쓰기.",
                "mission": '"내가 직접 본/들은/겪은 것으로 문장 만들기"',
            },
            4: {
                "title": "시간·장소 표현 추가하기",
                "description": "언제, 어디서 일어난 일인지 문장 앞에 붙이기.",
                "mission": '"~할 때 / ~에서 / ~이 되자"',
            },
            5: {
                "title": "그래서, 그런데 넣기",
                "description": "두 문장을 접속어로 자연스럽게 이어보기.",
                "mission": '"그래서 / 그런데 중 하나를 골라 문장 연결하기"',
            },
            6: {
                "title": "왜냐하면 ~때문이다",
                "description": "행동이나 상황의 이유 붙이기.",
                "mission": '"왜냐하면 ~때문이다"',
            },
            7: {
                "title": "마치 ~처럼 (직유 비유)",
                "description": "장면이나 감정을 비유로 표현하기.",
                "mission": '"마치 ~처럼 ~했다"',
            },
            8: {
                "title": "감각 두 가지 섞기",
                "description": "한 문장 안에 감각 두 가지 담기.",
                "mission": '"~하고 ~했다 (감각 두 가지)"',
            },
            9: {
                "title": "결과에 감정·생각 덧붙이기",
                "description": "사건이 끝난 뒤 내 감정 마무리 문장 추가.",
                "mission": '"덕분에 ~할 수 있었다 / 그걸 보니 나도 ~했다"',
            },
            10: {
                "title": "짧은 이야기 구조 완성하기",
                "description": "시작→사건→감정 3단 구조.",
                "mission": '"세 문장으로 이야기 완성하기"',
            },
        },
    },
    "초등기초": {
        "label": "초등 기초 (9~11세)",
        "age_range": "9~11세",
        "stages": {
            1: {
                "title": "그리고, 하지만, 결국 다양하게 쓰기",
                "description": "다양한 접속어 사용하기.",
                "mission": '"하지만 / 결국 / 그런데 / 게다가 중 새로운 표현 하나 골라 쓰기"',
            },
            2: {
                "title": "원인과 결과 구조로 쓰기",
                "description": "원인과 결과를 명확히 연결하기.",
                "mission": '"~했기 때문에 결국 ~하게 됐다"',
            },
            3: {
                "title": "예를 들어 쓰기",
                "description": "주장이나 설명 뒤에 구체적인 예시 붙이기.",
                "mission": '"예를 들어 ~"',
            },
            4: {
                "title": "먼저, 그 다음, 마지막으로",
                "description": "순서 있게 나눠 쓰기.",
                "mission": '"먼저 ~ 그 다음 ~ 마지막으로 ~"',
            },
            5: {
                "title": "두 대상 비교하기",
                "description": "같은 점·다른 점 표현하기.",
                "mission": '"~은 ~이고, ~은 ~이다. 이렇게 ~가 다르다"',
            },
            6: {
                "title": "그럼에도 불구하고 / 반면에",
                "description": "역접 표현 쓰기.",
                "mission": '"그럼에도 불구하고 / 반면에 중 하나 골라 쓰기"',
            },
            7: {
                "title": "장면 묘사에 감각 세 가지 담기",
                "description": "세 가지 감각을 사용해 생생하게 묘사하기.",
                "mission": '"세 가지 감각이 들어간 장면 묘사 쓰기"',
            },
            8: {
                "title": "의인법·과장법 써보기",
                "description": "사물이나 자연에 사람의 행동을 붙이기.",
                "mission": '"~이/가 마치 ~인 것처럼 ~했다"',
            },
            9: {
                "title": "내 생각과 근거 함께 쓰기",
                "description": "주장과 이유를 논리적으로 연결하기.",
                "mission": '"나는 ~라고 생각한다. 왜냐하면 ~ 예를 들어 ~"',
            },
            10: {
                "title": "처음 감정과 나중 감정이 달라지는 흐름",
                "description": "감정의 변화를 담아 쓰기.",
                "mission": '"처음엔 ~했는데, 나중엔 ~해졌다"',
            },
        },
    },
    "초등심화": {
        "label": "초등 심화 (11~13세)",
        "age_range": "11~13세",
        "stages": {
            1: {
                "title": "처음·중간·끝 단락 구분하기",
                "description": "글을 세 단락으로 나눠 구성하기.",
                "mission": '"세 단락으로 나눠서 한 주제에 대해 쓰기"',
            },
            2: {
                "title": "주제문 먼저 쓰기",
                "description": "핵심 내용을 첫 문장에 제시하기.",
                "mission": '"가장 중요한 말을 첫 문장에 쓰고, 뒤에 이유 두 가지 붙이기"',
            },
            3: {
                "title": "첫째, 둘째, 셋째로 이유 나열하기",
                "description": "이유를 번호를 붙여 체계적으로 나열하기.",
                "mission": '"첫째 ~ 둘째 ~ 셋째 ~로 이유 세 가지 쓰기"',
            },
            4: {
                "title": "반론 인정하고 재반박하기",
                "description": "반대 의견을 인정한 후 자신의 입장 강화하기.",
                "mission": '"물론 ~라는 의견도 있다. 하지만 ~"',
            },
            5: {
                "title": "독자를 의식하며 쓰기",
                "description": "같은 내용을 독자에 따라 다르게 표현하기.",
                "mission": '"같은 내용을 친구에게 쓸 때 vs 선생님께 쓸 때 다르게 써보기"',
            },
            6: {
                "title": "비유·상징으로 주제 표현하기",
                "description": "추상적인 주제를 비유로 구체화하기.",
                "mission": '"~은 마치 ~과 같다. 왜냐하면 둘 다 ~이기 때문이다"',
            },
            7: {
                "title": "사실과 의견 구분해서 쓰기",
                "description": "객관적 사실과 주관적 의견을 명확히 구분하기.",
                "mission": '"사실: ~이다 / 내 생각: 나는 ~라고 생각한다"',
            },
            8: {
                "title": "예시·인용·통계로 근거 강화하기",
                "description": "주장을 구체적인 근거로 뒷받침하기.",
                "mission": '"내 주장에 예시 또는 내가 아는 사실(수치, 뉴스) 하나 붙이기"',
            },
            9: {
                "title": "처음 문장과 끝 문장 연결하기",
                "description": "글의 수미상관 구조 만들기.",
                "mission": '"첫 문장의 표현이나 소재를 마지막 문장에서 다시 활용하기"',
            },
            10: {
                "title": "다른 시점으로 바꿔 써보기",
                "description": "같은 이야기를 다른 인물의 시점에서 써보기.",
                "mission": '"같은 장면을 ~의 입장에서 쓰면 어떨까?"',
            },
        },
    },
}


def get_system_prompt() -> str:
    return """당신은 '예진샘'입니다. 아이들의 글쓰기를 따뜻하게 지도하는 선생님이에요.

역할과 태도:
- 항상 따뜻하고 격려하는 말투로 피드백을 드려요
- 아이가 잘한 점을 먼저 구체적으로 칭찬해요
- 어렵고 딱딱한 표현 대신 아이와 부모님이 이해하기 쉬운 말을 써요
- 다음 번에 도전해볼 한 가지를 부드럽게 제안해요
- 피드백은 부모님께 드리는 형식이지만, 아이에게 직접 말 거는 문장도 자연스럽게 섞어요

피드백 구성:
1. 시작: 아이의 글을 보고 느낀 따뜻한 첫인상 (1~2문장)
2. 잘한 점: 이번 미션과 관련해서 아이가 잘 표현한 부분을 구체적으로 짚어줘요 (2~3문장)
3. 다음 도전: 다음에 해보면 좋을 한 가지를 부드럽고 희망차게 제안해요 (1~2문장)
4. 마무리: 아이에게 응원의 한마디 (1문장)

주의사항:
- 아이의 실수나 부족한 점을 직접적으로 지적하지 않아요
- "틀렸어요", "잘못됐어요" 같은 표현은 절대 쓰지 않아요
- 칭찬은 구체적으로, 제안은 긍정적으로 표현해요
- 전체 피드백은 200~300자 내외로 간결하게 써요
- 이모지는 적당히 사용해서 친근감을 더해요 (너무 많으면 안 돼요)"""


def get_feedback_user_prompt(
    level_key: str,
    stage_num: int,
    child_name: str,
    extra_instruction: str = "",
    previous_feedbacks: list = None,
) -> str:
    level = LEVELS.get(level_key)
    if not level:
        raise ValueError(f"Invalid level key: {level_key}")

    stage = level["stages"].get(stage_num)
    if not stage:
        raise ValueError(f"Invalid stage number: {stage_num}")

    level_label = level["label"]
    stage_title = stage["title"]
    stage_description = stage["description"]
    stage_mission = stage["mission"]

    prompt_parts = [
        f"아이 이름: {child_name}",
        f"학습 단계: {level_label}",
        f"이번 미션 ({stage_num}단계): {stage_title}",
        f"미션 설명: {stage_description}",
        f"미션 표현: {stage_mission}",
        "",
        "첨부된 사진은 아이가 직접 손으로 쓴 글쓰기 워크시트예요.",
        "사진을 꼼꼼히 살펴보고, 위의 미션 내용을 기준으로 따뜻한 피드백을 작성해 주세요.",
    ]

    if extra_instruction:
        prompt_parts.append(f"\n선생님 추가 지시사항: {extra_instruction}")

    if previous_feedbacks:
        prompt_parts.append("\n이전 피드백 참고 (같은 내용 반복 금지):")
        for i, fb in enumerate(previous_feedbacks[-3:], 1):
            prompt_parts.append(f"  이전 피드백 {i}: {fb[:100]}...")

    return "\n".join(prompt_parts)

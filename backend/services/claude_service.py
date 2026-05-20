"""
claude_service.py - Claude AI integration for generating writing feedback
"""

import base64
import os
from pathlib import Path

import anthropic

from prompts import get_feedback_user_prompt, get_system_prompt


def generate_feedback(
    image_path: str,
    level_key: str,
    stage_num: int,
    child_name: str,
    extra_instruction: str = "",
    previous_feedbacks: list = None,
) -> str:
    """
    Generate writing feedback using Claude vision.

    Args:
        image_path: Path to the uploaded worksheet image
        level_key: One of '표현력', '초등기초', '초등심화'
        stage_num: Stage number 1-10
        child_name: Child's name for personalized feedback
        extra_instruction: Optional additional instructions from teacher
        previous_feedbacks: List of previous feedback texts to avoid repetition

    Returns:
        Generated feedback text as a string
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)

    # Read and encode the image
    image_path_obj = Path(image_path)
    if not image_path_obj.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    with open(image_path_obj, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine media type based on file extension
    ext = image_path_obj.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(ext, "image/jpeg")

    # Build the user prompt
    user_prompt = get_feedback_user_prompt(
        level_key=level_key,
        stage_num=stage_num,
        child_name=child_name,
        extra_instruction=extra_instruction,
        previous_feedbacks=previous_feedbacks or [],
    )

    # Call Claude with vision
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=get_system_prompt(),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            }
        ],
    )

    return response.content[0].text

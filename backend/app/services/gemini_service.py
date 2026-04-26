import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

# Supported visual styles for avatar prompt generation.
# The values are explicit English style hints to keep image output consistent.
CHARACTER_STYLES: Dict[str, str] = {
    "cartoon_furry": "cartoon furry style, playful proportions, expressive eyes",
    "anime": "anime style, clean cel shading, dynamic character design",
    "realistic": "realistic style, natural lighting, detailed skin and fabric textures",
    "pixel": "pixel-art style, retro 16-bit aesthetics, crisp pixel edges",
}


def _get_api_key() -> str:
    """
    Read Gemini API key from environment and fail fast if it is missing.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment variables.")
    return api_key


def generate_avatar_prompt(short_description: str, style: str = "cartoon_furry") -> str:
    """
    Build a detailed English prompt from a short character description.

    The function intentionally appends fixed style keywords required
    for the target avatar format.
    """
    cleaned_description = short_description.strip()
    if not cleaned_description:
        raise ValueError("short_description must not be empty.")

    style_key = (style or "").strip().lower() or "cartoon_furry"
    style_hint = CHARACTER_STYLES.get(style_key, CHARACTER_STYLES["cartoon_furry"])

    # Keep prompt explicit and image-model friendly:
    # subject + composition + quality + expression.
    prompt = (
        f"Create a detailed character portrait based on this concept: {cleaned_description}. "
        f"Style direction: {style_hint}. "
        "single main character, vertical 9:16 aspect ratio. "
        "high quality digital art, vibrant colors, clean lines. "
        "confident pose, expressive face. "
        "clean background suitable for animated talking avatar videos."
    )
    return prompt


def generate_image(prompt: str, output_path: Optional[str] = None) -> str:
    """
    Generate one image with Gemini image model and save it to disk.

    Returns absolute path to the saved file.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be empty.")

    try:
        api_key = _get_api_key()
        genai.configure(api_key=api_key)
        model = genai.ImageGenerationModel("gemini-2.5-flash-image-preview")

        logger.info("Sending image generation request to Gemini.")
        response = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="9:16",
        )

        # Build output path if not provided.
        if output_path:
            output_file = Path(output_path)
        else:
            generated_dir = Path(__file__).resolve().parent.parent.parent / "generated_images"
            generated_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            output_file = generated_dir / f"gemini_{timestamp}.png"

        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Response format can vary between SDK versions.
        # We try several known extraction strategies.
        generated_images = getattr(response, "generated_images", None)
        if not generated_images:
            raise RuntimeError("Gemini did not return generated images.")

        image_obj = getattr(generated_images[0], "image", None)
        if image_obj is None:
            raise RuntimeError("Gemini response image object is missing.")

        # Most versions expose PIL-style save().
        if hasattr(image_obj, "save"):
            image_obj.save(str(output_file))
        # Fallback for byte payload formats.
        elif hasattr(image_obj, "image_bytes"):
            output_file.write_bytes(image_obj.image_bytes)
        elif hasattr(image_obj, "data"):
            output_file.write_bytes(image_obj.data)
        else:
            raise RuntimeError("Unsupported Gemini image response format.")

        absolute_path = str(output_file.resolve())
        logger.info("Gemini image saved to %s", absolute_path)
        return absolute_path

    except ValueError:
        logger.exception("Gemini configuration error.")
        raise
    except Exception as exc:
        # Keep one broad handler to include network issues, quota limits,
        # authentication errors, and SDK-level exceptions.
        logger.exception("Gemini image generation failed.")
        raise RuntimeError(
            "Failed to generate image via Gemini API. Check network, API key, and quota."
        ) from exc


def check_gemini_health() -> bool:
    """
    Verify Gemini API availability with a minimal test request.
    """
    try:
        api_key = _get_api_key()
        genai.configure(api_key=api_key)

        # Lightweight text request is enough to verify credentials + connectivity.
        model = genai.GenerativeModel("gemini-1.5-flash")
        result = model.generate_content("Reply with: OK")
        response_text = (getattr(result, "text", "") or "").strip().lower()

        is_healthy = bool(response_text)
        if is_healthy:
            logger.info("Gemini health check passed.")
        else:
            logger.warning("Gemini health check returned empty response.")
        return is_healthy
    except Exception:
        logger.exception("Gemini health check failed.")
        return False


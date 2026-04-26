import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from gtts import gTTS

logger = logging.getLogger(__name__)


def generate_audio(
    text: str,
    output_path: Optional[str] = None,
    language: str = "ru",
    slow: bool = False,
) -> str:
    """
    Generate MP3 audio from input text using gTTS.

    Returns absolute path to the saved audio file.
    """
    cleaned_text = text.strip() if text else ""
    if not cleaned_text:
        raise ValueError("Text for TTS must not be empty.")

    try:
        # Create gTTS synthesis object.
        tts = gTTS(text=cleaned_text, lang=language, slow=slow)

        # If user did not pass output path, build timestamp-based path.
        if output_path:
            target_file = Path(output_path)
        else:
            output_dir = Path(__file__).resolve().parent.parent.parent / "generated_audio"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_file = output_dir / f"audio_{timestamp}.mp3"

        target_file.parent.mkdir(parents=True, exist_ok=True)

        # Save resulting MP3 file.
        tts.save(str(target_file))
        absolute_path = str(target_file.resolve())
        logger.info("TTS audio generated at %s", absolute_path)
        return absolute_path

    except ValueError:
        logger.exception("Validation error while generating TTS audio.")
        raise
    except OSError as exc:
        logger.exception("File system error while saving TTS audio.")
        raise RuntimeError(f"Failed to save audio file: {exc}") from exc
    except Exception as exc:
        # Covers network issues (Google TTS endpoint), language issues,
        # and other runtime errors from gTTS.
        logger.exception("TTS generation failed.")
        raise RuntimeError("Failed to generate audio. Check network and input parameters.") from exc


def get_audio_duration(audio_path: str) -> float:
    """
    Return MP3 duration in seconds.

    Preferred method: mutagen.mp3.MP3 metadata.
    Fallback: rough estimate by file size when mutagen is unavailable.
    """
    try:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        try:
            from mutagen.mp3 import MP3

            audio_info = MP3(str(path))
            duration = float(audio_info.info.length)
            logger.info("Audio duration from mutagen: %.2f sec", duration)
            return duration
        except ImportError:
            # Approximation fallback:
            # at ~128 kbps, bytes/sec ~= 16000.
            size_bytes = path.stat().st_size
            approx_seconds = float(size_bytes / 16000.0)
            logger.warning(
                "mutagen is not installed; using approximate duration %.2f sec for %s",
                approx_seconds,
                audio_path,
            )
            return approx_seconds
    except Exception as exc:
        logger.exception("Failed to get audio duration for %s", audio_path)
        raise RuntimeError(f"Unable to determine audio duration: {exc}") from exc


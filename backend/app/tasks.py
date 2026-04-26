import json
import logging
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from .celery_app import celery_app
from .services import tts_service
from .services.capcut_service import CapCutMateClient

logger = logging.getLogger(__name__)

# ... (все вспомогательные функции _parse_scenes, _transcribe_with_timestamps и т.д. остаются без изменений) ...
def _parse_scenes(scenes_json: Optional[Union[str, List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    if not scenes_json: return []
    logger.info(f"DEBUG: Raw scenes_json type: {type(scenes_json)}")
    logger.info(f"DEBUG: Raw scenes_json content: {repr(scenes_json)}")
    if isinstance(scenes_json, list): raw_items = scenes_json
    elif isinstance(scenes_json, str):
        cleaned_json = scenes_json.strip()
        if len(cleaned_json) > 1 and cleaned_json.startswith('"') and cleaned_json.endswith('"'):
            if cleaned_json[1] in ('[', '{'):
                logger.warning("Detected double-quoted JSON string. Stripping outer quotes and un-escaping.")
                cleaned_json = cleaned_json[1:-1].replace('\\"', '"')
        try: raw_items = json.loads(cleaned_json)
        except json.JSONDecodeError as exc:
            logger.error(f"CRITICAL: JSON parse failed at line {exc.lineno}, column {exc.colno}")
            logger.error(f"CRITICAL: Problematic string after cleaning: {repr(cleaned_json)}")
            raise ValueError(f"Unable to parse scenes_json. Error: {exc.msg}") from exc
    else: raise ValueError(f"scenes_json must be string or list, got {type(scenes_json)}")
    if not isinstance(raw_items, list): raise ValueError("Parsed scenes_json is not a list.")
    parsed: List[Dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict): continue
        start_raw = str(item.get("start_time", 0.0) or 0.0).replace(",", ".")
        start_seconds = max(0.0, float(start_raw))
        parsed.append({"start_time": start_seconds, "text": str(item.get("text", "")).strip(), "scene_description": str(item.get("scene_description", "") or "").strip(), "image_path": str(item.get("image_path", "") or "").strip(), "background": str(item.get("background", "") or "").strip()})
    return sorted(parsed, key=lambda x: x["start_time"])
def _transcribe_with_timestamps(audio_path: str) -> List[Dict[str, Any]]:
    try: from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper is not installed; subtitles transcription skipped.")
        return []
    model_size = os.getenv("WHISPER_MODEL_SIZE", "small")
    model = WhisperModel(model_size, compute_type="int8")
    segments, _ = model.transcribe(audio_path, word_timestamps=True)
    subtitles: List[Dict[str, Any]] = []
    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        if not text: continue
        subtitles.append({"start": float(getattr(seg, "start", 0.0)), "end": float(getattr(seg, "end", 0.0)), "text": text})
    return subtitles
def _resolve_voice_settings(voice: str) -> Dict[str, Any]:
    voice_key = (voice or "ru").strip().lower()
    if voice_key == "ru-male": return {"language": "ru", "slow": True}
    return {"language": "ru", "slow": False}
def _is_video_file(path: str) -> bool:
    return Path(path).suffix.lower() in {".mp4", ".mov", ".webm"}
def _prepare_scene_media_files(scene_media_files: Optional[List[str]], target_dir: Path) -> List[str]:
    if not scene_media_files: return []
    target_dir.mkdir(parents=True, exist_ok=True)
    prepared_paths: List[str] = []
    for idx, media_path in enumerate(scene_media_files):
        source = Path(media_path)
        if not source.exists():
            logger.warning("Scene media file does not exist: %s", media_path)
            continue
        unique_name = f"scene_{idx}_{uuid4().hex}{source.suffix or '.bin'}"
        target = target_dir / unique_name
        shutil.copy2(source, target)
        prepared_paths.append(str(target.resolve()))
    return prepared_paths
def _animate_image_with_avatar_pipeline(image_path: str, audio_path: str) -> str:
    logger.info("SadTalker/Wav2Lip pipeline is not configured; using static image: %s", image_path)
    return image_path

@celery_app.task(bind=True, name="app.tasks.generate_video_task")
def generate_video_task(
    self,
    text: str,
    image_path: str,
    voice: str = "ru",
    style: str = "cartoon_furry",
    use_background_music: bool = False,
    music_volume: int = 30,
    music_track: str = "background", # <--- ИЗМЕНЕНИЕ ЗДЕСЬ
    add_subtitles: bool = False,
    subtitle_color: str = "#FFFFFF",
    subtitle_font_size: int = 42,
    scenes_json: Optional[str] = None,
    scene_media_files: Optional[List[str]] = None,
) -> dict:
    task_id = self.request.id
    logger.info("Started generate_video_task: task_id=%s", task_id)
    try:
        app_dir = Path(__file__).resolve().parent
        backend_dir = app_dir.parent
        videos_dir = backend_dir / "generated_videos"
        uploads_dir = backend_dir / "uploads"
        videos_dir.mkdir(parents=True, exist_ok=True)
        
        timed_scenes: List[Dict[str, Any]] = []
        scenes = _parse_scenes(scenes_json) if scenes_json else []

        resolved_image_path = image_path
        self.update_state(state="PROGRESS", meta={"progress": 40, "step": "Изображение-аватар получено"})
        logger.info("Task %s: main avatar image path is %s", task_id, resolved_image_path)

        prepared_scene_media = _prepare_scene_media_files(scene_media_files, uploads_dir / "scenes")
        for idx, media_path in enumerate(prepared_scene_media):
            if idx >= len(scenes): break
            if _is_video_file(media_path): scenes[idx]["video_path"] = media_path
            else: scenes[idx]["image_path"] = media_path

        self.update_state(state="PROGRESS", meta={"progress": 50, "step": "Создание аудио (gTTS)"})
        logger.info("Task %s: generating audio (voice=%s)", task_id, voice)
        voice_settings = _resolve_voice_settings(voice)
        audio_path = tts_service.generate_audio(text, language=voice_settings["language"], slow=voice_settings["slow"])
        logger.info("Task %s: audio generated at %s", task_id, audio_path)

        if scenes:
            for scene in scenes:
                scene_video_path = str(scene.get("video_path", "") or "").strip()
                scene_image_path = str(scene.get("image_path", "") or "").strip()
                if not scene_video_path and not scene_image_path:
                    logger.warning("Scene has no video or image, scene skipped.")
                    continue
                scene_video_result = ""
                if not scene_video_path and scene_image_path:
                    animated_output = _animate_image_with_avatar_pipeline(scene_image_path, audio_path)
                    if _is_video_file(animated_output):
                        scene_video_result = animated_output
                timed_scenes.append({"start_time": float(scene["start_time"]), "video_path": scene_video_path or scene_video_result, "image_path": scene_image_path, "text": scene.get("text", "")})
        
        self.update_state(state="PROGRESS", meta={"progress": 60, "step": "Подготовка CapCut"})
        capcut_base_url = os.getenv("CAPCUT_MATE_URL", "http://capcut-mate:30000")
        capcut_client = CapCutMateClient(capcut_base_url)
        if not capcut_client.check_health():
            raise RuntimeError("CapCut Mate API is unavailable.")

        draft_id = capcut_client.create_draft(draft_name=f"avatar_{task_id}")
        capcut_client.add_media_to_draft(draft_id, resolved_image_path, audio_path)
        logger.info("Task %s: media added to draft %s", task_id, draft_id)

        if timed_scenes:
            capcut_client.add_scenes_with_timings(draft_id, timed_scenes)
            logger.info("Task %s: timed scenes added (%s)", task_id, len(timed_scenes))

        # --- НАЧАЛО ИЗМЕНЕННОЙ ЛОГИКИ МУЗЫКИ ---
        if use_background_music:
            assets_dir = backend_dir / "assets"
            track_name = music_track if music_track.endswith('.mp3') else f"{music_track}.mp3"
            potential_music_path = assets_dir / track_name
            
            if potential_music_path.exists():
                music_path = potential_music_path
                capcut_client.add_background_music(
                    draft_id,
                    str(music_path),
                    volume=float(max(0, min(100, music_volume))) / 100.0,
                )
                logger.info("Task %s: background music '%s' added.", task_id, track_name)
            else:
                logger.warning("Music track '%s' not found in assets. Skipping background music.", track_name)
        # --- КОНЕЦ ИЗМЕНЕННОЙ ЛОГИКИ МУЗЫКИ ---

        duration = tts_service.get_audio_duration(audio_path)
        capcut_client.set_draft_duration(draft_id, duration)
        logger.info("Task %s: draft duration set to %.3f sec", task_id, duration)

        if add_subtitles:
            subtitle_items = _transcribe_with_timestamps(audio_path)
            for item in subtitle_items:
                item["color"] = subtitle_color
                item["font_size"] = int(max(16, min(72, subtitle_font_size)))
            if subtitle_items:
                capcut_client.add_subtitles(draft_id, subtitle_items)
                logger.info("Task %s: subtitles added (%s)", task_id, len(subtitle_items))

        self.update_state(state="PROGRESS", meta={"progress": 70, "step": "Рендеринг видео"})
        render_task_id = capcut_client.render_draft(draft_id)
        logger.info("Task %s: render started (%s)", task_id, render_task_id)

        # ... (остальная часть функции без изменений) ...
        last_reported_progress = 70
        start_wait = time.time()
        while True:
            status_payload = capcut_client.get_render_status(render_task_id)
            render_status = str(status_payload.get("status", "pending")).lower()
            render_progress = int(status_payload.get("progress", 0))
            mapped_progress = 70 + int(render_progress * 0.2)
            mapped_progress = max(70, min(90, mapped_progress))
            threshold_progress = (mapped_progress // 10) * 10
            if threshold_progress >= last_reported_progress + 10:
                last_reported_progress = threshold_progress
                self.update_state(state="PROGRESS", meta={"progress": last_reported_progress, "step": f"Рендеринг видео ({render_progress}%)"})
                logger.info("Task %s: render progress update task_progress=%s render_progress=%s", task_id, last_reported_progress, render_progress)
            if render_status == "completed": break
            if render_status == "failed": raise RuntimeError(f"Render failed for task {render_task_id}")
            if time.time() - start_wait > 300: raise TimeoutError("Render did not complete within 300 seconds.")
            time.sleep(3)
        
        video_url = capcut_client.wait_for_render(render_task_id, poll_interval=1, timeout=30)
        output_path = videos_dir / f"{task_id}.mp4"
        capcut_client.download_video(video_url, str(output_path))
        logger.info("Task %s: video downloaded to %s", task_id, output_path)
        self.update_state(state="PROGRESS", meta={"progress": 100, "step": "Видео готово"})
        
        return {
            "status": "SUCCESS",
            "video_path": str(output_path.resolve()),
            "video_url": f"/api/download/{task_id}",
            "result_url": f"/api/download/{task_id}",
            "progress": 100,
            "current_step": "Completed",
        }
    except Exception as e:
        trace = traceback.format_exc()
        logger.error("Task %s failed: %s", task_id, e)
        logger.error("Task %s traceback:\n%s", task_id, trace)
        self.update_state(state="FAILURE", meta={"error": str(e), "exc_type": type(e).__name__})
        raise



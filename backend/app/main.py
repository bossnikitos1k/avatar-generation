import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from celery.result import AsyncResult
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .celery_app import celery_app
from .models import GenerateResponse, StatusResponse
from .tasks import generate_video_task

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Avatar Generation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UPLOADS_DIR = BACKEND_DIR / "uploads"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

def _estimate_tts_duration_seconds(text: str) -> float:
    words = len((text or "").split())
    return words / 2.4 if words else 0.0

@app.post("/api/generate", response_model=GenerateResponse)
async def generate(
    text: str = Form(...),
    image: UploadFile = File(...),
    scene_media: List[UploadFile] = File(...),
    voice: str = Form(default="ru"),
    style: str = Form(default="cartoon_furry"),
    use_background_music: bool = Form(default=False),
    music_volume: int = Form(default=30),
    music_track: Optional[str] = Form(default="background"), # <--- ИЗМЕНЕНИЕ ЗДЕСЬ
    add_subtitles: bool = Form(default=False),
    subtitle_color: str = Form(default="#FFFFFF"),
    subtitle_font_size: int = Form(default=42),
    scenes_json: Optional[str] = Form(None),
) -> GenerateResponse:
    try:
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            raise HTTPException(status_code=400, detail="Текст не должен быть пустым.")
        
        logger.info("Received /api/generate request (voice=%s, style=%s)", voice, style)
        
        safe_filename = f"upload_{uuid4().hex}_{image.filename}"
        image_target_path = UPLOADS_DIR / safe_filename
        with open(image_target_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_path = str(image_target_path)
        logger.info("Main image uploaded and saved to %s", image_path)
            
        scene_media_files: List[str] = []
        incoming_scene_dir = UPLOADS_DIR / "incoming_scene_media"
        incoming_scene_dir.mkdir(parents=True, exist_ok=True)
        for idx, uploaded in enumerate(scene_media or []):
            safe_name = uploaded.filename or f"scene_media_{idx}"
            suffix = Path(safe_name).suffix or ".bin"
            unique_name = f"{uuid4().hex}_{idx}{suffix}"
            incoming_path = incoming_scene_dir / unique_name
            with open(incoming_path, "wb") as buffer:
                shutil.copyfileobj(uploaded.file, buffer)
            scene_media_files.append(str(incoming_path.resolve()))
            
        task = generate_video_task.delay(
            text=cleaned_text,
            image_path=image_path,
            voice=voice,
            style=style,
            use_background_music=use_background_music,
            music_volume=music_volume,
            music_track=music_track, # <--- И ИЗМЕНЕНИЕ ЗДЕСЬ
            add_subtitles=add_subtitles,
            subtitle_color=subtitle_color,
            subtitle_font_size=subtitle_font_size,
            scenes_json=scenes_json,
            scene_media_files=scene_media_files,
        )
        logger.info("Celery task created: %s", task.id)
        return GenerateResponse(
            task_id=task.id,
            status="PENDING",
            message="Task created. Use /api/status/{task_id} to track progress.",
        )
    except Exception as exc:
        logger.exception("Failed in /api/generate")
        raise HTTPException(status_code=500, detail=f"Generation start failed: {exc}") from exc

# ... (остальной код файла get_status, download_video и т.д. остается без изменений) ...
@app.get("/api/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str) -> StatusResponse:
    try:
        logger.info("Received /api/status request for task %s", task_id)
        result = AsyncResult(task_id, app=celery_app)
        raw_state = result.state
        info = result.info if isinstance(result.info, dict) else {}
        if raw_state == "PENDING":
            return StatusResponse(task_id=task_id, status="PENDING", progress=0, current_step="Task is waiting in queue.")
        if raw_state == "STARTED":
            return StatusResponse(task_id=task_id, status="STARTED", progress=int(info.get("progress", 0)), current_step=str(info.get("current_step", "Task is being processed.")))
        if raw_state == "SUCCESS":
            task_result = result.result if isinstance(result.result, dict) else {}
            result_url = task_result.get("result_url") or f"/api/download/{task_id}"
            return StatusResponse(task_id=task_id, status="SUCCESS", progress=100, current_step=str(task_result.get("current_step", "Video is ready.")), result_url=result_url)
        if raw_state == "FAILURE":
            error_text = str(result.result)
            return StatusResponse(task_id=task_id, status="FAILURE", progress=int(info.get("progress", 0)) if info else 0, current_step=str(info.get("current_step", "Task failed.")) if info else "Task failed.", error=error_text)
        return StatusResponse(task_id=task_id, status=raw_state, progress=int(info.get("progress", 0)) if info else 0, current_step=str(info.get("current_step", "Task state updated.")) if info else "Task state updated.")
    except Exception as exc:
        logger.exception("Failed in /api/status for task %s", task_id)
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {exc}") from exc
@app.get("/api/download/{task_id}")
async def download_video(task_id: str) -> FileResponse:
    try:
        logger.info("Received /api/download request for task %s", task_id)
        result = AsyncResult(task_id, app=celery_app)
        if result.state != "SUCCESS":
            raise HTTPException(status_code=400, detail=f"Task is not completed yet. Current state: {result.state}")
        task_result = result.result if isinstance(result.result, dict) else {}
        video_path = task_result.get("video_path")
        if not video_path:
            raise HTTPException(status_code=404, detail="No video path found for this task.")
        video_file = Path(video_path)
        if not video_file.exists():
            raise HTTPException(status_code=404, detail="Generated video file not found.")
        filename = task_result.get("filename") or f"{task_id}.mp4"
        logger.info("Sending video file %s for task %s", video_file, task_id)
        return FileResponse(path=str(video_file), media_type="video/mp4", filename=filename, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except Exception as exc:
        logger.exception("Failed in /api/download for task %s", task_id)
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}") from exc
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    logger.warning("Frontend directory not found: %s", FRONTEND_DIR)




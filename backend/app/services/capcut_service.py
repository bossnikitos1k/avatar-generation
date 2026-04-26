import logging
import os
import time
import json
from pathlib import Path
from typing import Any, Dict, List, Union

import requests
from requests import Response
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)


class CapCutMateClient:
    """
    HTTP client wrapper around CapCut Mate OpenAPI endpoints.
    """

    def __init__(self, base_url: str, timeout: int = 300):
        """
        Initialize client with base URL and request timeout (seconds).
        """
        default_url = os.getenv("CAPCUT_MATE_URL", "http://capcut-mate:30000")
        self.base_url = (base_url or default_url).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        logger.info("CapCutMateClient initialized (base_url=%s, timeout=%s)", self.base_url, self.timeout)

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}{endpoint}"

    @staticmethod
    def _parse_json(response: Response) -> Dict:
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response: {response.text}") from exc

    @staticmethod
    def _extract_data(payload: Dict) -> Dict:
        # Support both {"data": {...}} and flat payloads.
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def create_draft(self, draft_name: str, resolution: str = "1080x1920", fps: int = 30) -> str:
        """
        Create a draft project and return draft_id.
        """
        endpoint = "/openapi/capcut-mate/v1/create_draft"
        body = {"draft_name": draft_name, "resolution": resolution, "fps": fps}
        logger.info("Creating draft: name=%s, resolution=%s, fps=%s", draft_name, resolution, fps)

        try:
            response = self.session.post(self._url(endpoint), json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            data = self._extract_data(payload)
            draft_id = data.get("draft_id")
            if not draft_id:
                raise RuntimeError(f"draft_id not found in response: {payload}")
            logger.info("Draft created successfully: draft_id=%s", draft_id)
            return str(draft_id)
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to create draft due to network/request error.")
            raise RuntimeError(f"Failed to create draft: {exc}") from exc

    def create_project(
        self,
        draft_name: str,
        audio_url: str,
        scenes_json: Union[str, List[Dict[str, Any]], None],
        resolution: str = "1080x1920",
        fps: int = 30,
    ) -> Dict[str, Any]:
        """
        Create draft and attach scene materials in one easy_create_material call.

        For each scene item with `video_path`, this method creates:
            {"video_url": "<video_path>"}
        """
        if not audio_url or not str(audio_url).strip():
            raise ValueError("audio_url must not be empty.")

        endpoint = "/openapi/capcut-mate/v1/easy_create_material"

        # 1) Create draft first.
        create_body = {"draft_name": draft_name, "resolution": resolution, "fps": fps}
        logger.info("Creating project draft before easy_create_material (name=%s)", draft_name)

        try:
            create_resp = self.session.post(self._url("/openapi/capcut-mate/v1/create_draft"), json=create_body, timeout=self.timeout)
            create_resp.raise_for_status()
            create_payload = self._parse_json(create_resp)
            create_data = self._extract_data(create_payload)
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to create draft for create_project.")
            raise RuntimeError(f"Failed to create draft: {exc}") from exc

        draft_url = create_data.get("draft_url") or create_data.get("draft_id")
        if not draft_url:
            raise RuntimeError(f"Draft creation response missing draft_url/draft_id: {create_payload}")

        # 2) Parse scenes JSON/list and build materials array.
        if scenes_json is None:
            raw_scenes: List[Dict[str, Any]] = []
        elif isinstance(scenes_json, str):
            try:
                parsed = json.loads(scenes_json)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid scenes_json: expected JSON array.") from exc
            if not isinstance(parsed, list):
                raise ValueError("Invalid scenes_json: expected JSON array.")
            raw_scenes = [item for item in parsed if isinstance(item, dict)]
        elif isinstance(scenes_json, list):
            raw_scenes = [item for item in scenes_json if isinstance(item, dict)]
        else:
            raise ValueError("scenes_json must be string, list, or None.")

        materials = []
        for scene in raw_scenes:
            video_path = str(scene.get("video_path", "") or "").strip()
            if video_path:
                materials.append({"video_url": video_path})

        # 3) Send one easy_create_material request with draft_url/audio_url/materials.
        body = {
            "draft_url": draft_url,
            "audio_url": str(audio_url).strip(),
            "materials": materials,
        }
        logger.info("Calling easy_create_material (draft=%s, materials=%s)", draft_url, len(materials))

        try:
            response = self.session.post(self._url(endpoint), json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            success = bool(payload.get("success", True))
            if not success:
                raise RuntimeError(f"easy_create_material reported failure: {payload}")
            return self._extract_data(payload)
        except (RequestException, Timeout) as exc:
            logger.exception("easy_create_material request failed.")
            raise RuntimeError(f"Failed to call easy_create_material: {exc}") from exc

    def add_media_to_draft(self, draft_id: str, image_path: str, audio_path: str) -> bool:
        """
        Upload image and audio files to an existing draft.
        """
        endpoint = "/openapi/capcut-mate/v1/add_media"
        image_file = Path(image_path)
        audio_file = Path(audio_path)
        if not image_file.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info("Adding media to draft %s (image=%s, audio=%s)", draft_id, image_file, audio_file)

        files = {
            "image": (image_file.name, image_file.open("rb"), "application/octet-stream"),
            "audio": (audio_file.name, audio_file.open("rb"), "audio/mpeg"),
        }
        data = {"draft_id": draft_id}

        try:
            response = self.session.post(self._url(endpoint), files=files, data=data, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            success = bool(payload.get("success", True))
            if not success:
                raise RuntimeError(f"CapCut add_media reported failure: {payload}")
            logger.info("Media added successfully to draft %s", draft_id)
            return True
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to upload media to draft %s", draft_id)
            raise RuntimeError(f"Failed to add media to draft: {exc}") from exc
        finally:
            # Explicitly close file descriptors to avoid leaks.
            files["image"][1].close()
            files["audio"][1].close()

    def set_draft_duration(self, draft_id: str, duration: float) -> bool:
        """
        Set draft timeline duration (seconds).
        """
        endpoint = "/openapi/capcut-mate/v1/set_duration"
        body = {"draft_id": draft_id, "duration": float(duration)}
        logger.info("Setting draft duration: draft_id=%s, duration=%.3f", draft_id, duration)

        try:
            response = self.session.post(self._url(endpoint), json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            success = bool(payload.get("success", True))
            if not success:
                raise RuntimeError(f"CapCut set_duration reported failure: {payload}")
            logger.info("Draft duration updated: draft_id=%s", draft_id)
            return True
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to set duration for draft %s", draft_id)
            raise RuntimeError(f"Failed to set draft duration: {exc}") from exc

    def add_background_music(self, draft_id: str, music_path: str, volume: float = 0.3) -> bool:
        """
        Add background music track to the existing draft.

        volume is normalized to [0.0 .. 1.0].
        """
        endpoint = "/openapi/capcut-mate/v1/add_background_music"
        music_file = Path(music_path)
        if not music_file.exists():
            raise FileNotFoundError(f"Background music file not found: {music_path}")

        normalized_volume = max(0.0, min(1.0, float(volume)))
        logger.info(
            "Adding background music to draft %s (track=%s, volume=%.2f)",
            draft_id,
            music_file,
            normalized_volume,
        )

        files = {
            "music": (music_file.name, music_file.open("rb"), "audio/mpeg"),
        }
        data = {"draft_id": draft_id, "volume": normalized_volume}

        try:
            response = self.session.post(self._url(endpoint), files=files, data=data, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            success = bool(payload.get("success", True))
            if not success:
                raise RuntimeError(f"CapCut add_background_music reported failure: {payload}")
            logger.info("Background music added successfully to draft %s", draft_id)
            return True
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to add background music to draft %s", draft_id)
            raise RuntimeError(f"Failed to add background music: {exc}") from exc
        finally:
            files["music"][1].close()

    def add_subtitles(self, draft_id: str, subtitles_data: list) -> bool:
        """
        Add subtitles with timestamps to draft timeline.

        subtitles_data example:
        [{"start": 0.0, "end": 1.2, "text": "hello", "color": "#FFFFFF", "font_size": 42}]
        """
        endpoint = "/openapi/capcut-mate/v1/add_subtitles"
        body = {"draft_id": draft_id, "subtitles": subtitles_data}
        logger.info("Adding subtitles to draft %s (items=%s)", draft_id, len(subtitles_data or []))

        try:
            response = self.session.post(self._url(endpoint), json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            success = bool(payload.get("success", True))
            if not success:
                raise RuntimeError(f"CapCut add_subtitles reported failure: {payload}")
            logger.info("Subtitles added successfully to draft %s", draft_id)
            return True
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to add subtitles to draft %s", draft_id)
            raise RuntimeError(f"Failed to add subtitles: {exc}") from exc

    def add_scenes_with_timings(self, draft_id: str, scenes_data: list) -> bool:
        """
        Add scene switch instructions to draft timeline by start_time.

        scenes_data example:
        [{"start_time": 0.0, "image_path": "/tmp/a.png"}]
        """
        endpoint = "/openapi/capcut-mate/v1/add_scenes_with_timings"
        body = {"draft_id": draft_id, "scenes": scenes_data}
        logger.info("Adding timed scenes to draft %s (scenes=%s)", draft_id, len(scenes_data or []))

        try:
            response = self.session.post(self._url(endpoint), json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            success = bool(payload.get("success", True))
            if not success:
                raise RuntimeError(f"CapCut add_scenes_with_timings reported failure: {payload}")
            logger.info("Timed scenes added successfully to draft %s", draft_id)
            return True
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to add timed scenes to draft %s", draft_id)
            raise RuntimeError(f"Failed to add timed scenes: {exc}") from exc

    def render_draft(self, draft_id: str, output_format: str = "mp4", quality: str = "high") -> str:
        """
        Start draft rendering and return render_task_id.
        """
        endpoint = "/openapi/capcut-mate/v1/render"
        body = {"draft_id": draft_id, "format": output_format, "quality": quality}
        logger.info("Starting render for draft %s (format=%s, quality=%s)", draft_id, output_format, quality)

        try:
            response = self.session.post(self._url(endpoint), json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            data = self._extract_data(payload)
            render_task_id = data.get("render_task_id")
            if not render_task_id:
                raise RuntimeError(f"render_task_id not found in response: {payload}")
            logger.info("Render started: render_task_id=%s", render_task_id)
            return str(render_task_id)
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to start render for draft %s", draft_id)
            raise RuntimeError(f"Failed to render draft: {exc}") from exc

    def get_render_status(self, render_task_id: str) -> dict:
        """
        Get render task status payload.

        Expected shape:
        {
            "status": "pending|processing|completed|failed",
            "progress": 0-100,
            "result_url": "..."  # optional
        }
        """
        endpoint = f"/openapi/capcut-mate/v1/render_status/{render_task_id}"
        logger.info("Fetching render status: render_task_id=%s", render_task_id)

        try:
            response = self.session.get(self._url(endpoint), timeout=self.timeout)
            response.raise_for_status()
            payload = self._parse_json(response)
            data = self._extract_data(payload)
            status_payload = {
                "status": str(data.get("status", "pending")),
                "progress": int(data.get("progress", 0)),
                "result_url": data.get("result_url"),
            }
            logger.info(
                "Render status received: task=%s status=%s progress=%s",
                render_task_id,
                status_payload["status"],
                status_payload["progress"],
            )
            return status_payload
        except (RequestException, Timeout) as exc:
            logger.exception("Failed to fetch render status for %s", render_task_id)
            raise RuntimeError(f"Failed to get render status: {exc}") from exc

    def wait_for_render(self, render_task_id: str, poll_interval: int = 3, timeout: int = 300) -> str:
        """
        Poll render status until completed/failed/timeout.
        Returns final result_url on success.
        """
        logger.info(
            "Waiting for render completion: task=%s poll_interval=%s timeout=%s",
            render_task_id,
            poll_interval,
            timeout,
        )
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.error("Render timeout exceeded for task %s", render_task_id)
                raise TimeoutError(f"Render did not complete within {timeout} seconds.")

            status_payload = self.get_render_status(render_task_id)
            status = status_payload.get("status", "pending").lower()
            progress = status_payload.get("progress", 0)
            logger.info("Render poll: task=%s status=%s progress=%s", render_task_id, status, progress)

            if status == "completed":
                result_url = status_payload.get("result_url")
                if not result_url:
                    raise RuntimeError("Render completed but result_url is missing.")
                logger.info("Render completed successfully: task=%s url=%s", render_task_id, result_url)
                return str(result_url)

            if status == "failed":
                logger.error("Render failed for task %s", render_task_id)
                raise RuntimeError(f"Render failed for task {render_task_id}.")

            time.sleep(poll_interval)

    def download_video(self, video_url: str, output_path: str) -> bool:
        """
        Download rendered video from URL to local file path.
        """
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading video from %s to %s", video_url, target)

        try:
            with self.session.get(video_url, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()
                with target.open("wb") as file_out:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file_out.write(chunk)
            logger.info("Video downloaded successfully: %s", target.resolve())
            return True
        except (RequestException, Timeout, OSError) as exc:
            logger.exception("Failed to download video from %s", video_url)
            raise RuntimeError(f"Failed to download video: {exc}") from exc

    def check_health(self) -> bool:
        """
        Check service health using /health or OpenAPI health endpoint.
        """
        endpoints = ["/health", "/openapi/capcut-mate/v1/health"]
        for endpoint in endpoints:
            url = self._url(endpoint)
            try:
                logger.info("Checking CapCut Mate health endpoint: %s", url)
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    logger.info("CapCut Mate health check passed via %s", endpoint)
                    return True
                logger.warning("Health endpoint %s returned status %s", endpoint, response.status_code)
            except (RequestException, Timeout):
                logger.exception("Health check request failed for endpoint %s", endpoint)
        logger.error("CapCut Mate health check failed for all known endpoints.")
        return False


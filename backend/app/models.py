from typing import Optional

from pydantic import BaseModel, Field


class Scene(BaseModel):
    """
    Scene item provided by frontend.

    start_time is passed in seconds (float) to simplify timeline calculations.
    """

    start_time: float = Field(..., ge=0, description="Scene start time in seconds.")
    text: Optional[str] = Field(default=None, description="Optional scene-specific narration text.")
    scene_description: Optional[str] = Field(
        default=None,
        description="Optional prompt fragment for image generation in this scene.",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Optional local path to pre-uploaded scene image file.",
    )
    background: Optional[str] = Field(
        default=None,
        description="Optional additional background/context description for this scene.",
    )


class GenerateResponse(BaseModel):
    """
    Response returned right after task creation.
    """

    task_id: str = Field(..., description="Celery task identifier.")
    status: str = Field(..., description="Initial task status.")
    message: str = Field(..., description="Human-readable message for client.")


class StatusResponse(BaseModel):
    """
    Detailed task status for progress polling endpoint.
    """

    task_id: str = Field(..., description="Celery task identifier.")
    status: str = Field(..., description="Current Celery task status.")
    progress: int = Field(..., ge=0, le=100, description="Progress percentage (0-100).")
    current_step: str = Field(..., description="Current processing step.")
    result_url: Optional[str] = Field(default=None, description="URL to download final result.")
    error: Optional[str] = Field(default=None, description="Error message if task failed.")


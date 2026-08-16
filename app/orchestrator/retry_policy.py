from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_image_attempts: int = 3
    max_video_attempts: int = 2


from app.domain.enums import RunStatus


PROGRESS = {
    RunStatus.CREATED.value: 0, RunStatus.PRODUCT_ANALYZING.value: 5, RunStatus.PRODUCT_ANALYZED.value: 12,
    RunStatus.SCENE_ROUTING.value: 15, RunStatus.SCENE_SELECTED.value: 20, RunStatus.MOTION_ROUTING.value: 23,
    RunStatus.MOTIONS_SELECTED.value: 28, RunStatus.STORYBOARD_BUILDING.value: 30, RunStatus.STORYBOARD_READY.value: 36,
    RunStatus.KEYFRAMES_GENERATING.value: 45, RunStatus.KEYFRAMES_READY.value: 58, RunStatus.IMAGE_QA.value: 62,
    RunStatus.IMAGE_QA_PASSED.value: 68, RunStatus.VIDEOS_GENERATING.value: 75, RunStatus.VIDEOS_READY.value: 86,
    RunStatus.VIDEO_QA.value: 89, RunStatus.VIDEO_QA_PASSED.value: 93, RunStatus.COMPOSING.value: 96,
    RunStatus.COMPLETED.value: 100, RunStatus.INTERRUPTED.value: 0, RunStatus.PARTIAL_FAILED.value: 0, RunStatus.FAILED.value: 0,
}


"""Nigoh va bosh holati."""

from proctoring.gaze.head_pose import HeadPose, estimate_head_pose
from proctoring.gaze.gaze_estimator import GazeEstimator, GazeResult

__all__ = ["GazeEstimator", "GazeResult", "HeadPose", "estimate_head_pose"]

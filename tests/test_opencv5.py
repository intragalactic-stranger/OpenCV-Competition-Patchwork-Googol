"""Fast guards that the OpenCV 5 features Patchwork relies on are present."""

import cv2


def test_opencv_major_version_is_5():
    assert cv2.__version__.split(".")[0] == "5"


def test_dnn_engine_constants_exist():
    assert {cv2.dnn.ENGINE_AUTO, cv2.dnn.ENGINE_CLASSIC, cv2.dnn.ENGINE_NEW}
    assert cv2.dnn.ENGINE_NEW != cv2.dnn.ENGINE_CLASSIC


def test_charuco_and_yunet_available():
    assert hasattr(cv2.aruco, "CharucoDetector")
    assert hasattr(cv2, "FaceDetectorYN")

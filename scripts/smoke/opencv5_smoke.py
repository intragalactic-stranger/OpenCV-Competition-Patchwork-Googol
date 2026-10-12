"""Phase 0 smoke test: prove the OpenCV 5 features Patchwork depends on actually work here.

Checks
  1. DNN: a SegFormer-like ONNX graph (Conv, LayerNorm, MatMul, Softmax, Resize, dynamic H/W)
     loads in ENGINE_NEW and matches onnxruntime; ENGINE_CLASSIC is tried for comparison.
  2. ChArUco calibration round-trip through a known, distorted pinhole camera.
  3. YuNet face detector (OpenCV Zoo) loads and runs.
  4. ORB + RANSAC homography recovers a known warp.

Writes eval/results/smoke/opencv5_smoke.json. Exit code 1 if any required check fails.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "eval" / "results" / "smoke"
MODEL_DIR = ROOT / "data" / "models"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)

rng = np.random.default_rng(0)


# ---------------------------------------------------------------------------------------------
# 1. DNN engine
# ---------------------------------------------------------------------------------------------
def build_segformer_like_onnx(path: Path, c_in: int = 3, c: int = 16, n_cls: int = 4) -> None:
    """Tiny graph with the op mix SegFormer needs: patch-embed conv, LayerNorm, attention-style
    MatMul + Softmax over tokens, a 1x1 classifier and a bilinear Resize back to input size.
    H and W are symbolic (dynamic shapes)."""
    init = []

    def w(name, arr):
        init.append(numpy_helper.from_array(arr.astype(np.float32), name))
        return name

    w("conv_w", rng.normal(0, 0.2, (c, c_in, 4, 4)))
    w("conv_b", rng.normal(0, 0.1, (c,)))
    w("ln_g", 1 + rng.normal(0, 0.05, (c,)))
    w("ln_b", rng.normal(0, 0.05, (c,)))
    w("wq", rng.normal(0, 0.3, (c, c)))
    w("wk", rng.normal(0, 0.3, (c, c)))
    w("cls_w", rng.normal(0, 0.3, (n_cls, c, 1, 1)))
    w("cls_b", rng.normal(0, 0.1, (n_cls,)))
    init.append(numpy_helper.from_array(np.array([0, c, -1], np.int64), "tok_shape"))
    init.append(numpy_helper.from_array(np.array([0.25], np.float32), "attn_scale"))
    init.append(numpy_helper.from_array(np.array([2, 3], np.int64), "hw_idx"))

    nodes = [
        helper.make_node("Conv", ["x", "conv_w", "conv_b"], ["f"], strides=[4, 4]),  # (1,c,H/4,W/4)
        helper.make_node("Shape", ["f"], ["f_shape"]),
        helper.make_node("Reshape", ["f", "tok_shape"], ["t0"]),  # (1,c,N)
        helper.make_node("Transpose", ["t0"], ["t"], perm=[0, 2, 1]),  # (1,N,c)
        helper.make_node("LayerNormalization", ["t", "ln_g", "ln_b"], ["tn"], axis=-1, epsilon=1e-5),
        helper.make_node("MatMul", ["tn", "wq"], ["q"]),
        helper.make_node("MatMul", ["tn", "wk"], ["k"]),
        helper.make_node("Transpose", ["k"], ["kt"], perm=[0, 2, 1]),
        helper.make_node("MatMul", ["q", "kt"], ["s0"]),  # (1,N,N)
        helper.make_node("Mul", ["s0", "attn_scale"], ["s"]),
        helper.make_node("Softmax", ["s"], ["a"], axis=-1),
        helper.make_node("MatMul", ["a", "tn"], ["o"]),  # (1,N,c)
        helper.make_node("Add", ["o", "t"], ["r"]),  # residual
        helper.make_node("Transpose", ["r"], ["r_t"], perm=[0, 2, 1]),  # (1,c,N)
        helper.make_node("Reshape", ["r_t", "f_shape"], ["g"]),  # (1,c,H/4,W/4)
        helper.make_node("Conv", ["g", "cls_w", "cls_b"], ["logits_lr"]),
        helper.make_node("Shape", ["x"], ["x_shape"]),
        helper.make_node("Gather", ["x_shape", "hw_idx"], ["x_hw"], axis=0),
        helper.make_node("Shape", ["logits_lr"], ["l_shape"]),
        helper.make_node("Slice", ["l_shape", "zero", "two"], ["l_nc"]),
        helper.make_node("Concat", ["l_nc", "x_hw"], ["out_size"], axis=0),
        helper.make_node("Resize", ["logits_lr", "", "", "out_size"], ["logits"], mode="linear"),
    ]
    init.append(numpy_helper.from_array(np.array([0], np.int64), "zero"))
    init.append(numpy_helper.from_array(np.array([2], np.int64), "two"))

    graph = helper.make_graph(
        nodes,
        "segformer_like",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, c_in, "H", "W"])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, n_cls, "H", "W"])],
        init,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def run_cv(path: Path, engine: int, x: np.ndarray) -> tuple[np.ndarray, float]:
    net = cv2.dnn.readNetFromONNX(str(path), engine)
    net.setInput(x)
    net.forward()  # warm-up
    t0 = time.perf_counter()
    y = net.forward()
    return np.asarray(y), (time.perf_counter() - t0) * 1000


def check_dnn(results: dict) -> bool:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / "smoke_segformer_like.onnx"
    build_segformer_like_onnx(path)
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    ok = True
    per_size = []
    # Dynamic shapes: one model, several input sizes (multiples of 32), as segment.py will use.
    for h, w in [(64, 96), (128, 224), (256, 448)]:
        x = rng.random((1, 3, h, w), dtype=np.float32)
        ref = sess.run(None, {"x": x})[0]
        row = {"input": [h, w], "ort_shape": list(ref.shape)}
        for name, eng in [("ENGINE_NEW", cv2.dnn.ENGINE_NEW), ("ENGINE_CLASSIC", cv2.dnn.ENGINE_CLASSIC)]:
            try:
                y, ms = run_cv(path, eng, x)
                diff = float(np.max(np.abs(y.reshape(ref.shape) - ref)))
                row[name] = {"loaded": True, "max_abs_diff": diff, "ms": round(ms, 2)}
            except Exception as e:  # noqa: BLE001 - we want the error text in the report
                msg = " ".join(str(e).split())
                row[name] = {"loaded": False, "error": msg[:240]}
        new = row["ENGINE_NEW"]
        if not (new.get("loaded") and new["max_abs_diff"] <= 1e-3):
            ok = False
        per_size.append(row)
    results["dnn"] = {"ok": ok, "model": path.name, "opset": 17, "runs": per_size}
    return ok


# ---------------------------------------------------------------------------------------------
# 2. ChArUco calibration round-trip
# ---------------------------------------------------------------------------------------------
def distort_image(ideal: np.ndarray, K: np.ndarray, dist: np.ndarray) -> np.ndarray:
    """Render what a lens with `dist` would see: for every distorted output pixel find the ideal
    pixel it comes from (undistortPoints) and sample there."""
    h, w = ideal.shape[:2]
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1).reshape(-1, 1, 2)
    und = cv2.undistortPoints(pts, K, dist, P=K).reshape(h, w, 2)
    return cv2.remap(ideal, und[..., 0], und[..., 1], cv2.INTER_LINEAR, borderValue=255)


def check_charuco(results: dict) -> bool:
    W, H = 1920, 1080
    K = np.array([[1400.0, 0, 960.0], [0, 1400.0, 540.0], [0, 0, 1]])
    dist = np.array([-0.28, 0.08, 0.0005, -0.0003, 0.0])
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
    sq, mk = 0.06, 0.045  # metres
    board = cv2.aruco.CharucoBoard((7, 5), sq, mk, dictionary)
    px_per_m = 4000
    board_img = board.generateImage((int(7 * sq * px_per_m), int(5 * sq * px_per_m)), marginSize=0)
    detector = cv2.aruco.CharucoDetector(board)

    obj_pts, img_pts, used = [], [], 0
    for _ in range(18):
        rvec = np.array([rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(-0.2, 0.2)])
        R, _ = cv2.Rodrigues(rvec)
        center = np.array([7 * sq / 2, 5 * sq / 2, 0])
        t = np.array([rng.uniform(-0.25, 0.25), rng.uniform(-0.12, 0.12), rng.uniform(0.6, 1.0)])
        t = t - R @ center
        # plane (board metres) -> image: H = K [r1 r2 t]; board pixels -> metres scale first
        Hb = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ np.diag([1 / px_per_m, 1 / px_per_m, 1])
        ideal = cv2.warpPerspective(board_img, Hb, (W, H), borderValue=255)
        img = distort_image(ideal, K, dist)
        corners, ids, _, _ = detector.detectBoard(img)
        if ids is None or len(ids) < 10:
            continue
        o, p = board.matchImagePoints(corners, ids)
        obj_pts.append(o)
        img_pts.append(p)
        used += 1
    rms, K_est, dist_est, _, _ = cv2.calibrateCamera(obj_pts, img_pts, (W, H), None, None)
    fx_err = abs(K_est[0, 0] - K[0, 0]) / K[0, 0]
    k1_err = abs(dist_est.ravel()[0] - dist[0])
    ok = used >= 10 and rms < 0.5 and fx_err < 0.01 and k1_err < 0.03
    results["charuco"] = {
        "ok": bool(ok),
        "views_used": used,
        "rms_px": round(float(rms), 4),
        "fx_true": K[0, 0],
        "fx_est": round(float(K_est[0, 0]), 2),
        "fx_rel_err": round(float(fx_err), 5),
        "k1_true": dist[0],
        "k1_est": round(float(dist_est.ravel()[0]), 4),
    }
    return ok


# ---------------------------------------------------------------------------------------------
# 3. YuNet
# ---------------------------------------------------------------------------------------------
def check_yunet(results: dict) -> bool:
    path = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
    try:
        if not path.exists():
            urllib.request.urlretrieve(YUNET_URL, path)
        det = cv2.FaceDetectorYN.create(str(path), "", (640, 360), 0.6, 0.3, 5000)
        img = np.full((360, 640, 3), 127, np.uint8)
        _, faces = det.detect(img)
        n = 0 if faces is None else len(faces)
        results["yunet"] = {"ok": True, "model": path.name, "faces_on_blank_frame": n}
        return True
    except Exception as e:  # noqa: BLE001
        results["yunet"] = {"ok": False, "error": str(e)[:300]}
        return False


# ---------------------------------------------------------------------------------------------
# 4. ORB + homography
# ---------------------------------------------------------------------------------------------
def check_orb(results: dict) -> bool:
    # asphalt-like texture: multi-scale noise
    base = np.zeros((400, 400), np.float32)
    for s in (2, 8, 32):
        n = rng.random((400 // s + 1, 400 // s + 1)).astype(np.float32)
        base += cv2.resize(n, (400, 400), interpolation=cv2.INTER_CUBIC) / s
    img = cv2.normalize(base, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    H_true = np.array([[0.98, -0.12, 25.0], [0.11, 0.99, -14.0], [0.0, 0.0, 1.0]])
    warped = cv2.warpPerspective(img, H_true, (400, 400))
    orb = cv2.ORB_create(2000)
    k1, d1 = orb.detectAndCompute(img, None)
    k2, d2 = orb.detectAndCompute(warped, None)
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < 0.75 * n.distance]
    src = np.float32([k1[m.queryIdx].pt for m in good])
    dst = np.float32([k2[m.trainIdx].pt for m in good])
    H_est, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    corners = np.float32([[100, 100], [300, 100], [300, 300], [100, 300]]).reshape(-1, 1, 2)
    err = float(
        np.max(
            np.linalg.norm(cv2.perspectiveTransform(corners, H_est) - cv2.perspectiveTransform(corners, H_true), axis=2)
        )
    )
    ok = err < 2.0 and int(inl.sum()) >= 25
    results["orb_homography"] = {
        "ok": ok,
        "good_matches": len(good),
        "inliers": int(inl.sum()),
        "corner_err_px": round(err, 3),
    }
    return ok


def write_evidence_md(results: dict, status: dict) -> None:
    """Human-readable evidence for docs/midpoint (regenerated on every run)."""
    lines = [
        "# OpenCV 5 smoke test (generated by `make smoke`)",
        "",
        f"OpenCV `{results['opencv_version']}` · NumPy `{results['numpy']}` · onnxruntime `{results['onnxruntime']}`",
        "",
        "## DNN engine: SegFormer-like ONNX graph with dynamic H×W",
        "",
        "| Input H×W | ENGINE_NEW loads | max abs diff vs onnxruntime | ENGINE_NEW ms | ENGINE_CLASSIC |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("dnn", {}).get("runs", []):
        n, c = r["ENGINE_NEW"], r["ENGINE_CLASSIC"]
        err = c.get("error", "")
        node = err.split("Node [")[1].split("]")[0] if "Node [" in err else err[:60]
        cls = "loads" if c.get("loaded") else f"fails to import (node `{node}`, dynamic shape)"
        lines.append(
            f"| {r['input'][0]}×{r['input'][1]} | {'yes' if n.get('loaded') else 'no'} | "
            f"{n.get('max_abs_diff', float('nan')):.2e} | {n.get('ms', '-')} | {cls} |"
        )
    ch, orb = results.get("charuco", {}), results.get("orb_homography", {})
    lines += [
        "",
        "## Other checks",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| ChArUco calibration (distorted synthetic camera) | RMS {ch.get('rms_px')} px; fx {ch.get('fx_est')} "
        f"vs true {ch.get('fx_true')} ({ch.get('fx_rel_err', 0) * 100:.3f}% error); k1 {ch.get('k1_est')} vs "
        f"{ch.get('k1_true')} |",
        f"| YuNet face detector (OpenCV Zoo) | {'loads and runs' if status.get('yunet') else 'FAILED'} |",
        f"| ORB + RANSAC homography | {orb.get('inliers')} inliers, corner error {orb.get('corner_err_px')} px |",
        "",
        f"**{sum(status.values())}/{len(status)} checks passed.**",
    ]
    assets = ROOT / "docs" / "midpoint" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "opencv5_smoke.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    results: dict = {
        "opencv_version": cv2.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
    }
    checks = [check_dnn, check_charuco, check_yunet, check_orb]
    status = {}
    for fn in checks:
        name = fn.__name__.removeprefix("check_")
        try:
            status[name] = fn(results)
        except Exception as e:  # noqa: BLE001
            status[name] = False
            results[name] = {"ok": False, "error": repr(e)[:300]}
        detail = results.get(name, results.get("orb_homography"))
        print(f"[{'PASS' if status[name] else 'FAIL'}] {name}: {json.dumps(detail)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "opencv5_smoke.json").write_text(json.dumps(results, indent=2))
    write_evidence_md(results, status)
    print(f"\nOpenCV {cv2.__version__} — {sum(status.values())}/{len(status)} checks passed")
    return 0 if all(status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

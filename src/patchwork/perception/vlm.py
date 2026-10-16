"""Context attributes from the evidence image with a vision-language model (Amazon Nova Lite on Bedrock).

The model sees the defect's evidence image (dashcam crop with the detected outline | 3 m x 3 m bird's-eye crop)
and answers a fixed JSON schema. Measurements never come from here: area, position and severity stay with
OpenCV geometry. The attributes feed the agent's exposure score (water pooling, wheel path).
"""

from __future__ import annotations

import json
import re

import boto3

MODEL = "apac.amazon.nova-lite-v1:0"  # first-party model only (D-17, D-27)
REGION = "ap-south-1"
PROMPT = """You are inspecting road damage for a municipal engineer. The image has two panels.
Left: a crop of a dashcam frame; the damage the vision system detected is outlined in red.
Right: the same spot seen from directly above (bird's-eye view, 3 m x 3 m, white grid = 0.5 m).

Answer ONLY with one JSON object, no other text:
{"water_pooling": true|false,      // standing water or a wet sheen inside the outlined damage
 "wheel_path": true|false,         // the damage lies where car wheels run (left or right tyre track of a lane)
 "surface": "asphalt"|"concrete"|"paver"|"unpaved",
 "near_road_edge": true|false,     // within about 0.5 m of the kerb or road edge
 "looks_like_damage": true|false,  // false if the outline is a shadow, manhole cover, patch or marking
 "note": "<= 12 words"}"""


def describe(image_jpeg: bytes, client=None) -> dict:
    client = client or boto3.client("bedrock-runtime", region_name=REGION)
    r = client.converse(
        modelId=MODEL,
        messages=[
            {
                "role": "user",
                "content": [{"image": {"format": "jpeg", "source": {"bytes": image_jpeg}}}, {"text": PROMPT}],
            }
        ],
        inferenceConfig={"temperature": 0.0, "maxTokens": 200},
    )
    text = r["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", re.sub(r"//[^\n]*", "", text), re.S)
    out = json.loads(m.group(0)) if m else {}
    keep = {
        "water_pooling": bool,
        "wheel_path": bool,
        "surface": str,
        "near_road_edge": bool,
        "looks_like_damage": bool,
        "note": str,
    }
    attrs = {k: t(out[k]) for k, t in keep.items() if k in out}
    attrs["vlm_model"] = MODEL
    attrs["vlm_tokens"] = r["usage"]["totalTokens"]
    return attrs

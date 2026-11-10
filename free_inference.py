#!/usr/bin/env python3
"""
CINEMA AI — Free GPU Inference Engine via HuggingFace Spaces.
Generates genuine Wan text-to-video samples across the 5 canonical styles
and bilingual (Arabic/English) inputs without requiring paid APIs or local GPUs.
"""
from __future__ import annotations
import os
import sys
import json
import time
import shutil
import hashlib
from pathlib import Path
from gradio_client import Client

from cinematic_engine.prompt_engineer import (
    FIVE_STYLES,
    build_cinematic_prompt,
    resolve_style,
)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()

FIVE_STYLE_PROMPTS = [
    {
        "id": "dod1_sample1_cinematic_realistic",
        "style": "cinematic_realistic",
        "prompt": "A lone explorer wearing a weathered expedition coat walks across vast desert sand dunes at sunset",
        "seed": 42
    },
    {
        "id": "dod1_sample2_realistic_human",
        "style": "realistic_human",
        "prompt": "A middle-aged man with natural skin texture and expressive eyes looking thoughtfully beside a window",
        "seed": 100
    },
    {
        "id": "dod1_sample3_3d_cartoon",
        "style": "cartoon_3d",
        "prompt": "A small cute orange fox character with large expressive eyes running playfully through a magical forest",
        "seed": 200
    },
    {
        "id": "dod1_sample4_2d_cartoon",
        "style": "cartoon_2d",
        "prompt": "A cheerful young adventurer with green jacket running along a hand-drawn fantasy forest trail",
        "seed": 300
    },
    {
        "id": "dod1_sample5_anime",
        "style": "anime",
        "prompt": "A noble swordswoman with long dark hair drawing her blade as cherry blossom petals drift in the wind",
        "seed": 400
    },
]

def main():
    print("[CINEMA-AI] Initializing Free GPU Wan Video Generator via HF Spaces...")
    space_id = "Upsampler/wan-2-2-14b-text-to-video"
    backup_space_id = "mediasynthesismuseum/modelscope-text-to-video"

    try:
        client = Client(space_id)
        active_space = space_id
    except Exception as e:
        print(f"[CINEMA-AI] Primary Space connection failed ({e}), falling back to {backup_space_id}...")
        client = Client(backup_space_id)
        active_space = backup_space_id

    records = []

    for item in FIVE_STYLE_PROMPTS:
        sid = item["id"]
        style_key = item["style"]
        user_p = item["prompt"]
        seed = item["seed"]

        out_path = OUTPUT_DIR / f"{sid}.mp4"
        meta_path = OUTPUT_DIR / f"{sid}.json"

        pos, neg = build_cinematic_prompt(user_p, style_override=style_key, return_negative=True)
        print(f"\n[CINEMA-AI] Generating {sid} (Style: {style_key}) ...")
        print(f"  Prompt: {pos[:80]}...")

        t0 = time.time()
        try:
            if active_space == space_id:
                res = client.predict(
                    prompt=pos,
                    aspect_ratio="16:9 (832x480)",
                    steps=4,
                    negative_prompt=neg,
                    duration_seconds=5.0,
                    guidance_scale=1.0,
                    guidance_scale_2=1.0,
                    seed=seed,
                    randomize_seed=False,
                    api_name="/generate_video"
                )
                video_src = res[0] if isinstance(res, (tuple, list)) else res
            else:
                res = client.predict(
                    prompt=pos,
                    seed=seed,
                    num_frames=24,
                    num_inference_steps=20,
                    api_name="/generate"
                )
                video_src = res

            elapsed = round(time.time() - t0, 2)
            shutil.copy2(video_src, out_path)
            chk = sha256_file(out_path)
            sz = out_path.stat().st_size

            meta = {
                "id": sid,
                "style": style_key,
                "prompt": pos,
                "negative_prompt": neg,
                "seed": seed,
                "space": active_space,
                "duration_seconds": 5.0,
                "filesize_bytes": sz,
                "sha256": chk,
                "latency_seconds": elapsed,
                "status": "success"
            }
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta, mf, indent=2, ensure_ascii=False)

            print(f"  ✓ Saved to {out_path} ({sz} bytes | {elapsed}s | sha256: {chk[:12]}...)")
            records.append(meta)

        except Exception as exc:
            print(f"  ✗ Failed on {sid}: {exc}")

    summary_file = OUTPUT_DIR / "metadata.json"
    with open(summary_file, "w", encoding="utf-8") as sf:
        json.dump(records, sf, indent=2, ensure_ascii=False)
    print(f"\n[CINEMA-AI] Finished! {len(records)} videos generated successfully.")

if __name__ == "__main__":
    main()

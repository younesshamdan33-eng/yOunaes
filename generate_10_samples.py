#!/usr/bin/env python3
"""
CINEMA AI — Automated Multi-Style Free GPU Video Generation.
Generates 10 distinct 5-second cinematic videos (2 per canonical style)
using high-speed free GPU inference (Lightricks LTX-Video distilled).
Outputs to outputs/dod1/<style>/sample_<n>.mp4 with metadata.json.
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
    build_cinematic_prompt,
    resolve_style,
)

BASE_OUT = Path("outputs/dod1")
BASE_OUT.mkdir(parents=True, exist_ok=True)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()

# 10 targeted prompts (2 per canonical style)
SAMPLES = [
    # 1. Cinematic Realistic
    ("cinematic_realistic", 1, "A lone explorer wearing a weathered expedition coat walks across vast golden desert sand dunes at sunset", 42),
    ("cinematic_realistic", 2, "A rainy neon-lit city street at night with futuristic flying vehicles passing above tall skyscrapers", 142),

    # 2. Realistic Human
    ("realistic_human", 1, "A middle-aged man with natural skin texture and expressive thoughtful eyes looking beside a modern apartment window", 100),
    ("realistic_human", 2, "A young woman with natural curly hair giving a subtle warm smile in soft overcast morning light", 101),

    # 3. 3D Cartoon
    ("cartoon_3d", 1, "A small cute orange fox character with large expressive eyes running playfully through a magical glowing forest", 200),
    ("cartoon_3d", 2, "A friendly little blue robot character exploring an ancient stone cavern with wonder and soft dimensional lighting", 201),

    # 4. 2D Cartoon
    ("cartoon_2d", 1, "A cheerful young adventurer with green jacket running along a hand-drawn fantasy forest trail with swirling autumn leaves", 300),
    ("cartoon_2d", 2, "A brave cartoon cat knight waving a tiny wooden sword on top of a hand-painted hill with bold clean lines", 301),

    # 5. Anime
    ("anime", 1, "A noble anime swordswoman with long dark hair drawing her gleaming blade as delicate cherry blossom petals drift in the wind", 400),
    ("anime", 2, "A determined young anime protagonist standing atop a dramatic shrine overlook looking out towards a scenic painted sky", 401),
]

def main():
    print("=== CINEMA AI — Generating 10 Videos across 5 Canonical Styles ===")
    client = Client("Lightricks/ltx-video-distilled")
    records = []

    for style, idx, raw_prompt, seed in SAMPLES:
        style_dir = BASE_OUT / style
        style_dir.mkdir(parents=True, exist_ok=True)
        out_file = style_dir / f"sample_{idx}.mp4"
        meta_file = style_dir / f"sample_{idx}.json"

        pos, neg = build_cinematic_prompt(raw_prompt, style_override=style, return_negative=True)
        print(f"\n[Generating] {style} - Sample {idx} (seed={seed}) ...")
        print(f"  Prompt: {pos[:75]}...")

        t0 = time.time()
        try:
            res = client.predict(
                prompt=pos,
                negative_prompt=neg,
                input_image_filepath=None,
                input_video_filepath=None,
                height_ui=512,
                width_ui=704,
                mode="text-to-video",
                duration_ui=5,
                ui_frames_to_use=9,
                seed_ui=seed,
                randomize_seed=False,
                ui_guidance_scale=1.0,
                improve_texture_flag=True,
                api_name="/text_to_video"
            )
            elapsed = round(time.time() - t0, 2)
            video_path = res[0]["video"] if isinstance(res[0], dict) else res[0]
            shutil.copy2(video_path, out_file)
            chk = sha256_file(out_file)
            sz = out_file.stat().st_size

            meta = {
                "style": style,
                "sample_index": idx,
                "prompt": pos,
                "negative_prompt": neg,
                "seed": seed,
                "duration_seconds": 5.1,
                "width": 704,
                "height": 512,
                "filesize_bytes": sz,
                "sha256": chk,
                "latency_seconds": elapsed,
                "backend": "Lightricks/ltx-video-distilled (Free GPU)"
            }
            with open(meta_file, "w", encoding="utf-8") as mf:
                json.dump(meta, mf, indent=2, ensure_ascii=False)

            print(f"  ✓ Saved: {out_file} ({sz} bytes | {elapsed}s | sha256: {chk[:12]}...)")
            records.append(meta)

        except Exception as exc:
            print(f"  ✗ Failed on {style}_{idx}: {exc}")

    # Write overall index
    index_file = BASE_OUT / "manifest.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"\n=== Completed {len(records)}/10 Videos Successfully! ===")

if __name__ == "__main__":
    main()

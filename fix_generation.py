from pathlib import Path
import shutil

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")
original = s

# Add missing 2D cartoon shot
if '"cartoon2d"' not in s[s.index("EVAL_SHOTS = ["):s.index("# ============================================================ توليد")]:
    fox = '    Shot("a small fox character with big eyes", "jumps over a stream", "magical forest", "cartoon3d", "tracking", "golden_hour", "playful"),'
    assert s.count(fox) == 1, "3D shot anchor mismatch"
    s = s.replace(fox, fox + '\n    Shot("a young adventurer with expressive eyes", "runs through a colorful enchanted forest", "hand-drawn fantasy landscape", "cartoon2d", "tracking", "golden_hour", "playful and vibrant"),', 1)

# Insert GPU tier selection
anchor = '    from diffusers.utils import export_to_video\n'
insert = '''    from diffusers.utils import export_to_video

    resources = Resources(cfg)
    tier_idx = resources.pick_tier()
    tier_frames, tier_h, tier_w = TIERS[tier_idx]
    gpu_state = resources.snapshot()
    log.info("GPU tier=%s resolution=%sx%s frames=%s GPU=%s VRAM=%s GB",
             tier_idx, tier_w, tier_h, tier_frames,
             gpu_state.get("gpu"), gpu_state.get("vram_total_gb"))
'''
assert s.count(anchor) == 1, "generate anchor mismatch"
s = s.replace(anchor, insert, 1)

# Use selected tier
old = 'height=cfg.gen_h, width=cfg.gen_w, num_frames=cfg.gen_frames'
assert s.count(old) == 1, "generation dimensions mismatch"
s = s.replace(old, 'height=tier_h, width=tier_w, num_frames=tier_frames', 1)

# Save generation metadata
old_meta = 'jdump({"prompt": p, "negative": neg, "seed": cfg.seed + i, "lora": str(lora)}, str(f) + ".json")'
new_meta = '''jdump({
            "prompt": p, "negative": neg, "seed": cfg.seed + i,
            "lora": str(lora), "tier": tier_idx,
            "width": tier_w, "height": tier_h, "frames": tier_frames,
            "steps": cfg.gen_steps, "fps": cfg.fps,
            "gpu": gpu_state.get("gpu"),
            "vram_total_gb": gpu_state.get("vram_total_gb")
        }, str(f) + ".json")'''
assert s.count(old_meta) == 1, "metadata anchor mismatch"
s = s.replace(old_meta, new_meta, 1)

backup = Path("cinema_trainer.py.pre_generation_fix.backup")
assert not backup.exists(), "Backup already exists; refusing to overwrite"
shutil.copy2(p, backup)
p.write_text(s, encoding="utf-8")
print("PATCH APPLIED")
print("Backup:", backup)

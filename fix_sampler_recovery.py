from pathlib import Path
import sys

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")

replacements = [
(
'''    consumed = sam.state(); pf = Prefetcher(files, sam, cfg.prefetch, res); pf.start()
''',
'''    # Exact recovery: sampler advances only in the training consumer.
    # Background prefetch is disabled until it can preserve consumed positions.
    consumed = sam.state()
'''
),
(
'''                d, consumed = pf.get(); lat = crop_latent(d["lat"].float(), tier).unsqueeze(0).cuda()
''',
'''                d = None
                for attempt in range(len(files)):
                    sample_index = sam.next()
                    sample_path = files[sample_index]
                    try:
                        d = torch.load(sample_path, map_location="cpu", weights_only=False)
                        if not isinstance(d, dict) or "lat" not in d or "emb" not in d:
                            raise ValueError("invalid latent cache payload")
                    except Exception as e:
                        consumed = sam.state()
                        log.warning("تخطي عينة كاش تالفة %s: %r", sample_path, e)
                        continue
                    consumed = sam.state()
                    break
                if d is None:
                    raise RuntimeError("لا توجد عينة كاش سليمة بعد فحص جميع الملفات")
                lat = crop_latent(d["lat"].float(), tier).unsqueeze(0).cuda()
'''
),
(
'''    pf.halt = True; payload = save("final")
''',
'''    payload = save("final")
'''
)
]

for old, new in replacements:
    count = s.count(old)
    if count != 1:
        sys.exit(f"ERROR: Expected one exact match, found {count}. No changes made.")
    s = s.replace(old, new, 1)

tmp = p.with_name("cinema_trainer.py.retmp")
tmp.write_text(s, encoding="utf-8")
tmp.replace(p)

print("SUCCESS: training now owns sampler advancement.")
print("SUCCESS: background prefetch disabled in train().")
print("SUCCESS: corrupt cache samples are skipped and recorded.")

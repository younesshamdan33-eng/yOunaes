from pathlib import Path
import sys

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")

old_init = '''    db = db or DB(cfg); st = Status(cfg); res = Resources(cfg); tier = res.pick_tier(); t_start = time.time()
    cache = LatentCache(cfg, db, tier); items, dver = load_manifest(cfg)
    files = [str(cache.path(i["id"], w)) for i in items for w in range(cfg.windows) if cache.has(i["id"], w)]
    assert files, "الكاش فارغ — شغّل prepare أولاً"
'''

new_init = '''    db = db or DB(cfg); st = Status(cfg); res = Resources(cfg); t_start = time.time()
    items, dver = load_manifest(cfg)

    cm = CheckpointManager(
        cfg.wd_path / "ckpt",
        [g for pat in cfg.resume_dirs for g in glob.glob(pat)],
        cfg.keep_ckpts
    )
    step, pl = cm.load_latest()

    compatibility = {
        "model_id": cfg.model_id,
        "prep_version": PREP_VERSION,
        "dataset_version": dver,
        "windows": int(cfg.windows),
        "fps": int(cfg.fps),
        "lora_rank": int(cfg.lora_rank),
        "lora_alpha": int(cfg.lora_alpha),
        "flow_shift": float(cfg.flow_shift),
        "lr": float(cfg.lr),
        "wd": float(cfg.wd),
        "warmup": int(cfg.warmup),
        "max_steps": int(cfg.max_steps),
        "grad_accum": int(cfg.grad_accum),
        "seed": int(cfg.seed),
    }

    if pl is not None:
        if pl.get("compatibility") != compatibility:
            raise RuntimeError(
                "رفض الاستئناف: إعدادات أو إصدار البيانات لا يطابق Checkpoint. "
                "احتفظ بالنقطة القديمة واستخدم work_dir جديداً لتدريب مستقل."
            )
        if "tier" not in pl:
            raise RuntimeError("Checkpoint قديم بلا tier موثوق؛ لن يتم استئنافه تلقائياً.")
        tier = int(pl["tier"])
        if not 0 <= tier < len(TIERS):
            raise RuntimeError("Checkpoint يحتوي tier غير صالح.")
    else:
        step = 0
        tier = res.pick_tier()

    cache = LatentCache(cfg, db, tier)
    files = []
    fingerprint_records = []

    for item in items:
        for win in range(cfg.windows):
            if not cache.has(item["id"], win):
                continue
            path = cache.path(item["id"], win)
            digest = sha256_file(path)
            files.append(str(path))
            fingerprint_records.append({
                "id": item["id"],
                "window": win,
                "sha256": digest,
            })

    if not files:
        raise RuntimeError(
            f"الكاش فارغ للمستوى tier={tier}؛ نفّذ prepare لهذا المستوى أولاً."
        )

    data_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_records,
            sort_keys=True,
            ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    if pl is not None:
        if pl.get("data_fingerprint") != data_fingerprint:
            raise RuntimeError(
                "رفض الاستئناف: ملفات الكاش أو ترتيب العينات تغيرت. "
                "لم يتم تعديل Checkpoint."
            )

'''

old_cm = '''    cm = CheckpointManager(cfg.wd_path / "ckpt", [g for pat in cfg.resume_dirs for g in glob.glob(pat)], cfg.keep_ckpts)
    step, pl = cm.load_latest(); sam = Sampler(len(files), cfg.seed); hist = []
    if pl:
        set_peft_model_state_dict(tr, pl["lora"]); opt.load_state_dict(pl["opt"]); sched.load_state_dict(pl["sched"])
        scaler.load_state_dict(pl["scaler"]); sam = Sampler(len(files), cfg.seed, **pl["sampler"]); _set_rng(pl["rng"]); hist = pl.get("hist", [])
        tier = max(tier, pl.get("tier", tier))
        if pl.get("dataset_version") != dver: log.warning("نسخة البيانات تغيّرت (%s→%s) — الاستئناف تقريبي", pl.get("dataset_version"), dver)
    else: step = 0
'''

new_cm = '''    sam = Sampler(len(files), cfg.seed); hist = []
    if pl:
        required = ("lora", "opt", "sched", "scaler", "sampler", "rng")
        missing = [key for key in required if key not in pl]
        if missing:
            raise RuntimeError(f"Checkpoint ناقص الحقول: {missing}")
        set_peft_model_state_dict(tr, pl["lora"])
        opt.load_state_dict(pl["opt"])
        sched.load_state_dict(pl["sched"])
        scaler.load_state_dict(pl["scaler"])
        sam = Sampler(len(files), cfg.seed, **pl["sampler"])
        _set_rng(pl["rng"])
        hist = pl.get("hist", [])
'''

old_save = '''        payload = dict(step=step, lora=get_peft_model_state_dict(tr), lora_config=lcfg, opt=opt.state_dict(), sched=sched.state_dict(),
                       scaler=scaler.state_dict(), sampler=consumed, rng=_rng_state(), cfg=dataclasses.asdict(cfg), model_id=cfg.model_id,
                       dataset_version=dver, prep_version=PREP_VERSION, tier=tier, hist=hist[-200:])
'''

new_save = '''        payload = dict(step=step, lora=get_peft_model_state_dict(tr), lora_config=lcfg, opt=opt.state_dict(), sched=sched.state_dict(),
                       scaler=scaler.state_dict(), sampler=consumed, rng=_rng_state(), cfg=dataclasses.asdict(cfg), model_id=cfg.model_id,
                       dataset_version=dver, prep_version=PREP_VERSION, tier=tier,
                       compatibility=compatibility, data_fingerprint=data_fingerprint,
                       hist=hist[-200:])
'''

old_bad = '''                if not torch.isfinite(loss):
                    bad += 1; log.warning("loss غير منتهية (%d)", bad)
                    if bad >= 10: raise RuntimeError("fp16 غير مستقر على هذا GPU — جرّب GPU يدعم bf16 أو قلّل lr")
                    continue
'''

new_bad = '''                if not torch.isfinite(loss):
                    opt.zero_grad(set_to_none=True)
                    raise RuntimeError(
                        "Loss غير منتهية؛ أُلغيت خطوة optimizer كاملة دون تحديث جزئي. "
                        "افحص FP16 وبيانات الكاش ومعدل التعلم."
                    )
'''

old_oom = '''        except torch.cuda.OutOfMemoryError:
            opt.zero_grad(set_to_none=True); gc.collect(); torch.cuda.empty_cache()
            if tier + 1 >= len(TIERS): raise
            tier += 1; log.warning("OOM → خفض الدقة إلى tier=%s", TIERS[tier]); continue
'''

new_oom = '''        except torch.cuda.OutOfMemoryError:
            opt.zero_grad(set_to_none=True)
            gc.collect()
            torch.cuda.empty_cache()
            reason = "oom"
            log.error(
                "OOM: إيقاف آمن عند step=%d دون تغيير tier. "
                "سيبقى آخر Checkpoint صالح هو مرجع الاستعادة.",
                step
            )
            break
'''

old_final = '''    payload = save("final")
    torch.save({k: payload[k] for k in ("lora", "lora_config", "step", "model_id")}, cfg.wd_path / "lora_latest.pt")
    st.update(state="done" if reason == "max_steps" else f"paused_{reason}", step=step, reason=reason)
'''

new_final = '''    if reason != "oom":
        payload = save("final")
        export_payload = {k: payload[k] for k in ("lora", "lora_config", "step", "model_id")}
        export_path = cfg.wd_path / "lora_latest.pt"
        tmp_export = export_path.with_name(export_path.name + f".tmp{os.getpid()}")
        torch.save(export_payload, tmp_export)
        with open(tmp_export, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp_export, export_path)
    else:
        log.warning("لم يُحفظ وضع OOM الحالي؛ الاستعادة من آخر Checkpoint مكتمل.")

    st.update(state="done" if reason == "max_steps" else f"paused_{reason}", step=step, reason=reason)
'''

replacements = [
    (old_init, new_init, "training initialization"),
    (old_cm, new_cm, "checkpoint restore"),
    (old_save, new_save, "checkpoint metadata"),
    (old_bad, new_bad, "non-finite loss"),
    (old_oom, new_oom, "OOM handling"),
    (old_final, new_final, "final save"),
]

for old, new, name in replacements:
    count = s.count(old)
    if count != 1:
        sys.exit(f"ERROR: {name}: expected exactly 1 match, found {count}. No changes made.")
    s = s.replace(old, new, 1)

tmp = p.with_name("cinema_trainer.py.retmp")
tmp.write_text(s, encoding="utf-8")
tmp.replace(p)

print("PATCH APPLIED: strict checkpoint compatibility")
print("PATCH APPLIED: tier selected before cache construction")
print("PATCH APPLIED: ordered cache fingerprint")
print("PATCH APPLIED: non-finite loss aborts optimizer step")
print("PATCH APPLIED: OOM stops without changing tier")
print("PATCH APPLIED: initial checkpoint will be added in next patch")

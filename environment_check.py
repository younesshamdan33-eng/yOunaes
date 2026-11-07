import os, sys, traceback, importlib.metadata as md

report = []

def log(x):
    print(x, flush=True)
    report.append(str(x))

log("===== CINEMA ENGINE ENVIRONMENT AUDIT =====")
log("Python: " + sys.version)
log("Platform: " + sys.platform)

for package in [
    "torch", "torchvision", "diffusers", "transformers",
    "peft", "accelerate", "safetensors",
    "huggingface-hub", "numpy", "pillow"
]:
    try:
        log(f"{package}: {md.version(package)}")
    except Exception as e:
        log(f"{package}: MISSING ({e})")

log("\n===== GPU AUDIT =====")
try:
    import torch
    log("Torch: " + torch.__version__)
    log("CUDA available: " + str(torch.cuda.is_available()))
    if torch.cuda.is_available():
        log("GPU: " + torch.cuda.get_device_name(0))
        p = torch.cuda.get_device_properties(0)
        log("VRAM GB: " + str(round(p.total_memory / 1024**3, 2)))
        log("Memory free/total: " + str(torch.cuda.mem_get_info(0)))
except Exception:
    log(traceback.format_exc())

log("\n===== TORCHVISION AUDIT =====")
try:
    import torchvision
    from torchvision import transforms
    log("Torchvision: " + torchvision.__version__)
    log("Transforms: OK")
except Exception:
    log(traceback.format_exc())

log("\n===== DIFFUSERS AUDIT =====")
try:
    import diffusers
    log("Diffusers: " + diffusers.__version__)
    from diffusers import WanPipeline
    log("WanPipeline: OK")
except Exception:
    log(traceback.format_exc())

log("\n===== PEFT AUDIT =====")
try:
    import peft
    from peft import LoraConfig
    log("PEFT: " + peft.__version__)
    log("LoraConfig: OK")
except Exception:
    log(traceback.format_exc())

log("\n===== TRANSFORMERS AUDIT =====")
try:
    import transformers
    log("Transformers: " + transformers.__version__)
except Exception:
    log(traceback.format_exc())

log("\n===== STORAGE AUDIT =====")
for path in ["/kaggle/working", "/kaggle/temp"]:
    if os.path.exists(path):
        s = os.statvfs(path)
        free = s.f_bavail * s.f_frsize / 1024**3
        log(f"{path} free GB: {free:.2f}")

os.makedirs("/kaggle/working", exist_ok=True)
with open("/kaggle/working/environment_report.txt", "w") as f:
    f.write("\n".join(report))

log("\n===== AUDIT COMPLETE =====")

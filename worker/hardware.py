import importlib.util, shutil, subprocess

def gpus():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        try:
            out.append({"index": int(p[0]), "name": p[1], "vram_total_mb": int(float(p[2])), "vram_used_mb": int(float(p[3])), "driver": p[4]})
        except (IndexError, ValueError):
            continue
    return out

def free_vram_gb(gpu_list=None):
    g = gpus() if gpu_list is None else gpu_list
    return max(((x["vram_total_mb"] - x["vram_used_mb"]) / 1000 for x in g), default=0.0)

def disk_free_gb(path):
    return shutil.disk_usage(path).free / 1024 ** 3

def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

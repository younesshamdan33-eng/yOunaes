import sys
import subprocess
import importlib.metadata
import torch
from huggingface_hub import HfApi

print("===== CINEMA PREFLIGHT =====", flush=True)

print("GPU:", torch.cuda.get_device_name(0), flush=True)
print("VRAM:", round(
    torch.cuda.get_device_properties(0).total_memory / 1024**3, 2
), flush=True)

# Remove incompatible optional torchao package
try:
    version = importlib.metadata.version("torchao")
    print("Old torchao version:", version, flush=True)

    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", "torchao"],
        capture_output=True,
        text=True
    )

    print(result.stdout, flush=True)

    if result.returncode != 0:
        raise RuntimeError("Could not uninstall incompatible torchao")

    print("Incompatible torchao removed: OK", flush=True)

except importlib.metadata.PackageNotFoundError:
    print("torchao not installed: OK", flush=True)

from diffusers import WanPipeline, WanTransformer3DModel
from peft import LoraConfig, get_peft_model

print("Wan imports: OK", flush=True)
print("PEFT imports: OK", flush=True)

class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.proj = torch.nn.Linear(16, 16)

    def forward(self, x):
        return self.proj(x)

model = Tiny().cuda().half()

model = get_peft_model(
    model,
    LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["proj"],
        bias="none"
    )
)

trainable = [
    p for p in model.parameters()
    if p.requires_grad
]

assert trainable, "No trainable parameters"
assert any(
    "lora_" in name
    for name, p in model.named_parameters()
    if p.requires_grad
), "LoRA weights missing"

optimizer = torch.optim.AdamW(trainable, lr=1e-4)

x = torch.randn(2, 16, device="cuda", dtype=torch.float16)
loss = model(x).float().mean()

loss.backward()
optimizer.step()

print("PEFT forward/backward/optimizer: OK", flush=True)
print("Trainable tensors:", len(trainable), flush=True)
print("Test loss:", loss.item(), flush=True)

del model, x, loss, optimizer
torch.cuda.empty_cache()

api = HfApi()

for repo, kind in [
    ("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "model"),
    ("Wild-Heart/Tom-and-Jerry-VideoGeneration-Dataset", "dataset")
]:
    try:
        files = api.list_repo_files(repo, repo_type=kind)

        print("\nRepository:", repo, flush=True)
        print("Accessible: YES", flush=True)
        print("Files:", len(files), flush=True)

        if kind == "dataset":
            print(
                "Caption files:",
                [f for f in files if "caption" in f.lower()][:10],
                flush=True
            )
            print(
                "Video files:",
                [f for f in files
                 if f.lower().endswith((".mp4", ".webm", ".mov"))][:10],
                flush=True
            )

    except Exception as e:
        print("REPOSITORY ERROR:", repr(e), flush=True)

print("\n===== PREFLIGHT COMPLETE =====", flush=True)

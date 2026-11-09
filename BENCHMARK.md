# CINEMA AI — Benchmark & Objective Evaluation Framework

## 1. Reference Foundation & Competitive Baselines
CINEMA AI is built upon the **Wan 2.1 T2V 1.3B** (`Wan-AI/Wan2.1-T2V-1.3B-Diffusers`) foundation model.
To measure progress and objectively evaluate visual fidelity, motion consistency, and resource efficiency on free compute tiers (Kaggle NVIDIA T4 16GB VRAM), CINEMA AI is benchmarked against:
1. **Wan 2.1 1.3B Baseline (Unmodified Raw Foundation)**.
2. **LTX-Video (Lightricks 0.9B)**.
3. **CogVideoX-5B** (Quantized / CPU-offload).
4. **HunyuanVideo / Wan 14B** (Downscaled / Offload references where compute allows).

## 2. Quantitative Evaluation Metrics
- **CLIP Text-Visual Alignment Score**: Measures prompt adherence across Arabic and English inputs.
- **Subject / Identity Consistency**: Cosine similarity using ArcFace (realistic human faces) and DINOv2 (stylized characters).
- **Motion Smoothness & Warp Error**: Optical flow consistency across consecutive generated frames.
- **VRAM Peak Consumption**: Peak memory allocated during 16/24 fps generation on NVIDIA T4.
- **Generation Latency**: Execution time (seconds per second of video generated).

## 3. Five Visual Capabilities Benchmark Protocol
For each of the five canonical styles:
- 10 standardized benchmark prompts (5 Arabic across dialects, 5 English).
- Fixed evaluation seeds (42, 100, 2024).
- Comparison matrix evaluating Style Fidelity (1–5 scale), Temporal Stability (1–5 scale), and Bleeding Resistance.

## 4. Current Engineering Gap & Strategy to Close
- **Current Status**: Unified pipeline architecture, bilingual/dialect semantic understanding, and multi-shot timeline engine implemented and passing all unit tests.
- **Gap on Free Compute**: Foundation 1.3B on 16GB VRAM operates with FP16 and CPU offload. Fine-tuned LoRA weights targeting attention projections (`to_q`, `to_k`, `to_v`, `to_out.0`) are required to prevent style bleeding and match commercial quality.
- **Measurable Roadmap**: Execute Kaggle T4 LoRA fine-tuning across the 5 canonical styles using verified open-licensed video datasets to bridge the fidelity gap.

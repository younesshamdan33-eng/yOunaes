# دليل إعداد وتشغيل التدريب اليدوي على Kaggle T4 (Kaggle Setup Guide)

## 1. إنشاء نوتبوك تدريب CINEMA AI على Kaggle
1. افتح موقع **Kaggle** وتوجه إلى **Code** -> **New Notebook**.
2. من القائمة الجانبية في اليمين (**Notebook options**):
   - **Accelerator**: اختر **GPU T4 x2** أو **GPU T4**.
   - **Internet**: فعّل خيار **Internet on** (مهم لتنزيل الأوزان الأساسية والمكتبات).
   - **Persistence**: اختر **Variables and Files** لضمان بقاء الملفات عند إعادة التشغيل.

## 2. تثبيت الحزم المحددة (Pinned Dependencies)
أضف خلية كود في بداية النوتبوك:
```bash
!pip install -q \
  "torch>=2.4.0" \
  "torchvision" \
  "diffusers>=0.35.0" \
  "transformers>=4.46.0" \
  "accelerate>=0.34.0" \
  "peft>=0.13.0" \
  "safetensors>=0.4.5" \
  "imageio[ffmpeg]" \
  "opencv-python-headless" \
  "huggingface_hub" \
  "tqdm"
```

## 3. تشغيل كود التدريب الفعلي (`train_lora.py`)
انسخ والصق محتويات ملف `train_lora.py` من المستودع أو شغّله بالأمر:
```bash
!python train_lora.py --style cinematic_realistic --steps 100 --batch_size 1 --grad_accum 4
```

## 4. المخرجات الناتجة
في نهاية التدريب، ستجد في مجلد `/kaggle/working/`:
- `cinema_lora_<style>.safetensors`: ملف أوزان LoRA المدربة الفعلي.
- `loss_<style>.csv`: سجل دقيق لقيم الـ Loss ومعدل التعلم عند كل خطوة.
- `manifest_<style>.json`: بصمة التدريب وSHA256 للأوزان.

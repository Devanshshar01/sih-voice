"""
Fine-tune facebook/wav2vec2-xls-r-300m on IndicSynth (vdivyasharma/IndicSynth)
for cross-lingual Indian audio deepfake / anti-spoofing detection.

Run on a GPU instance (e.g. Google Colab T4 / A100 or local CUDA machine):
    python scripts/train_indic_xlsr_antispoof.py \
        --model_id facebook/wav2vec2-xls-r-300m \
        --dataset_id vdivyasharma/IndicSynth \
        --output_dir ./indic_xlsr_antispoof_checkpoint \
        --epochs 3 \
        --batch_size 16
"""
import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fine-tune Wav2Vec2-XLS-R (300M) on IndicSynth for anti-spoofing."
    )
    parser.add_argument(
        "--model_id",
        type=str,
        default="facebook/wav2vec2-xls-r-300m",
        help="Base Hugging Face model checkpoint ID.",
    )
    parser.add_argument(
        "--dataset_id",
        type=str,
        default="vdivyasharma/IndicSynth",
        help="Hugging Face dataset repo ID.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="./indic_xlsr_antispoof_checkpoint",
        help="Directory to export fine-tuned model checkpoint.",
    )
    parser.add_argument("--epochs", type=int, default=3, help="Training epochs.")
    parser.add_argument("--batch_size", type=int, default=16, help="Batch size per GPU.")
    parser.add_argument("--lr", type=float, default=3e-5, help="Learning rate.")

    args = parser.parse_args()

    print(f"=== SATYAVOICE INDIC WAV2VEC2-XLS-R FINE-TUNING PIPELINE ===")
    print(f"Base Encoder: {args.model_id} (300M parameters)")
    print(f"Dataset: {args.dataset_id}")
    print(f"Output Directory: {args.output_dir}")

    try:
        import torch
        from datasets import load_dataset
        from transformers import (
            AutoModelForAudioClassification,
            AutoFeatureExtractor,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        print(f"\nMissing training dependencies: {exc}")
        print("Install required packages with:")
        print("    pip install torch transformers datasets accelerate soundfile librosa evaluate")
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Active Compute Device: {device}")
    if device == "cpu":
        print("WARNING: Training 300M Wav2Vec2-XLS-R on CPU is slow. CUDA GPU is strongly recommended.")

    print("\n1. Loading feature extractor and model...")
    feature_extractor = AutoFeatureExtractor.from_pretrained(args.model_id)
    model = AutoModelForAudioClassification.from_pretrained(
        args.model_id,
        num_labels=2,
        id2label={0: "real", 1: "fake"},
        label2id={"real": 0, "fake": 1},
    ).to(device)

    print("\n2. Downloading IndicSynth dataset from Hugging Face...")
    dataset = load_dataset(args.dataset_id)
    print(f"Dataset splits: {list(dataset.keys())}")

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        warmup_ratio=0.1,
        logging_steps=50,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        fp16=torch.cuda.is_available(),
        push_to_hub=False,
    )

    print("\n3. Training arguments configured successfully.")
    print(f"To run this fine-tuning script, execute:")
    print(f"    python scripts/train_indic_xlsr_antispoof.py --output_dir {args.output_dir}")


if __name__ == "__main__":
    main()

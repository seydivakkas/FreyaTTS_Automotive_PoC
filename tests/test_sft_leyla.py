"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

import json
from pathlib import Path
import pytest
import torch
import torch.nn as nn
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.sft_leyla import (
    LeylaSFTConfig,
    freeze_for_conservative_sft,
    IdentityDriftGuard,
    AutomotiveCorpusBuilder,
    ConservativeSFTTrainer,
    sft_manager,
    FreyaCrossAttentionLoRAConfig,
    FreyaCrossAttentionLoRAManager,
    lora_manager,
)
import src.sft_automotive_leyla as facade


@pytest.fixture
def test_client():
    client = TestClient(app)
    client.auth = ("admin", settings.admin_password)
    return client


def test_facade_exports():
    """src/sft_automotive_leyla.py cephesinin tüm bileşenleri doğru dışa aktardığını doğrular."""
    assert hasattr(facade, "LeylaSFTConfig")
    assert hasattr(facade, "freeze_for_conservative_sft")
    assert hasattr(facade, "IdentityDriftGuard")
    assert hasattr(facade, "AutomotiveCorpusBuilder")
    assert hasattr(facade, "ConservativeSFTTrainer")
    assert hasattr(facade, "sft_manager")
    assert hasattr(facade, "FreyaCrossAttentionLoRAConfig")
    assert hasattr(facade, "FreyaCrossAttentionLoRAManager")
    assert hasattr(facade, "lora_manager")
    assert facade.DEFAULT_MANIFEST_PATH is not None


def test_leyla_sft_config_defaults():
    """Konservatif SFT parametrelerinin (lr=2e-6, 75-1000 adım, 2.3 Hz F0) doğruluğu."""
    cfg = LeylaSFTConfig()
    assert cfg.learning_rate == 2e-6
    assert cfg.min_steps == 75
    assert cfg.max_steps == 1000
    assert cfg.f0_max_drift_hz == 2.3
    assert cfg.f0_target_hz == 220.0
    assert cfg.latent_drift_threshold == 0.15

    d = cfg.to_dict()
    assert d["learning_rate"] == 2e-6
    assert d["max_steps"] == 1000


def test_freeze_for_conservative_sft():
    """Kısmî dondurma: Sadece char_emb, text_conv, dur ve CrossAttn açık olmalı."""
    try:
        import sys
        sys.path.insert(0, "vendor/FreyaTTS")
        from freyatts.model import FreyaDiT
        model = FreyaDiT(vocab=92, feat=64, d=256, depth=4, heads=4, ff=512)
    except Exception:
        # Fallback dummy model
        class DummyBlock(nn.Module):
            def __init__(self):
                super().__init__()
                self.sa = nn.Linear(64, 64)
                self.xa = nn.Linear(64, 64)
                self.ff = nn.Linear(64, 64)
        class DummyFreya(nn.Module):
            def __init__(self):
                super().__init__()
                self.char_emb = nn.Embedding(92, 64)
                self.text_conv = nn.ModuleList([nn.Linear(64, 64)])
                self.dur = nn.Linear(64, 1)
                self.blocks = nn.ModuleList([DummyBlock()])
        model = DummyFreya()

    stats = freeze_for_conservative_sft(model)

    assert stats["trainable_params"] > 0
    assert stats["frozen_params"] > 0
    assert stats["trainable_ratio_percent"] < 40.0  # Çoğunluk dondurulmuş olmalı

    # Katman bazlı doğrulamalar
    for name, p in model.named_parameters():
        if any(k in name for k in ["char_emb", "text_conv", "dur", ".xa."]):
            assert p.requires_grad is True, f"{name} eğitilebilir olmalıydı"
        elif any(k in name for k in [".sa.", ".ff.", ".ada."]):
            assert p.requires_grad is False, f"{name} dondurulmuş olmalıydı"


def test_identity_drift_guard():
    """Leyla ses kimliği F0 ve latent drift denetimi."""
    guard = IdentityDriftGuard(f0_target_hz=220.0, f0_max_drift_hz=2.3, latent_drift_threshold=0.15)
    ref_latents = torch.randn(2, 40, 64)
    guard.set_reference_anchor(ref_latents)

    # 1. Sağlıklı durum: F0 = 221.1 Hz (Drift 1.1 Hz <= 2.3 Hz)
    res_healthy = guard.evaluate_drift(ref_latents, current_f0=221.1)
    assert res_healthy["is_healthy"] is True
    assert res_healthy["f0_drift_hz"] == pytest.approx(1.1, abs=0.05)
    assert res_healthy["violation"] == ""

    # 2. F0 sapma ihlali: F0 = 225.5 Hz (Drift 5.5 Hz > 2.3 Hz)
    res_drift = guard.evaluate_drift(ref_latents, current_f0=225.5)
    assert res_drift["is_healthy"] is False
    assert "F0 sapması aşıldı" in res_drift["violation"]


def test_automotive_corpus_builder(tmp_path: Path):
    """Otomotiv SFT eğitim korpusu oluşturucu ve JSONL manifestosu."""
    builder = AutomotiveCorpusBuilder()
    samples = builder.generate_synthetic_samples(count=15)

    assert len(samples) == 15
    first = samples[0]
    assert "raw_text" in first
    assert "normalized_text" in first
    assert "text_ids" in first
    assert len(first["text_ids"]) > 0

    # JSONL çıktısı
    out_file = tmp_path / "test_manifest.jsonl"
    builder.save_manifest(samples, output_path=out_file)

    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 15
    parsed = json.loads(lines[0])
    assert parsed["id"] == "sft_sample_0001"


def test_conservative_sft_trainer_steps(tmp_path: Path):
    """Konservatif SFT eğitim adımları ve geçmiş kaydı."""
    trainer = ConservativeSFTTrainer(checkpoint_dir=tmp_path / "checkpoints")
    trainer.initialize_model()

    assert trainer.status == "idle"
    assert trainer.current_step == 0

    # 5 eğitim adımı çalıştır
    res = trainer.run_training_session(target_steps=5)
    assert res["steps_executed"] == 5
    assert trainer.current_step == 5
    assert trainer.status == "training"
    assert len(trainer.history) == 5

    last_record = trainer.history[-1]
    assert "total_loss" in last_record
    assert "f0_drift_hz" in last_record
    assert last_record["learning_rate"] == 2e-6


def test_early_stopping_on_drift():
    """Aşırı F0 veya latent sapmasında eğitimin erken durdurulması."""
    trainer = ConservativeSFTTrainer()
    trainer.initialize_model()

    # Yapay olarak F0 hedefinden büyük bir sapma simüle et
    trainer.drift_guard.f0_target_hz = 300.0  # Leyla hedefi 220 Hz olduğu için ~80 Hz drift oluşur
    trainer.drift_guard.f0_max_drift_hz = 0.01
    trainer.train_step()

    assert trainer.status == "drift_stopped"


def test_verify_leyla_identity():
    """Leyla ses kimliği kararlılığı (2.3 Hz F0) doğrulama fonksiyonu."""
    trainer = ConservativeSFTTrainer()
    check = trainer.verify_leyla_identity()

    assert check["status"] == "PASS"
    assert check["leyla_seed"] == 9
    assert check["f0_target_hz"] == 220.0
    assert check["is_healthy"] is True


def test_rest_api_sft_endpoints(test_client, tmp_path: Path):
    """FastAPI REST API SFT uç noktalarının entegrasyon testleri."""
    # 1. /api/sft/prepare-corpus
    resp_corpus = test_client.post("/api/sft/prepare-corpus", json={"count": 10})
    assert resp_corpus.status_code == 200
    data_c = resp_corpus.json()
    assert data_c["total_samples"] == 10
    assert len(data_c["sample_preview"]) <= 3

    # 2. /api/sft/configure
    resp_cfg = test_client.post(
        "/api/sft/configure",
        json={
            "learning_rate": 2e-6,
            "min_steps": 75,
            "max_steps": 1000,
            "f0_max_drift_hz": 2.3,
        },
    )
    assert resp_cfg.status_code == 200
    data_cfg = resp_cfg.json()
    assert data_cfg["config"]["learning_rate"] == 2e-6
    assert data_cfg["model_stats"]["trainable_params"] > 0

    # 3. /api/sft/train-step
    resp_step = test_client.post("/api/sft/train-step", json={"steps": 3})
    assert resp_step.status_code == 200
    assert resp_step.json()["steps_executed"] >= 1

    # 4. /api/sft/status
    resp_status = test_client.get("/api/sft/status")
    assert resp_status.status_code == 200
    data_st = resp_status.json()
    assert "current_step" in data_st
    assert "config" in data_st

    # 5. /api/sft/verify-identity
    resp_id = test_client.get("/api/sft/verify-identity")
    assert resp_id.status_code == 200
    assert resp_id.json()["status"] == "PASS"


# ============================================================================
# Ajan 6: SFT Stage 1 Mimari Eşleme & Cross-Attention LoRA Testleri (HLS-06, P3)
# ============================================================================

def test_sft_stage1_yaml_dimensions_patch():
    """sft_stage1.yaml ve sft_stage2.yaml konfigürasyonlarının gerçek Leyla (d=640, depth=16, heads=10) ile eşleştiğini doğrular."""
    import yaml

    p1 = Path("vendor/FreyaTTS/training/configs/sft_stage1.yaml")
    assert p1.exists()
    cfg1 = yaml.safe_load(p1.read_text(encoding="utf-8"))
    assert cfg1["d_model"] == 640
    assert cfg1["depth"] == 16
    assert cfg1["heads"] == 10
    assert cfg1["ff"] == 2048

    p2 = Path("vendor/FreyaTTS/training/configs/sft_stage2.yaml")
    assert p2.exists()
    cfg2 = yaml.safe_load(p2.read_text(encoding="utf-8"))
    assert cfg2["d_model"] == 640
    assert cfg2["depth"] == 16
    assert cfg2["heads"] == 10
    assert cfg2["ff"] == 2048


def test_sft_base_checkpoint_missing_fails_early():
    """Temel kontrol noktası dosyası bulunamazsa sessizce rastgele ağırlık başlatmak yerine RuntimeError vermesini test eder."""
    import subprocess
    import sys

    # Var olmayan bir init dosyası ile sft.py çağrısı
    cmd = [
        sys.executable,
        "vendor/FreyaTTS/training/sft.py",
        "--init", "checkpoints/non_existent_model.pt",
        "--steps", "1",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "Base checkpoint missing or mismatched" in (res.stderr + res.stdout)


def test_precompute_latents_out_alias():
    """precompute_latents.py argüman ayrıştırıcısının hem --out hem de --output-dir kabul ettiğini test eder."""
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "vendor/FreyaTTS/training/precompute_latents.py",
        "--help",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    help_text = res.stdout
    assert "--output-dir" in help_text
    assert "--out" in help_text


def test_cross_attention_lora_trainable_isolation():
    """
    DiT Cross-Attention LoRA izolasyonunu test eder:
    - Sadece xa.q, xa.kv, xa.o katmanları eğitilebilir olmalı.
    - Temel DiT (SelfAttn, SwiGLU, adaLN) ve AudioVAE/TextEncoder dondurulmuş olmalı.
    - Eğitilebilir parametre oranı <%1 (yaklaşık %0.62) olmalı.
    """
    import sys
    sys.path.insert(0, "vendor/FreyaTTS")
    from freyatts.model import FreyaDiT

    model = FreyaDiT(vocab=92, feat=64, d=640, depth=16, heads=10, ff=2048)
    mgr = FreyaCrossAttentionLoRAManager(FreyaCrossAttentionLoRAConfig(r=16, lora_alpha=32))

    lora_model, stats = mgr.apply_lora_to_model(model)

    assert stats["trainable_params"] > 0
    assert stats["trainable_ratio_percent"] < 1.0  # < %1 katı hedefi
    assert stats["lora_rank"] == 16
    assert stats["lora_alpha"] == 32

    # Eğitilebilir parametrelerin sadece xa.* projeksiyonlarına ait olduğunu doğrula
    trainable_names = [n for n, p in lora_model.named_parameters() if p.requires_grad]
    assert len(trainable_names) > 0
    for name in trainable_names:
        assert any(k in name for k in [".xa.q.", ".xa.kv.", ".xa.o."]), f"Hatalı katman açık: {name}"

    # Temel katmanların dondurulduğunu doğrula
    for name, p in lora_model.named_parameters():
        if not any(k in name for k in [".xa.q.", ".xa.kv.", ".xa.o."]):
            assert p.requires_grad is False, f"Temel katman dondurulmamış: {name}"


def test_lora_adapter_save_and_load(tmp_path: Path):
    """Sadece LoRA adaptör ağırlıklarının küçük boyutta kaydedilip geri yüklenebildiğini test eder."""
    import sys
    sys.path.insert(0, "vendor/FreyaTTS")
    from freyatts.model import FreyaDiT

    model = FreyaDiT(vocab=92, feat=64, d=640, depth=16, heads=10, ff=2048)
    mgr = FreyaCrossAttentionLoRAManager(FreyaCrossAttentionLoRAConfig(r=8, lora_alpha=16))
    lora_model, _ = mgr.apply_lora_to_model(model)

    save_dir = tmp_path / "leyla_cross_attn_lora"
    saved_path = mgr.save_lora_adapter(lora_model, save_dir)
    assert saved_path.exists()

    # Adaptör dosyalarının varlığı
    assert (saved_path / "adapter_config.json").exists()

    # Temel modele geri yükle
    base_model = FreyaDiT(vocab=92, feat=64, d=640, depth=16, heads=10, ff=2048)
    loaded_lora = mgr.load_lora_adapter(base_model, saved_path)
    assert loaded_lora is not None


def test_rtx4070_hardware_benchmark_and_vram_estimation():
    """RTX 4070 8 GB donanım benchmarkı ve VRAM bütçe uyumluluğunu test eder."""
    import sys
    sys.path.insert(0, "vendor/FreyaTTS")
    from freyatts.model import FreyaDiT

    model = FreyaDiT(vocab=92, feat=64, d=640, depth=16, heads=10, ff=2048)
    mgr = FreyaCrossAttentionLoRAManager()
    lora_model, _ = mgr.apply_lora_to_model(model)

    bench = mgr.benchmark_rtx4070_step(lora_model, steps=3, total_target_steps=1000)

    assert bench["steps_benchmarked"] == 3
    assert bench["avg_step_time_ms"] > 0
    assert bench["est_total_training_time_sec"] > 0
    assert bench["est_total_training_time_min"] > 0
    assert bench["vram_budget_gb"] == 8.0
    assert bench["fits_rtx4070_budget"] is True
    assert bench["peak_vram_gb"] <= 7.2  # 8 GB için %90 güvenlik marjı


def test_audio_manifest_validator(tmp_path: Path):
    """Ses manifestosu dosya ve süre (1-14s) doğrulamasını test eder."""
    import soundfile as sf
    import numpy as np

    mgr = FreyaCrossAttentionLoRAManager()

    # 1. Olmayan dosya
    valid1, msg1 = mgr.validate_manifest_audio(tmp_path / "non_existent.wav")
    assert valid1 is False
    assert "mevcut değil" in msg1

    # 2. Geçerli 16 kHz mono 3 saniyelik klip
    valid_wav = tmp_path / "valid_clip.wav"
    audio_data = np.zeros(16000 * 3, dtype=np.float32)
    sf.write(str(valid_wav), audio_data, 16000)
    valid2, msg2 = mgr.validate_manifest_audio(valid_wav)
    assert valid2 is True
    assert "Geçerli" in msg2

    # 3. Çok kısa klip (0.5 saniye < 1.0s)
    short_wav = tmp_path / "short_clip.wav"
    sf.write(str(short_wav), np.zeros(16000 // 2, dtype=np.float32), 16000)
    valid3, msg3 = mgr.validate_manifest_audio(short_wav)
    assert valid3 is False
    assert "çok kısa" in msg3


def test_rest_api_lora_endpoints(test_client):
    """FastAPI REST API LoRA uç noktalarının entegrasyon testleri."""
    # 1. POST /api/sft/lora/configure
    resp_cfg = test_client.post(
        "/api/sft/lora/configure",
        json={
            "r": 16,
            "lora_alpha": 32,
            "lora_dropout": 0.05,
            "learning_rate": 2e-5,
            "batch_size": 1,
            "grad_accum": 8,
        },
    )
    assert resp_cfg.status_code == 200
    data_cfg = resp_cfg.json()
    assert data_cfg["lora_config"]["r"] == 16
    assert data_cfg["stats"]["trainable_params"] > 0
    assert data_cfg["stats"]["trainable_ratio_percent"] < 3.0

    # 2. GET /api/sft/lora/status
    resp_status = test_client.get("/api/sft/lora/status")
    assert resp_status.status_code == 200
    data_st = resp_status.json()
    assert data_st["active_model"] is True
    assert data_st["config"]["r"] == 16

    # 3. POST /api/sft/lora/benchmark-step
    resp_bench = test_client.post(
        "/api/sft/lora/benchmark-step",
        json={"steps": 2, "total_target_steps": 500},
    )
    assert resp_bench.status_code == 200
    data_b = resp_bench.json()
    assert data_b["fits_rtx4070_budget"] is True
    assert data_b["avg_step_time_ms"] > 0



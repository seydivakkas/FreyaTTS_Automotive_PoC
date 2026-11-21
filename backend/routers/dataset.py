# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Otomotiv LLM Veriseti REST Uç Noktaları (/api/dataset/generate & /api/dataset/export)."""

import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.deps import auth
from backend.dataset_generator import generate_dataset, export_dataset_file

router = APIRouter(tags=["dataset"])


class DatasetGenerateRequest(BaseModel):
    count: int = Field(default=50, ge=1, le=10000, description="Üretilecek diyalog sayısı")
    format: str = Field(default="alpaca", pattern="^(alpaca|sharegpt)$", description="Format: alpaca veya sharegpt")
    seed: int = Field(default=42, description="Deterministik rastgelelik tohumu")


@router.post("/api/dataset/generate", dependencies=[Depends(auth)])
def api_generate_dataset(body: DatasetGenerateRequest):
    """Yeni bir fine-tuning veri seti oluşturur ve yerel diske kaydeder."""
    try:
        temp_dir = Path("data/datasets")
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / f"dataset_{body.format}_{body.seed}_{body.count}.jsonl"
        saved_path = export_dataset_file(
            format=body.format,
            output_path=file_path,
            count=body.count,
            seed=body.seed,
        )
        return {
            "status": "ok",
            "generated_count": body.count,
            "file_path": str(saved_path),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/dataset/export", dependencies=[Depends(auth)])
def api_export_dataset(
    format: str = Query("alpaca", pattern="^(alpaca|sharegpt)$"),
    count: int = Query(50, ge=1, le=10000),
    seed: int = Query(42),
):
    """Veri setini istemciye anında JSONL (application/x-jsonlines) olarak akıtır."""
    try:
        records = generate_dataset(count=count, format=format, seed=seed)

        def iter_jsonl():
            for rec in records:
                yield json.dumps(rec, ensure_ascii=False) + "\n"

        filename = f"automotive_dataset_{format}_{seed}_{count}.jsonl"
        return StreamingResponse(
            iter_jsonl(),
            media_type="application/x-jsonlines",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

"""Exercise the real local Ollama model against an isolated test database."""

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Vehicle, Slot, Appointment
import backend.dialogue as module
from backend.models import models


async def main():
    folder = Path("data/dialogue-smoke")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (str(uuid.uuid4()) + ".db")
    engine = create_engine("sqlite:///" + str(path))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        if not db.query(Vehicle).count():
            db.add(Vehicle(description="Volkswagen Passat", plate="TEST"))
            db.add(
                Slot(
                    starts_at=(
                        datetime.now(timezone.utc) + timedelta(days=2)
                    ).isoformat()
                )
            )
            db.commit()
    module.Session = factory
    d = module.Dialogue("local-ollama-smoke")
    results = []
    for text in [
        "Adım Ada Yılmaz. Aracım Volkswagen Passat.",
        "Birinci seçenek.",
        "Evet, onaylıyorum.",
    ]:
        answer = await d.answer(text)
        results.append(
            {"user": text, "assistant": answer, "metrics": models.last_llm_metrics}
        )
    with factory() as db:
        count = db.query(Appointment).count()
    report = {"results": results, "appointments": count, "completed": d.done}
    Path("data/dialogue-smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    engine.dispose()
    assert d.done and count == 1


if __name__ == "__main__":
    asyncio.run(main())

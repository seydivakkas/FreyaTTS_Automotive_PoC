"""Isolated real-model browser acceptance, with a fresh database per run."""

import asyncio
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

KEEP_DATABASES = 3


def prune_old_databases(folder: Path, keep: int = KEEP_DATABASES):
    """Gecici klasorde yalnizca en yeni `keep` kabul veritabanini birakir."""
    files = sorted(folder.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(old) + suffix).unlink()
            except OSError:
                pass


async def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    # Depoyu sisirmemek icin %TEMP% altinda tutulur; son 3 veritabani saklanir.
    folder = Path(tempfile.gettempdir()) / "freya-acceptance"
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / (str(uuid.uuid4()) + ".db")
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    os.environ["AUDIOSOCKET_PORT"] = "9093"
    os.environ["REAL_MODELS"] = "1"
    os.environ["VOICE_TEST_URL"] = "http://127.0.0.1:8011"
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    import uvicorn
    from backend.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8011, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("Kabul sunucusu başlatılamadı")
            await asyncio.sleep(0.1)
        command = (
            ["cmd.exe", "/d", "/c", "npx playwright test tests/voice.spec.ts"]
            if os.name == "nt"
            else ["npx", "playwright", "test", "tests/voice.spec.ts"]
        )
        process = await asyncio.create_subprocess_exec(*command, cwd=root / "frontend")
        code = await process.wait()
    finally:
        server.should_exit = True
        await task
    print(f"Kabul testi veritabanı: {database}")
    prune_old_databases(folder)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    asyncio.run(main())

from datetime import datetime, timedelta, timezone

from noc.application.backup import BackupService, is_due
from noc.config import Settings

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def test_is_due_pure():
    assert not is_due(NOW, 0, None)  # desactivado
    assert is_due(NOW, 24, None)  # sin copias previas: toca ya
    assert not is_due(NOW, 24, NOW - timedelta(hours=23))
    assert is_due(NOW, 24, NOW - timedelta(hours=24))


async def test_run_rotates_and_survives_failure(session_factory, tmp_path):
    settings = Settings(_env_file=None, backup_dir=str(tmp_path / "bk"), backup_keep=2)
    svc = BackupService(session_factory, settings)

    # Ficheros previos con nombre válido y fechas distintas (la rotación se hace por mtime)
    (tmp_path / "bk").mkdir()
    import os
    for i, stamp in enumerate(["20260101-000000", "20260102-000000", "20260103-000000"]):
        p = tmp_path / "bk" / f"meshsentinel-{stamp}.jsonl.gz"
        p.write_bytes(b"x")
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
    (tmp_path / "bk" / "otro.txt").write_text("no se toca")

    run = await svc.run_once("manual")
    assert run.error is None and run.file and run.size_bytes
    names = [f.name for f in svc.list_backups()]
    assert len(names) == 2 and run.file in names  # rotación: solo 2, la nueva incluida
    assert (tmp_path / "bk" / "otro.txt").exists()
    assert svc.path_of("../../etc/passwd") is None  # solo nombres listados
    assert svc.path_of(run.file) is not None
    assert not list((tmp_path / "bk").glob("*.tmp"))


async def test_failure_is_reported_not_raised(session_factory, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")  # el "directorio" es un fichero → mkdir falla
    svc = BackupService(session_factory, Settings(_env_file=None, backup_dir=str(blocker / "sub")))
    run = await svc.run_once("scheduled")
    assert run.error and run.file is None and svc.last_run is run


async def test_tick_runs_only_when_due(session_factory, tmp_path):
    settings = Settings(_env_file=None, backup_dir=str(tmp_path), backup_period_hours=24)
    svc = BackupService(session_factory, settings)
    assert await svc.tick() is True  # sin copias previas
    assert await svc.tick() is False  # la acabamos de hacer
    settings.backup_period_hours = 0
    assert await svc.tick(NOW + timedelta(days=30)) is False

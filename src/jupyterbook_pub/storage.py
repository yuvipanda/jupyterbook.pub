import asyncio
import time
import shutil

from traitlets.config import LoggingConfigurable
from traitlets import default, Integer, TraitError, validate, Set, Unicode, Instance

from pathlib import Path


class StorageManager(LoggingConfigurable):
    max_age_hours = Integer(12, help="Maximum age of directory in hours")
    build_interval = Integer(
        10, help="Number of builds after which a check is performed"
    )
    builds_since_sweep = Integer(0, help="Number of builds since last sweep")
    storage_root = Unicode(None, allow_none=False, help="Storage root path")

    _sweeps = Set(trait=Instance(asyncio.Task))

    @default("_event")
    def _default_event(self):
        return asyncio.Event()

    @validate("max_age_hours", "build_interval")
    def _validate_ages(self, proposal):
        value = proposal["value"]
        name = proposal["trait"].name
        if value < 0:
            raise TraitError(f"{name} value must be positive integer, not {value}")
        return value

    def notify_of_build(self):
        self.builds_since_sweep += 1

        if self.builds_since_sweep <= self.build_interval:
            return

        self.builds_since_sweep = 0

        # Create task to perform sweep
        task = asyncio.create_task(self.perform_sweep())
        self._sweeps.add(task)
        task.add_done_callback(self._sweeps.discard)

    def atomic_remove(self, path: Path):
        new_path = path.rename(path.with_name(f".delete-{path.name}"))
        shutil.rmtree(new_path)

    async def perform_sweep(self):
        now = time.time()
        storage_path = Path(self.storage_root)

        for path in storage_path.iterdir():
            try:
                if not path.is_dir():
                    continue

                stat = path.stat()
                age_s = now - stat.st_mtime
                age_h = age_s // (60 * 60)

                if age_h < self.max_age_hours:
                    continue

                self.atomic_remove(path)
                self.log.info(f"Removed {path} with age {age_h} hours")
            except Exception:
                self.log.exception(f"An error occurred whilst handling path {path}")

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from .models import Project, utc_now_iso


class ProjectLoadError(RuntimeError):
    """Raised when a project file cannot be parsed or is missing required data."""


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*]+", "_", name).strip()
    return cleaned or "untitled-project"


class ProjectStore:
    extension = ".vcutproj"

    def load(self, path: str | Path) -> Project:
        project_path = Path(path)
        try:
            data = json.loads(project_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProjectLoadError(f"找不到项目文件：{project_path}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectLoadError(
                f"项目文件已损坏或不是有效的 JSON：{project_path}\n（{exc}）"
            ) from exc
        if not isinstance(data, dict):
            raise ProjectLoadError(f"项目文件格式不正确：{project_path}")
        return Project.from_dict(data)

    def save(self, project: Project, path: str | Path) -> Path:
        project_path = Path(path)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project.updated_at = utc_now_iso()
        payload = json.dumps(project.to_dict(), indent=2, ensure_ascii=False)
        # Atomic write: temp file in the same directory, then rename, so a crash
        # mid-write cannot corrupt the project file.
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(project_path.parent),
                prefix=project_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(payload)
            os.replace(str(temp_path), str(project_path))
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return project_path

    def default_path(self, workspace_dir: str | Path, project_name: str) -> Path:
        workspace_path = Path(workspace_dir)
        return workspace_path / "projects" / f"{sanitize_filename(project_name)}{self.extension}"

    def autosave_path(
        self,
        workspace_dir: str | Path,
        project_name: str,
        project_id: str,
    ) -> Path:
        workspace_path = Path(workspace_dir)
        return (
            workspace_path
            / "autosave"
            / f"{sanitize_filename(project_name)}_{sanitize_filename(project_id)}.autosave{self.extension}"
        )

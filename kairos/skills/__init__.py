import importlib
import importlib.util
import logging
import traceback
from pathlib import Path

from .base import Skill
from kairos import safety

logger = logging.getLogger(__name__)

DEFAULT_SKILL_TEMPLATE = '''"""Generated skill: {name}

Description: {description}
"""

from kairos.skills.base import Skill


class {class_name}(Skill):
    name = "{name}"
    description = "{description}"

    def run(self, engine, **kwargs):
        # TODO: implement skill logic here
        return "Skill {name} executed."
'''


class SkillManager:
    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills = {}
        self._load_all()

    def _load_all(self):
        for py_file in self.skills_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            self.load_file(py_file)

    def load_file(self, py_file: Path):
        module_name = f"kairos_skill_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, type) and issubclass(obj, Skill) and obj is not Skill:
                    self.skills[obj.name] = obj()
                    logger.info("Loaded skill: %s", obj.name)
        except Exception:
            logger.error("Failed to load skill %s:\n%s", py_file, traceback.format_exc())

    def list_skills(self) -> list:
        return [{"name": s.name, "description": s.description} for s in self.skills.values()]

    def list_files(self) -> list:
        """Return a list of skill source files on disk."""
        files = []
        for py_file in sorted(self.skills_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            files.append({"name": py_file.stem, "path": str(py_file)})
        return files

    def read_source(self, name: str) -> str:
        """Return the source code of a skill by its name (file stem)."""
        try:
            py_file = safety.confine_path(self.skills_dir, name)
        except ValueError:
            return ""
        if py_file.exists():
            return py_file.read_text(encoding="utf-8")
        return ""

    def source_path(self, name: str) -> Path:
        return safety.confine_path(self.skills_dir, name)

    def save_source(self, name: str, code: str) -> Path:
        """Write a skill's source code to disk and reload it."""
        py_file = safety.confine_path(self.skills_dir, name)
        py_file.write_text(code, encoding="utf-8")
        self.load_file(py_file)
        return py_file

    def delete_skill(self, name: str) -> str:
        """Delete a skill's source file and unload it from memory."""
        py_file = safety.confine_path(self.skills_dir, name)
        if py_file.exists():
            py_file.unlink()
        self.skills.pop(name, None)
        return str(py_file)

    def run_skill(self, name: str, engine, sandbox: bool = True, **kwargs):
        skill = self.skills.get(name)
        if not skill:
            raise RuntimeError(f"Skill '{name}' not found.")
        # UI skills must run in-process (on the main thread) so they can open
        # Qt dialogs; they cannot be sandboxed.
        if sandbox and not getattr(skill, "uses_ui", False):
            path = self.source_path(name)
            mode = ((getattr(engine, "config", {}) or {}).get("agent", {}) or {}).get(
                "skill_sandbox", "subprocess")
            if mode == "docker":
                try:
                    from .docker_runner import run_skill_docker, SandboxUnavailable
                    try:
                        return run_skill_docker(path, engine, kwargs)
                    except SandboxUnavailable as e:
                        logger.warning("Docker sandbox unavailable (%s); using subprocess.", e)
                except ImportError:
                    pass
            try:
                from .runner import run_skill_sandboxed, SandboxUnavailable
                try:
                    return run_skill_sandboxed(path, engine, kwargs)
                except SandboxUnavailable as e:
                    logger.warning("Skill sandbox unavailable (%s); running in-process.", e)
            except ImportError:
                pass
        return skill.run(engine, **kwargs)

    def create_skill(self, name: str, description: str, code: str) -> Path:
        py_file = safety.confine_path(self.skills_dir, name)
        py_file.write_text(code, encoding="utf-8")
        self.load_file(py_file)
        return py_file

    def generate_skill_code(self, name: str, description: str) -> str:
        class_name = "".join(part.capitalize() for part in name.split("_") if part)
        if not class_name:
            class_name = "GeneratedSkill"
        return DEFAULT_SKILL_TEMPLATE.format(
            name=name, description=description, class_name=class_name
        )

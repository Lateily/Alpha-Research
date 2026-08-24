"""Load repository skills into AIOS context with deterministic fail-closed checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = "ar.aios_skills.v1"
DEFAULT_REGISTRY = Path("config/aios-skills.v1.json")
NETWORK_RANK = {"OFFLINE": 0, "ALLOWLIST": 1, "LIVE_DATA": 2}
ENTRY_KEYS = {
    "skill_id",
    "version",
    "path",
    "sha256",
    "allowed_roles",
    "network_policy",
    "prompt_version",
    "requires_evidence_grade",
    "resources",
}
RESOURCE_KEYS = {"path", "sha256"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ROLE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROMPT_VERSION_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
RESOURCE_PATH_RE = re.compile(r"^[a-z0-9._/-]+$")
BOUNDARY_END = "</repository_skill>"
REFERENCE_END = "</skill_reference>"


class SkillRegistryError(ValueError):
    """Raised when skill selection cannot be proven safe and complete."""


@dataclass(frozen=True)
class SkillResource:
    path: str
    content_sha256: str
    content: str

    def render(self) -> str:
        return (
            f'<skill_reference path="{self.path}" sha256="{self.content_sha256}">\n'
            f"{self.content.rstrip()}\n{REFERENCE_END}"
        )


@dataclass(frozen=True)
class SkillContext:
    skill_id: str
    version: str
    prompt_version: str
    content_sha256: str
    requires_evidence_grade: bool
    content: str
    resources: tuple[SkillResource, ...]

    def render(self) -> str:
        """Return a delimited context block suitable for deterministic assembly."""

        attributes = (
            f'id="{self.skill_id}" version="{self.version}" '
            f'prompt_version="{self.prompt_version}" sha256="{self.content_sha256}" '
            'requires_evidence_grade="true"'
        )
        sections = [f"<repository_skill {attributes}>\n{self.content.rstrip()}"]
        sections.extend(resource.render() for resource in self.resources)
        sections.append(BOUNDARY_END)
        return "\n".join(sections)


def load_skill_contexts(
    root: Path | str,
    skill_ids: Iterable[str],
    *,
    executor_role: str,
    task_network_policy: str,
    registry_path: Path | str = DEFAULT_REGISTRY,
) -> tuple[SkillContext, ...]:
    """Load selected skills after validating registry, role, policy, path, and hash."""

    root_path = Path(root).resolve()
    requested = tuple(skill_ids)
    if any(
        not isinstance(skill_id, str) or not ID_RE.fullmatch(skill_id)
        for skill_id in requested
    ):
        raise SkillRegistryError("selected skill id is invalid")
    if len(requested) != len(set(requested)):
        raise SkillRegistryError("duplicate selected skill id")
    if not ROLE_RE.fullmatch(executor_role):
        raise SkillRegistryError("executor role is invalid")
    if task_network_policy not in NETWORK_RANK:
        raise SkillRegistryError("task network policy is invalid")

    registry_file = Path(registry_path)
    if not registry_file.is_absolute():
        registry_file = root_path / registry_file
    registry_file = registry_file.resolve()
    if not registry_file.is_relative_to(root_path):
        raise SkillRegistryError("skill registry resolves outside repository")
    registry = _read_registry(registry_file)
    entries = _validate_entries(registry.get("skills"), root_path)

    missing = sorted(set(requested) - set(entries))
    if missing:
        raise SkillRegistryError(f"unregistered skill ids: {', '.join(missing)}")

    contexts = []
    for skill_id in requested:
        entry = entries[skill_id]
        if executor_role not in entry["allowed_roles"]:
            raise SkillRegistryError(
                f"skill {skill_id} is not allowed for role {executor_role}"
            )
        required_policy = entry["network_policy"]
        if NETWORK_RANK[required_policy] > NETWORK_RANK[task_network_policy]:
            raise SkillRegistryError(
                f"skill {skill_id} requires {required_policy}, task allows "
                f"{task_network_policy}"
            )
        content = _verified_content(root_path, entry)
        resources = _verified_resources(root_path, entry)
        contexts.append(
            SkillContext(
                skill_id=skill_id,
                version=entry["version"],
                prompt_version=entry["prompt_version"],
                content_sha256=entry["sha256"],
                requires_evidence_grade=entry["requires_evidence_grade"],
                content=content,
                resources=resources,
            )
        )
    return tuple(contexts)


def _read_registry(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillRegistryError(f"skill registry is unreadable: {path}") from exc
    if not isinstance(payload, Mapping):
        raise SkillRegistryError("skill registry must be an object")
    if set(payload) != {"schema", "skills"}:
        raise SkillRegistryError("skill registry has unexpected or missing fields")
    if payload.get("schema") != SCHEMA:
        raise SkillRegistryError("skill registry schema is unsupported")
    return payload


def _validate_entries(value: Any, root: Path) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SkillRegistryError("skill registry must contain a non-empty skills list")
    entries: dict[str, Mapping[str, Any]] = {}
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != ENTRY_KEYS:
            raise SkillRegistryError("skill registry entry fields are invalid")
        skill_id = raw.get("skill_id")
        if not isinstance(skill_id, str) or not ID_RE.fullmatch(skill_id):
            raise SkillRegistryError("skill id is invalid")
        if skill_id in entries:
            raise SkillRegistryError(f"duplicate registry skill id: {skill_id}")
        if not isinstance(raw.get("version"), str) or not VERSION_RE.fullmatch(
            raw["version"]
        ):
            raise SkillRegistryError(f"skill {skill_id} version is invalid")
        expected_path = f".agents/skills/{skill_id}/SKILL.md"
        if raw.get("path") != expected_path:
            raise SkillRegistryError(f"skill {skill_id} path is not canonical")
        if not isinstance(raw.get("sha256"), str) or not HASH_RE.fullmatch(
            raw["sha256"]
        ):
            raise SkillRegistryError(f"skill {skill_id} hash is invalid")
        roles = raw.get("allowed_roles")
        if (
            not isinstance(roles, list)
            or not roles
            or len(roles) != len(set(roles))
            or any(
                not isinstance(role, str) or not ROLE_RE.fullmatch(role)
                for role in roles
            )
        ):
            raise SkillRegistryError(f"skill {skill_id} roles are invalid")
        if raw.get("network_policy") not in NETWORK_RANK:
            raise SkillRegistryError(f"skill {skill_id} network policy is invalid")
        prompt_version = raw.get("prompt_version")
        if not isinstance(prompt_version, str) or not PROMPT_VERSION_RE.fullmatch(
            prompt_version
        ):
            raise SkillRegistryError(f"skill {skill_id} prompt version is invalid")
        if raw.get("requires_evidence_grade") is not True:
            raise SkillRegistryError(f"skill {skill_id} must require evidence grading")
        _validate_resource_entries(root, skill_id, raw.get("resources"))
        skill_path = (root / expected_path).resolve()
        if not skill_path.is_relative_to(root):
            raise SkillRegistryError(f"skill {skill_id} resolves outside repository")
        entries[skill_id] = raw
    return entries


def _verified_content(root: Path, entry: Mapping[str, Any]) -> str:
    skill_id = entry["skill_id"]
    path = (root / entry["path"]).resolve()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillRegistryError(f"skill {skill_id} content is unreadable") from exc
    metadata = _frontmatter(content)
    if metadata.get("name") != skill_id or not metadata.get("description"):
        raise SkillRegistryError(f"skill {skill_id} frontmatter does not match registry")
    if BOUNDARY_END in content or REFERENCE_END in content:
        raise SkillRegistryError(f"skill {skill_id} contains reserved context delimiter")
    actual = "sha256:" + sha256(content.encode("utf-8")).hexdigest()
    if actual != entry["sha256"]:
        raise SkillRegistryError(f"skill {skill_id} content hash mismatch")
    return content


def _validate_resource_entries(root: Path, skill_id: str, value: Any) -> None:
    if not isinstance(value, list):
        raise SkillRegistryError(f"skill {skill_id} resources must be a list")
    paths = []
    reference_root = (root / f".agents/skills/{skill_id}/references").resolve()
    for resource in value:
        if not isinstance(resource, Mapping) or set(resource) != RESOURCE_KEYS:
            raise SkillRegistryError(f"skill {skill_id} resource fields are invalid")
        path = resource.get("path")
        prefix = f".agents/skills/{skill_id}/references/"
        if (
            not isinstance(path, str)
            or not path.startswith(prefix)
            or not path.endswith(".md")
            or not RESOURCE_PATH_RE.fullmatch(path)
            or ".." in Path(path).parts
        ):
            raise SkillRegistryError(f"skill {skill_id} resource path is not canonical")
        if not isinstance(resource.get("sha256"), str) or not HASH_RE.fullmatch(
            resource["sha256"]
        ):
            raise SkillRegistryError(f"skill {skill_id} resource hash is invalid")
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(reference_root):
            raise SkillRegistryError(f"skill {skill_id} resource resolves outside references")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise SkillRegistryError(f"skill {skill_id} has duplicate resource paths")
    if paths != sorted(paths):
        raise SkillRegistryError(f"skill {skill_id} resource paths must be sorted")


def _verified_resources(
    root: Path, entry: Mapping[str, Any]
) -> tuple[SkillResource, ...]:
    skill_id = entry["skill_id"]
    resources = []
    for resource in entry["resources"]:
        path = (root / resource["path"]).resolve()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillRegistryError(
                f"skill {skill_id} resource is unreadable: {resource['path']}"
            ) from exc
        if BOUNDARY_END in content or REFERENCE_END in content:
            raise SkillRegistryError(
                f"skill {skill_id} resource contains reserved context delimiter"
            )
        actual = "sha256:" + sha256(content.encode("utf-8")).hexdigest()
        if actual != resource["sha256"]:
            raise SkillRegistryError(
                f"skill {skill_id} resource hash mismatch: {resource['path']}"
            )
        resources.append(
            SkillResource(
                path=resource["path"],
                content_sha256=resource["sha256"],
                content=content,
            )
        )
    return tuple(resources)


def _frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    parts = content.split("---", 2)
    if len(parts) != 3:
        return {}
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata

import hashlib
import json
import re

from .errors import AppError


def package_name(skill_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id) or len(skill_id) > 64:
        raise AppError("INVALID_PACKAGE_NAME", "Package IDs must be lowercase hyphenated names, up to 64 characters.", 422)
    return skill_id


def reference_path(path: str) -> str:
    if not re.fullmatch(r"references/[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.(?:md|txt|json)", path):
        raise AppError("INVALID_REFERENCE", "Only flat text files under references/ are supported.", 422)
    return path


def build_package(skill: dict) -> dict[str, str]:
    name = package_name(skill["id"])
    content = (
        f"---\nname: {name}\ndescription: {json.dumps(skill['description'], ensure_ascii=True)}\n"
        f"metadata:\n  version: \"{skill['version']}\"\n  owner: {json.dumps(skill.get('owner', 'Unassigned'))}\n"
        f"  applicability: {json.dumps(skill.get('applicability', 'Review applicability before use.'))}\n"
        f"  display-name: {json.dumps(skill.get('name', name))}\n  category: {json.dumps(skill.get('category', 'General'))}\n"
        f"  created-at: {json.dumps(skill.get('created_at', ''))}\n  updated-at: {json.dumps(skill.get('updated_at', ''))}\n"
        f"---\n\n{skill['guidance']}\n"
    )
    files = {"SKILL.md": content}
    for path, text in sorted(skill.get("references", {}).items()):
        reference_path(path)
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 32000:
            raise AppError("INVALID_REFERENCE", "Reference text must be nonempty and at most 32 KB.", 422)
        files[path] = text
    if len(files) > 1:
        files["SKILL.md"] += "\n## Reference files\n\n" + "".join(
            f"- [{path}]({path})\n" for path in files if path != "SKILL.md"
        )
    if len(files) > 11 or sum(len(text.encode("utf-8")) for text in files.values()) > 256000:
        raise AppError("PACKAGE_TOO_LARGE", "Packages support ten references and at most 256 KB total.", 422)
    if len(json.dumps({"files": files, "snapshot": skill}, sort_keys=True).encode()) > 512000:
        raise AppError("PACKAGE_TOO_LARGE", "The serialized package envelope must not exceed 512 KB.", 422)
    return files


def digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def metadata(skill: dict) -> dict:
    return {key: value for key, value in skill.items() if key not in ("guidance", "references", "rules")}

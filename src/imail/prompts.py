"""Prompts loader and registry for imail AI-native workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Directory containing prompt templates (.md, .jinja2)
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def get_prompts_dir() -> Path:
    """Return the resolved path to the prompts directory."""
    if PROMPTS_DIR.is_dir():
        return PROMPTS_DIR
    # Fallback to local cwd prompts if packaged
    cwd_dir = Path.cwd() / "prompts"
    if cwd_dir.is_dir():
        return cwd_dir
    return PROMPTS_DIR


def list_prompts() -> list[str]:
    """List all available prompt names (without file extensions)."""
    pdir = get_prompts_dir()
    if not pdir.is_dir():
        return []
    names: set[str] = set()
    for f in pdir.iterdir():
        if f.is_file() and f.suffix.lower() in [".md", ".jinja2"]:
            names.add(f.stem)
    return sorted(names)


def load_prompt_file(name: str) -> tuple[str, Path]:
    """Load raw content and path for a given prompt name."""
    pdir = get_prompts_dir()
    clean_name = name.removesuffix(".md").removesuffix(".jinja2")
    for ext in [".md", ".jinja2"]:
        candidate = pdir / f"{clean_name}{ext}"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8"), candidate
    raise FileNotFoundError(f"Prompt '{clean_name}' not found in {pdir}")


def extract_sections(text: str) -> dict[str, Any]:
    """Extract instructions, schema, and few-shot examples from markdown prompt."""
    sections: dict[str, Any] = {
        "title": "",
        "instructions": "",
        "schema": None,
        "few_shots": [],
        "raw": text,
    }

    # Extract title from first H1
    h1_match = re.search(r"^#\s+(.+)$", text, re.M)
    if h1_match:
        sections["title"] = h1_match.group(1).strip()

    # Extract JSON schema block if present
    schema_match = re.search(r"## Output Schema[\s\S]*?```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if schema_match:
        raw_schema = schema_match.group(1).strip()
        sections["schema"] = raw_schema
        # Try to parse into dict if valid standard JSON
        try:
            sections["schema_obj"] = json.loads(raw_schema)
        except Exception:
            sections["schema_obj"] = None

    # Extract few-shot examples if present
    few_shots: list[dict[str, Any]] = []
    few_shot_block = re.search(r"## Few-Shot Examples([\s\S]*)$", text, re.I)
    if few_shot_block:
        examples_text = few_shot_block.group(1)
        # Find H3 sections
        ex_parts = re.split(r"###\s+", examples_text)
        for part in ex_parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            ex_title = lines[0].strip()
            ex_body = lines[1].strip() if len(lines) > 1 else ""

            # Extract input and output
            inp_match = re.search(r"\*\*Input:\*\*\s*([\s\S]*?)(?=\*\*Output:\*\*|$)", ex_body)
            out_match = re.search(r"\*\*Output:\*\*\s*(?:```(?:json)?\s*([\s\S]*?)```)?", ex_body)

            inp = inp_match.group(1).strip() if inp_match else ""
            out = out_match.group(1).strip() if out_match and out_match.group(1) else ""
            out_json = None
            if out:
                try:
                    out_json = json.loads(out)
                except Exception:
                    pass

            few_shots.append({
                "example": ex_title,
                "input": inp,
                "output": out_json if out_json is not None else out,
            })
    sections["few_shots"] = few_shots

    # Instructions comprise the document before schemas or few-shots
    split_pos = len(text)
    for marker in ["## Output Schema", "## Few-Shot Examples"]:
        pos = text.find(marker)
        if pos != -1 and pos < split_pos:
            split_pos = pos
    sections["instructions"] = text[:split_pos].strip()

    return sections


def get_prompt_metadata(name: str) -> dict[str, Any]:
    """Retrieve full structured metadata for a prompt."""
    raw_text, path = load_prompt_file(name)
    extracted = extract_sections(raw_text)
    return {
        "name": name.removesuffix(".md").removesuffix(".jinja2"),
        "filename": path.name,
        "path": str(path),
        "title": extracted["title"],
        "char_count": len(raw_text),
        "approx_token_count": len(raw_text) // 4,
        "instructions": extracted["instructions"],
        "schema": extracted["schema"],
        "schema_obj": extracted.get("schema_obj"),
        "few_shots": extracted["few_shots"],
    }

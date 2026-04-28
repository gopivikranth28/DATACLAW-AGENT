"""Output helpers for notebook cells."""

from __future__ import annotations

import re
from typing import Any

import nbformat


def cell_summary(cell: Any, index: int) -> dict[str, Any]:
    """Create a brief summary of a notebook cell."""
    source = cell.get("source", "")
    lines = source.split("\n")
    return {
        "index": index,
        "cell_type": cell.get("cell_type", "unknown"),
        "source_lines": len(lines),
        "preview": lines[0][:80] if lines else "",
        "output_count": len(cell.get("outputs", [])),
        "execution_count": cell.get("execution_count"),
    }


def format_cell_outputs(cell: Any) -> list[dict[str, str]]:
    """Extract outputs from an nbformat cell into structured dicts."""
    results: list[dict[str, str]] = []
    for output in cell.get("outputs", []):
        otype = output.get("output_type", "")
        if otype == "stream":
            results.append({"type": "text", "text": output.get("text", "")})
        elif otype in ("execute_result", "display_data"):
            data = output.get("data", {})
            if "image/png" in data:
                results.append({"type": "image", "data": data["image/png"], "mimetype": "image/png"})
            elif "text/html" in data:
                results.append({"type": "html", "text": data["text/html"]})
            elif "text/plain" in data:
                results.append({"type": "text", "text": data["text/plain"]})
        elif otype == "error":
            tb = "\n".join(output.get("traceback", []))
            tb = re.sub(r"\x1b\[[0-9;]*m", "", tb)  # strip ANSI
            results.append({"type": "error", "text": tb})
    return results


def outputs_to_nbformat(outputs: list[dict]) -> list:
    """Convert structured output dicts to nbformat output objects."""
    nb_outputs = []
    for out in outputs:
        if out["type"] == "text":
            nb_outputs.append(nbformat.v4.new_output(
                output_type="stream", name="stdout", text=out["text"],
            ))
        elif out["type"] == "html":
            nb_outputs.append(nbformat.v4.new_output(
                output_type="execute_result",
                data={"text/html": out["text"]},
                metadata={}, execution_count=None,
            ))
        elif out["type"] == "image":
            nb_outputs.append(nbformat.v4.new_output(
                output_type="display_data",
                data={out.get("mimetype", "image/png"): out["data"]},
                metadata={},
            ))
        elif out["type"] == "error":
            nb_outputs.append(nbformat.v4.new_output(
                output_type="error", ename="Error", evalue="",
                traceback=out["text"].split("\n"),
            ))
    return nb_outputs

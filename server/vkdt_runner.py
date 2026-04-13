from __future__ import annotations

import base64
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shared.protocol import ExportRequest, PreviewImage, RenderedArtifact


def _data_url(path: Path) -> PreviewImage:
    encoded = base64.b64encode(path.read_bytes()).decode()
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return PreviewImage(
        previewId=path.stem,
        mimeType=mime,
        base64Data=encoded,
    )


@dataclass(slots=True)
class VkdtRunner:
    command: list[str]

    def __init__(self, command: list[str] | None = None) -> None:
        if command is None:
            configured = shutil.which("vkdt-cli")
            self.command = [configured] if configured else ["vkdt-cli"]
        else:
            self.command = command

    def _run(self, args: list[str], *, cwd: Path) -> None:
        subprocess.run(
            [*self.command, *args], cwd=cwd, check=True, capture_output=True, text=True
        )

    @staticmethod
    def _resolve_output(prefix: Path, suffix: str) -> Path:
        direct = prefix.with_suffix(suffix)
        if direct.exists():
            return direct
        matches = sorted(prefix.parent.glob(f"{prefix.name}*{suffix}"))
        if matches:
            return matches[0]
        raise FileNotFoundError(f"vkdt did not produce expected output for {prefix}")

    def render_preview(
        self,
        *,
        graph_path: Path,
        width: int,
        height: int,
        output_name: str = "preview",
    ) -> tuple[PreviewImage, RenderedArtifact]:
        prefix = graph_path.parent / output_name
        self._run(
            [
                "-g",
                str(graph_path),
                "--format",
                "o-jpg",
                "--filename",
                str(prefix),
                "--width",
                str(width),
                "--height",
                str(height),
                "--output",
                "main",
            ],
            cwd=graph_path.parent,
        )
        output = self._resolve_output(prefix, ".jpg")
        return _data_url(output), RenderedArtifact(
            kind="preview",
            format="o-jpg",
            path=str(output),
            mimeType="image/jpeg",
        )

    def render_export(
        self,
        *,
        graph_path: Path,
        export: ExportRequest,
    ) -> RenderedArtifact:
        prefix = graph_path.parent / export.filename
        args = [
            "-g",
            str(graph_path),
            "--format",
            export.format,
            "--filename",
            str(prefix),
            "--output",
            export.output,
        ]
        if export.width is not None:
            args.extend(["--width", str(export.width)])
        if export.height is not None:
            args.extend(["--height", str(export.height)])
        if export.quality is not None:
            args.extend(["--quality", str(export.quality)])
        if export.lastFrameOnly:
            args.append("--last-frame-only")
        self._run(args, cwd=graph_path.parent)
        suffix = ".exr" if export.format == "o-exr" else ".jpg"
        mime = "image/x-exr" if export.format == "o-exr" else "image/jpeg"
        output = self._resolve_output(prefix, suffix)
        return RenderedArtifact(
            kind="export",
            format=export.format,
            path=str(output),
            mimeType=mime,
        )

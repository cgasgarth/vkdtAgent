from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    name: str
    stage: str
    summary: str
    params: tuple[str, ...]


MODULE_SPECS = (
    ModuleSpec("i-raw", "input", "RAW input source", ("filename",)),
    ModuleSpec("hotpx", "cleanup", "Hot and stuck pixel cleanup", ("thrs",)),
    ModuleSpec(
        "denoise",
        "cleanup",
        "Baseline RAW denoise and black-level cleanup",
        ("strength", "luma", "detail", "gainmap"),
    ),
    ModuleSpec(
        "hilite",
        "cleanup",
        "Highlight reconstruction and desaturation control",
        ("white", "desat", "soft"),
    ),
    ModuleSpec(
        "demosaic",
        "cleanup",
        "RAW demosaic stage",
        ("colour", "method"),
    ),
    ModuleSpec(
        "jddcnn",
        "cleanup",
        "Joint RAW denoise and demosaic via neural model",
        ("model",),
    ),
    ModuleSpec(
        "align",
        "cleanup",
        "Burst-frame alignment for stacking and noise reduction",
        ("merge_k", "merge_n", "blur0", "blur1", "blur2", "blur3", "sub"),
    ),
    ModuleSpec(
        "crop",
        "geometry",
        "Crop, rotation, and perspective corrections",
        ("crop", "rotate", "perspect"),
    ),
    ModuleSpec(
        "lens",
        "geometry",
        "Lens and chromatic aberration corrections",
        ("center", "scale", "squish0", "squish1", "ca red", "ca blue"),
    ),
    ModuleSpec(
        "colour",
        "color",
        "Exposure, white balance, saturation, and input color transform",
        ("exposure", "sat", "gamut", "clip", "clipmax", "temp", "white"),
    ),
    ModuleSpec(
        "exposure",
        "tone",
        "Simple exposure adjustment for local or global use",
        ("exposure",),
    ),
    ModuleSpec(
        "filmcurv",
        "tone",
        "Default tone curve and filmic contrast mapping",
        ("light", "contrast", "bias", "colour"),
    ),
    ModuleSpec(
        "OpenDRT",
        "tone",
        "Alternative display transform for creative rendering",
        (
            "i gamut",
            "i oetf",
            "o gamut",
            "eotf",
            "tn_Lp",
            "tn_con",
            "tn_sh",
            "tn_toe",
            "tn_off",
            "clamp",
        ),
    ),
    ModuleSpec(
        "llap",
        "detail",
        "Local contrast and clarity",
        ("sigma", "shadows", "hilights", "clarity"),
    ),
    ModuleSpec(
        "contrast",
        "detail",
        "Edge-aware contrast and texture shaping",
        ("radius", "edges", "detail", "thrs"),
    ),
    ModuleSpec("eq", "detail", "Frequency-band detail shaping", ("detail", "edges")),
    ModuleSpec("deconv", "detail", "Scene-referred sharpening", ("sigma", "iter")),
    ModuleSpec("usm", "detail", "Display-referred sharpening", ("amount", "thrs")),
    ModuleSpec(
        "grade", "grade", "Lift gamma gain color grading", ("lift", "gamma", "gain")
    ),
    ModuleSpec(
        "curves",
        "grade",
        "Curve-based tone and channel adjustments",
        ("channel", "mode", "edit", "radius", "edges"),
    ),
    ModuleSpec("ca", "cleanup", "Defringe after color stage", ("thrs", "amount")),
    ModuleSpec(
        "zones",
        "tone",
        "Zonal exposure and tone control",
        ("radius", "epsilon", "gamma", "nzones", "zone"),
    ),
    ModuleSpec(
        "grad",
        "tone",
        "Graduated filter for skies, horizons, and broad local exposure shifts",
        ("rgb", "stops", "dist", "width", "rotate"),
    ),
    ModuleSpec(
        "vignette",
        "tone",
        "Parametric vignette creation or correction",
        ("center", "coef0", "coef1", "angle"),
    ),
    ModuleSpec(
        "dehaze",
        "tone",
        "Single-image dehaze and atmospheric contrast recovery",
        ("radius", "epsilon", "strength", "t0", "haze"),
    ),
    ModuleSpec(
        "pick",
        "local",
        "Color picker and neutral reference sampling",
        ("nspots", "spots", "picked"),
    ),
    ModuleSpec(
        "mask", "local", "Parametric mask", ("mode", "vmin", "vmax", "envelope")
    ),
    ModuleSpec(
        "draw", "local", "Drawn mask strokes", ("opacity", "radius", "hardness", "draw")
    ),
    ModuleSpec("guided", "local", "Edge-aware mask refinement", ("radius", "epsilon")),
    ModuleSpec(
        "blend",
        "local",
        "Blend local adjustments back into the graph",
        ("mode", "mask", "opacity", "taathrs"),
    ),
    ModuleSpec("inpaint", "local", "Inpaint masked areas", ("mode",)),
    ModuleSpec(
        "wavelet",
        "local",
        "Wavelet-based smoothing and retouching under masks",
        ("scale", "exposure"),
    ),
    ModuleSpec(
        "negative", "creative", "Invert and balance scanned negatives", ("Dmin",)
    ),
    ModuleSpec(
        "filmsim",
        "creative",
        "Analog film and print simulation",
        (
            "process",
            "film",
            "ev film",
            "grain",
            "size",
            "uniform",
            "paper",
            "ev paper",
            "enlarge",
            "filter c/m/y",
            "tune m",
            "tune y",
            "couplers",
            "halation",
            "radius",
            "strength",
            "hal mids",
        ),
    ),
    ModuleSpec(
        "grain",
        "creative",
        "Display-referred grain",
        ("size", "strength", "decay", "octaves"),
    ),
    ModuleSpec(
        "frame",
        "creative",
        "Decorative border and frame treatment",
        ("border", "line", "size", "linewd", "align", "linepos"),
    ),
    ModuleSpec("colenc", "output", "Color encoding before export", ("prim", "trc")),
    ModuleSpec("o-jpg", "output", "JPEG export sink", ("filename", "quality")),
    ModuleSpec("o-exr", "output", "EXR export sink", ("filename",)),
    ModuleSpec("o-web", "output", "Web-oriented still export wrapper", tuple()),
    ModuleSpec("display", "output", "Display sink", tuple()),
    ModuleSpec("hist", "analysis", "Histogram tap", tuple()),
)


PLAYBOOKS = {
    "core-raw-balance": {
        "id": "core-raw-balance",
        "title": "Core RAW Balance",
        "summary": (
            "Start with colour exposure and white balance, then tune hilite "
            "and filmcurv before detail work."
        ),
        "recommendedModules": ["colour", "hilite", "filmcurv"],
    },
    "cleanup-detail": {
        "id": "cleanup-detail",
        "title": "Cleanup And Detail",
        "summary": (
            "Use hotpx, denoise, demosaic choices, llap, contrast, deconv, or usm "
            "for noise and sharpness requests."
        ),
        "recommendedModules": [
            "hotpx",
            "denoise",
            "demosaic",
            "jddcnn",
            "llap",
            "contrast",
            "deconv",
            "usm",
        ],
    },
    "geometry-lens": {
        "id": "geometry-lens",
        "title": "Geometry And Lens",
        "summary": (
            "Use crop and lens for crop, straighten, perspective, lens "
            "correction, and CA cleanup requests."
        ),
        "recommendedModules": ["crop", "lens", "ca"],
    },
    "creative-grade": {
        "id": "creative-grade",
        "title": "Creative Grade",
        "summary": (
            "Use filmcurv or OpenDRT for tone mapping, then grade and curves "
            "for look shaping."
        ),
        "recommendedModules": ["filmcurv", "OpenDRT", "grade", "curves"],
    },
    "atmosphere-tone": {
        "id": "atmosphere-tone",
        "title": "Atmosphere And Tone",
        "summary": (
            "Use grad, dehaze, zones, and vignette for broad scene shaping, "
            "depth, and edge falloff control."
        ),
        "recommendedModules": ["grad", "dehaze", "zones", "vignette"],
    },
    "local-adjustments": {
        "id": "local-adjustments",
        "title": "Local Adjustments",
        "summary": (
            "Local edits usually need a mask or draw node, optional guided "
            "refinement, an effect node, and blend."
        ),
        "recommendedModules": [
            "mask",
            "draw",
            "guided",
            "exposure",
            "grade",
            "inpaint",
            "wavelet",
            "blend",
        ],
    },
    "creative-effects": {
        "id": "creative-effects",
        "title": "Creative Effects",
        "summary": (
            "Use filmsim, grain, negative, and frame for strong stylistic or "
            "scanned-film workflows."
        ),
        "recommendedModules": ["filmsim", "grain", "negative", "frame"],
    },
    "export-delivery": {
        "id": "export-delivery",
        "title": "Export Delivery",
        "summary": (
            "Use colenc before o-jpg or o-exr and choose final size, quality, "
            "and filename deliberately."
        ),
        "recommendedModules": ["colenc", "o-jpg", "o-exr"],
    },
}


def module_catalog() -> list[dict[str, object]]:
    return [asdict(spec) for spec in MODULE_SPECS]


def adjustment_surfaces(
    present_modules: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for module in present_modules:
        name = module.get("module")
        if isinstance(name, str):
            grouped.setdefault(name, []).append(module)

    surfaces: list[dict[str, object]] = []
    for spec in MODULE_SPECS:
        present = grouped.get(spec.name, [])
        surfaces.append(
            {
                "module": spec.name,
                "stage": spec.stage,
                "summary": spec.summary,
                "params": list(spec.params),
                "present": bool(present),
                "presentInstances": present,
                "canAdd": spec.name not in {"i-raw"},
            }
        )
    return surfaces


def playbook_ids() -> list[str]:
    return sorted(PLAYBOOKS)


def get_playbook(playbook_id: str) -> dict[str, object]:
    if playbook_id not in PLAYBOOKS:
        raise ValueError(f"unknown playbook: {playbook_id}")
    return cast(dict[str, object], PLAYBOOKS[playbook_id])

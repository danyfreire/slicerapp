import json
import os
import re
import shutil
import subprocess
import traceback
import textwrap
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = ROOT_DIR / "uploads"
OUTPUTS_DIR = ROOT_DIR / "outputs"
STATE_DIR = ROOT_DIR / "backend" / "state"
STATE_FILE = STATE_DIR / "jobs.json"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="SlicerApp Local API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClipUpdate(BaseModel):
    hook: str | None = None
    status: Literal["pending", "approved", "discarded"] | None = None


class BulkStatusUpdate(BaseModel):
    status: Literal["pending", "approved", "discarded"]


class SelectedStatusUpdate(BaseModel):
    clip_ids: list[str]
    status: Literal["pending", "approved", "discarded"]


def load_jobs() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        backup_path = STATE_FILE.with_suffix(f".corrupt-{uuid.uuid4().hex[:8]}.json")
        shutil.copyfile(STATE_FILE, backup_path)
        STATE_FILE.write_text("{}", encoding="utf-8")
        return {}


def save_jobs(jobs: dict) -> None:
    STATE_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(
            status_code=500,
            detail="FFmpeg y ffprobe deben estar instalados y disponibles en PATH.",
        )


def probe_duration(path: Path) -> float:
    ensure_ffmpeg()
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail="El video no parece ser válido.")
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="No se pudo leer la duración del video.") from exc
    return duration


def build_clip_windows(duration: float, clip_duration: float, max_clips: int, interval: float) -> list[dict]:
    if duration < clip_duration:
        raise HTTPException(status_code=400, detail="La duración del video es insuficiente para el clip solicitado.")

    available_windows = []
    start = 0.0
    while start + clip_duration <= duration + 0.001:
        available_windows.append((round(start, 2), round(start + clip_duration, 2)))
        start += interval

    if not available_windows:
        raise HTTPException(status_code=400, detail="No se pudieron generar ventanas de corte para este video.")

    clips = []
    for index in range(1, max_clips + 1):
        start, end = available_windows[(index - 1) % len(available_windows)]
        clips.append(
            {
                "id": str(uuid.uuid4()),
                "index": index,
                "start": start,
                "end": end,
                "hook": "",
                "status": "pending",
                "output_path": None,
                "cycle": ((index - 1) // len(available_windows)) + 1,
            }
        )
    return clips


def sanitize_hook(text: str) -> str:
    cleaned = str(text).strip()
    cleaned = re.sub(r"^\s*(?:[-*]|\d+[\).\-\:])\s*", "", cleaned)
    cleaned = cleaned.strip(" \"'“”‘’")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*\(\d+(?:\.\d+)?s-\d+(?:\.\d+)?s\)\s*$", "", cleaned)
    cleaned = re.sub(r"\b\d+\s*(?:segundos?|secs?|seconds?)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsiete\s+segundos?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:en|durante|para)\s+segundos?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:hooks?|clips?|videos?)\s*:?\s*", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" .,:;") + "." if cleaned and not cleaned.endswith((".", "?", "!")) else cleaned


def normalize_hooks(raw_hooks: list, clips: list[dict]) -> list[str]:
    hooks = []
    relaxed_hooks = []
    forbidden = re.compile(
        r"\b(?:segundos?|seconds?|secs?|duraci[oó]n|hooks?|clips?|videos?|tiktok|reels|shorts)\b",
        re.IGNORECASE,
    )
    cliches = re.compile(r"\b(?:mi alma|pasión en cada nota|secretos olvidados)\b", re.IGNORECASE)
    for item in raw_hooks:
        cleaned = sanitize_hook(str(item))
        words = cleaned.split()
        if cleaned and 8 <= len(words) <= 22 and not forbidden.search(cleaned) and not cliches.search(cleaned):
            hooks.append(cleaned)
        elif cleaned and len(words) >= 5 and not forbidden.search(cleaned) and not cliches.search(cleaned):
            relaxed_hooks.append(cleaned)
    if len(hooks) < len(clips):
        hooks.extend([hook for hook in relaxed_hooks if hook not in hooks])
    if not hooks:
        return []
    return [hooks[index % len(hooks)] for index in range(len(clips))]


def extract_hook_list(parsed) -> list:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("hooks", "hook_texts", "texts", "frases", "_hooks"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        for value in parsed.values():
            if isinstance(value, list):
                return value
    return []


def parse_manual_hooks(manual_hooks: str, count: int) -> list[str]:
    hooks = []
    for line in manual_hooks.splitlines():
        cleaned = sanitize_hook(line)
        if cleaned:
            hooks.append(cleaned)
    if not hooks:
        return []
    return [hooks[i % len(hooks)] for i in range(count)]


def hooks_prompt(
    count: int,
    video_context: str,
    hook_objective: str,
    hook_tone: str,
    hook_type: str,
    clip_duration: float,
    output_format: str = "json",
) -> str:
    description = video_context.strip() or (
        "un video musical corto; puede ser guitarra, grabación casera, producción, ensayo, "
        "ideas en proceso o momentos creativos"
    )
    objective = hook_objective.strip() or "hacer que la persona siga leyendo y quiera ver qué pasa"
    tone = hook_tone.strip() or "humano, emocional, natural, con curiosidad y tensión"
    hook_style = hook_type.strip() or "curiosidad"
    max_words = 20 if clip_duration <= 7 else 24
    if output_format == "lines":
        output_rules = (
            "Devuelve solo los textos listos para copiar y pegar.\n\n"
            "Formato exacto:\n"
            "- un hook por línea\n"
            "- sin JSON\n"
            "- sin comillas\n"
            "- sin numeración\n"
            "- sin bullets\n"
            "- sin explicaciones antes o después"
        )
    else:
        output_rules = (
            "Devuelve únicamente JSON válido.\n\n"
            "Formato exacto:\n"
            "{\"hooks\":[\"texto 1\",\"texto 2\"]}\n\n"
            "No agregues texto fuera del JSON."
        )
    return (
        "Actúa como un experto en hooks virales para contenido corto vertical.\n\n"
        "Tu tarea es generar textos altamente adictivos para overlays de videos cortos.\n\n"
        "NO debes mencionar plataformas, marketing, hooks ni redes sociales.\n\n"
        "La persona usuaria te dará:\n"
        "- una descripción visual\n"
        "- un objetivo comunicacional\n"
        "- un tono emocional\n"
        "- un tipo psicológico de hook\n\n"
        "Tu trabajo es generar hooks que hagan que la persona siga leyendo hasta el final.\n\n"
        f"DESCRIPCIÓN DEL VIDEO:\n{description}\n\n"
        f"OBJETIVO DEL HOOK:\n{objective}\n\n"
        f"TONO:\n{tone}\n\n"
        f"TIPO DE HOOK:\n{hook_style}\n\n"
        f"Genera exactamente {count} hooks.\n\n"
        "Cada hook debe:\n"
        f"- tener entre 11 y {max_words} palabras\n"
        "- sentirse humano y natural\n"
        "- sonar emocionalmente específico\n"
        "- conectar principalmente con el OBJETIVO y no solamente con lo visual\n"
        "- mantener curiosidad, tensión emocional o identificación\n"
        "- evitar lenguaje genérico o poético vacío\n\n"
        "MUY IMPORTANTE:\n\n"
        "La descripción visual es contexto.\n"
        "El OBJETIVO es la prioridad absoluta.\n\n"
        "Ejemplos:\n"
        "- si el video muestra una playa pero el objetivo es vender tranquilidad, habla del escape emocional\n"
        "- si el objetivo es destacar una canción, habla de la sensación emocional que transmite\n"
        "- si el objetivo es generar identificación, habla del pensamiento interno de la persona\n"
        "- si el objetivo es vender algo, genera deseo indirecto sin sonar anuncio\n\n"
        "NO inventes:\n"
        "- artistas\n"
        "- marcas\n"
        "- precios\n"
        "- letras\n"
        "- historias\n"
        "- promesas\n"
        "- nombres no mencionados\n\n"
        "REGLAS SEGÚN TIPO:\n\n"
        "- pregunta: usar preguntas abiertas, incómodas o emocionalmente específicas\n"
        "- curiosidad: abrir loops mentales incompletos\n"
        "- identificación: hacer sentir “esto literalmente me pasa”\n"
        "- tensión: crear sensación de conflicto, caos o incomodidad\n"
        "- vulnerable: sonar íntimo, humano o emocionalmente expuesto\n"
        "- provocador: atacar ideas comunes o comportamientos normales\n"
        "- venta suave: crear deseo indirecto sin parecer publicidad\n"
        "- melancólico: transmitir nostalgia, distancia emocional o vacío\n\n"
        "PROHIBIDO:\n"
        "- frases motivacionales vacías\n"
        "- frases filosóficas genéricas\n"
        "- clichés tipo mi alma, vibra, pasión, energía, viaje interior, secretos ocultos, nadie habla de esto\n"
        "- lenguaje corporativo\n"
        "- frases que podrían funcionar para cualquier video\n"
        "- describir literalmente lo que se ve\n"
        "- repetir estructuras\n"
        "- sonar como IA\n\n"
        "NO uses:\n"
        "- comillas\n"
        "- hashtags\n"
        "- emojis\n"
        "- numeración\n"
        "- títulos\n"
        "- explicaciones\n\n"
        "NO menciones:\n"
        "- TikTok\n"
        "- Reels\n"
        "- Shorts\n"
        "- hooks\n"
        "- clips\n"
        "- duración\n"
        "- segundos\n\n"
        "La prioridad NO es sonar inteligente.\n\n"
        "La prioridad es generar una reacción emocional inmediata.\n\n"
        f"{output_rules}"
    )


def ollama_batch(
    count: int,
    clips: list[dict],
    video_context: str,
    hook_objective: str,
    hook_tone: str,
    hook_type: str,
    clip_duration: float,
) -> list[str]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    payload = json.dumps(
        {
            "model": model,
            "prompt": hooks_prompt(count, video_context, hook_objective, hook_tone, hook_type, clip_duration),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.7, "top_p": 0.9},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data.get("response", "")
        parsed = json.loads(raw)
        raw_hooks = extract_hook_list(parsed)
        if raw_hooks:
            return normalize_hooks(raw_hooks, clips[:count])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        return []
    return []


def ollama_hooks(
    clips: list[dict],
    video_context: str,
    hook_objective: str,
    hook_tone: str,
    hook_type: str,
    clip_duration: float,
) -> tuple[list[str], str]:
    hooks: list[str] = []
    batch_size = 5
    while len(hooks) < len(clips):
        remaining = len(clips) - len(hooks)
        batch_count = min(batch_size, remaining)
        batch_hooks = ollama_batch(
            batch_count,
            clips[len(hooks) : len(hooks) + batch_count],
            video_context,
            hook_objective,
            hook_tone,
            hook_type,
            clip_duration,
        )
        if not batch_hooks:
            break
        hooks.extend(batch_hooks[:batch_count])

    if hooks:
        if len(hooks) < len(clips):
            hooks = [hooks[index % len(hooks)] for index in range(len(clips))]
            return hooks[: len(clips)], "ollama_partial"
        return hooks[: len(clips)], "ollama"
    raise HTTPException(
        status_code=502,
        detail="Ollama no devolvió hooks válidos. Revisa que Ollama esté abierto, que el modelo exista y que la descripción sea clara.",
    )


def generate_hooks(
    clips: list[dict],
    hook_mode: str,
    video_context: str,
    hook_objective: str,
    hook_tone: str,
    hook_type: str,
    manual_hooks: str,
    clip_duration: float,
) -> tuple[list[str], str]:
    if hook_mode == "manual":
        hooks = parse_manual_hooks(manual_hooks, len(clips))
        if hooks:
            return hooks, "manual"
        raise HTTPException(status_code=400, detail="Pega al menos un hook para usar el modo manual.")

    if hook_mode == "ollama":
        return ollama_hooks(clips, video_context, hook_objective, hook_tone, hook_type, clip_duration)

    if hook_mode != "openai":
        raise HTTPException(status_code=400, detail="Modo de hooks inválido. Usa manual, ollama u openai.")

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="Falta OPENAI_API_KEY para usar OpenAI API.")

    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = {
        "role": "user",
        "content": hooks_prompt(len(clips), video_context, hook_objective, hook_tone, hook_type, clip_duration),
    }
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Eres copywriter musical para TikTok/Reels/Shorts."},
                prompt,
            ],
            temperature=0.9,
        )
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)
        raw_hooks = extract_hook_list(parsed)
        if raw_hooks:
            hooks = normalize_hooks(raw_hooks, clips)
            if len(hooks) >= len(clips):
                return hooks[: len(clips)], "openai"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI no pudo generar hooks: {exc}") from exc
    raise HTTPException(status_code=502, detail="OpenAI no devolvió hooks válidos.")


def clean_hook_text(text: str) -> str:
    return sanitize_hook(text)


def wrap_hook_lines(text: str) -> list[str]:
    clean_text = clean_hook_text(text)
    return textwrap.wrap(clean_text, width=23) or [clean_text]


def build_centered_text_filter(text: str, font_option: str, text_dir: Path, clip_index: int) -> str:
    lines = wrap_hook_lines(text)
    font_size = 52
    line_gap = 28
    line_step = font_size + line_gap
    text_height = (len(lines) * font_size) + ((len(lines) - 1) * line_gap)
    first_line_y = f"(h-{text_height})/2"

    filters = []
    for index, line in enumerate(lines):
        text_path = text_dir / f"clip_{clip_index:03}_line_{index:02}.txt"
        text_path.write_text(line, encoding="utf-8")
        y_expr = f"{first_line_y}+{index * line_step}"
        filters.append(
            f"drawtext={font_option}textfile='{ffmpeg_path_value(text_path)}':"
            f"fontcolor=white:fontsize={font_size}:borderw=5:bordercolor=black:"
            "x=(w-text_w)/2:"
            f"y={y_expr}"
        )
    return ",".join(filters)


def ffmpeg_escape_value(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
    )


def ffmpeg_path_value(path: Path) -> str:
    return ffmpeg_escape_value(str(path).replace("\\", "/"))


def drawtext_font_option() -> str:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for font in candidates:
        if font.exists():
            return f"fontfile='{ffmpeg_path_value(font)}':"
    return ""


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "ollama_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "default_hook_mode": "openai" if os.getenv("OPENAI_API_KEY") else "ollama",
        "uploads": str(UPLOADS_DIR),
        "outputs": str(OUTPUTS_DIR),
    }


@app.post("/api/prompt-preview")
async def prompt_preview(
    clip_duration: float = Form(7),
    max_clips: int = Form(30),
    output_format: str = Form("json"),
    video_context: str = Form(""),
    hook_objective: str = Form(""),
    hook_tone: str = Form(""),
    hook_type: str = Form("curiosidad"),
) -> dict:
    return {
        "inputs": {
            "clip_duration": clip_duration,
            "max_clips": max_clips,
            "output_format": output_format,
            "video_context": video_context,
            "hook_objective": hook_objective,
            "hook_tone": hook_tone,
            "hook_type": hook_type,
        },
        "prompt": hooks_prompt(
            max_clips,
            video_context,
            hook_objective,
            hook_tone,
            hook_type,
            clip_duration,
            output_format,
        ),
    }


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    clip_duration: float = Form(7),
    max_clips: int = Form(30),
    interval: float = Form(2),
    format: str = Form("vertical_9_16"),
    hook_mode: str = Form("ollama"),
    video_context: str = Form(""),
    hook_objective: str = Form(""),
    hook_tone: str = Form(""),
    hook_type: str = Form("curiosidad"),
    manual_hooks: str = Form(""),
) -> dict:
    try:
        ensure_ffmpeg()
        if clip_duration <= 0 or interval <= 0 or max_clips <= 0:
            raise HTTPException(status_code=400, detail="Los valores de configuración deben ser mayores que cero.")
        if not file.content_type or not file.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="Sube un archivo de video válido.")

        job_id = str(uuid.uuid4())
        suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
        upload_path = UPLOADS_DIR / f"{job_id}{suffix}"
        with upload_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        duration = probe_duration(upload_path)
        clips = build_clip_windows(duration, clip_duration, max_clips, interval)
        hooks, resolved_hook_mode = generate_hooks(
            clips,
            hook_mode,
            video_context,
            hook_objective,
            hook_tone,
            hook_type,
            manual_hooks,
            clip_duration,
        )
        for clip, hook in zip(clips, hooks):
            clip["hook"] = hook

        job = {
            "id": job_id,
            "original_filename": file.filename,
            "upload_path": str(upload_path),
            "duration": round(duration, 2),
            "settings": {
                "clip_duration": clip_duration,
                "max_clips": max_clips,
                "interval": interval,
                "format": format,
                "hook_mode": resolved_hook_mode,
                "video_context": video_context,
                "hook_objective": hook_objective,
                "hook_tone": hook_tone,
                "hook_type": hook_type,
            },
            "clips": clips,
            "status": "ready",
        }
        jobs = load_jobs()
        jobs[job_id] = job
        save_jobs(jobs)
        return job
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = load_jobs().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


@app.patch("/api/jobs/{job_id}/clips/{clip_id}")
def update_clip(job_id: str, clip_id: str, payload: ClipUpdate) -> dict:
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    for clip in job["clips"]:
        if clip["id"] == clip_id:
            if payload.hook is not None:
                clip["hook"] = payload.hook.strip()
            if payload.status is not None:
                clip["status"] = payload.status
            save_jobs(jobs)
            return clip
    raise HTTPException(status_code=404, detail="Clip no encontrado.")


@app.patch("/api/jobs/{job_id}/clips-status")
def update_all_clips_status(job_id: str, payload: BulkStatusUpdate) -> dict:
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado. Genera de nuevo las propuestas.")
    for clip in job["clips"]:
        clip["status"] = payload.status
    save_jobs(jobs)
    return job


@app.patch("/api/jobs/{job_id}/selected-clips-status")
def update_selected_clips_status(job_id: str, payload: SelectedStatusUpdate) -> dict:
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado. Genera de nuevo las propuestas.")
    selected_ids = set(payload.clip_ids)
    if not selected_ids:
        raise HTTPException(status_code=400, detail="Selecciona al menos un clip.")
    for clip in job["clips"]:
        if clip["id"] in selected_ids:
            clip["status"] = payload.status
    save_jobs(jobs)
    return job


@app.post("/api/jobs/{job_id}/render")
def render_job(job_id: str) -> dict:
    ensure_ffmpeg()
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    approved = [clip for clip in job["clips"] if clip["status"] == "approved"]
    if not approved:
        raise HTTPException(status_code=400, detail="Aprueba al menos un clip antes de renderizar.")

    input_path = Path(job["upload_path"])
    if not input_path.exists():
        raise HTTPException(status_code=404, detail="No se encontró el video original.")

    job_output_dir = OUTPUTS_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)
    text_dir = job_output_dir / "_text"
    text_dir.mkdir(parents=True, exist_ok=True)

    rendered_count = 0
    render_errors = []
    for clip in approved:
        output_path = job_output_dir / f"clip_{clip['index']:03}.mp4"
        clip["hook"] = clean_hook_text(clip["hook"])
        font_option = drawtext_font_option()
        video_filter = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"{build_centered_text_filter(clip['hook'], font_option, text_dir, clip['index'])}"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip["start"]),
            "-i",
            str(input_path),
            "-t",
            str(round(clip["end"] - clip["start"], 2)),
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            error = f"FFmpeg falló renderizando clip {clip['index']}: {result.stderr[-800:]}"
            clip["render_error"] = error
            render_errors.append(error)
            continue
        clip["output_path"] = str(output_path)
        clip.pop("render_error", None)
        rendered_count += 1

    job["status"] = "rendered_with_errors" if render_errors else "rendered"
    job["render_errors"] = render_errors
    save_jobs(jobs)
    if rendered_count == 0:
        raise HTTPException(
            status_code=500,
            detail=render_errors[0] if render_errors else "No se pudo renderizar ningún clip.",
        )
    return job


@app.get("/api/jobs/{job_id}/clips/{clip_id}/download")
def download_clip(job_id: str, clip_id: str) -> FileResponse:
    job = load_jobs().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    for clip in job["clips"]:
        if clip["id"] == clip_id and clip.get("output_path"):
            path = Path(clip["output_path"])
            if path.exists():
                return FileResponse(path, media_type="video/mp4", filename=path.name)
    raise HTTPException(status_code=404, detail="Clip renderizado no encontrado.")

import json
import os
import re
import shutil
import subprocess
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClipUpdate(BaseModel):
    hook: str | None = None
    status: Literal["pending", "approved", "discarded"] | None = None


def load_jobs() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


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

    clips = []
    start = 0.0
    index = 1
    while start + clip_duration <= duration + 0.001 and len(clips) < max_clips:
        clips.append(
            {
                "id": str(uuid.uuid4()),
                "index": index,
                "start": round(start, 2),
                "end": round(start + clip_duration, 2),
                "hook": "",
                "status": "pending",
                "output_path": None,
            }
        )
        start += interval
        index += 1
    return clips


def fallback_hooks(clips: list[dict], video_context: str = "") -> list[str]:
    context = video_context.strip()
    seeds = [
        "A veces un riff suena mejor cuando parece que lo encontraste por accidente.",
        "Este tono de guitarra tiene algo entre nostalgia, ruido y ganas de no explicar nada.",
        "No sé si esto es una canción todavía, pero ya tiene una vibra que me dice que siga.",
        "El truco no es tocar perfecto, es encontrar ese sonido que te hace quedarte un segundo más.",
        "Hay riffs que no piden permiso: entran con fuzz, se quedan flotando y te cambian el ánimo.",
        "Ese fuzz no está tratando de sonar limpio; está tratando de dejar una marca rara en la memoria.",
        "Hay algo retro en este riff, como si hubiera salido de una cinta perdida y todavía quisiera pelear.",
        "Si este sonido se siente medio roto, probablemente por eso mismo me dan ganas de repetirlo.",
        "No todo riff necesita explicar hacia dónde va; algunos solo necesitan abrir una puerta y hacer ruido.",
        "Esto empezó como una idea suelta, pero el sonido decidió que era más importante de lo planeado.",
        "Hay momentos de grabación que no se sienten perfectos, pero sí honestos, y eso suele durar más.",
        "A veces la toma que ibas a borrar es justo la que tiene algo que no se puede repetir.",
        "No siempre se trata de mostrar una canción terminada; a veces basta con mostrar la chispa.",
        "Este pedazo todavía está crudo, pero ya tiene esa pequeña tensión que hace que quieras escucharlo otra vez.",
    ]
    if context:
        seeds.extend(
            [
                f"Esto va sobre {context}, pero sin explicarlo demasiado: solo dejando que el momento respire.",
                f"Si este clip tiene una idea central, está en esa sensación de {context} que aparece sin pedir permiso.",
                f"Hay algo en {context} que funciona mejor cuando se siente directo, imperfecto y cerca.",
            ]
        )
    hooks = []
    for i, clip in enumerate(clips):
        base = seeds[i % len(seeds)]
        hooks.append(base)
    return hooks


def parse_manual_hooks(manual_hooks: str, count: int) -> list[str]:
    hooks = []
    for line in manual_hooks.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[\).\-\:])\s*", "", line).strip()
        if cleaned:
            hooks.append(cleaned)
    if not hooks:
        return []
    return [hooks[i % len(hooks)] for i in range(count)]


def hooks_prompt(count: int, video_context: str) -> str:
    context = video_context.strip() or (
        "un video musical corto; puede ser guitarra, grabación casera, producción, ensayo, "
        "ideas en proceso o momentos creativos"
    )
    return (
        f"Genera exactamente {count} hooks en español para clips verticales cortos. "
        f"Contexto del video: {context}. "
        "Deben ser frases un poco largas, naturales, con vibra poética pero clara, "
        "pensadas para retener lectura mientras se ve el clip. "
        "Evita hashtags, emojis, comillas, numeración y explicaciones. "
        "Responde solo un arreglo JSON de strings."
    )


def ollama_hooks(clips: list[dict], video_context: str) -> tuple[list[str], str]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    payload = json.dumps(
        {
            "model": model,
            "prompt": hooks_prompt(len(clips), video_context),
            "stream": False,
            "format": "json",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data.get("response", "")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = parsed.get("hooks", parsed.get("texts", []))
        if isinstance(parsed, list):
            hooks = [str(item).strip() for item in parsed if str(item).strip()]
            if len(hooks) >= len(clips):
                return hooks[: len(clips)], "ollama"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        return fallback_hooks(clips, video_context), "local_templates"
    return fallback_hooks(clips, video_context), "local_templates"


def generate_hooks(clips: list[dict], hook_mode: str, video_context: str, manual_hooks: str) -> tuple[list[str], str]:
    if hook_mode == "manual":
        hooks = parse_manual_hooks(manual_hooks, len(clips))
        if hooks:
            return hooks, "manual"
        return fallback_hooks(clips, video_context), "local_templates"

    if hook_mode == "ollama":
        return ollama_hooks(clips, video_context)

    if hook_mode == "templates":
        return fallback_hooks(clips, video_context), "local_templates"

    if not os.getenv("OPENAI_API_KEY"):
        return fallback_hooks(clips, video_context), "local_templates"

    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = {
        "role": "user",
        "content": hooks_prompt(len(clips), video_context),
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
        if isinstance(parsed, list):
            hooks = [str(item).strip() for item in parsed if str(item).strip()]
            if len(hooks) >= len(clips):
                return hooks[: len(clips)], "openai"
    except Exception:
        return fallback_hooks(clips, video_context), "local_templates"
    return fallback_hooks(clips, video_context), "local_templates"


def clean_hook_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*\(\d+(?:\.\d+)?s-\d+(?:\.\d+)?s\)\s*$", "", text).strip()


def wrap_hook_lines(text: str) -> list[str]:
    clean_text = clean_hook_text(text)
    return textwrap.wrap(clean_text, width=23) or [clean_text]


def ffmpeg_text_value(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
        .replace("%", "\\%")
    )


def build_centered_text_filter(text: str, font_option: str) -> str:
    lines = wrap_hook_lines(text)
    font_size = 52
    line_gap = 28
    line_step = font_size + line_gap
    padding_y = 54
    box_width = 880
    box_height = max(180, (len(lines) * font_size) + ((len(lines) - 1) * line_gap) + (padding_y * 2))
    first_line_y = f"(h-{box_height})/2+{padding_y}"

    filters = [
        f"drawbox=x=(w-{box_width})/2:y=(h-{box_height})/2:w={box_width}:h={box_height}:color=black@0.52:t=fill"
    ]
    for index, line in enumerate(lines):
        y_expr = f"{first_line_y}+{index * line_step}"
        filters.append(
            f"drawtext={font_option}text='{ffmpeg_text_value(line)}':"
            f"fontcolor=white:fontsize={font_size}:"
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
        "default_hook_mode": "openai" if os.getenv("OPENAI_API_KEY") else "local_templates",
        "uploads": str(UPLOADS_DIR),
        "outputs": str(OUTPUTS_DIR),
    }


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    clip_duration: float = Form(7),
    max_clips: int = Form(30),
    interval: float = Form(2),
    format: str = Form("vertical_9_16"),
    hook_mode: str = Form("templates"),
    video_context: str = Form(""),
    manual_hooks: str = Form(""),
) -> dict:
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
    hooks, resolved_hook_mode = generate_hooks(clips, hook_mode, video_context, manual_hooks)
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
        },
        "clips": clips,
        "status": "ready",
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    return job


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

    for clip in approved:
        output_path = job_output_dir / f"clip_{clip['index']:03}.mp4"
        clip["hook"] = clean_hook_text(clip["hook"])
        font_option = drawtext_font_option()
        video_filter = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"{build_centered_text_filter(clip['hook'], font_option)}"
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
            raise HTTPException(status_code=500, detail=f"FFmpeg falló renderizando clip {clip['index']}: {result.stderr[-800:]}")
        clip["output_path"] = str(output_path)

    job["status"] = "rendered"
    save_jobs(jobs)
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

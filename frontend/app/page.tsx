"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import { Check, Download, FileVideo, Pencil, Scissors, Trash2, Wand2 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ClipStatus = "pending" | "approved" | "discarded";

type Clip = {
  id: string;
  index: number;
  start: number;
  end: number;
  hook: string;
  status: ClipStatus;
  output_path: string | null;
};

type Job = {
  id: string;
  original_filename: string;
  duration: number;
  status: string;
  clips: Clip[];
  settings: {
    hook_mode?: string;
    video_context?: string;
  };
};

type HookMode = "templates" | "manual" | "ollama" | "openai";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [clipDuration, setClipDuration] = useState(7);
  const [maxClips, setMaxClips] = useState(30);
  const [interval, setIntervalValue] = useState(2);
  const [hookMode, setHookMode] = useState<HookMode>("templates");
  const [videoContext, setVideoContext] = useState("");
  const [manualHooks, setManualHooks] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const approvedCount = useMemo(() => job?.clips.filter((clip) => clip.status === "approved").length ?? 0, [job]);
  const renderedClips = useMemo(() => job?.clips.filter((clip) => clip.output_path) ?? [], [job]);

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Selecciona un video primero.");
      return;
    }
    setBusy(true);
    setError("");
    const body = new FormData();
    body.append("file", file);
    body.append("clip_duration", String(clipDuration));
    body.append("max_clips", String(maxClips));
    body.append("interval", String(interval));
    body.append("format", "vertical_9_16");
    body.append("hook_mode", hookMode);
    body.append("video_context", videoContext);
    body.append("manual_hooks", manualHooks);

    try {
      const response = await fetch(`${API_BASE}/api/jobs`, { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "No se pudo crear el job.");
      setJob(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error inesperado.");
    } finally {
      setBusy(false);
    }
  }

  async function patchClip(clipId: string, payload: Partial<Pick<Clip, "hook" | "status">>) {
    if (!job) return;
    const response = await fetch(`${API_BASE}/api/jobs/${job.id}/clips/${clipId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      setError(data.detail ?? "No se pudo actualizar el clip.");
      return;
    }
    setJob({
      ...job,
      clips: job.clips.map((clip) => (clip.id === clipId ? data : clip)),
    });
  }

  async function renderApproved() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.id}/render`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "No se pudo renderizar.");
      setJob(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error inesperado.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-paper">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-5 py-8">
        <header className="flex flex-col gap-3 border-b border-ink/15 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-moss">SlicerApp local</p>
            <h1 className="mt-2 text-4xl font-black tracking-normal text-ink md:text-6xl">Clips verticales con hooks</h1>
          </div>
          <div className="rounded border border-ink/15 bg-white px-4 py-3 text-sm text-ink/70">
            Backend: <span className="font-mono text-ink">{API_BASE}</span>
          </div>
        </header>

        <form onSubmit={submit} className="grid gap-4 rounded border border-ink/15 bg-white p-4 shadow-sm">
          <div className="grid gap-4 md:grid-cols-[1.4fr_0.6fr_0.6fr_0.6fr_auto] md:items-end">
            <label className="grid gap-2">
              <span className="text-sm font-semibold">Video</span>
              <span className="flex h-12 items-center gap-3 rounded border border-ink/15 px-3">
                <FileVideo className="h-5 w-5 text-fuzz" />
                <input className="w-full text-sm" type="file" accept="video/*" onChange={onFileChange} />
              </span>
            </label>
            <NumberField label="Duración" value={clipDuration} min={1} onChange={setClipDuration} suffix="s" />
            <NumberField label="Máx. clips" value={maxClips} min={1} onChange={setMaxClips} />
            <NumberField label="Intervalo" value={interval} min={1} onChange={setIntervalValue} suffix="s" />
            <button
              className="flex h-12 items-center justify-center gap-2 rounded bg-ink px-5 font-semibold text-white transition hover:bg-fuzz disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busy}
            >
              <Wand2 className="h-5 w-5" />
              {busy ? "Procesando" : "Generar"}
            </button>
          </div>

          <div className="grid gap-4 border-t border-ink/10 pt-4 md:grid-cols-[260px_1fr]">
            <label className="grid gap-2">
              <span className="text-sm font-semibold">Modo de hooks</span>
              <select
                className="h-12 rounded border border-ink/15 bg-white px-3 outline-none focus:border-fuzz"
                value={hookMode}
                onChange={(event) => setHookMode(event.target.value as HookMode)}
              >
                <option value="templates">Plantillas locales gratis</option>
                <option value="manual">Pegar mis hooks</option>
                <option value="ollama">Ollama local gratis</option>
                <option value="openai">OpenAI API opcional</option>
              </select>
            </label>

            <label className="grid gap-2">
              <span className="text-sm font-semibold">Contexto o prompt del video</span>
              <input
                className="h-12 rounded border border-ink/15 px-3 outline-none focus:border-fuzz"
                value={videoContext}
                onChange={(event) => setVideoContext(event.target.value)}
                placeholder="Ej: grabación casera de una voz doblada, textura nostálgica, proceso de producción..."
              />
            </label>
          </div>

          {hookMode === "manual" ? (
            <label className="grid gap-2">
              <span className="text-sm font-semibold">Hooks para usar</span>
              <textarea
                className="min-h-36 rounded border border-ink/15 p-3 leading-relaxed outline-none focus:border-fuzz"
                value={manualHooks}
                onChange={(event) => setManualHooks(event.target.value)}
                placeholder={"Pega un hook por línea.\nPuedes pedirlos en ChatGPT y pegarlos aquí.\nSi hay menos hooks que clips, SlicerApp los reutiliza en orden."}
              />
            </label>
          ) : null}
        </form>

        {error ? <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div> : null}

        {job ? (
          <section className="grid gap-4">
            <div className="flex flex-col gap-3 border-b border-ink/15 pb-4 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-2xl font-bold">Propuestas</h2>
                <p className="text-sm text-ink/65">
                  {job.clips.length} clips generados desde {job.original_filename} · duración {job.duration}s · {approvedCount} aprobados · hooks: {job.settings?.hook_mode ?? "local"}
                </p>
              </div>
              <button
                onClick={renderApproved}
                disabled={busy || approvedCount === 0}
                className="flex h-11 items-center justify-center gap-2 rounded bg-fuzz px-4 font-semibold text-white transition hover:bg-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Scissors className="h-5 w-5" />
                Renderizar aprobados
              </button>
            </div>

            <div className="overflow-hidden rounded border border-ink/15 bg-white">
              <div className="grid grid-cols-[70px_90px_90px_1fr_170px] border-b border-ink/10 bg-ink px-3 py-3 text-sm font-semibold text-white">
                <span>#</span>
                <span>Inicio</span>
                <span>Final</span>
                <span>Hook sugerido</span>
                <span>Acciones</span>
              </div>
              {job.clips.map((clip) => (
                <ClipRow key={clip.id} clip={clip} jobId={job.id} onPatch={patchClip} />
              ))}
            </div>

            {renderedClips.length ? (
              <div className="rounded border border-ink/15 bg-white p-4">
                <h2 className="text-2xl font-bold">Exportados</h2>
                <div className="mt-3 grid gap-2">
                  {renderedClips.map((clip) => (
                    <a
                      key={clip.id}
                      href={`${API_BASE}/api/jobs/${job.id}/clips/${clip.id}/download`}
                      className="flex items-center justify-between rounded border border-ink/10 px-3 py-3 text-sm hover:border-fuzz"
                    >
                      <span className="font-mono">{clip.output_path}</span>
                      <Download className="h-5 w-5 text-moss" />
                    </a>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}
      </section>
    </main>
  );
}

function NumberField({
  label,
  value,
  min,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="grid gap-2">
      <span className="text-sm font-semibold">{label}</span>
      <span className="flex h-12 items-center rounded border border-ink/15 px-3">
        <input
          className="w-full bg-transparent outline-none"
          type="number"
          min={min}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        {suffix ? <span className="text-sm text-ink/50">{suffix}</span> : null}
      </span>
    </label>
  );
}

function ClipRow({
  clip,
  jobId,
  onPatch,
}: {
  clip: Clip;
  jobId: string;
  onPatch: (clipId: string, payload: Partial<Pick<Clip, "hook" | "status">>) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(clip.hook);

  async function saveEdit() {
    await onPatch(clip.id, { hook: draft, status: "approved" });
    setEditing(false);
  }

  const stateClass =
    clip.status === "approved"
      ? "bg-moss text-white"
      : clip.status === "discarded"
        ? "bg-ink/20 text-ink/55"
        : "bg-gold/25 text-ink";

  return (
    <div className="grid grid-cols-[70px_90px_90px_1fr_170px] items-center gap-0 border-b border-ink/10 px-3 py-3 text-sm last:border-b-0">
      <span className="font-mono">{clip.index}</span>
      <span className="font-mono">{clip.start}s</span>
      <span className="font-mono">{clip.end}s</span>
      <div className="pr-4">
        <span className={`mb-2 inline-flex rounded px-2 py-1 text-xs font-semibold ${stateClass}`}>{clip.status}</span>
        {editing ? (
          <textarea
            className="min-h-24 w-full rounded border border-ink/20 p-2 outline-none focus:border-fuzz"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        ) : (
          <p className="leading-relaxed text-ink/80">{clip.hook}</p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {editing ? (
          <IconButton label="Guardar" onClick={saveEdit}>
            <Check className="h-4 w-4" />
          </IconButton>
        ) : (
          <>
            <IconButton label="Aprobar" onClick={() => onPatch(clip.id, { status: "approved" })}>
              <Check className="h-4 w-4" />
            </IconButton>
            <IconButton label="Editar" onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" />
            </IconButton>
            <IconButton label="Descartar" onClick={() => onPatch(clip.id, { status: "discarded" })}>
              <Trash2 className="h-4 w-4" />
            </IconButton>
            {clip.output_path ? (
              <a className="rounded border border-ink/15 p-2 hover:border-moss" title="Descargar" href={`${API_BASE}/api/jobs/${jobId}/clips/${clip.id}/download`}>
                <Download className="h-4 w-4" />
              </a>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function IconButton({ children, label, onClick }: { children: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button className="rounded border border-ink/15 p-2 transition hover:border-fuzz hover:text-fuzz" title={label} type="button" onClick={onClick}>
      {children}
    </button>
  );
}

"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import { Check, Clipboard, Download, FileVideo, Pencil, Scissors, Trash2, Wand2 } from "lucide-react";

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
    hook_objective?: string;
    hook_tone?: string;
    hook_type?: string;
  };
};

type HookMode = "manual" | "ollama" | "openai";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [clipDuration, setClipDuration] = useState(7);
  const [maxClips, setMaxClips] = useState(30);
  const [interval, setIntervalValue] = useState(2);
  const [hookMode, setHookMode] = useState<HookMode>("ollama");
  const [videoContext, setVideoContext] = useState("");
  const [hookObjective, setHookObjective] = useState("");
  const [hookTone, setHookTone] = useState("");
  const [hookType, setHookType] = useState("curiosidad");
  const [manualHooks, setManualHooks] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [selectedClipIds, setSelectedClipIds] = useState<string[]>([]);
  const [showPromptPreview, setShowPromptPreview] = useState(false);
  const [promptPreview, setPromptPreview] = useState("");
  const [promptInputs, setPromptInputs] = useState<Record<string, string | number>>({});
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const approvedCount = useMemo(() => job?.clips.filter((clip) => clip.status === "approved").length ?? 0, [job]);
  const discardedCount = useMemo(() => job?.clips.filter((clip) => clip.status === "discarded").length ?? 0, [job]);
  const renderedClips = useMemo(() => job?.clips.filter((clip) => clip.output_path) ?? [], [job]);
  const selectedCount = selectedClipIds.length;
  const allSelected = Boolean(job?.clips.length) && selectedCount === job?.clips.length;
  const showPromptBuilder = hookMode === "manual" || hookMode === "ollama" || hookMode === "openai";

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
    body.append("hook_objective", hookObjective);
    body.append("hook_tone", hookTone);
    body.append("hook_type", hookType);
    body.append("manual_hooks", manualHooks);

    try {
      const response = await fetch(`${API_BASE}/api/jobs`, { method: "POST", body });
      const data = await readApiResponse(response);
      if (!response.ok) throw new Error(data.detail ?? "No se pudo crear el job.");
      setJob(data);
      setSelectedClipIds([]);
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
    const data = await readApiResponse(response);
    if (!response.ok) {
      handleApiError(data.detail ?? "No se pudo actualizar el clip.");
      return;
    }
    setJob({
      ...job,
      clips: job.clips.map((clip) => (clip.id === clipId ? data : clip)),
    });
  }

  async function approveSelected() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.id}/selected-clips-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_ids: selectedClipIds, status: "approved" }),
      });
      const data = await readApiResponse(response);
      if (!response.ok) throw new Error(data.detail ?? "No se pudieron aprobar los clips seleccionados.");
      setJob(data);
      setSelectedClipIds([]);
    } catch (caught) {
      handleApiError(caught instanceof Error ? caught.message : "Error inesperado.");
    } finally {
      setBusy(false);
    }
  }

  function handleApiError(message: string) {
    setError(message);
    if (message.toLowerCase().includes("job no encontrado")) {
      setJob(null);
    }
  }

  function toggleClipSelection(clipId: string, checked: boolean) {
    setSelectedClipIds((current) => (checked ? [...new Set([...current, clipId])] : current.filter((id) => id !== clipId)));
  }

  function toggleAllSelection(checked: boolean) {
    setSelectedClipIds(checked && job ? job.clips.map((clip) => clip.id) : []);
  }

  async function renderApproved() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.id}/render`, { method: "POST" });
      const data = await readApiResponse(response);
      if (!response.ok) throw new Error(data.detail ?? "No se pudo renderizar.");
      setJob(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error inesperado.");
    } finally {
      setBusy(false);
    }
  }

  function startNewJob() {
    setJob(null);
    setSelectedClipIds([]);
    setError("");
  }

  async function loadPromptPreview() {
    setError("");
    const body = new FormData();
    body.append("clip_duration", String(clipDuration));
    body.append("max_clips", String(maxClips));
    body.append("output_format", hookMode === "manual" ? "lines" : "json");
    body.append("video_context", videoContext);
    body.append("hook_objective", hookObjective);
    body.append("hook_tone", hookTone);
    body.append("hook_type", hookType);

    try {
      const response = await fetch(`${API_BASE}/api/prompt-preview`, { method: "POST", body });
      const data = await readApiResponse(response);
      if (!response.ok) throw new Error(data.detail ?? "No se pudo construir el prompt.");
      setPromptPreview(data.prompt ?? "");
      setPromptInputs(data.inputs ?? {});
      setShowPromptPreview(true);
      setCopiedPrompt(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error inesperado.");
    }
  }

  async function copyPrompt() {
    if (!promptPreview) return;
    try {
      await navigator.clipboard.writeText(promptPreview);
      setCopiedPrompt(true);
    } catch {
      setError("No se pudo copiar el prompt automáticamente.");
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

          <div className="grid grid-cols-1 gap-4 border-t border-ink/10 pt-4 md:grid-cols-12">
            <label className={`grid gap-2 ${showPromptBuilder ? "md:col-span-3" : "md:col-span-3"}`}>
              <span className="text-sm font-semibold">Modo de hooks</span>
              <select
                className="h-12 rounded border border-ink/15 bg-white px-3 outline-none focus:border-fuzz"
                value={hookMode}
                onChange={(event) => setHookMode(event.target.value as HookMode)}
              >
                <option value="manual">Pegar mis hooks</option>
                <option value="ollama">Ollama local</option>
                <option value="openai">OpenAI API opcional</option>
              </select>
            </label>

            {showPromptBuilder ? (
              <label className="grid gap-2 md:col-span-5">
                <span className="text-sm font-semibold">Descripción del video</span>
                <input
                  className="h-12 rounded border border-ink/15 px-3 outline-none focus:border-fuzz"
                  value={videoContext}
                  onChange={(event) => setVideoContext(event.target.value)}
                  placeholder="Ej: carretera al atardecer vista desde un paso peatonal..."
                />
              </label>
            ) : null}

            {showPromptBuilder ? (
              <label className="grid gap-2 md:col-span-4">
                <span className="text-sm font-semibold">Objetivo</span>
                <input
                  className="h-12 rounded border border-ink/15 px-3 outline-none focus:border-fuzz"
                  value={hookObjective}
                  onChange={(event) => setHookObjective(event.target.value)}
                  placeholder="Ej: hablar de la canción de fondo, vender un viaje..."
                />
              </label>
            ) : null}

            {showPromptBuilder ? (
              <label className="grid gap-2 md:col-span-3">
                <span className="text-sm font-semibold">Tono</span>
                <input
                  className="h-12 rounded border border-ink/15 px-3 outline-none focus:border-fuzz"
                  value={hookTone}
                  onChange={(event) => setHookTone(event.target.value)}
                  placeholder="Ej: melancólico, incómodo, vulnerable, rebelde..."
                />
              </label>
            ) : null}

            {showPromptBuilder ? (
              <label className="grid gap-2 md:col-span-3">
                <span className="text-sm font-semibold">Tipo</span>
                <select
                  className="h-12 rounded border border-ink/15 bg-white px-3 outline-none focus:border-fuzz"
                  value={hookType}
                  onChange={(event) => setHookType(event.target.value)}
                >
                  <option value="curiosidad">Curiosidad</option>
                  <option value="pregunta">Pregunta</option>
                  <option value="identificacion">Identificación</option>
                  <option value="tension">Tensión</option>
                  <option value="vulnerable">Vulnerable</option>
                  <option value="provocador">Provocador</option>
                  <option value="venta suave">Venta suave</option>
                  <option value="melancolico">Melancólico</option>
                </select>
              </label>
            ) : null}

            {showPromptBuilder ? (
              <div className="flex items-end md:col-span-2">
                <button
                  className="h-12 w-full rounded border border-ink/20 px-4 font-semibold text-ink transition hover:border-fuzz hover:text-fuzz"
                  type="button"
                  onClick={loadPromptPreview}
                >
                  {hookMode === "manual" ? "Crear prompt" : "Ver prompt"}
                </button>
              </div>
            ) : null}
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

          {showPromptPreview && showPromptBuilder ? (
            <div className="rounded border border-ink/15 bg-paper p-4">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <h2 className="text-lg font-bold">{hookMode === "manual" ? "Prompt para copiar" : "Prompt interno"}</h2>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="flex h-10 items-center justify-center gap-2 rounded border border-ink/20 px-3 text-sm font-semibold text-ink transition hover:border-fuzz hover:text-fuzz"
                    type="button"
                    onClick={copyPrompt}
                  >
                    <Clipboard className="h-4 w-4" />
                    {copiedPrompt ? "Copiado" : "Copiar"}
                  </button>
                  <button className="h-10 px-3 text-sm font-semibold text-ink/60 hover:text-fuzz" type="button" onClick={() => setShowPromptPreview(false)}>
                    Ocultar
                  </button>
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-sm text-ink/70 md:grid-cols-3">
                {Object.entries(promptInputs).map(([key, value]) => (
                  <div key={key} className="rounded border border-ink/10 bg-white px-3 py-2">
                    <span className="font-semibold">{key}</span>: <span>{String(value || "-")}</span>
                  </div>
                ))}
              </div>
              <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded border border-ink/10 bg-white p-3 text-sm leading-relaxed text-ink/80">
                {promptPreview}
              </pre>
            </div>
          ) : null}
        </form>

        {error ? <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div> : null}

        {job ? (
          <section className="grid gap-4">
            <div className="flex flex-col gap-3 border-b border-ink/15 pb-4 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-2xl font-bold">Propuestas</h2>
                <p className="text-sm text-ink/65">
                  {job.clips.length} clips generados desde {job.original_filename} · duración {job.duration}s · {approvedCount} aprobados · {discardedCount} descartados · {selectedCount} seleccionados · hooks: {job.settings?.hook_mode ?? "local"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={approveSelected}
                  disabled={busy || selectedCount === 0}
                  className="flex h-11 items-center justify-center gap-2 rounded border border-moss px-4 font-semibold text-moss transition hover:bg-moss hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Check className="h-5 w-5" />
                  Aprobar seleccionados
                </button>
                <button
                  onClick={renderApproved}
                  disabled={busy || approvedCount === 0}
                  className="flex h-11 items-center justify-center gap-2 rounded bg-fuzz px-4 font-semibold text-white transition hover:bg-ink disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Scissors className="h-5 w-5" />
                  Renderizar aprobados
                </button>
              </div>
            </div>

            <div className="overflow-hidden rounded border border-ink/15 bg-white">
              <div className="grid grid-cols-[56px_70px_90px_90px_1fr_170px] border-b border-ink/10 bg-ink px-3 py-3 text-sm font-semibold text-white">
                <label className="flex items-center justify-center" title="Aprobar todos">
                  <input
                    className="h-4 w-4 accent-fuzz"
                    type="checkbox"
                    checked={allSelected}
                    ref={(input) => {
                      if (input) input.indeterminate = selectedCount > 0 && selectedCount < job.clips.length;
                    }}
                    onChange={(event) => toggleAllSelection(event.target.checked)}
                    disabled={busy}
                  />
                </label>
                <span>#</span>
                <span>Inicio</span>
                <span>Final</span>
                <span>Hook sugerido</span>
                <span>Acciones</span>
              </div>
              {job.clips.map((clip) => (
                <ClipRow
                  key={clip.id}
                  clip={clip}
                  jobId={job.id}
                  selected={selectedClipIds.includes(clip.id)}
                  onSelect={toggleClipSelection}
                  onPatch={patchClip}
                />
              ))}
            </div>

            {renderedClips.length ? (
              <div className="rounded border border-ink/15 bg-white p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <h2 className="text-2xl font-bold">Exportados</h2>
                  <button
                    className="flex h-11 items-center justify-center gap-2 rounded border border-ink/20 px-4 font-semibold text-ink transition hover:border-fuzz hover:text-fuzz"
                    type="button"
                    onClick={startNewJob}
                  >
                    <Wand2 className="h-5 w-5" />
                    Generar nuevos clips
                  </button>
                </div>
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

async function readApiResponse(response: Response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { detail: text || response.statusText };
  }
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
  selected,
  onSelect,
  onPatch,
}: {
  clip: Clip;
  jobId: string;
  selected: boolean;
  onSelect: (clipId: string, checked: boolean) => void;
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
    <div className="grid grid-cols-[56px_70px_90px_90px_1fr_170px] items-center gap-0 border-b border-ink/10 px-3 py-3 text-sm last:border-b-0">
      <label className="flex items-center justify-center" title={clip.status === "approved" ? "Quitar aprobación" : "Aprobar"}>
        <input
          className="h-4 w-4 accent-fuzz"
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelect(clip.id, event.target.checked)}
        />
      </label>
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

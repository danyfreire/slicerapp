# SlicerApp local

MVP local para generar clips verticales con hooks editables quemados sobre el video.

## Estructura

- `frontend/`: Next.js + React + Tailwind.
- `backend/`: FastAPI + FFmpeg + generadores de hooks.
- `uploads/`: videos originales subidos.
- `outputs/`: clips renderizados.
- `backend/state/jobs.json`: estado local del flujo.

## Requisitos

1. Node.js 20.9 o superior.
2. Python 3.11 o superior.
3. FFmpeg y ffprobe instalados y disponibles en `PATH`.
4. Opcional: Ollama local u OpenAI API si quieres hooks generados por un LLM.

En Windows, si te faltan Python o FFmpeg:

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

Después cierra y vuelve a abrir la terminal para refrescar `PATH`.

Comprueba FFmpeg:

```powershell
ffmpeg -version
ffprobe -version
```

## Modos de hooks

SlicerApp tiene cuatro modos:

- `Plantillas locales gratis`: no usa internet ni API key. Usa frases locales y adapta algunas al contexto que escribas.
- `Pegar mis hooks`: puedes pedir hooks en ChatGPT, copiarlos y pegarlos en la app, uno por línea.
- `Ollama local gratis`: usa un modelo local si tienes Ollama corriendo en tu máquina. Si Ollama no responde, vuelve a plantillas locales.
- `OpenAI API opcional`: usa `OPENAI_API_KEY` si más adelante decides usar la API.

Para Ollama:

```powershell
winget install Ollama.Ollama
ollama pull llama3.2
ollama serve
```

## Configuración

Desde la raíz del proyecto:

```powershell
Copy-Item .env.example backend\.env
```

Puedes dejar `OPENAI_API_KEY` vacío. Si usas Ollama, revisa que estos valores existan en `backend\.env`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

## Instalar dependencias

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Frontend, en otra terminal:

```powershell
cd frontend
npm.cmd install
```

## Correr localmente

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm.cmd run dev
```

Abre `http://localhost:3000`.

## Flujo

1. Sube un video.
2. Ajusta duración de clip, máximo de clips e intervalo entre cortes.
3. Elige modo de hooks y escribe el contexto del video.
4. Genera propuestas de cortes y hooks.
5. Aprueba, edita o descarta cada texto.
6. Renderiza los clips aprobados.
7. Descarga desde la pantalla final o abre los archivos en `outputs/<job-id>/`.

## Notas

- ChatGPT y la API de OpenAI son productos separados. Tener ChatGPT no reemplaza una `OPENAI_API_KEY`.
- Para una opción gratis con LLM, usa Ollama local o pega hooks generados desde ChatGPT.
- El procesamiento pesado corre en FastAPI local con FFmpeg, no en Vercel.
- Vercel solo sería útil luego para desplegar la interfaz Next.js.
- No hay login ni base de datos; el estado se guarda como JSON local.

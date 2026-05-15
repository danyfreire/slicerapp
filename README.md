# SlicerApp local

SlicerApp es una app local para convertir videos largos o medianos en clips verticales cortos con textos tipo hook quemados sobre el video.

El objetivo del MVP es funcionar primero en tu máquina:

- Frontend: Next.js + React + Tailwind.
- Backend local: Python + FastAPI.
- Video: FFmpeg.
- Hooks: plantillas locales, hooks pegados, Ollama local u OpenAI API opcional.
- Estado: JSON local, sin login y sin base de datos.

## Estructura

- `frontend/`: interfaz web.
- `backend/`: API local, generación de hooks y render con FFmpeg.
- `uploads/`: videos originales subidos.
- `outputs/`: clips renderizados.
- `backend/state/jobs.json`: estado local de jobs y clips.

## Requisitos

1. Node.js 20.9 o superior.
2. Python 3.11 o superior.
3. FFmpeg y ffprobe instalados y disponibles en `PATH`.
4. Opcional: Ollama local u OpenAI API si quieres hooks generados por un LLM.

En Windows, si faltan Python o FFmpeg:

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

Cierra y vuelve a abrir la terminal para refrescar `PATH`.

Comprueba FFmpeg:

```powershell
ffmpeg -version
ffprobe -version
```

## Configuración

Desde la raíz del proyecto:

```powershell
Copy-Item .env.example backend\.env
```

Puedes dejar `OPENAI_API_KEY` vacío. SlicerApp funciona sin pagar API usando plantillas locales o hooks pegados.

Si usas Ollama, revisa estos valores en `backend\.env`:

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

Opción rápida desde la raíz del proyecto:

```powershell
.\start-dev.bat
```

Para detener backend y frontend:

```powershell
.\stop-dev.bat
```

Para reiniciar ambos:

```powershell
.\restart-dev.bat
```

Opción manual:

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

Abre:

```text
http://localhost:3000
```

## Flujo de uso

1. Sube un video.
2. Ajusta duración del clip, máximo de clips e intervalo entre cortes.
3. Elige modo de hooks.
4. Escribe el contexto del video si quieres orientar los textos.
5. Genera propuestas de cortes y hooks.
6. Aprueba, edita o descarta cada texto.
7. Renderiza los clips aprobados.
8. Descarga desde la pantalla final o abre los archivos en `outputs/<job-id>/`.

## Modos de hooks

SlicerApp tiene tres modos:

- `Pegar mis hooks`: puedes crear un prompt desde la app, copiarlo en ChatGPT u otro LLM, y pegar el resultado en la app, un hook por línea.
- `Ollama local`: usa un modelo local si tienes Ollama corriendo.
- `OpenAI API opcional`: usa `OPENAI_API_KEY` si más adelante decides usar la API.

Ejemplo de contexto:

```text
Grabación casera de guitarras y voces, textura nostálgica, proceso indie, errores bonitos y tomas imperfectas.
```

Ejemplo de hooks para pegar:

```text
A veces una toma imperfecta dice más que una versión demasiado limpia.
Esto no está terminado todavía, pero ya tiene una vibra que me pide seguir.
Hay sonidos que funcionan porque parecen encontrados, no planeados.
```

## Usar Ollama gratis

Instala Ollama:

```powershell
winget install Ollama.Ollama
```

Descarga un modelo:

```powershell
ollama pull llama3.2
```

Levanta Ollama:

```powershell
ollama serve
```

Luego en SlicerApp elige `Ollama local gratis`.

## Render de texto

El texto se renderiza con FFmpeg:

- formato vertical `1080x1920`
- video centrado con crop automático
- hook centrado horizontal y verticalmente
- fondo semitransparente detrás del texto
- salida en `outputs/<job-id>/`

Si cambias código del backend, reinicia FastAPI y vuelve a renderizar los clips aprobados.

## GitHub

Flujo recomendado para guardar cambios:

```powershell
git status
git add .
git commit -m "Describe el cambio"
git push
```

En otra máquina:

```powershell
git clone https://github.com/danyfreire/slicerapp.git
cd slicerapp
```

Luego instala dependencias siguiendo las secciones anteriores.

## Notas

- ChatGPT y la API de OpenAI son productos separados. Tener ChatGPT no reemplaza una `OPENAI_API_KEY`.
- Para una opción gratis con LLM, usa Ollama local o pega hooks generados desde ChatGPT.
- El procesamiento pesado corre en FastAPI local con FFmpeg, no en Vercel.
- Vercel solo sería útil luego para desplegar la interfaz Next.js.
- No subas `backend\.env`; ya está ignorado por Git.
- No hay login ni base de datos todavía; el estado se guarda como JSON local.

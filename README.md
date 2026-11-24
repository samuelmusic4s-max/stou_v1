# SC.IA

Curador multi-fuente con IA en Python + PySide6.

## Compilar en Windows (desde `git clone`)

Requisitos: [Git](https://git-scm.com/) y [uv](https://docs.astral.sh/uv/).

```powershell
git clone <URL_DEL_REPO>
cd scia
uv sync --dev
uv run pyinstaller --clean --noconfirm scia.spec
```

El ejecutable queda en `dist\SC.IA\SC.IA.exe` (formato `--onedir`, listo para empaquetar con InstallForge).

## Ejecutar en desarrollo

```powershell
uv run scia
```

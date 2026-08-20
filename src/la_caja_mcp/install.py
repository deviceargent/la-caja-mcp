"""Instalador de la-caja-mcp como MCP local: `la-caja-mcp install`.

Para el usuario promedio que quiere "instalar mejor memoria" en su
agente sin tocar config a mano. Detecta los agentes instalados, escribe
la entrada MCP correcta de cada uno (formato especifico por agente) y
verifica que quedo registrada. Un comando, cero JSON manual.

Uso:
  la-caja-mcp install                  # detecta y registra en los agentes presentes
  la-caja-mcp install --agent opencode # solo un agente
  la-caja-mcp install --scope project  # solo en el proyecto actual
  la-caja-mcp install --name caja      # nombre de la entrada MCP
  la-caja-mcp install --caja-db <ruta> # memoria persistente para el server
  la-caja-mcp install --list           # solo lista los agentes detectados
"""

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field

NOMBRE_DEFECTO = "caja"


@dataclass
class Agente:
    id: str
    nombre: str
    detectar: callable
    escribir: callable
    verificar: callable = None
    presente: bool = False


def _comando_server(caja_db=None):
    """Comando portable para el server. Si el paquete esta instalado (el
    exe en PATH), usa el exe: apunta al Python que tiene el modulo.
    Fallback: python -m con el Python actual. Devuelve (comando, args)."""
    exe = shutil.which("la-caja-mcp")
    if exe:
        args = [exe, "--transport", "stdio"]
    else:
        args = [sys.executable, "-m", "la_caja_mcp.mcp_server", "--transport", "stdio"]
    if caja_db:
        args += ["--caja-db", caja_db]
    return args[0], args[1:]


def _verificar_comando(comando, args, timeout=15):
    """Prueba que el comando del server realmente arranca el modulo y su
    parser CLI. Con `--help` argparse responde y sale 0 si el modulo
    carga; si el python no tiene el paquete, muere con ModuleNotFoundError
    y se captura el stderr. El fallo tipico que se previene: escribir una
    config cuyo python no tiene la_caja_mcp instalado. Devuelve (ok,
    detalle)."""
    import subprocess

    try:
        proc = subprocess.run(
            [comando] + args + ["--help"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "el comando no respondio (timeout)"
    if proc.returncode == 0:
        return True, "el server arranca (import + CLI OK)"
    stderr = proc.stderr or ""
    if "No module named" in stderr:
        return False, "el python indicado no tiene el paquete la_caja_mcp instalado (corre: pip install la-caja-mcp)"
    return False, (stderr.strip()[:200] or "el comando fallo al arrancar")


def _leer_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _escribir_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


# --- formatos por agente ---


def _entry_opencode(comando, args, name):
    return {
        "type": "local",
        "command": [comando] + args,
        "enabled": True,
    }


def _write_opencode(scope, comando, args, name, caja_db):
    if scope == "global":
        path = _opencode_global_path()
    else:
        path = _opencode_project_path()
    cfg = _leer_json(path) or {"$schema": "https://opencode.ai/config.json"}
    cfg.setdefault("mcp", {})[name] = _entry_opencode(comando, args, name)
    _escribir_json(path, cfg)
    return path


def _entry_claude(comando, args):
    return {"command": comando, "args": args}


def _write_claude_code(scope, comando, args, name, caja_db):
    if scope == "global":
        path = os.path.join(os.path.expanduser("~"), ".claude.json")
        cfg = _leer_json(path) or {}
        cfg.setdefault("mcpServers", {})[name] = _entry_claude(comando, args)
    else:
        path = ".mcp.json"
        cfg = _leer_json(path) or {"mcpServers": {}}
        cfg["mcpServers"][name] = _entry_claude(comando, args)
    _escribir_json(path, cfg)
    return path


def _write_cursor(scope, comando, args, name, caja_db):
    path = os.path.join(".cursor", "mcp.json")
    cfg = _leer_json(path) or {"mcpServers": {}}
    cfg["mcpServers"][name] = _entry_claude(comando, args)
    _escribir_json(path, cfg)
    return path


def _write_vscode(scope, comando, args, name, caja_db):
    path = os.path.join(".vscode", "mcp.json")
    cfg = _leer_json(path) or {"mcpServers": {}}
    cfg["mcpServers"][name] = _entry_claude(comando, args)
    _escribir_json(path, cfg)
    return path


def _claude_desktop_path():
    """Ruta al claude_desktop_config.json que el Claude Desktop instalado
    realmente lee. Prioridad:
      1) config clasico %APPDATA%\\Claude\\claude_desktop_config.json
      2) config MSIX (LocalCache\\Roaming\\Claude dentro del paquete)
      3) paquete MSIX instalado sin config aun (se crea ahi)
      4) clasico por defecto
    """
    home = os.path.expanduser("~")
    clasico = os.path.join(os.environ.get("APPDATA", home), "Claude", "claude_desktop_config.json")
    if os.path.exists(clasico):
        return clasico
    msix = _claude_desktop_msix_path()
    if msix and os.path.exists(msix):
        return msix
    if msix:
        return msix
    return clasico


def _claude_desktop_msix_path():
    """Ubicacion del config dentro del paquete MSIX/UWP, si Claude Desktop
    esta instalado como app de la Store. En MSIX el %APPDATA% del proceso
    se redirige a LocalCache\\Roaming dentro del paquete."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    base = os.path.join(local, "Packages")
    try:
        dirs = os.listdir(base)
    except OSError:
        return None
    for d in dirs:
        if not d.startswith("Claude_"):
            continue
        cfg = os.path.join(base, d, "LocalCache", "Roaming", "Claude", "claude_desktop_config.json")
        if os.path.exists(cfg):
            return cfg
    for d in dirs:
        if not d.startswith("Claude_"):
            continue
        claude_dir = os.path.join(base, d, "LocalCache", "Roaming", "Claude")
        if os.path.isdir(claude_dir) or os.path.isdir(os.path.join(base, d)):
            return os.path.join(claude_dir, "claude_desktop_config.json")
    return None


def _write_claude_desktop(scope, comando, args, name, caja_db):
    path = _claude_desktop_path()
    cfg = _leer_json(path) or {}
    cfg.setdefault("mcpServers", {})[name] = _entry_claude(comando, args)
    _escribir_json(path, cfg)
    return path


# --- deteccion ---


def _en_path(prog):
    return shutil.which(prog) is not None


def _opencode_global_dir():
    # XDG_CONFIG_HOME tiene precedencia; si no, ~/.config/opencode en
    # cualquier SO (donde opencode guarda config + jsonc). Fallback APPDATA.
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg and os.path.isdir(os.path.join(xdg, "opencode")):
        return os.path.join(xdg, "opencode")
    home = os.path.expanduser("~")
    cfg = os.path.join(home, ".config", "opencode")
    if os.path.isdir(cfg):
        return cfg
    if os.name == "nt":
        appdata = os.path.join(os.environ.get("APPDATA", home), "opencode")
        if os.path.isdir(appdata):
            return appdata
    return cfg


def _opencode_global_path():
    d = _opencode_global_dir()
    for nombre in ("opencode.json", "opencode.jsonc"):
        p = os.path.join(d, nombre)
        if os.path.exists(p):
            return p
    return os.path.join(d, "opencode.json")


def _opencode_project_path():
    for p in ("opencode.json", "opencode.jsonc", ".opencode/opencode.json"):
        if os.path.exists(p):
            return p
    return "opencode.json"


def _detectar_opencode():
    return _en_path("opencode") or os.path.exists(os.path.join(_opencode_global_dir(), "opencode.json")) or os.path.exists(os.path.join(_opencode_global_dir(), "opencode.jsonc"))


def _detectar_claude_code():
    return _en_path("claude")


def _detectar_cursor():
    return _en_path("cursor") or os.path.isdir(".cursor")


def _detectar_vscode():
    return _en_path("code") or os.path.isdir(".vscode")


def _detectar_claude_desktop():
    # presente si hay un paquete MSIX instalado, o ya existe un config clasico
    return _claude_desktop_msix_path() is not None or os.path.exists(
        os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Claude", "claude_desktop_config.json")
    )


AGENTES = [
    Agente("opencode", "opencode", _detectar_opencode, _write_opencode),
    Agente("claude-code", "Claude Code", _detectar_claude_code, _write_claude_code),
    Agente("cursor", "Cursor", _detectar_cursor, _write_cursor),
    Agente("vscode", "VS Code", _detectar_vscode, _write_vscode),
    Agente("claude-desktop", "Claude Desktop", _detectar_claude_desktop, _write_claude_desktop),
]


def detectar_presentes():
    for a in AGENTES:
        try:
            a.presente = bool(a.detectar())
        except Exception:
            a.presente = False
    return [a for a in AGENTES if a.presente]


def listar():
    return [(a.id, a.presente) for a in AGENTES]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="la-caja-mcp install", description="Registra la-caja-mcp como MCP local en los agentes instalados.")
    parser.add_argument("--agent", choices=[a.id for a in AGENTES], default=None, help="solo este agente")
    parser.add_argument("--scope", choices=["project", "global"], default="project", help="opencode/claude-code: proyecto actual o global")
    parser.add_argument("--name", default=NOMBRE_DEFECTO, help=f"nombre de la entrada MCP (default: {NOMBRE_DEFECTO})")
    parser.add_argument("--caja-db", default=None, help="ruta a la memoria persistente (SQLite) para el server")
    parser.add_argument("--list", action="store_true", help="solo listar agentes detectados")
    args = parser.parse_args(argv)

    presentes = detectar_presentes()
    if args.list:
        for a in AGENTES:
            print(f"{'[x]' if a.presente else '[ ]'} {a.id}  ({a.nombre})")
        return 0
    if not presentes:
        print("No se detecto ningun agente MCP instalado (opencode, Claude Code, Cursor, VS Code, Claude Desktop).")
        print("Instala uno y volve a correr: la-caja-mcp install")
        return 1

    comando, args_server = _comando_server(args.caja_db)
    print(f"Verificando que el server arranca: {comando} {' '.join(args_server)}")
    ok, detalle = _verificar_comando(comando, args_server)
    if not ok:
        print("[error] el comando del server no arranca. La config NO se escribio.")
        print(f"       {detalle}")
        print("       Instala el paquete y volve a intentar: pip install la-caja-mcp")
        return 1

    objetivos = presentes if not args.agent else [a for a in presentes if a.id == args.agent]
    if not objetivos:
        print(f"El agente '{args.agent}' no se detecto en este sistema.")
        return 1

    for a in objetivos:
        try:
            path = a.escribir(args.scope, comando, args_server, args.name, args.caja_db)
            print(f"[ok] {a.nombre}: entrada '{args.name}' escrita en {path}")
            print(f"     comando: {comando} {' '.join(args_server)}")
        except Exception as e:
            print(f"[error] {a.nombre}: {e}")
            return 1

    print("Server verificado y config escrita. Reinicia tu agente para que tome")
    print(f"la config. La memoria queda disponible como el MCP '{args.name}'")
    print("(tools procesar_consulta, consultar, contexto_primado, historial, stats + debate).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
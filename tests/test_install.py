"""Tests del instalador (la-caja-mcp install): deteccion de agentes y
escritura de config por agente, en directorios temporales (sin tocar la
config real del sistema)."""

import json
import os
import sys

from la_caja_mcp import install as ins


def test_comando_server_portable(tmp_path, monkeypatch):
    # sin el paquete instalado (exe ausente), usa python -m con el python actual
    monkeypatch.setattr(ins.shutil, "which", lambda _: None)
    comando, args = ins._comando_server()
    assert comando
    assert "-m" in args and "la_caja_mcp.mcp_server" in args
    assert "--transport" in args and "stdio" in args


def test_comando_server_prefiere_exe(tmp_path, monkeypatch):
    # con el paquete instalado, usa el ejecutable la-caja-mcp (apunta al
    # python que tiene el modulo)
    monkeypatch.setattr(ins.shutil, "which", lambda _: r"C:\exe\la-caja-mcp.exe")
    comando, args = ins._comando_server()
    assert comando == r"C:\exe\la-caja-mcp.exe"
    assert args[0] == "--transport" and args[1] == "stdio"


def test_verificar_comando_ok(tmp_path, monkeypatch):
    # el comando real de este entorno arranca (el paquete esta instalado)
    comando, args = ins._comando_server()
    ok, detalle = ins._verificar_comando(comando, args, timeout=20)
    assert ok, detalle


def test_verificar_comando_falla_modulo_ausente(tmp_path, monkeypatch):
    # comando con un modulo inexistente: falla con el mensaje de instalacion
    ok, detalle = ins._verificar_comando(
        sys.executable, ["-m", "modulo_inexistente_del_probe", "--transport", "stdio"], timeout=10
    )
    assert not ok
    assert "pip install la-caja-mcp" in detalle


def test_comando_server_con_caja_db(tmp_path):
    db = str(tmp_path / "m.db")
    comando, args = ins._comando_server(db)
    assert "--caja-db" in args and db in args


def test_opencode_escribe_config_valida(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    comando, args = ins._comando_server()
    path = ins._write_opencode("project", comando, args, "caja", None)
    assert path == "opencode.json"
    cfg = json.loads(open(path, encoding="utf-8").read())
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    entry = cfg["mcp"]["caja"]
    assert entry["type"] == "local"
    assert entry["enabled"] is True
    assert entry["command"][0] == comando
    assert entry["command"][1:] == args


def test_opencode_preserva_config_existente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open("opencode.json", "w", encoding="utf-8") as fh:
        json.dump({"username": "tester"}, fh)
    comando, args = ins._comando_server()
    ins._write_opencode("project", comando, args, "caja", None)
    cfg = json.loads(open("opencode.json", encoding="utf-8").read())
    assert cfg["username"] == "tester"
    assert "caja" in cfg["mcp"]


def test_opencode_global_respeta_jsonc(tmp_path, monkeypatch):
    d = tmp_path / ".config" / "opencode"
    d.mkdir(parents=True)
    with open(d / "opencode.jsonc", "w", encoding="utf-8") as fh:
        fh.write('{"username": "g"}')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    path = ins._opencode_global_path()
    assert path.endswith("opencode.jsonc")
    comando, args = ins._comando_server()
    escrito = ins._write_opencode("global", comando, args, "caja", None)
    assert escrito == path
    cfg = json.loads(open(path, encoding="utf-8").read())
    assert cfg["username"] == "g"
    assert "caja" in cfg["mcp"]


def test_claude_code_escribe_mcp_servers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    comando, args = ins._comando_server()
    path = ins._write_claude_code("project", comando, args, "caja", None)
    cfg = json.loads(open(path, encoding="utf-8").read())
    entry = cfg["mcpServers"]["caja"]
    assert entry["command"] == comando
    assert entry["args"] == args


def test_claude_code_global_preserva(tmp_path, monkeypatch):
    claude = tmp_path / ".claude.json"
    claude.write_text(json.dumps({"some": "state"}), encoding="utf-8")
    monkeypatch.setattr(os.path, "expanduser", lambda *a: str(tmp_path))
    comando, args = ins._comando_server()
    path = ins._write_claude_code("global", comando, args, "caja", None)
    cfg = json.loads(open(path, encoding="utf-8").read())
    assert cfg["some"] == "state"
    assert "caja" in cfg["mcpServers"]


def test_claude_desktop_apunta_a_appdata(tmp_path, monkeypatch):
    # sin MSIX instalado, el config clasico va a %APPDATA%\\Claude
    monkeypatch.setattr(ins, "_claude_desktop_msix_path", lambda: None)
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    comando, args = ins._comando_server()
    path = ins._write_claude_desktop("project", comando, args, "caja", None)
    assert str(appdata / "Claude" / "claude_desktop_config.json") == path
    cfg = json.loads(open(path, encoding="utf-8").read())
    assert "caja" in cfg["mcpServers"]


def test_claude_desktop_msix_redirige_al_paquete(tmp_path, monkeypatch):
    # Claude Desktop como app de la Store: %APPDATA% se redirige a
    # LocalCache\\Roaming\\Claude dentro del paquete MSIX.
    paquete = tmp_path / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    paquete.mkdir(parents=True)
    with open(paquete / "claude_desktop_config.json", "w", encoding="utf-8") as fh:
        json.dump({"preferences": {"epitaxyPrefs": {}}}, fh)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert ins._claude_desktop_msix_path() == str(paquete / "claude_desktop_config.json")
    assert ins._detectar_claude_desktop() is True
    comando, args = ins._comando_server()
    path = ins._write_claude_desktop("project", comando, args, "caja", None)
    assert path == str(paquete / "claude_desktop_config.json")
    cfg = json.loads(open(path, encoding="utf-8").read())
    # no rompe las preferencias existentes del usuario
    assert "preferences" in cfg
    assert "caja" in cfg["mcpServers"]


def test_claude_desktop_msix_sin_config_aun(tmp_path, monkeypatch):
    # paquete MSIX instalado pero el usuario nunca lanzo la app: se crea el
    # config dentro del paquete, no en %APPDATA% clasico.
    paquete = tmp_path / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    paquete.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    comando, args = ins._comando_server()
    path = ins._write_claude_desktop("project", comando, args, "caja", None)
    assert path == str(paquete / "claude_desktop_config.json")
    cfg = json.loads(open(path, encoding="utf-8").read())
    assert "caja" in cfg["mcpServers"]


def test_listar_devuelve_todos_los_agentes():
    lista = ins.listar()
    ids = [x[0] for x in lista]
    assert "opencode" in ids
    assert "claude-code" in ids
    assert "cursor" in ids
    assert "vscode" in ids
    assert "claude-desktop" in ids
    assert len(lista) == 5


def test_main_list_sin_errores():
    assert ins.main(["--list"]) == 0


def test_main_instala_opencode_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert ins.main(["--agent", "opencode", "--scope", "project", "--name", "caja"]) == 0
    cfg = json.loads(open("opencode.json", encoding="utf-8").read())
    assert "caja" in cfg["mcp"]


def test_main_sin_agentes_retorna_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ins, "detectar_presentes", lambda: [])
    assert ins.main([]) == 1


def test_main_agente_inexistente_falla(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # simula que opencode esta detectado pero claude-code no
    def fake_detect():
        import types

        a = types.SimpleNamespace(id="opencode", nombre="opencode", presente=True)
        return [a]

    monkeypatch.setattr(ins, "detectar_presentes", fake_detect)
    assert ins.main(["--agent", "claude-code"]) == 1
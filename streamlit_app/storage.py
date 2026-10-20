"""
Storage backend abstraction.

Every table the app reads/writes goes through a Storage object with three
methods: read_csv, write_csv, exists. Two backends:

  - LocalStorage  — plain files in streamlit_app/data/. Works today, no setup.
  - DriveStorage   — a shared Google Drive folder via a service account.
                      Needs GOOGLE_SERVICE_ACCOUNT_JSON + FC_DRIVE_FOLDER_ID
                      (see streamlit_app/README.md for the one-time setup).

Pick the backend with the FC_STORAGE_BACKEND env var ("local" | "drive"),
default "local". Nothing outside this file knows or cares which one is live —
the collector and every page just call get_storage().read_csv(TABLE_X).
"""
import io
import os
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _setting(name: str, default=None):
    """Env var first (cron / local), then Streamlit secrets (Community Cloud)."""
    if name in os.environ:
        return os.environ[name]
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


class LocalStorage:
    """CSV files on disk. Good for local dev and for a single cron machine."""

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.data_dir, name)

    def exists(self, name: str) -> bool:
        return os.path.exists(self._path(name))

    def read_csv(self, name: str, **kwargs) -> pd.DataFrame:
        path = self._path(name)
        if not os.path.exists(path):
            return pd.DataFrame()
        return pd.read_csv(path, **kwargs)

    def write_csv(self, name: str, df: pd.DataFrame) -> None:
        df.to_csv(self._path(name), index=False)


class DriveStorage:
    """
    A shared Google Drive folder, written/read as a service account.

    Setup (one time, see README.md for the full walkthrough):
      1. Create a GCP project, enable the Drive API.
      2. Create a service account, download its JSON key.
      3. Share your Drive folder with the service account's email
         (it shows up as a "user" you can share with, like any person).
      4. Set env vars:
           GOOGLE_SERVICE_ACCOUNT_JSON = path to the key file, OR the raw
                                         JSON text (Streamlit Cloud secrets
                                         usually prefer the raw text)
           FC_DRIVE_FOLDER_ID          = the folder's id (from its URL)

    Files are matched by name inside that one folder. write_csv overwrites
    the existing file's content (same file id) rather than creating
    duplicates, so Drive's native "last modified" / version history still
    works if you ever need to roll back a bad tag edit.
    """

    def __init__(self, folder_id: str | None = None, service_account_info=None):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        self.folder_id = folder_id or _setting("FC_DRIVE_FOLDER_ID")

        if service_account_info is None:
            raw = _setting("GOOGLE_SERVICE_ACCOUNT_JSON")
            if raw is None:
                raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set (env var or Streamlit secret)")
            if not isinstance(raw, str):
                # Pasted into secrets as a TOML table rather than a JSON string.
                creds = service_account.Credentials.from_service_account_info(
                    dict(raw), scopes=["https://www.googleapis.com/auth/drive"]
                )
            elif os.path.exists(raw):
                creds = service_account.Credentials.from_service_account_file(
                    raw, scopes=["https://www.googleapis.com/auth/drive"]
                )
            else:
                import json
                creds = service_account.Credentials.from_service_account_info(
                    json.loads(raw), scopes=["https://www.googleapis.com/auth/drive"]
                )
        else:
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=["https://www.googleapis.com/auth/drive"]
            )

        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._file_id_cache: dict[str, str] = {}

    def _find_file_id(self, name: str) -> str | None:
        if name in self._file_id_cache:
            return self._file_id_cache[name]
        q = f"name = '{name}' and '{self.folder_id}' in parents and trashed = false"
        resp = self.svc.files().list(q=q, fields="files(id, name)").execute()
        files = resp.get("files", [])
        if not files:
            return None
        self._file_id_cache[name] = files[0]["id"]
        return files[0]["id"]

    def exists(self, name: str) -> bool:
        return self._find_file_id(name) is not None

    def read_csv(self, name: str, **kwargs) -> pd.DataFrame:
        from googleapiclient.http import MediaIoBaseDownload

        file_id = self._find_file_id(name)
        if file_id is None:
            return pd.DataFrame()
        request = self.svc.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        return pd.read_csv(buf, **kwargs)

    def write_csv(self, name: str, df: pd.DataFrame) -> None:
        from googleapiclient.http import MediaIoBaseUpload

        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        media = MediaIoBaseUpload(buf, mimetype="text/csv", resumable=False)

        file_id = self._find_file_id(name)
        if file_id is None:
            metadata = {"name": name, "parents": [self.folder_id]}
            created = self.svc.files().create(body=metadata, media_body=media, fields="id").execute()
            self._file_id_cache[name] = created["id"]
        else:
            self.svc.files().update(fileId=file_id, media_body=media).execute()


_storage_singleton = None


def get_storage():
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    backend = str(_setting("FC_STORAGE_BACKEND", "local")).lower()
    if backend == "drive":
        _storage_singleton = DriveStorage()
    else:
        _storage_singleton = LocalStorage()
    return _storage_singleton

"""Tests for upload path resolution."""

from upload_paths import resolve_upload_file_path


def test_resolve_upload_file_path_falls_back_to_upload_dir(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    upload.mkdir()
    image = upload / "worksheet.jpg"
    image.write_bytes(b"jpeg")

    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    monkeypatch.chdir(tmp_path)

    resolved = resolve_upload_file_path("/old/volume/path/worksheet.jpg")

    assert resolved == image.resolve()

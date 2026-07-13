import gzip
import os
import subprocess
import tempfile
from unittest.mock import ANY, patch
import pytest

import gs_fastcopy

JSON_STR = b'{"A": 3}'


@pytest.fixture
def local_files():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = os.path.join(tmp_dir, "src.txt")
        dest = os.path.join(tmp_dir, "dest.txt")
        src_gz = os.path.join(tmp_dir, "src.txt.gz")
        dest_gz = os.path.join(tmp_dir, "dest.txt.gz")

        with open(src, "wb") as f:
            f.write(JSON_STR)

        with gzip.open(src_gz, "wb") as f:
            f.write(JSON_STR)

        yield src, dest, src_gz, dest_gz


# --- Local to Local tests ---


def test_copy_local_to_local_no_compression(local_files):
    src, dest, _, _ = local_files
    gs_fastcopy.copy(src, dest)
    assert os.path.exists(dest)
    with open(dest, "rb") as f:
        assert f.read() == JSON_STR


def test_copy_local_to_local_compression(local_files):
    src, _, _, dest_gz = local_files
    gs_fastcopy.copy(src, dest_gz)
    assert os.path.exists(dest_gz)
    with gzip.open(dest_gz, "rb") as f:
        assert f.read() == JSON_STR


def test_copy_local_to_local_decompression(local_files):
    _, dest, src_gz, _ = local_files
    gs_fastcopy.copy(src_gz, dest)
    assert os.path.exists(dest)
    with open(dest, "rb") as f:
        assert f.read() == JSON_STR


# --- GCS mocked transfers ---

# Custom subprocess.run mock to simulate gcloud / pigz / gunzip etc
builtin_run = subprocess.run


def build_subprocess_run_mock():
    calls = []

    def mock_run(*args, **kwargs):
        commands = args[0]
        calls.append(commands)

        if commands[0:3] == ["gcloud", "storage", "cp"]:
            # Check for GCS to Local copy
            # gcloud storage cp gs://bucket/file.ext dest_file
            src_path = commands[-2]
            dest_file = commands[-1]
            if src_path.startswith("gs://") and not dest_file.startswith("gs://"):
                with open(dest_file, "wb") as f:
                    if src_path.endswith(".gz"):
                        f.write(gzip.compress(JSON_STR))
                    else:
                        f.write(JSON_STR)
            return subprocess.CompletedProcess(args, 0, b"", None)

        return builtin_run(*args, **kwargs)

    return mock_run, calls


def build_upload_chunks_concurrently_mock(uploaded_data):
    def side_effecter(buffer_file_name, gs_blob, **kwargs):
        with open(buffer_file_name, "rb") as f:
            data = f.read()
            if buffer_file_name.endswith(".gz"):
                data = gzip.decompress(data)
            uploaded_data.append((gs_blob.name, data))

    return side_effecter


@patch("gs_fastcopy.transfer_manager.upload_chunks_concurrently")
def test_copy_local_to_gcs_no_compression(mock_upload, local_files):
    src, _, _, _ = local_files
    uploaded = []
    mock_upload.side_effect = build_upload_chunks_concurrently_mock(uploaded)

    gs_fastcopy.copy(src, "gs://my-bucket/my-file.json")

    assert len(uploaded) == 1
    assert uploaded[0] == ("my-file.json", JSON_STR)


@patch("gs_fastcopy.transfer_manager.upload_chunks_concurrently")
def test_copy_local_to_gcs_compression(mock_upload, local_files):
    src, _, _, _ = local_files
    uploaded = []
    mock_upload.side_effect = build_upload_chunks_concurrently_mock(uploaded)

    gs_fastcopy.copy(src, "gs://my-bucket/my-file.json.gz")

    assert len(uploaded) == 1
    assert uploaded[0] == ("my-file.json.gz", JSON_STR)


@patch("gs_fastcopy.transfer_manager.upload_chunks_concurrently")
def test_copy_local_to_gcs_decompression(mock_upload, local_files):
    _, _, src_gz, _ = local_files
    uploaded = []
    mock_upload.side_effect = build_upload_chunks_concurrently_mock(uploaded)

    gs_fastcopy.copy(src_gz, "gs://my-bucket/my-file.json")

    assert len(uploaded) == 1
    assert uploaded[0] == ("my-file.json", JSON_STR)


def test_copy_gcs_to_local_no_compression(local_files):
    _, dest, _, _ = local_files
    mock_run, run_calls = build_subprocess_run_mock()

    with patch("gs_fastcopy.subprocess.run", side_effect=mock_run):
        gs_fastcopy.copy("gs://my-bucket/my-file.json", dest)

    assert os.path.exists(dest)
    with open(dest, "rb") as f:
        assert f.read() == JSON_STR


def test_copy_gcs_to_local_decompression(local_files):
    _, dest, _, _ = local_files
    mock_run, run_calls = build_subprocess_run_mock()

    with patch("gs_fastcopy.subprocess.run", side_effect=mock_run):
        gs_fastcopy.copy("gs://my-bucket/my-file.json.gz", dest)

    assert os.path.exists(dest)
    with open(dest, "rb") as f:
        assert f.read() == JSON_STR


def test_copy_gcs_to_local_compression(local_files):
    _, _, _, dest_gz = local_files
    mock_run, run_calls = build_subprocess_run_mock()

    with patch("gs_fastcopy.subprocess.run", side_effect=mock_run):
        gs_fastcopy.copy("gs://my-bucket/my-file.json", dest_gz)

    assert os.path.exists(dest_gz)
    with gzip.open(dest_gz, "rb") as f:
        assert f.read() == JSON_STR


def test_copy_gcs_to_gcs_same_compression():
    mock_run, run_calls = build_subprocess_run_mock()

    with patch("gs_fastcopy.subprocess.run", side_effect=mock_run):
        gs_fastcopy.copy("gs://my-bucket/src.json", "gs://my-bucket/dest.json")

    # Should call gcloud storage cp gs://... gs://... directly
    gcloud_calls = [c for c in run_calls if c[0:3] == ["gcloud", "storage", "cp"]]
    assert len(gcloud_calls) == 1
    assert gcloud_calls[0][-2] == "gs://my-bucket/src.json"
    assert gcloud_calls[0][-1] == "gs://my-bucket/dest.json"


@patch("gs_fastcopy.transfer_manager.upload_chunks_concurrently")
def test_copy_gcs_to_gcs_mixed_compression_uncompressed_to_compressed(mock_upload):
    uploaded = []
    mock_upload.side_effect = build_upload_chunks_concurrently_mock(uploaded)
    mock_run, run_calls = build_subprocess_run_mock()

    with patch("gs_fastcopy.subprocess.run", side_effect=mock_run):
        gs_fastcopy.copy("gs://my-bucket/src.json", "gs://my-bucket/dest.json.gz")

    # Should download src.json (not gzipped) to temp file first, then compress to another temp file, then upload
    gcloud_dl_calls = [
        c
        for c in run_calls
        if c[0:3] == ["gcloud", "storage", "cp"] and c[-2].startswith("gs://")
    ]
    assert len(gcloud_dl_calls) == 1
    assert gcloud_dl_calls[0][-2] == "gs://my-bucket/src.json"

    assert len(uploaded) == 1
    assert uploaded[0] == ("dest.json.gz", JSON_STR)


@patch("gs_fastcopy.transfer_manager.upload_chunks_concurrently")
def test_copy_gcs_to_gcs_mixed_compression_compressed_to_uncompressed(mock_upload):
    uploaded = []
    mock_upload.side_effect = build_upload_chunks_concurrently_mock(uploaded)
    mock_run, run_calls = build_subprocess_run_mock()

    with patch("gs_fastcopy.subprocess.run", side_effect=mock_run):
        gs_fastcopy.copy("gs://my-bucket/src.json.gz", "gs://my-bucket/dest.json")

    # Should download src.json.gz to temp file first, then decompress to another temp file, then upload
    gcloud_dl_calls = [
        c
        for c in run_calls
        if c[0:3] == ["gcloud", "storage", "cp"] and c[-2].startswith("gs://")
    ]
    assert len(gcloud_dl_calls) == 1
    assert gcloud_dl_calls[0][-2] == "gs://my-bucket/src.json.gz"

    assert len(uploaded) == 1
    assert uploaded[0] == ("dest.json", JSON_STR)

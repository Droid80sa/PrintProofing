import re

import pytest

from app.storage import LocalStorage


@pytest.fixture()
def storage_root(tmp_path):
    return str(tmp_path)


def test_local_storage_generate_url_relative(storage_root):
    storage = LocalStorage(storage_root)
    url = storage.generate_url("foo bar.pdf")
    assert url == "/storage/local/foo%20bar.pdf"


def test_local_storage_generate_url_with_domain_base(storage_root):
    storage = LocalStorage(storage_root, public_base_url="https://proof.example.com")
    url = storage.generate_url("proofs/latest.pdf")
    assert url.startswith("https://proof.example.com/storage/local/proofs/latest.pdf?expires=")
    assert re.search(r"\?expires=\d+$", url)


def test_local_storage_generate_url_with_custom_path_base(storage_root):
    storage = LocalStorage(storage_root, public_base_url="https://cdn.example.com/proofs")
    url = storage.generate_url("artwork.pdf")
    assert url.startswith("https://cdn.example.com/proofs/artwork.pdf?expires=")
    assert re.search(r"\?expires=\d+$", url)

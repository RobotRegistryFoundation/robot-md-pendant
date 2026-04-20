def test_version_is_importable():
    from pendantd import __version__
    assert __version__.startswith("0.1.")

from app.core.converter import convert_cflv_to_mp4


def test_convert_too_small(tmp_path):
    cflv = tmp_path / "a.cflv"
    cflv.write_bytes(b"CFLV" + b"\x00" * 10)
    ok, err = convert_cflv_to_mp4(str(cflv), str(tmp_path / "a.mp4"))
    assert not ok
    assert err

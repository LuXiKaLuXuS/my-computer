from app.services.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("MySecret123!")
    assert verify_password("MySecret123!", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_api_key_generation():
    full, prefix, key_hash = generate_api_key()
    assert full.startswith("mc_")
    assert prefix == full[:12]
    assert verify_api_key(full, key_hash)
    assert not verify_api_key("mc_invalid", key_hash)
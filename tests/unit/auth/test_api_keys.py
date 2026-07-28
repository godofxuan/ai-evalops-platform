from collections.abc import Iterator

from app.auth.api_keys import extract_key_prefix, generate_api_key, verify_api_key


class DeterministicRandomBytes:
    def __init__(self) -> None:
        self._values: Iterator[bytes] = iter(
            (
                bytes.fromhex("001122334455"),
                bytes(range(32)),
                bytes.fromhex("00112233445566778899aabbccddeeff"),
            )
        )

    def __call__(self, length: int) -> bytes:
        value = next(self._values)
        assert len(value) == length
        return value


def test_generated_api_key_is_verifiable_without_retaining_plaintext() -> None:
    generated = generate_api_key(random_bytes=DeterministicRandomBytes())
    plaintext = generated.plaintext.get_secret_value()

    assert generated.prefix == "evk_001122334455"
    assert extract_key_prefix(plaintext) == generated.prefix
    assert verify_api_key(plaintext, generated.key_hash)
    assert not verify_api_key(f"{plaintext}wrong", generated.key_hash)
    assert plaintext not in generated.key_hash
    assert plaintext not in repr(generated)

"""Tests for core.crypto — credential encryption at rest."""
import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from core.crypto import (
    EnvKeyBox,
    MissingKeyError,
    get_secret_box,
    last4,
    mask_secret,
)

_TEST_KEY = Fernet.generate_key().decode()


class TestEnvKeyBox(unittest.TestCase):

    def test_roundtrip(self):
        with patch.dict(os.environ, {"AI_CONFIG_KEY": _TEST_KEY}):
            box = EnvKeyBox()
            ct, version = box.encrypt("sk-secret-value-1234")
            self.assertNotIn(b"sk-secret", ct)
            self.assertEqual(1, version)
            self.assertEqual("sk-secret-value-1234", box.decrypt(ct, version))

    def test_ciphertext_differs_between_calls(self):
        """Fernet is randomized; identical plaintext must not produce identical bytes."""
        with patch.dict(os.environ, {"AI_CONFIG_KEY": _TEST_KEY}):
            box = EnvKeyBox()
            first, _ = box.encrypt("same")
            second, _ = box.encrypt("same")
            self.assertNotEqual(first, second)

    def test_missing_key_raises_on_use_not_on_construction(self):
        """The app must still boot without AI_CONFIG_KEY; only crypto operations fail."""
        with patch.dict(os.environ, {}, clear=True):
            box = EnvKeyBox()          # must not raise
            with self.assertRaises(MissingKeyError):
                box.encrypt("anything")

    def test_wrong_key_raises_missing_key_error(self):
        with patch.dict(os.environ, {"AI_CONFIG_KEY": _TEST_KEY}):
            ct, version = EnvKeyBox().encrypt("value")
        other = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"AI_CONFIG_KEY": other}):
            with self.assertRaises(MissingKeyError):
                EnvKeyBox().decrypt(ct, version)


class TestMasking(unittest.TestCase):

    def test_mask_secret_shows_only_last_four(self):
        self.assertEqual("sk-****wxyz", mask_secret("sk-abcdefghijklmnowxyz"))

    def test_mask_short_secret_reveals_nothing(self):
        self.assertEqual("****", mask_secret("abc"))

    def test_mask_empty(self):
        self.assertEqual("", mask_secret(""))

    def test_last4(self):
        self.assertEqual("wxyz", last4("sk-abcdefghijklmnowxyz"))


class TestFactory(unittest.TestCase):

    def test_get_secret_box_returns_env_box(self):
        self.assertIsInstance(get_secret_box(), EnvKeyBox)


if __name__ == "__main__":
    unittest.main()

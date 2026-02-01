"""Encryption utilities for sensitive data like API keys."""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class APIKeyEncryption:
    """Encrypts and decrypts API keys using Fernet symmetric encryption.
    
    The encryption key is derived from the application's SECRET_KEY.
    This provides secure storage of user API keys in the database.
    """
    
    def __init__(self, secret_key: str):
        """Initialize encryption with the application secret key.
        
        Args:
            secret_key: The application's SECRET_KEY from settings.
                       This is used to derive the Fernet encryption key.
        """
        # Derive a 32-byte key from the secret key using SHA256
        # Fernet requires a 32-byte base64-encoded key
        key_bytes = hashlib.sha256(secret_key.encode()).digest()
        self._fernet_key = base64.urlsafe_b64encode(key_bytes)
        self._fernet = Fernet(self._fernet_key)
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string (e.g., API key).
        
        Args:
            plaintext: The string to encrypt.
            
        Returns:
            Base64-encoded encrypted string, suitable for database storage.
        """
        encrypted = self._fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt(self, encrypted: str) -> str:
        """Decrypt an encrypted string.
        
        Args:
            encrypted: The base64-encoded encrypted string from the database.
            
        Returns:
            The original plaintext string.
            
        Raises:
            ValueError: If decryption fails (invalid key or corrupted data).
        """
        try:
            decrypted = self._fernet.decrypt(encrypted.encode())
            return decrypted.decode()
        except InvalidToken as e:
            raise ValueError("Failed to decrypt: invalid key or corrupted data") from e
    
    def is_valid_encrypted(self, value: str) -> bool:
        """Check if a value appears to be validly encrypted.
        
        Args:
            value: The value to check.
            
        Returns:
            True if the value can be decrypted, False otherwise.
        """
        try:
            self.decrypt(value)
            return True
        except (ValueError, InvalidToken):
            return False


def get_api_key_encryption() -> APIKeyEncryption:
    """Get an APIKeyEncryption instance using the application settings.
    
    Returns:
        Configured APIKeyEncryption instance.
    """
    from agent_system.composition_root.config import get_settings
    
    settings = get_settings()
    return APIKeyEncryption(settings.secret_key)

"""
Encryption utilities for protecting sensitive health data in the database.

Uses AES-256 encryption in GCM mode for authenticated encryption.
"""

import os
import base64
import json
from typing import Any, Optional, Union, List
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import logging

logger = logging.getLogger(__name__)


class HealthDataEncryption:
    """Handles encryption/decryption of sensitive health data."""
    
    def __init__(self, key: Optional[bytes] = None):
        """
        Initialize encryption with a key.
        
        Args:
            key: 32-byte encryption key. If None, will try to load from environment
                 or generate a new one.
        """
        if key is None:
            key = self._get_or_generate_key()
        
        if len(key) != 32:
            raise ValueError("Encryption key must be exactly 32 bytes")
        
        self.key = key
    
    def _get_or_generate_key(self) -> bytes:
        """Get encryption key from environment or generate a new one."""
        
        # Try to get from environment variable
        env_key = os.getenv("HEALTH_DATA_ENCRYPTION_KEY")
        if env_key:
            try:
                return base64.b64decode(env_key.encode())
            except Exception as e:
                logger.warning(f"Invalid encryption key in environment: {e}")
        
        # Generate a new key and warn about it
        key = os.urandom(32)
        key_b64 = base64.b64encode(key).decode()
        
        logger.warning(
            "No encryption key found in environment. Generated new key.\n"
            f"IMPORTANT: Add this to your .env file:\n"
            f"HEALTH_DATA_ENCRYPTION_KEY={key_b64}\n"
            "Without this, you won't be able to decrypt existing data!"
        )
        
        return key
    
    def encrypt(self, data: Union[str, List[str], dict]) -> str:
        """
        Encrypt sensitive data.
        
        Args:
            data: Data to encrypt (string, list, or dict)
            
        Returns:
            Base64-encoded encrypted data with nonce and tag
        """
        try:
            # Convert to JSON if not string
            if isinstance(data, (list, dict)):
                plaintext = json.dumps(data, ensure_ascii=False).encode('utf-8')
            else:
                plaintext = str(data).encode('utf-8')
            
            # Generate random nonce
            nonce = os.urandom(12)
            
            # Create cipher
            cipher = Cipher(
                algorithms.AES(self.key),
                modes.GCM(nonce),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            
            # Encrypt data
            ciphertext = encryptor.update(plaintext) + encryptor.finalize()
            
            # Combine nonce + tag + ciphertext and encode
            encrypted_data = nonce + encryptor.tag + ciphertext
            return base64.b64encode(encrypted_data).decode()
            
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise ValueError(f"Failed to encrypt data: {e}")
    
    def decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt sensitive data.
        
        Args:
            encrypted_data: Base64-encoded encrypted data
            
        Returns:
            Decrypted data as string
        """
        try:
            # Decode from base64
            data = base64.b64decode(encrypted_data.encode())
            
            # Extract components
            nonce = data[:12]
            tag = data[12:28]
            ciphertext = data[28:]
            
            # Create cipher
            cipher = Cipher(
                algorithms.AES(self.key),
                modes.GCM(nonce, tag),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            
            # Decrypt data
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            return plaintext.decode('utf-8')
            
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise ValueError(f"Failed to decrypt data: {e}")
    
    def decrypt_json(self, encrypted_data: str) -> Union[List[str], dict]:
        """
        Decrypt data and parse as JSON.
        
        Args:
            encrypted_data: Base64-encoded encrypted JSON data
            
        Returns:
            Parsed JSON data
        """
        decrypted_text = self.decrypt(encrypted_data)
        try:
            return json.loads(decrypted_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Decrypted data is not valid JSON: {e}")
            return decrypted_text


# Global encryption instance
_encryption_instance: Optional[HealthDataEncryption] = None


def get_encryption() -> HealthDataEncryption:
    """Get the global encryption instance."""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = HealthDataEncryption()
    return _encryption_instance


def encrypt_health_data(data: Union[str, List[str], dict]) -> str:
    """Convenience function to encrypt health data."""
    return get_encryption().encrypt(data)


def decrypt_health_data(encrypted_data: str) -> str:
    """Convenience function to decrypt health data."""
    return get_encryption().decrypt(encrypted_data)


def decrypt_health_data_json(encrypted_data: str) -> Union[List[str], dict]:
    """Convenience function to decrypt health data as JSON."""
    return get_encryption().decrypt_json(encrypted_data)


# Test function for verification
def test_encryption():
    """Test encryption/decryption functionality."""
    
    test_data = [
        "Patient has chest pain and shortness of breath",
        {
            "specialty": "CARDIOLOGY",
            "confidence": 0.95,
            "reasoning": "Clear cardiac symptoms present"
        },
        ["Page 1: Patient info", "Page 2: Clinical details", "Page 3: Assessment"]
    ]
    
    encryption = HealthDataEncryption()
    
    print("🔐 Testing Health Data Encryption")
    print("=" * 40)
    
    for i, data in enumerate(test_data, 1):
        print(f"\nTest {i}: {type(data).__name__}")
        print(f"Original: {str(data)[:50]}...")
        
        # Encrypt
        encrypted = encryption.encrypt(data)
        print(f"Encrypted: {encrypted[:50]}...")
        
        # Decrypt
        if isinstance(data, (list, dict)):
            decrypted = encryption.decrypt_json(encrypted)
        else:
            decrypted = encryption.decrypt(encrypted)
        
        print(f"Decrypted: {str(decrypted)[:50]}...")
        
        # Verify
        success = data == decrypted
        print(f"✅ Success: {success}")


if __name__ == "__main__":
    test_encryption()
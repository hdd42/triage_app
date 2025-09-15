from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError


class Prompt(BaseModel):
    id: str
    version: str = Field(default="v1", description="Prompt version identifier")
    role: str
    content: str
    variables: Optional[List[str]] = None
    locale: Optional[str] = None
    created_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    active: bool = Field(default=True, description="Whether this prompt version is active")


class Tool(BaseModel):
    name: str = Field(..., description="Tool name for dynamic calling")
    description: Optional[str] = None
    enabled: bool = Field(default=True)
    config: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Rule(BaseModel):
    id: str
    version: str = Field(default="v1", description="Rule version identifier")
    type: str
    description: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    active: bool = Field(default=True, description="Whether this rule version is active")
    data: Dict[str, str] = Field(default_factory=dict)


class Client(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    version: str = Field(default="v1", description="Client configuration version")
    rules: List[Rule] = Field(default_factory=list)
    prompts: List[Prompt] = Field(default_factory=list)
    tools: List[Tool] = Field(default_factory=list)
    created_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())
    active: bool = Field(default=True, description="Whether this client is active")


class ClientConfig(BaseModel):
    clients: List[Client] = Field(default_factory=list)
    version: str = Field(default="1.0", description="Configuration schema version")
    updated_at: Optional[str] = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def get_client(self, client_id: str) -> Optional[Client]:
        for c in self.clients:
            if c.id == client_id:
                return c
        return None
    
    def add_client(self, client: Client) -> None:
        """Add a new client to the configuration."""
        self.clients.append(client)
        self.updated_at = datetime.utcnow().isoformat()
    
    def update_client(self, client_id: str, client: Client) -> bool:
        """Update an existing client."""
        for i, c in enumerate(self.clients):
            if c.id == client_id:
                client.updated_at = datetime.utcnow().isoformat()
                self.clients[i] = client
                self.updated_at = datetime.utcnow().isoformat()
                return True
        return False
    
    def delete_client(self, client_id: str) -> bool:
        """Delete a client from the configuration."""
        for i, c in enumerate(self.clients):
            if c.id == client_id:
                del self.clients[i]
                self.updated_at = datetime.utcnow().isoformat()
                return True
        return False


def load_client_config(path: str | os.PathLike[str]) -> ClientConfig:
    p = Path(path)
    if not p.is_absolute():
        # resolve relative to current working directory
        p = Path.cwd() / p
    if not p.exists():
        raise FileNotFoundError(f"Client config not found at: {p}")

    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    try:
        return ClientConfig.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"Invalid client config format: {e}")


def save_client_config(config: ClientConfig, path: str | os.PathLike[str]) -> None:
    """Save client configuration to file."""
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    
    # Update timestamp before saving
    config.updated_at = datetime.utcnow().isoformat()
    
    # Create backup of existing file
    if p.exists():
        backup_path = p.with_suffix(f"{p.suffix}.backup")
        import shutil
        shutil.copy2(p, backup_path)
    
    with p.open("w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)


def create_default_client_config() -> ClientConfig:
    """Create a default client configuration for new installations."""
    return ClientConfig(
        clients=[],
        version="1.0"
    )

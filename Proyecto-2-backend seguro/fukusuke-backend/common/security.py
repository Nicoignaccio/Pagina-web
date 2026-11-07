"""Guardia de servicio privado: solo acepta llamadas con el secreto de servicio correcto."""
import secrets
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Header, HTTPException

from common.config import get_secret


@dataclass
class Ctx:
    user_id: Optional[str] = None
    roles: set = field(default_factory=set)
    caller: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & {"admin", "delivery"})


def make_guard(secret_name: str):
    def guard(
        x_service_token: str = Header(default=""),
        x_user_id: Optional[str] = Header(default=None),
        x_user_roles: str = Header(default=""),
        x_caller: Optional[str] = Header(default=None),
    ) -> Ctx:
        expected = get_secret(secret_name)
        if not secrets.compare_digest(x_service_token.encode(), expected.encode()):
            raise HTTPException(403, "Acceso directo no autorizado")
        return Ctx(x_user_id, {r for r in x_user_roles.split(",") if r}, x_caller)

    return guard


def only_callers(ctx: Ctx, *allowed: str) -> None:
    if ctx.caller not in allowed:
        raise HTTPException(403, "Llamador interno no autorizado")


def require_user(ctx: Ctx) -> str:
    if not ctx.user_id:
        raise HTTPException(401, "Identidad requerida")
    return ctx.user_id

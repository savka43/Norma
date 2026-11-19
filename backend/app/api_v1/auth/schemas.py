from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, StringConstraints

from app.core.models import UserRole

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
AcademicGroup = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
ProfileText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Email = Annotated[EmailStr, Field(max_length=254)]
NewPassword = Annotated[SecretStr, Field(min_length=12, max_length=128)]


class StudentRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: NewPassword
    full_name: FullName
    academic_group: AcademicGroup


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]


class SupervisorBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: NewPassword
    full_name: FullName
    position: ProfileText
    department: ProfileText


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: UserRole
    academic_group: str | None
    position: str | None
    department: str | None
    created_at: datetime

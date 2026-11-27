from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class ProfileUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    professional_summary: str | None = None
    portfolio_links: list[HttpUrl] = []
    linkedin_url: HttpUrl | None = None


class EducationInput(BaseModel):
    institution: str = Field(min_length=1, max_length=255)
    qualification: str | None = None
    field_of_study: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    current_status: str | None = None


class ExperienceInput(BaseModel):
    company: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    employment_type: str | None = None
    description: str | None = None
    achievements: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class SkillInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = "technical"
    proficiency: str | None = None
    years_experience: int | None = Field(default=None, ge=0, le=100)

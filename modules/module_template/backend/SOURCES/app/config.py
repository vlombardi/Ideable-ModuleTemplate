"""Application configuration.

On the host_app pattern: the required fields have no default, so a missing variable makes
``Settings()`` raise at import — naming the variable, echoing no value — and the container exits
non-zero at startup instead of serving traffic misconfigured. The credentialed ``DATABASE_URL``
default that used to live in ``database.py`` is gone — it carried a literal username and password in
the source — so a real connection string must now come from the environment.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings."""

    # Database connection string — required, no default.
    DATABASE_URL: str = Field(...)

    # Authentik JWKS endpoint — required, no default. Without it the backend cannot validate a JWT,
    # so there is no safe fallback value: refuse to start rather than accept every token or none.
    AUTHENTIK_JWKS_URL: str = Field(...)


    # A variable set to the EMPTY STRING must fail like a missing one, and this is not pedantry:
    # docker compose substitutes an empty string for any variable it cannot resolve (it says so --
    # "The X variable is not set. Defaulting to a blank string"), so empty is the realistic
    # misconfiguration, not absent.
    #
    # Without this, an empty DATABASE_URL passed pydantic (it is a valid `str`) and died deeper in
    # SQLAlchemy with `Could not parse SQLAlchemy URL from string ''` -- a message that names neither
    # the variable nor the file to fix, which is what the runtime-correctness work's fail-fast criterion asked for.
    @field_validator("DATABASE_URL", "AUTHENTIK_JWKS_URL")
    @classmethod
    def _must_not_be_blank(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(
                f"{info.field_name} is set but empty. Set a real value in the module's .env.config "
                f"or .env.secrets -- docker compose substitutes an empty string for any variable it "
                f"cannot resolve, so this usually means the variable is missing upstream."
            )
        return value

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

import os

import logging

from fastapi import FastAPI, Depends
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from sqlalchemy.orm import configure_mappers

from .audit import register_audit_listener, set_system_startup_at, set_current_user, clear_current_user
from .auth import _get_current_username_optional
from .database import Base, engine
from .routers.items import router as items_router

_log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
_app_log_level = getattr(logging, _log_level_str, logging.INFO)
logging.getLogger().setLevel(_app_log_level)

logger = logging.getLogger(__name__)


async def _audit_actor_dependency(username: str | None = Depends(_get_current_username_optional)):
    """Set the audit actor for every request that carries a valid JWT.

    Must be an async generator so FastAPI runs it in the same asyncio task
    as the route handler; otherwise the ContextVar is set in a thread-pool
    context and never propagates to the handler.
    """
    if username:
        set_current_user(username)
        logger.debug('Audit actor set: %s', username)
    yield
    clear_current_user()


register_audit_listener(engine)
set_system_startup_at(None)
configure_mappers()
Base.metadata.create_all(bind=engine)

_module_slug = os.getenv('MODULE_SLUG', 'template')
_swagger_oauth2_redirect_url = os.getenv(
    'MODULE_SWAGGER_CALLBACK_URL',
    f'/module/{_module_slug}/api/docs/oauth2-redirect',
)

app = FastAPI(
    title='ModuleTemplate Backend',
    version='1.0.0',
    docs_url=None,
    openapi_url='/api/openapi.json',
    redirect_slashes=False,
    dependencies=[Depends(_audit_actor_dependency)],
)


@app.on_event('startup')
async def _configure_logging():
    """Ensure app loggers respect LOG_LEVEL after uvicorn configures its own logging."""
    _level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    _level = getattr(logging, _level_str, logging.INFO)
    root = logging.getLogger()
    root.setLevel(_level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(_level)
        handler.setFormatter(logging.Formatter('%(levelname)s - %(name)s - %(message)s'))
        root.addHandler(handler)


@app.get('/health')
def health_check():
    return {'status': 'ok'}


@app.get('/api')
def api_root():
    return {'message': 'ModuleTemplate API', 'version': '1.0.0'}


@app.get('/api/docs')
def swagger_docs():
    return get_swagger_ui_html(
        openapi_url='openapi.json',
        title='ModuleTemplate Backend - Swagger UI',
        oauth2_redirect_url=_swagger_oauth2_redirect_url,
        init_oauth={
            'usePkceWithAuthorizationCodeGrant': True,
            'clientId': os.getenv('VITE_OIDC_CLIENT_ID', ''),
        },
        swagger_ui_parameters={
            'persistAuthorization': True,
        },
    )


@app.get('/api/docs/oauth2-redirect', include_in_schema=False)
def swagger_oauth2_redirect():
    return get_swagger_ui_oauth2_redirect_html()


app.include_router(items_router, prefix='/api')

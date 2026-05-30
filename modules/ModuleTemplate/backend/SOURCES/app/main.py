import os

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html

from .database import Base, engine
from .routers.items import router as items_router

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
)


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

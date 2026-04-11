from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

from .database import Base, engine
from .routers.items import router as items_router

Base.metadata.create_all(bind=engine)

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
    )


app.include_router(items_router, prefix='/api')

"""Server-rendered shells for the dashboard; the pages fetch data from the REST API."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=f"{get_settings().frontend_dir}/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@router.get("/view", response_class=HTMLResponse)
def result_page(request: Request):
    return templates.TemplateResponse(request, "document_result.html")

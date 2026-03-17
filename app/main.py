from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Query
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from typing import List, Optional
import io
import csv
import uuid

from .models import NormalizedProduct, BatchStatus, BatchSummary
from .services.importer import parse_csv_file
from .services.normalizer import normalize_records, guess_mapping, INTERNAL_FIELDS
from .services.rule_engine import decide_actions_for_products
from .services.exporter import generate_result_csv
from .services.storage import InMemoryStorage
import json


app = FastAPI(title="Product Content Optimizer", docs_url=None)

storage = InMemoryStorage()

# Temp store for uploaded CSV data waiting for column mapping confirmation.
_pending_uploads: dict = {}

import os as _os

_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=_os.path.join(_PROJECT_ROOT, "static")), name="static")
app.mount("/assets", StaticFiles(directory=_os.path.join(_PROJECT_ROOT, "assets")), name="assets")


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Product Content Optimizer – API",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        swagger_css_url="/static/swagger-overrides.css",
    )


UPLOAD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ProductManager.AI</title>
    <link rel="stylesheet" href="/static/styles.css" />
    <script>
    function setTheme(t){document.documentElement.setAttribute("data-theme",t);localStorage.setItem("pm_theme",t);
        document.querySelectorAll(".theme-btn").forEach(b=>b.classList.toggle("active",b.dataset.theme===t));}
    (function(){setTheme(localStorage.getItem("pm_theme")||"light")})();

    function initDrop(){
        const zone=document.getElementById("dropzone"),inp=document.getElementById("file"),nameEl=document.getElementById("filename");
        const errEl=document.getElementById("file-error");
        function validateFile(file){
            errEl.textContent="";
            if(!file){return false;}
            const valid=["text/csv","application/vnd.ms-excel"];
            const ext=file.name.split(".").pop().toLowerCase();
            if(!valid.includes(file.type)&&ext!=="csv"){
                errEl.textContent="Only CSV files are supported. Please select a .csv file.";
                inp.value="";nameEl.textContent="";return false;
            }
            return true;
        }
        zone.addEventListener("click",()=>inp.click());
        zone.addEventListener("dragover",e=>{e.preventDefault();zone.classList.add("dragover");});
        zone.addEventListener("dragleave",()=>zone.classList.remove("dragover"));
        zone.addEventListener("drop",e=>{e.preventDefault();zone.classList.remove("dragover");
            if(e.dataTransfer.files.length){
                const f=e.dataTransfer.files[0];
                if(validateFile(f)){inp.files=e.dataTransfer.files;nameEl.textContent=f.name;}
            }});
        inp.addEventListener("change",()=>{
            if(inp.files.length){
                if(validateFile(inp.files[0])){nameEl.textContent=inp.files[0].name;}
            }});
        document.querySelector("form").addEventListener("submit",e=>{
            if(!inp.files.length||!validateFile(inp.files[0])){e.preventDefault();}
        });
    }
    </script>
</head>
<body onload="initDrop()">
    <div class="topbar">
        <a href="/" class="topbar-logo"><img src="/assets/logo-dark.png" alt="Sartozo.AI" class="logo-light" /><img src="/assets/logo-light.png" alt="Sartozo.AI" class="logo-dark" /></a>
        <div class="topbar-right">
            <button class="theme-btn" data-theme="light" onclick="setTheme('light')" title="Light theme">&#9788;</button>
            <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')" title="Dark theme">&#9790;</button>
        </div>
    </div>

    <div class="page-center">
        <div class="card">
            <h1 class="heading-lg" style="margin-bottom:6px;">Optimize your product catalog</h1>
            <p class="text-secondary" style="margin-bottom:24px;">
                Upload a CSV with your products. We'll improve titles, descriptions and translations using AI &mdash; then you review and export.
            </p>

            <form action="/batches/preview" method="post" enctype="multipart/form-data">
                <div class="field">
                    <label class="field-label" for="file">Product catalog (CSV)</label>
                    <div class="file-drop" id="dropzone">
                        <div class="file-drop-icon">&#128206;</div>
                        <div class="file-drop-text"><strong>Click to upload</strong> or drag &amp; drop</div>
                        <div class="file-drop-hint">CSV files only, UTF-8 encoded</div>
                        <div class="file-drop-name" id="filename"></div>
                        <input id="file" name="file" type="file" accept=".csv" required />
                    </div>
                    <div id="file-error" class="file-error"></div>
                </div>

                <div class="field-row">
                    <div class="field">
                        <label class="field-label" for="mode">Processing mode</label>
                        <select id="mode" name="mode" class="field-select">
                            <option value="optimize">Optimize titles &amp; descriptions</option>
                            <option value="translate">Translate descriptions</option>
                        </select>
                    </div>
                    <div class="field">
                        <label class="field-label" for="target_language">Target language</label>
                        <select id="target_language" name="target_language" class="field-select">
                            <option value="">Same as input</option>
                            <option value="en">English</option>
                            <option value="sv">Swedish</option>
                            <option value="de">German</option>
                            <option value="fr">French</option>
                            <option value="es">Spanish</option>
                            <option value="pl">Polish</option>
                        </select>
                    </div>
                </div>

                <div class="field">
                    <label class="field-label" for="row_limit">Process first N rows (for testing)</label>
                    <select id="row_limit" name="row_limit" class="field-select">
                        <option value="0">All rows</option>
                        <option value="10" selected>First 10 rows</option>
                        <option value="20">First 20 rows</option>
                        <option value="50">First 50 rows</option>
                        <option value="100">First 100 rows</option>
                    </select>
                </div>

                <button type="submit" class="btn btn-primary btn-full" style="margin-top:8px;">
                    Start processing &rarr;
                </button>
            </form>

            <p class="footer-hint">
                Results appear instantly. You can also use the <code>POST /batches</code> API endpoint.
            </p>
        </div>
    </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def upload_page():
    return HTMLResponse(content=UPLOAD_HTML)


@app.post("/batches/preview", response_class=HTMLResponse)
async def preview_csv(
    file: UploadFile = File(...),
    mode: str = Form("optimize"),
    target_language: Optional[str] = Form(None),
    row_limit: int = Form(0),
):
    if file.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="Only CSV upload is supported.")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    records = parse_csv_file(io.StringIO(text))
    if not records:
        raise HTTPException(status_code=400, detail="CSV appears empty or has no rows.")

    if row_limit > 0:
        records = records[:row_limit]

    csv_columns = list(records[0].keys())
    guessed = guess_mapping(csv_columns)
    sample_rows = records[:5]

    upload_id = str(uuid.uuid4())
    _pending_uploads[upload_id] = {
        "records": records,
        "mode": mode,
        "target_language": target_language or "",
    }

    return HTMLResponse(content=_build_mapping_page(
        upload_id=upload_id,
        csv_columns=csv_columns,
        guessed=guessed,
        sample_rows=sample_rows,
        mode=mode,
        target_language=target_language or "",
        total_rows=len(records),
    ))


@app.post("/batches/confirm", response_class=HTMLResponse)
async def confirm_mapping(
    upload_id: str = Form(...),
    mode: str = Form("optimize"),
    target_language: str = Form(""),
    mappings_json: str = Form(...),
    optimize_fields: str = Form("title,description"),
):
    pending = _pending_uploads.get(upload_id)
    if not pending:
        raise HTTPException(status_code=400, detail="Upload session expired. Please re-upload your CSV.")

    return HTMLResponse(content=_build_processing_page(upload_id, mode, target_language, mappings_json, optimize_fields))


@app.post("/batches/run")
async def run_processing(
    upload_id: str = Form(...),
    mode: str = Form("optimize"),
    target_language: str = Form(""),
    optimize_fields: str = Form("title,description"),
    mappings_json: str = Form(...),
):
    pending = _pending_uploads.pop(upload_id, None)
    if not pending:
        raise HTTPException(status_code=400, detail="Upload session expired.")

    custom_mapping: dict = json.loads(mappings_json)
    records = pending["records"]
    opt_set = set(optimize_fields.split(","))

    batch_id = str(uuid.uuid4())
    normalized_products: List[NormalizedProduct] = normalize_records(records, custom_mapping=custom_mapping)

    actions = decide_actions_for_products(normalized_products, mode=mode)
    storage.create_batch(batch_id=batch_id, products=normalized_products, actions=actions)

    if target_language:
        storage.default_target_language = target_language

    storage.process_batch_synchronously(batch_id, optimize_fields=opt_set)

    return {"batch_id": batch_id}


def _build_processing_page(upload_id: str, mode: str, target_language: str, mappings_json: str, optimize_fields: str = "title,description") -> str:
    mappings_escaped = mappings_json.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Processing &mdash; ProductManager.AI</title>
    <link rel="stylesheet" href="/static/styles.css" />
    <style>
        .loader-card {{
            text-align: center;
            max-width: 480px;
        }}
        .icon-wrap {{
            width: 56px;
            height: 56px;
            margin: 0 auto 20px;
            position: relative;
        }}
        .spinner {{
            width: 56px;
            height: 56px;
            border: 3px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s cubic-bezier(0.4,0,0.2,1) infinite;
        }}
        .checkmark {{
            display: none;
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: var(--accent);
            color: var(--accent-text);
            font-size: 28px;
            line-height: 56px;
            text-align: center;
            animation: popIn 0.35s cubic-bezier(0.2,0.8,0.2,1.2);
        }}
        .done .spinner {{ display: none; }}
        .done .checkmark {{ display: block; }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        @keyframes popIn {{ 0% {{ transform: scale(0); }} 100% {{ transform: scale(1); }} }}

        .thinking-text {{
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--text-primary);
            min-height: 1.6em;
            transition: opacity 0.35s ease;
        }}
        .thinking-sub {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-top: 8px;
        }}

        .dots::after {{
            content: '';
            animation: dots 1.5s steps(4, end) infinite;
        }}
        @keyframes dots {{
            0%  {{ content: ''; }}
            25% {{ content: '.'; }}
            50% {{ content: '..'; }}
            75% {{ content: '...'; }}
        }}

        .progress-bar {{
            width: 100%;
            height: 6px;
            background: var(--border);
            border-radius: 999px;
            margin-top: 28px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            width: 0%;
            background: var(--accent);
            border-radius: 999px;
            transition: width 0.12s linear;
        }}
        .progress-pct {{
            font-size: 0.75rem;
            color: var(--text-tertiary);
            margin-top: 8px;
            font-variant-numeric: tabular-nums;
        }}
    </style>
    <script>
    function setTheme(t){{document.documentElement.setAttribute("data-theme",t);localStorage.setItem("pm_theme",t);
        document.querySelectorAll(".theme-btn").forEach(b=>b.classList.toggle("active",b.dataset.theme===t));}}
    (function(){{setTheme(localStorage.getItem("pm_theme")||"light")}})();

    const phrases = [
        "Boiling the water",
        "Reading every title carefully",
        "Consulting the SEO oracle",
        "Judging descriptions like a copywriter",
        "Feeding data to hungry algorithms",
        "Counting all the pixels",
        "Negotiating with search engines",
        "Brewing some strong coffee",
        "Polishing product copy to a shine",
        "Teaching products to sell themselves",
        "Whispering sweet keywords",
        "Waking up the AI hamsters",
        "Sprinkling conversion fairy dust",
        "Ironing out the wrinkles",
        "Double-checking for hallucinations",
        "Asking ChatGPT's cousin for help",
        "Optimizing like there is no tomorrow",
        "Rewriting titles with passion",
        "Making descriptions actually readable",
        "Convincing the algorithm you are worthy",
        "Almost there, pinky promise",
    ];

    let phraseIdx = 0;
    let pct = 0;
    let batchId = null;
    let serverReady = false;
    let pageStart = Date.now();
    const MIN_SHOW = 5000; // show animation for at least 5 seconds

    function nextPhrase() {{
        const el = document.getElementById("thinking");
        phraseIdx = (phraseIdx + 1) % phrases.length;
        el.style.opacity = 0;
        setTimeout(() => {{ el.textContent = phrases[phraseIdx]; el.style.opacity = 1; }}, 250);
    }}

    function setBar(val) {{
        pct = Math.min(val, 100);
        document.querySelector(".progress-fill").style.width = pct + "%";
        document.getElementById("pct").textContent = Math.round(pct) + "%";
    }}

    // Timer-based progress: ticks every 80ms. Ceiling limits how far it goes.
    let crawlTimer = null;
    function startCrawl(ceiling) {{
        crawlTimer = setInterval(() => {{
            if (pct >= ceiling) {{ clearInterval(crawlTimer); return; }}
            const gap = ceiling - pct;
            const step = Math.max(0.15, gap * 0.02);
            setBar(pct + step);
        }}, 80);
    }}

    function finishBar(cb) {{
        clearInterval(crawlTimer);
        const fin = setInterval(() => {{
            if (pct >= 100) {{
                clearInterval(fin);
                setBar(100);
                cb();
                return;
            }}
            setBar(pct + 1.2);
        }}, 30);
    }}

    function showDone() {{
        document.querySelector(".loader-card").classList.add("done");
        const el = document.getElementById("thinking");
        el.style.opacity = 0;
        setTimeout(() => {{
            el.textContent = "All done!";
            el.style.opacity = 1;
            document.querySelector(".thinking-sub").innerHTML = "Redirecting to your results...";
        }}, 300);
        setTimeout(() => {{ window.location.href = "/batches/" + batchId + "/review"; }}, 1400);
    }}

    function tryFinish() {{
        if (!serverReady) return;
        const elapsed = Date.now() - pageStart;
        const wait = Math.max(0, MIN_SHOW - elapsed);
        setTimeout(() => {{ finishBar(showDone); }}, wait);
    }}

    async function startProcessing() {{
        setInterval(nextPhrase, 1800);
        startCrawl(80);

        const form = new FormData();
        form.append("upload_id", "{upload_id}");
        form.append("mode", "{mode}");
        form.append("target_language", "{target_language}");
        form.append("optimize_fields", "{optimize_fields}");
        form.append("mappings_json", document.getElementById("mj").value);

        try {{
            const resp = await fetch("/batches/run", {{ method: "POST", body: form }});
            if (!resp.ok) {{
                clearInterval(crawlTimer);
                const err = await resp.json();
                alert(err.detail || "Processing failed.");
                window.location.href = "/";
                return;
            }}
            const data = await resp.json();
            batchId = data.batch_id;
            serverReady = true;
            tryFinish();
        }} catch(e) {{
            clearInterval(crawlTimer);
            alert("Something went wrong. Please try again.");
            window.location.href = "/";
        }}
    }}
    </script>
</head>
<body onload="startProcessing()">
    <input type="hidden" id="mj" value="{mappings_escaped}" />

    <div class="topbar">
        <a href="/" class="topbar-logo"><img src="/assets/logo-dark.png" alt="Sartozo.AI" class="logo-light" /><img src="/assets/logo-light.png" alt="Sartozo.AI" class="logo-dark" /></a>
        <div class="topbar-right">
            <button class="theme-btn" data-theme="light" onclick="setTheme('light')" title="Light">&#9788;</button>
            <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')" title="Dark">&#9790;</button>
        </div>
    </div>

    <div class="page-center">
        <div class="card loader-card">
            <div class="icon-wrap">
                <div class="spinner"></div>
                <div class="checkmark">&#10003;</div>
            </div>
            <div class="thinking-text" id="thinking">Boiling the water</div>
            <div class="thinking-sub">This may take a moment depending on catalog size<span class="dots"></span></div>
            <div class="progress-bar"><div class="progress-fill"></div></div>
            <div class="progress-pct" id="pct">0%</div>
        </div>
    </div>
</body>
</html>"""


def _build_mapping_page(
    upload_id: str,
    csv_columns: List[str],
    guessed: dict,
    sample_rows: List[dict],
    mode: str,
    target_language: str,
    total_rows: int = 0,
) -> str:
    internal_options = ["-- skip --"] + INTERNAL_FIELDS
    select_rows = ""
    for col in csv_columns:
        current = guessed.get(col, "")
        opts = ""
        for opt in internal_options:
            val = "" if opt == "-- skip --" else opt
            label = opt
            selected = 'selected' if val == current else ''
            opts += f'<option value="{val}" {selected}>{label}</option>'
        sample_vals = [str(row.get(col, ""))[:60] for row in sample_rows]
        sample_preview = " | ".join(sample_vals) if sample_vals else ""
        select_rows += f"""
        <tr>
            <td><strong>{col}</strong></td>
            <td class="text-mono" style="color:var(--text-tertiary);max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sample_preview}</td>
            <td><select class="field-select mapping-select" data-col="{col}" style="width:100%;">{opts}</select></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Map columns &mdash; ProductManager.AI</title>
    <link rel="stylesheet" href="/static/styles.css" />
    <script>
    function setTheme(t){{document.documentElement.setAttribute("data-theme",t);localStorage.setItem("pm_theme",t);
        document.querySelectorAll(".theme-btn").forEach(b=>b.classList.toggle("active",b.dataset.theme===t));}}
    (function(){{setTheme(localStorage.getItem("pm_theme")||"light")}})();

    function submitMappings(){{
        const selects=document.querySelectorAll(".mapping-select");
        const mapping={{}};
        const used={{}};
        let hasTitle=false,hasId=false;
        selects.forEach(s=>{{
            const col=s.dataset.col;
            const val=s.value;
            if(val){{
                if(used[val]){{
                    alert('Field "'+val+'" is assigned to multiple columns. Each field can only be used once.');
                    throw new Error("duplicate");
                }}
                used[val]=true;
                mapping[col]=val;
                if(val==="title")hasTitle=true;
                if(val==="id")hasId=true;
            }}
        }});
        if(!hasTitle){{alert("Please assign at least the Title field.");return;}}
        if(!hasId){{alert("Please assign at least the ID field.");return;}}
        document.getElementById("mappings_json").value=JSON.stringify(mapping);
        const fields=[];
        if(document.getElementById("opt_title").checked) fields.push("title");
        if(document.getElementById("opt_desc").checked) fields.push("description");
        if(fields.length===0){{alert("Select at least one field to optimize.");return;}}
        document.getElementById("optimize_fields").value=fields.join(",");
        document.getElementById("confirm-form").submit();
    }}
    </script>
</head>
<body>
    <div class="topbar">
        <a href="/" class="topbar-logo"><img src="/assets/logo-dark.png" alt="Sartozo.AI" class="logo-light" /><img src="/assets/logo-light.png" alt="Sartozo.AI" class="logo-dark" /></a>
        <div class="topbar-right">
            <button class="theme-btn" data-theme="light" onclick="setTheme('light')" title="Light">&#9788;</button>
            <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')" title="Dark">&#9790;</button>
        </div>
    </div>

    <div class="page-center" style="padding-top:28px;">
        <div class="card" style="max-width:820px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <span style="font-size:1.6rem;">&#9881;</span>
                <h1 class="heading-lg">Map your columns</h1>
            </div>
            <p class="text-secondary" style="margin-bottom:20px;">
                We detected <strong>{len(csv_columns)}</strong> columns and <strong>{total_rows}</strong> rows in your CSV.
                Assign each column to the correct product field. We pre-filled what we could guess.
                Fields marked <em>-- skip --</em> will go into extra attributes.
            </p>

            <div class="table-wrap" style="margin-bottom:20px;">
                <table>
                    <thead>
                        <tr>
                            <th>Your CSV column</th>
                            <th>Sample data</th>
                            <th>Maps to</th>
                        </tr>
                    </thead>
                    <tbody>
                        {select_rows}
                    </tbody>
                </table>
            </div>

            <div style="margin-bottom:20px;padding:16px 18px;border-radius:10px;border:1px solid var(--border);background:var(--card-bg);">
                <p style="font-weight:600;margin-bottom:10px;font-size:0.95rem;">Which fields should AI optimize?</p>
                <div style="display:flex;gap:24px;flex-wrap:wrap;">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.9rem;">
                        <input type="checkbox" id="opt_title" checked style="width:18px;height:18px;accent-color:var(--accent);" />
                        Optimize titles
                    </label>
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.9rem;">
                        <input type="checkbox" id="opt_desc" checked style="width:18px;height:18px;accent-color:var(--accent);" />
                        Optimize descriptions
                    </label>
                </div>
            </div>

            <form id="confirm-form" method="post" action="/batches/confirm">
                <input type="hidden" name="upload_id" value="{upload_id}" />
                <input type="hidden" name="mode" value="{mode}" />
                <input type="hidden" name="target_language" value="{target_language}" />
                <input type="hidden" id="mappings_json" name="mappings_json" value="" />
                <input type="hidden" id="optimize_fields" name="optimize_fields" value="title,description" />
            </form>

            <div style="display:flex;gap:10px;">
                <a href="/" class="btn btn-outline" style="flex:1;text-align:center;">&larr; Back</a>
                <button class="btn btn-primary" style="flex:2;" onclick="submitMappings()">
                    Confirm &amp; process &rarr;
                </button>
            </div>
        </div>
    </div>
</body>
</html>"""


@app.post("/batches", response_model=BatchSummary)
async def create_batch(
    file: UploadFile = File(...),
    mode: str = Form("optimize"),  # "optimize" or "translate"
    target_language: Optional[str] = Form(None),
    redirect: bool = Query(False),
):
    if file.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="Only CSV upload is supported in v1.")

    content = await file.read()
    try:
        records = parse_csv_file(io.StringIO(content.decode("utf-8")))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    batch_id = str(uuid.uuid4())
    normalized_products: List[NormalizedProduct] = normalize_records(records)

    actions = decide_actions_for_products(normalized_products, mode=mode)
    storage.create_batch(batch_id=batch_id, products=normalized_products, actions=actions)

    if target_language:
        storage.default_target_language = target_language
    storage.process_batch_synchronously(batch_id)

    if redirect:
        return RedirectResponse(url=f"/batches/{batch_id}/review", status_code=303)

    return storage.get_batch_summary(batch_id)


@app.get("/batches/{batch_id}", response_model=BatchSummary)
def get_batch(batch_id: str):
    summary = storage.get_batch_summary(batch_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return summary


@app.get("/batches/{batch_id}/export")
def export_batch(batch_id: str):
    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    csv_buffer = io.StringIO()
    generate_result_csv(batch, csv_buffer)
    csv_buffer.seek(0)

    return StreamingResponse(
        iter([csv_buffer.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch_{batch_id}.csv"'},
    )


@app.post("/batches/{batch_id}/regenerate", response_model=BatchSummary)
async def regenerate_batch_items(batch_id: str, product_ids: List[str]):
    """
    Regenerate selected rows (by product_id) within an existing batch.
    Expects JSON body: ["id1", "id2", ...]
    """
    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    storage.regenerate_products(batch_id, product_ids)
    return storage.get_batch_summary(batch_id)


@app.get("/batches/{batch_id}/review", response_class=HTMLResponse)
def review_batch(batch_id: str):
    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    total = len(batch.products)
    from .models import ProductStatus as PS
    done = sum(1 for r in batch.products if r.status == PS.DONE)
    failed = sum(1 for r in batch.products if r.status == PS.FAILED)
    skipped = sum(1 for r in batch.products if r.status == PS.SKIPPED)
    review = sum(1 for r in batch.products if r.status == PS.NEEDS_REVIEW)

    scores = [r.score for r in batch.products if r.score > 0]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    rows_html = ""
    for r in batch.products:
        pill_cls = f"pill-{r.status.value}"
        sc = r.score
        if sc >= 75:
            score_cls = "score-high"
        elif sc >= 50:
            score_cls = "score-mid"
        else:
            score_cls = "score-low"
        score_cell = f'<span class="score-badge {score_cls}">{sc}</span>' if sc > 0 else ''
        rows_html += f"""
        <tr data-id="{r.product.id}" data-status="{r.status.value}">
            <td><input type="checkbox" name="product_id" value="{r.product.id}" /></td>
            <td class="text-mono">{r.product.id}</td>
            <td>{r.product.title}</td>
            <td><strong>{r.optimized_title or ''}</strong></td>
            <td>{r.product.description}</td>
            <td>{r.optimized_description or ''}</td>
            <td>{r.translated_description or ''}</td>
            <td>{score_cell}</td>
            <td><span class="badge">{r.action.value}</span></td>
            <td><span class="pill {pill_cls}">{r.status.value}</span></td>
            <td class="note-text">{r.notes or r.error or ''}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Review &mdash; {batch_id[:8]}</title>
    <link rel="stylesheet" href="/static/styles.css" />
    <script>
    function setTheme(t){{document.documentElement.setAttribute("data-theme",t);localStorage.setItem("pm_theme",t);
        document.querySelectorAll(".theme-btn").forEach(b=>b.classList.toggle("active",b.dataset.theme===t));}}
    (function(){{setTheme(localStorage.getItem("pm_theme")||"light")}})();

    function applyFilters(){{
        const s=document.getElementById("search").value.toLowerCase();
        const f=document.getElementById("statusFilter").value;
        document.querySelectorAll("tbody tr").forEach(row=>{{
            const text=row.innerText.toLowerCase();
            const st=row.dataset.status||"";
            let ok=true;
            if(s&&!text.includes(s))ok=false;
            if(f&&st!==f)ok=false;
            row.style.display=ok?"":"none";
        }});
    }}

    let sortCol=-1, sortAsc=true;
    const numericCols = new Set([7]);
    function sortTable(colIdx){{
        const tbody=document.querySelector("tbody");
        const rows=Array.from(tbody.querySelectorAll("tr"));
        if(sortCol===colIdx){{ sortAsc=!sortAsc; }} else {{ sortCol=colIdx; sortAsc=true; }}
        const isNum = numericCols.has(colIdx);
        rows.sort((a,b)=>{{
            const aT=(a.children[colIdx]||{{}}).textContent||"";
            const bT=(b.children[colIdx]||{{}}).textContent||"";
            if(isNum){{
                const aN=parseFloat(aT)||0, bN=parseFloat(bT)||0;
                return sortAsc ? aN-bN : bN-aN;
            }}
            return sortAsc ? aT.localeCompare(bT) : bT.localeCompare(aT);
        }});
        rows.forEach(r=>tbody.appendChild(r));
        document.querySelectorAll("th").forEach((th,i)=>{{
            th.classList.remove("sorted-asc","sorted-desc");
            if(i===colIdx) th.classList.add(sortAsc?"sorted-asc":"sorted-desc");
        }});
    }}

    async function submitRegenerate(e){{
        e.preventDefault();
        const ids=Array.from(document.querySelectorAll("input[name='product_id']:checked")).map(c=>c.value);
        if(!ids.length){{alert("Select at least one product.");return;}}
        const r=await fetch("/batches/{batch_id}/regenerate",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(ids)}});
        if(!r.ok){{alert("Regeneration failed.");return;}}
        window.location.reload();
    }}

    function toggleAll(src){{document.querySelectorAll("input[name='product_id']").forEach(c=>c.checked=src.checked);}}
    </script>
</head>
<body>
    <div class="topbar">
        <a href="/" class="topbar-logo"><img src="/assets/logo-dark.png" alt="Sartozo.AI" class="logo-light" /><img src="/assets/logo-light.png" alt="Sartozo.AI" class="logo-dark" /></a>
        <div class="topbar-right">
            <button class="theme-btn" data-theme="light" onclick="setTheme('light')" title="Light">&#9788;</button>
            <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')" title="Dark">&#9790;</button>
        </div>
    </div>

    <div class="page-wide">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px;">
            <div>
                <h1 class="heading-lg">Batch review</h1>
                <p class="text-mono" style="margin-top:4px;">ID: {batch_id}</p>
            </div>
            <div style="display:flex;gap:8px;">
                <a href="/" class="btn btn-outline btn-sm">&larr; New batch</a>
                <a href="/batches/{batch_id}/export" class="btn btn-outline btn-sm">&#8681; Download CSV</a>
            </div>
        </div>

        <div class="insight-card">
            <div class="insight-icon">&#9889;</div>
            <div class="insight-body">
                <p class="insight-title">Optimization Summary</p>
                <p class="insight-text">
                    <strong>{done}</strong> out of <strong>{total}</strong> products were optimized
                    with an average quality score of <strong>{avg_score}/100</strong>.
                    {"Titles and descriptions have been expanded with relevant keywords, product type identifiers, and secondary search phrases using pipe separators — a proven approach to improve visibility across search engines and shopping platforms." if avg_score >= 50 else "Some products had limited metadata which restricted optimization potential. Adding more product attributes (category, material, color) will significantly improve results."}
                    Well-structured titles that include descriptive keywords and category terms are indexed more effectively by crawlers,
                    leading to higher product rankings, better click-through rates, and stronger organic visibility — directly impacting your ROI.
                </p>
            </div>
        </div>

        <div class="stats-row">
            <div class="stat-card"><div class="stat-value">{total}</div><div class="stat-label">Total</div></div>
            <div class="stat-card"><div class="stat-value" style="color:var(--status-done-text);">{done}</div><div class="stat-label">Done</div></div>
            <div class="stat-card"><div class="stat-value" style="color:var(--status-review-text);">{review}</div><div class="stat-label">Review</div></div>
            <div class="stat-card"><div class="stat-value" style="color:var(--status-failed-text);">{failed}</div><div class="stat-label">Failed</div></div>
            <div class="stat-card"><div class="stat-value">{skipped}</div><div class="stat-label">Skipped</div></div>
            <div class="stat-card"><div class="stat-value" style="color:var(--accent);">{avg_score}</div><div class="stat-label">Avg Score</div></div>
        </div>

        <div class="card-wide">
            <div class="controls">
                <div class="controls-left">
                    <input id="search" class="search-box" placeholder="Search products..." oninput="applyFilters()" />
                    <select id="statusFilter" class="filter-select" onchange="applyFilters()">
                        <option value="">All statuses</option>
                        <option value="done">Done</option>
                        <option value="needs_review">Needs review</option>
                        <option value="failed">Failed</option>
                        <option value="skipped">Skipped</option>
                    </select>
                </div>
                <div class="controls-right">
                    <button type="submit" form="regen-form" class="btn btn-primary btn-sm">&#x21bb; Regenerate selected</button>
                </div>
            </div>

            <div class="table-wrap">
                <form id="regen-form" onsubmit="submitRegenerate(event)">
                    <table>
                        <thead>
                            <tr>
                                <th style="width:36px;"><input type="checkbox" onclick="toggleAll(this)" /></th>
                                <th class="sortable" onclick="sortTable(1)">ID</th>
                                <th class="sortable" onclick="sortTable(2)">Old title</th>
                                <th class="sortable" onclick="sortTable(3)">New title</th>
                                <th class="sortable" onclick="sortTable(4)">Old description</th>
                                <th class="sortable" onclick="sortTable(5)">New description</th>
                                <th class="sortable" onclick="sortTable(6)">Translated</th>
                                <th class="sortable" onclick="sortTable(7)">Score</th>
                                <th class="sortable" onclick="sortTable(8)">Action</th>
                                <th class="sortable" onclick="sortTable(9)">Status</th>
                                <th class="sortable" onclick="sortTable(10)">Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                </form>
            </div>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health")
def health():
    return {"status": "ok"}


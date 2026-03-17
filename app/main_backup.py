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

# Settings storage (in-memory, would be DB in production)
_settings: dict = {
    "openai_api_key": "",
    "prompt_title": """You are an SEO expert. Optimize the following product title for search engines.
Keep it under 120 characters. Include relevant keywords. Use a pipe separator for secondary phrases.

Original title: {title}
Category: {category}
Brand: {brand}
Attributes: {attributes}

Return only the optimized title, nothing else.""",
    "prompt_description": """You are an e-commerce copywriter. Write a compelling product description.
Keep it 2-3 paragraphs. Focus on benefits and features. Do not mention price.

Product: {title}
Category: {category}
Brand: {brand}
Attributes: {attributes}
Original description: {description}

Return only the description, nothing else.""",
}

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


HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sartozo.AI — AI-Powered Product Feed Optimization</title>
    <link rel="stylesheet" href="/static/styles.css" />
    <style>
    html { scroll-behavior: smooth; }
    :root { --hp-bg: #000; --hp-text: #fff; --hp-muted: rgba(255,255,255,0.6); --hp-border: rgba(255,255,255,0.1); }

    .hp-body { background: var(--hp-bg); color: var(--hp-text); min-height: 100vh; overflow-x: hidden; }

    /* Navigation */
    .hp-nav { display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; position: relative; z-index: 100; }
    .hp-nav-logo img { height: 32px; filter: brightness(0) invert(1); }
    .hp-nav-links { display: flex; align-items: center; gap: 32px; }
    .hp-nav-link { color: var(--hp-muted); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }
    .hp-nav-link:hover { color: var(--hp-text); }
    .hp-nav-cta { background: var(--hp-text); color: var(--hp-bg); padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; transition: opacity 0.2s; }
    .hp-nav-cta:hover { opacity: 0.9; }

    /* Hero */
    .hp-hero { text-align: center; padding: 100px 24px 120px; position: relative; min-height: 600px; }
    .hp-badge { display: inline-block; color: var(--hp-muted); font-size: 0.85rem; margin-bottom: 28px; letter-spacing: 0.02em; }
    .hp-title { font-size: clamp(2.5rem, 6vw, 4rem); font-weight: 600; line-height: 1.1; margin-bottom: 24px; letter-spacing: -0.03em; position: relative; z-index: 2; }
    .hp-sub { font-size: 1.1rem; color: var(--hp-muted); max-width: 540px; margin: 0 auto 40px; line-height: 1.6; position: relative; z-index: 2; }
    .hp-buttons { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; position: relative; z-index: 2; }
    .hp-btn { padding: 14px 28px; border-radius: 6px; font-size: 0.9rem; font-weight: 500; text-decoration: none; transition: all 0.3s ease; }
    .hp-btn-primary { background: var(--hp-text); color: var(--hp-bg); }
    .hp-btn-primary:hover { opacity: 0.9; transform: translateY(-2px); box-shadow: 0 10px 30px rgba(255,255,255,0.1); }
    .hp-btn-secondary { background: transparent; color: var(--hp-text); border: 1px solid var(--hp-border); }
    .hp-btn-secondary:hover { border-color: rgba(255,255,255,0.3); background: rgba(255,255,255,0.05); }

    /* Mars Planet - positioned left */
    .hp-planet-container { position: absolute; left: -80px; top: 50%; transform: translateY(-50%); width: 380px; height: 380px; z-index: 1; pointer-events: none; }
    .hp-planet { position: relative; width: 100%; height: 100%; }
    .hp-mars { position: absolute; top: 50%; left: 50%; width: 180px; height: 180px; margin: -90px 0 0 -90px; border-radius: 50%; background: radial-gradient(circle at 30% 25%, #e8a87c, #c1440e 40%, #8b2500 70%, #4a1a0a 100%); box-shadow: 0 0 60px rgba(193,68,14,0.5), 0 0 120px rgba(193,68,14,0.3), inset -20px -20px 40px rgba(0,0,0,0.4), inset 10px 10px 30px rgba(255,200,150,0.15); animation: marsFloat 6s ease-in-out infinite, marsSpin 60s linear infinite; overflow: hidden; }
    .hp-mars::before { content: ''; position: absolute; top: 20%; left: 15%; width: 25px; height: 15px; background: rgba(139,37,0,0.6); border-radius: 50%; filter: blur(3px); }
    .hp-mars::after { content: ''; position: absolute; top: 55%; left: 60%; width: 40px; height: 20px; background: rgba(139,37,0,0.5); border-radius: 50%; filter: blur(4px); transform: rotate(-20deg); }
    .hp-crater { position: absolute; border-radius: 50%; background: rgba(74,26,10,0.4); box-shadow: inset 2px 2px 4px rgba(0,0,0,0.3); }
    .hp-crater-1 { width: 20px; height: 20px; top: 35%; left: 40%; }
    .hp-crater-2 { width: 12px; height: 12px; top: 65%; left: 25%; }
    .hp-crater-3 { width: 15px; height: 15px; top: 25%; left: 65%; }
    @keyframes marsFloat { 0%, 100% { transform: translate(-50%, -50%) translateY(0); } 50% { transform: translate(-50%, -50%) translateY(-15px); } }
    @keyframes marsSpin { from { background-position: 0 0; } to { background-position: 200px 0; } }

    /* Mars glow */
    .hp-mars-glow { position: absolute; top: 50%; left: 50%; width: 280px; height: 280px; margin: -140px 0 0 -140px; border-radius: 50%; background: radial-gradient(circle, rgba(193,68,14,0.2) 0%, rgba(193,68,14,0.1) 40%, transparent 70%); animation: glowPulse 4s ease-in-out infinite; }
    @keyframes glowPulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.15); opacity: 0.7; } }

    /* Orbits around Mars */
    .hp-orbit { position: absolute; top: 50%; left: 50%; border: 1px solid rgba(255,255,255,0.06); border-radius: 50%; }
    .hp-orbit-1 { width: 240px; height: 240px; margin: -120px 0 0 -120px; animation: orbitSpin 15s linear infinite; transform-origin: center; }
    .hp-orbit-2 { width: 320px; height: 320px; margin: -160px 0 0 -160px; animation: orbitSpin 25s linear infinite reverse; border-style: dashed; }
    .hp-orbit-3 { width: 380px; height: 380px; margin: -190px 0 0 -190px; animation: orbitSpin 35s linear infinite; border-color: rgba(255,255,255,0.03); }
    @keyframes orbitSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

    /* Moons/satellites */
    .hp-moon { position: absolute; border-radius: 50%; box-shadow: 0 0 15px currentColor; animation: moonGlow 2s ease-in-out infinite; }
    .hp-orbit-1 .hp-moon { width: 10px; height: 10px; top: -5px; left: 50%; margin-left: -5px; background: #f59e0b; color: rgba(245,158,11,0.6); }
    .hp-orbit-2 .hp-moon { width: 8px; height: 8px; top: 50%; right: -4px; margin-top: -4px; background: #ef4444; color: rgba(239,68,68,0.6); animation-delay: 0.5s; }
    .hp-orbit-3 .hp-moon { width: 6px; height: 6px; bottom: 20%; left: -3px; background: #a855f7; color: rgba(168,85,247,0.6); animation-delay: 1s; }
    @keyframes moonGlow { 0%, 100% { box-shadow: 0 0 10px currentColor; } 50% { box-shadow: 0 0 20px currentColor, 0 0 30px currentColor; } }

    /* Floating particles */
    .hp-particles { position: absolute; width: 100%; height: 100%; top: 0; left: 0; }
    .hp-particle { position: absolute; width: 3px; height: 3px; background: rgba(255,255,255,0.4); border-radius: 50%; animation: particleDrift 8s ease-in-out infinite; }
    .hp-particle:nth-child(1) { top: 20%; left: 30%; animation-delay: 0s; }
    .hp-particle:nth-child(2) { top: 60%; left: 70%; animation-delay: 2s; animation-duration: 10s; }
    .hp-particle:nth-child(3) { top: 40%; left: 85%; animation-delay: 4s; animation-duration: 12s; }
    .hp-particle:nth-child(4) { top: 80%; left: 20%; animation-delay: 1s; animation-duration: 9s; }
    @keyframes particleDrift { 0%, 100% { transform: translate(0, 0); opacity: 0.4; } 25% { transform: translate(10px, -15px); opacity: 0.8; } 50% { transform: translate(-5px, -25px); opacity: 0.4; } 75% { transform: translate(-15px, -10px); opacity: 0.7; } }

    /* Features */
    .hp-features { padding: 100px 48px; border-top: 1px solid var(--hp-border); }
    .hp-features-header { text-align: center; margin-bottom: 64px; }
    .hp-features-title { font-size: 2.2rem; font-weight: 600; margin-bottom: 12px; letter-spacing: -0.02em; }
    .hp-features-sub { color: var(--hp-muted); font-size: 1rem; }
    .hp-features-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 32px; max-width: 1100px; margin: 0 auto; }
    .hp-feature { padding: 32px; border: 1px solid var(--hp-border); border-radius: 12px; transition: border-color 0.3s, background 0.3s, transform 0.3s; }
    .hp-feature:hover { border-color: rgba(255,255,255,0.2); background: rgba(255,255,255,0.02); transform: translateY(-4px); }
    .hp-feature-icon { font-size: 1.8rem; margin-bottom: 16px; }
    .hp-feature-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 8px; }
    .hp-feature-desc { font-size: 0.9rem; color: var(--hp-muted); line-height: 1.6; }

    /* How it works */
    .hp-steps { padding: 100px 48px; text-align: center; }
    .hp-steps-title { font-size: 2.2rem; font-weight: 600; margin-bottom: 12px; letter-spacing: -0.02em; }
    .hp-steps-sub { color: var(--hp-muted); font-size: 1rem; margin-bottom: 64px; }
    .hp-steps-grid { display: flex; justify-content: center; gap: 64px; flex-wrap: wrap; max-width: 900px; margin: 0 auto; }
    .hp-step { text-align: center; max-width: 240px; }
    .hp-step-num { width: 48px; height: 48px; border: 2px solid var(--hp-border); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 600; margin: 0 auto 20px; transition: border-color 0.3s, background 0.3s; }
    .hp-step:hover .hp-step-num { border-color: rgba(193,68,14,0.6); background: rgba(193,68,14,0.1); }
    .hp-step-title { font-size: 1rem; font-weight: 600; margin-bottom: 8px; }
    .hp-step-desc { font-size: 0.85rem; color: var(--hp-muted); line-height: 1.5; }

    /* CTA */
    .hp-cta { padding: 100px 48px; text-align: center; border-top: 1px solid var(--hp-border); }
    .hp-cta-title { font-size: 2rem; font-weight: 600; margin-bottom: 16px; letter-spacing: -0.02em; }
    .hp-cta-sub { color: var(--hp-muted); font-size: 1rem; margin-bottom: 32px; }

    /* Footer */
    .hp-footer { padding: 32px 48px; text-align: center; font-size: 0.82rem; color: var(--hp-muted); border-top: 1px solid var(--hp-border); }

    /* Back to top button */
    .back-to-top { position: fixed; bottom: 32px; right: 32px; width: 48px; height: 48px; border-radius: 50%; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15); color: var(--hp-text); font-size: 1.2rem; cursor: pointer; opacity: 0; visibility: hidden; transform: translateY(20px); transition: all 0.3s ease; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(10px); z-index: 999; }
    .back-to-top:hover { background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.3); transform: translateY(-2px); }
    .back-to-top.visible { opacity: 1; visibility: visible; transform: translateY(0); }

    @media (max-width: 1024px) {
        .hp-planet-container { left: -150px; width: 320px; height: 320px; }
        .hp-mars { width: 140px; height: 140px; margin: -70px 0 0 -70px; }
        .hp-mars-glow { width: 220px; height: 220px; margin: -110px 0 0 -110px; }
    }
    @media (max-width: 768px) {
        .hp-nav { padding: 16px 24px; }
        .hp-nav-links { gap: 16px; }
        .hp-nav-link { display: none; }
        .hp-hero { padding: 80px 24px 100px; min-height: auto; }
        .hp-planet-container { position: relative; left: auto; top: auto; transform: none; width: 280px; height: 280px; margin: 40px auto 0; }
        .hp-mars { width: 100px; height: 100px; margin: -50px 0 0 -50px; }
        .hp-mars-glow { width: 160px; height: 160px; margin: -80px 0 0 -80px; }
        .hp-orbit-1 { width: 160px; height: 160px; margin: -80px 0 0 -80px; }
        .hp-orbit-2 { width: 220px; height: 220px; margin: -110px 0 0 -110px; }
        .hp-orbit-3 { width: 270px; height: 270px; margin: -135px 0 0 -135px; }
        .hp-features, .hp-steps, .hp-cta { padding: 60px 24px; }
    }
    </style>
</head>
<body class="hp-body">
    <nav class="hp-nav">
        <a href="/" class="hp-nav-logo"><img src="/assets/logo-light.png" alt="Sartozo.AI" /></a>
        <div class="hp-nav-links">
            <a href="#features" class="hp-nav-link">Features</a>
            <a href="#how-it-works" class="hp-nav-link">How it works</a>
            <a href="/settings" class="hp-nav-link">Settings</a>
            <a href="/upload" class="hp-nav-cta">Get Started</a>
        </div>
    </nav>

    <section class="hp-hero">
        <div class="hp-planet-container">
            <div class="hp-planet">
                <div class="hp-mars-glow"></div>
                <div class="hp-mars">
                    <div class="hp-crater hp-crater-1"></div>
                    <div class="hp-crater hp-crater-2"></div>
                    <div class="hp-crater hp-crater-3"></div>
                </div>
                <div class="hp-orbit hp-orbit-1"><div class="hp-moon"></div></div>
                <div class="hp-orbit hp-orbit-2"><div class="hp-moon"></div></div>
                <div class="hp-orbit hp-orbit-3"><div class="hp-moon"></div></div>
            </div>
        </div>

        <div class="hp-particles">
            <div class="hp-particle"></div>
            <div class="hp-particle"></div>
            <div class="hp-particle"></div>
            <div class="hp-particle"></div>
        </div>

        <div class="hp-badge">Sartozo.AI for E-commerce</div>
        <h1 class="hp-title">Optimize Every Product<br/>for Maximum Visibility</h1>
        <p class="hp-sub">
            AI-powered optimization for your product titles and descriptions. Boost search rankings, increase clicks, and drive more sales.
        </p>
        <div class="hp-buttons">
            <a href="/upload" class="hp-btn hp-btn-primary">Get Started</a>
            <a href="#how-it-works" class="hp-btn hp-btn-secondary">Learn More</a>
        </div>
    </section>

    <section class="hp-features" id="features">
        <div class="hp-features-header">
            <h2 class="hp-features-title">Complete feed optimization platform</h2>
            <p class="hp-features-sub">Everything you need to transform your product content</p>
        </div>
        <div class="hp-features-grid">
            <div class="hp-feature">
                <div class="hp-feature-icon">&#128269;</div>
                <div class="hp-feature-title">SEO-Optimized Titles</div>
                <div class="hp-feature-desc">AI expands short titles with relevant keywords and search phrases using proven e-commerce patterns.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-icon">&#128221;</div>
                <div class="hp-feature-title">Compelling Descriptions</div>
                <div class="hp-feature-desc">Generate conversion-focused product descriptions that highlight features and benefits.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-icon">&#127760;</div>
                <div class="hp-feature-title">Multi-Language Translation</div>
                <div class="hp-feature-desc">Translate optimized content to German, Swedish, French, Spanish, Polish and more.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-icon">&#128200;</div>
                <div class="hp-feature-title">Quality Scoring</div>
                <div class="hp-feature-desc">Every optimization gets a quality score (1-100) so you know the improvement level.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-icon">&#128736;</div>
                <div class="hp-feature-title">Custom Prompts</div>
                <div class="hp-feature-desc">Configure AI prompts to match your brand voice and SEO strategy.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-icon">&#128230;</div>
                <div class="hp-feature-title">CSV Import/Export</div>
                <div class="hp-feature-desc">Upload your feed as CSV, review results, and export the optimized data.</div>
            </div>
        </div>
    </section>

    <section class="hp-steps" id="how-it-works">
        <h2 class="hp-steps-title">How it works</h2>
        <p class="hp-steps-sub">Three simple steps to better product content</p>
        <div class="hp-steps-grid">
            <div class="hp-step">
                <div class="hp-step-num">1</div>
                <div class="hp-step-title">Upload your CSV</div>
                <div class="hp-step-desc">Drop your product feed file and map columns to standard fields.</div>
            </div>
            <div class="hp-step">
                <div class="hp-step-num">2</div>
                <div class="hp-step-title">AI optimizes content</div>
                <div class="hp-step-desc">Our AI analyzes each product and generates improved titles and descriptions.</div>
            </div>
            <div class="hp-step">
                <div class="hp-step-num">3</div>
                <div class="hp-step-title">Review &amp; export</div>
                <div class="hp-step-desc">Check results, regenerate if needed, then download your optimized feed.</div>
            </div>
        </div>
    </section>

    <section class="hp-cta">
        <h2 class="hp-cta-title">Ready to optimize your product feed?</h2>
        <p class="hp-cta-sub">Start with a free test — no API key required for demo mode.</p>
        <a href="/upload" class="hp-btn hp-btn-primary">Get Started Free</a>
    </section>

    <footer class="hp-footer">
        &copy; 2024 Sartozo.AI &mdash; AI-Powered Product Feed Optimization
    </footer>

    <button class="back-to-top" id="backToTop" onclick="window.scrollTo({top:0,behavior:'smooth'})" title="Back to top">
        &#8593;
    </button>

    <script>
    const btn = document.getElementById('backToTop');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 400) {
            btn.classList.add('visible');
        } else {
            btn.classList.remove('visible');
        }
    });
    </script>
</body>
</html>"""


UPLOAD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Upload Feed &mdash; Sartozo.AI</title>
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
            <a href="/upload" class="topbar-link" style="color:var(--accent);">Optimize Feed</a>
            <a href="/settings" class="topbar-link">Settings</a>
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
def homepage():
    return HTMLResponse(content=HOMEPAGE_HTML)


@app.get("/upload", response_class=HTMLResponse)
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
    elif mode == "translate":
        storage.default_target_language = "en"

    # Pass current prompts to AI provider
    storage._ai.set_prompts(_settings["prompt_title"], _settings["prompt_description"])

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
                window.location.href = "/upload";
                return;
            }}
            const data = await resp.json();
            batchId = data.batch_id;
            serverReady = true;
            tryFinish();
        }} catch(e) {{
            clearInterval(crawlTimer);
            alert("Something went wrong. Please try again.");
            window.location.href = "/upload";
        }}
    }}
    </script>
</head>
<body onload="startProcessing()">
    <input type="hidden" id="mj" value="{mappings_escaped}" />

    <div class="topbar">
        <a href="/" class="topbar-logo"><img src="/assets/logo-dark.png" alt="Sartozo.AI" class="logo-light" /><img src="/assets/logo-light.png" alt="Sartozo.AI" class="logo-dark" /></a>
        <div class="topbar-right">
            <a href="/upload" class="topbar-link">Optimize Feed</a>
            <a href="/settings" class="topbar-link">Settings</a>
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
            <a href="/upload" class="topbar-link">Optimize Feed</a>
            <a href="/settings" class="topbar-link">Settings</a>
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
                <a href="/upload" class="btn btn-outline" style="flex:1;text-align:center;">&larr; Back</a>
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
            <td>{r.translated_title or ''}</td>
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
    const numericCols = new Set([8]);
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
            <a href="/upload" class="topbar-link">Optimize Feed</a>
            <a href="/settings" class="topbar-link">Settings</a>
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
                <a href="/upload" class="btn btn-outline btn-sm">&larr; New batch</a>
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
                                <th class="sortable" onclick="sortTable(6)">Translated title</th>
                                <th class="sortable" onclick="sortTable(7)">Translated desc</th>
                                <th class="sortable" onclick="sortTable(8)">Score</th>
                                <th class="sortable" onclick="sortTable(9)">Action</th>
                                <th class="sortable" onclick="sortTable(10)">Status</th>
                                <th class="sortable" onclick="sortTable(11)">Notes</th>
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


# ─────────────────────────────────────────────────────────────────────────────
# Settings page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page():
    api_key_masked = ""
    if _settings["openai_api_key"]:
        key = _settings["openai_api_key"]
        api_key_masked = key[:7] + "..." + key[-4:] if len(key) > 15 else "••••••••"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Settings &mdash; Sartozo.AI</title>
    <link rel="stylesheet" href="/static/styles.css" />
    <script>
    function setTheme(t){{document.documentElement.setAttribute("data-theme",t);localStorage.setItem("pm_theme",t);
        document.querySelectorAll(".theme-btn").forEach(b=>b.classList.toggle("active",b.dataset.theme===t));}}
    (function(){{setTheme(localStorage.getItem("pm_theme")||"light")}})();

    function switchTab(tabId) {{
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.querySelector('[data-tab="'+tabId+'"]').classList.add('active');
        document.getElementById(tabId).classList.add('active');
    }}

    async function savePrompts() {{
        const titlePrompt = document.getElementById('prompt_title').value;
        const descPrompt = document.getElementById('prompt_description').value;
        const resp = await fetch('/api/settings/prompts', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{prompt_title: titlePrompt, prompt_description: descPrompt}})
        }});
        if (resp.ok) {{
            showSaved('prompts-status');
        }}
    }}

    async function saveApiKey() {{
        const key = document.getElementById('openai_key').value;
        const resp = await fetch('/api/settings/apikey', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{openai_api_key: key}})
        }});
        if (resp.ok) {{
            showSaved('apikey-status');
            if (key) {{
                document.getElementById('key-display').textContent = key.substring(0,7) + '...' + key.slice(-4);
                document.getElementById('key-display').style.display = 'inline';
            }}
            document.getElementById('openai_key').value = '';
        }}
    }}

    function showSaved(id) {{
        const el = document.getElementById(id);
        el.classList.add('show');
        setTimeout(() => el.classList.remove('show'), 2500);
    }}
    </script>
</head>
<body>
    <div class="topbar">
        <a href="/" class="topbar-logo"><img src="/assets/logo-dark.png" alt="Sartozo.AI" class="logo-light" /><img src="/assets/logo-light.png" alt="Sartozo.AI" class="logo-dark" /></a>
        <div class="topbar-right">
            <a href="/settings" class="topbar-link" style="color:var(--accent);">Settings</a>
            <button class="theme-btn" data-theme="light" onclick="setTheme('light')" title="Light">&#9788;</button>
            <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')" title="Dark">&#9790;</button>
        </div>
    </div>

    <div class="page-center" style="padding-top:28px;">
        <div class="card" style="max-width:800px;">
            <h1 class="heading-lg" style="margin-bottom:20px;">Settings</h1>

            <div class="tabs">
                <button class="tab-btn active" data-tab="tab-prompts" onclick="switchTab('tab-prompts')">Prompts</button>
                <button class="tab-btn" data-tab="tab-api" onclick="switchTab('tab-api')">API Keys</button>
            </div>

            <div id="tab-prompts" class="tab-content active">
                <div class="setting-group">
                    <div class="setting-group-title">Title Optimization Prompt</div>
                    <p class="setting-description">
                        This prompt is sent to the AI when optimizing product titles.
                        Available variables: <code>{{title}}</code>, <code>{{category}}</code>, <code>{{brand}}</code>, <code>{{attributes}}</code>
                    </p>
                    <textarea id="prompt_title" class="prompt-textarea">{_settings["prompt_title"]}</textarea>
                </div>

                <div class="setting-group">
                    <div class="setting-group-title">Description Generation Prompt</div>
                    <p class="setting-description">
                        This prompt is sent to the AI when generating product descriptions.
                        Available variables: <code>{{title}}</code>, <code>{{category}}</code>, <code>{{brand}}</code>, <code>{{attributes}}</code>, <code>{{description}}</code>
                    </p>
                    <textarea id="prompt_description" class="prompt-textarea">{_settings["prompt_description"]}</textarea>
                </div>

                <div style="display:flex;align-items:center;">
                    <button class="btn btn-primary" onclick="savePrompts()">Save prompts</button>
                    <span id="prompts-status" class="save-status">&#10003; Saved</span>
                </div>
            </div>

            <div id="tab-api" class="tab-content">
                <div class="setting-group">
                    <div class="setting-group-title">OpenAI API Key</div>
                    <p class="setting-description">
                        Enter your OpenAI API key to enable AI-powered title and description generation.
                        Get your API key from <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--accent);">platform.openai.com</a>.
                        Your key is stored securely and never shared.
                    </p>
                    <div style="margin-bottom:12px;">
                        <span style="font-size:0.82rem;color:var(--text-tertiary);">Current key: </span>
                        <code id="key-display" style="font-size:0.82rem;{'display:inline;' if api_key_masked else 'display:none;'}">{api_key_masked}</code>
                        <span style="font-size:0.82rem;color:var(--text-tertiary);{'display:none;' if api_key_masked else ''}" id="no-key">Not set</span>
                    </div>
                    <input type="password" id="openai_key" class="api-key-input" placeholder="sk-..." />
                </div>

                <div style="display:flex;align-items:center;">
                    <button class="btn btn-primary" onclick="saveApiKey()">Save API key</button>
                    <span id="apikey-status" class="save-status">&#10003; Saved</span>
                </div>

                <div style="margin-top:24px;padding:16px;border-radius:8px;background:var(--bg-2);border:1px solid var(--border);">
                    <p style="font-size:0.85rem;color:var(--text-secondary);margin:0;">
                        <strong>Note:</strong> When an API key is set, the system will use OpenAI GPT-4o-mini for generation.
                        Without an API key, a placeholder algorithm is used that demonstrates the flow without actual AI.
                    </p>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/api/settings/prompts")
async def save_prompts(data: dict):
    if "prompt_title" in data:
        _settings["prompt_title"] = data["prompt_title"]
    if "prompt_description" in data:
        _settings["prompt_description"] = data["prompt_description"]
    # Sync to AI provider immediately
    storage._ai.set_prompts(_settings["prompt_title"], _settings["prompt_description"])
    return {"status": "ok"}


@app.post("/api/settings/apikey")
async def save_api_key(data: dict):
    if "openai_api_key" in data:
        _settings["openai_api_key"] = data["openai_api_key"]
        storage._ai.set_api_key(data["openai_api_key"])
        # Also sync prompts so they're ready to use
        storage._ai.set_prompts(_settings["prompt_title"], _settings["prompt_description"])
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings():
    return {
        "prompt_title": _settings["prompt_title"],
        "prompt_description": _settings["prompt_description"],
        "has_api_key": bool(_settings["openai_api_key"]),
    }

